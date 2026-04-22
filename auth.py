"""
Browser session manager using Playwright.

Keeps a real browser window open and routes all mail API calls through
it via page.evaluate(). This means auth happens exactly as it does
when the user browses webmail.medtronic.com normally — no token
extraction or app registration needed.

Thread safety: Playwright's sync API must be called from the thread that
created the browser. A dedicated daemon thread owns the browser and
processes tasks from a queue so Flask worker threads never touch
Playwright directly.
"""
import queue
import threading
import config

# ── Shared state ─────────────────────────────────────────────────────────────
# status: idle | opening | waiting_login | active | error
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
    """
    Run JavaScript in the live browser window and return the result.
    Called from Flask worker threads; the browser thread executes it.
    """
    if not is_ready():
        raise RuntimeError("Browser session is not active. Please sign in again.")
    task = _Task(js)
    _task_queue.put(task)
    if not task.wait(timeout):
        raise TimeoutError("Browser task timed out after %ds" % timeout)
    if task.error:
        raise RuntimeError(task.error)
    return task.result


# ── Browser worker thread ─────────────────────────────────────────────────────

def _worker(q: queue.Queue):
    _set(status="opening", error=None, user=None)

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

        with sync_playwright() as pw:
            # Prefer installed Chrome (better corporate SSO); fall back to Chromium
            try:
                browser = pw.chromium.launch(headless=False, channel="chrome")
            except Exception:
                browser = pw.chromium.launch(headless=False)

            context = browser.new_context(ignore_https_errors=True)
            page = context.new_page()

            _set(status="waiting_login")
            page.goto(config.OWA_URL, wait_until="domcontentloaded", timeout=30_000)

            # Wait until the user has passed the login page
            try:
                page.wait_for_function(
                    """() => {
                        const url = window.location.href.toLowerCase();
                        const pastLogin = !url.includes('logon') &&
                                          !url.includes('/login') &&
                                          !url.includes('sso');
                        const hasApp = !!document.querySelector(
                            '#app, [role="main"], [aria-label="Inbox"]'
                        );
                        return pastLogin && hasApp;
                    }""",
                    timeout=300_000,   # 5-minute login window
                )
            except PWTimeout:
                _set(status="error", error="Login timed out. Please try again.")
                browser.close()
                return

            # Let OWA finish loading
            page.wait_for_timeout(2_500)

            # Best-effort: read the signed-in user's email from the page
            user = page.evaluate("""() => {
                try {
                    return (
                        document.querySelector('[aria-label*="@medtronic"]')
                            ?.getAttribute('aria-label') ||
                        document.querySelector('[title*="@medtronic"]')
                            ?.getAttribute('title') ||
                        document.cookie.match(/hpn=([^;]+)/)?.[1] || ''
                    );
                } catch(e) { return ''; }
            }""")

            _set(status="active", user=user or "")

            # ── Main task loop ────────────────────────────────────────────────
            while True:
                try:
                    task: _Task | None = q.get(timeout=1)
                except queue.Empty:
                    # Keep-alive: verify the page is still responsive
                    try:
                        page.evaluate("() => document.readyState")
                    except Exception:
                        _set(status="error",
                             error="Browser was closed. Please sign in again.")
                        break
                    continue

                if task is None:   # shutdown signal
                    break

                try:
                    task.complete(result=page.evaluate(task.js))
                except Exception as exc:
                    task.complete(error=str(exc))

            try:
                browser.close()
            except Exception:
                pass

    except Exception as exc:
        _set(status="error", error=f"Browser error: {exc}")


# ── Public control ────────────────────────────────────────────────────────────

def start_login():
    global _task_queue
    if _task_queue:
        _task_queue.put(None)   # stop any existing browser thread

    _task_queue = queue.Queue()
    _set(status="idle", error=None, user=None)
    threading.Thread(target=_worker, args=(_task_queue,), daemon=True).start()


def clear():
    global _task_queue
    if _task_queue:
        _task_queue.put(None)
    _task_queue = None
    _set(status="idle", error=None, user=None)
