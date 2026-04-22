"""
Browser session manager using Playwright.

Key design choices:
- Persistent browser context (.playwright_session/) saves cookies/session
  so MFA is only required once per corporate session expiry (~8-24 h).
- Login detection completes when OWA inbox is fully loaded (handles
  redirect from webmail.medtronic.com → outlook.cloud.microsoft).
- Keep-alive tolerates brief navigation pauses before reporting closure.
"""
import os
import queue
import threading
import config

_SESSION_DIR = os.path.join(os.path.dirname(__file__), ".playwright_session")

# ── Shared state ─────────────────────────────────────────────────────────────
_state: dict = {"status": "idle", "error": None, "user": None}
_state_lock = threading.Lock()
_task_queue: queue.Queue | None = None


def _set(**kwargs):
    with _state_lock:
        _state.update(kwargs)


def get_state() -> dict:
    with _state_lock:
        return dict(_state)


def is_ready() -> bool:
    return get_state()["status"] == "active"


# ── Task execution ────────────────────────────────────────────────────────────

class _Task:
    def __init__(self, js: str):
        self.js = js
        self.result = None
        self.error: str | None = None
        self._done = threading.Event()

    def wait(self, timeout: float = 30) -> bool:
        return self._done.wait(timeout)

    def complete(self, result=None, error: str | None = None):
        self.result = result
        self.error = error
        self._done.set()


def evaluate(js: str, timeout: float = 30):
    """Run JavaScript in the browser from any Flask worker thread."""
    if not is_ready():
        raise RuntimeError("Browser session is not active. Please sign in again.")
    task = _Task(js)
    _task_queue.put(task)
    if not task.wait(timeout):
        raise TimeoutError("Browser task timed out after %ds" % timeout)
    if task.error:
        raise RuntimeError(task.error)
    return task.result


# ── Login detection ───────────────────────────────────────────────────────────
# Fires only when OWA's inbox is fully rendered, NOT during the auth/MFA chain.
# Accepts both webmail.medtronic.com and outlook.cloud.microsoft (redirect target).

_LOGIN_DONE_JS = """() => {
    const url  = window.location.href;
    const title = document.title || '';

    // Must be on an OWA server (Medtronic redirects to outlook.office365.com)
    const onOWA = url.includes('webmail.medtronic.com') ||
                  url.includes('outlook.cloud.microsoft') ||
                  url.includes('outlook.office365.com') ||
                  url.includes('outlook.office.com');
    if (!onOWA) return false;

    // Reject auth/MFA/redirect paths
    if (url.includes('/auth/')   ||
        url.includes('/logon')   ||
        url.includes('/login')   ||
        url.includes('/sso')     ||
        url.includes('/saml')    ||
        url.includes('/adfs/')) return false;

    // Reject pages whose <title> still says sign-in / authentication
    if (/sign.?in|authenticat|verification|two.?factor|mfa/i.test(title))
        return false;

    // Page must be fully loaded and on the /mail section
    if (document.readyState !== 'complete') return false;
    if (!url.includes('/mail')) return false;

    // Any rendered page body is enough — new Outlook doesn't use [role="main"]
    return !!document.body && document.body.children.length > 0;
}"""


# ── Browser worker thread ─────────────────────────────────────────────────────

def _worker(q: queue.Queue):
    _set(status="opening", error=None, user=None)

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

        with sync_playwright() as pw:
            os.makedirs(_SESSION_DIR, exist_ok=True)

            # launch_persistent_context saves cookies + localStorage between runs.
            # After the first MFA, subsequent launches restore the session
            # automatically (no re-authentication unless the session expires).
            launch_kwargs = dict(
                headless=False,
                ignore_https_errors=True,
                args=["--no-first-run", "--no-default-browser-check"],
            )
            try:
                context = pw.chromium.launch_persistent_context(
                    _SESSION_DIR, channel="chrome", **launch_kwargs
                )
            except Exception:
                # Chrome not installed — fall back to bundled Chromium
                context = pw.chromium.launch_persistent_context(
                    _SESSION_DIR, **launch_kwargs
                )

            # Suppress "Open email links" / protocol-handler permission dialog.
            # Outlook calls navigator.registerProtocolHandler(); this no-ops it
            # so Chrome never shows the dialog (and Windows never opens Default Apps).
            context.add_init_script("navigator.registerProtocolHandler = () => {};")

            # Re-use existing page if one was saved; otherwise open a new one
            page = context.pages[0] if context.pages else context.new_page()

            _set(status="waiting_login")
            page.goto(config.OWA_URL, wait_until="domcontentloaded", timeout=30_000)

            # Wait until OWA inbox is fully rendered (survives MFA redirects)
            try:
                page.wait_for_function(_LOGIN_DONE_JS, timeout=300_000)
            except PWTimeout:
                _set(status="error", error="Login timed out. Please try again.")
                context.close()
                return

            # Let any final rendering settle
            page.wait_for_timeout(2_000)

            # Best-effort: read signed-in user from OWA's page
            user = page.evaluate("""() => {
                try {
                    return (
                        document.querySelector('[aria-label*="@"]')
                            ?.getAttribute('aria-label') ||
                        document.querySelector('[title*="@"]')
                            ?.getAttribute('title') || ''
                    );
                } catch(e) { return ''; }
            }""")

            _set(status="active", user=user or "")

            # ── Main task loop ────────────────────────────────────────────
            consecutive_nav_errors = 0

            while True:
                try:
                    task: _Task | None = q.get(timeout=1)
                except queue.Empty:
                    # Keep-alive: distinguish navigation (transient) from closure
                    try:
                        page.evaluate("() => true")
                        consecutive_nav_errors = 0
                    except Exception:
                        consecutive_nav_errors += 1
                        # Allow up to ~8 s of navigation before treating as closed
                        if consecutive_nav_errors >= 8:
                            _set(status="error",
                                 error="Browser was closed. Please sign in again.")
                            break
                    continue

                if task is None:   # shutdown signal
                    break

                consecutive_nav_errors = 0
                try:
                    task.complete(result=page.evaluate(task.js))
                except Exception as exc:
                    task.complete(error=str(exc))

            try:
                context.close()
            except Exception:
                pass

    except Exception as exc:
        _set(status="error", error=f"Browser error: {exc}")


# ── Public control ────────────────────────────────────────────────────────────

def start_login():
    global _task_queue
    if _task_queue:
        _task_queue.put(None)   # stop any existing browser

    _task_queue = queue.Queue()
    _set(status="idle", error=None, user=None)
    threading.Thread(target=_worker, args=(_task_queue,), daemon=True).start()


def clear():
    global _task_queue
    if _task_queue:
        _task_queue.put(None)
    _task_queue = None
    _set(status="idle", error=None, user=None)
