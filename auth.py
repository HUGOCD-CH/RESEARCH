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
import re
import threading
import time
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


def get_token() -> str:
    """Return the current Bearer token (from state or MSAL sessionStorage)."""
    if not is_ready():
        return ""
    # Return token stored at login time if still present
    stored = get_state().get("token", "")
    if stored:
        return stored
    # Fall back to live MSAL sessionStorage read (handles token refresh)
    try:
        return evaluate("""() => {
            const now = Math.floor(Date.now() / 1000);
            for (const s of [sessionStorage, localStorage]) {
                try {
                    for (let i = 0; i < s.length; i++) {
                        const key = s.key(i);
                        if (!key) continue;
                        let val;
                        try { val = JSON.parse(s.getItem(key) || ''); }
                        catch(e) { continue; }
                        if (!val || val.credentialType !== 'AccessToken') continue;
                        const t = val.secret || '';
                        if (!t.startsWith('eyJ')) continue;
                        const exp = parseInt(val.expiresOn || 0);
                        if (!exp || exp > now) return t;
                    }
                } catch(e) {}
            }
            return '';
        }""") or ""
    except Exception:
        return ""


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
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            os.makedirs(_SESSION_DIR, exist_ok=True)

            launch_kwargs = dict(
                headless=False,
                ignore_https_errors=True,
                args=[
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
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

            # Suppress the "Open email links with which app?" dialog.
            context.add_init_script("navigator.registerProtocolHandler = () => {};")

            # Re-use existing page if one was saved; otherwise open a new one
            page = context.pages[0] if context.pages else context.new_page()

            # Python-side response interceptor: captures the OAuth2 access_token
            # that Azure AD returns to the browser during the MFA login flow.
            # The token endpoint POST returns JSON with access_token, which we
            # store and later pass as Authorization: Bearer to Graph API calls.
            _captured: dict = {"token": ""}

            def _on_response(response):
                try:
                    url = response.url
                    if not any(d in url for d in ('login.microsoftonline.com',
                                                   'login.microsoft.com',
                                                   'login.windows.net')):
                        return
                    if response.status != 200:
                        return
                    try:
                        import json as _json
                        body = response.text()
                        data = _json.loads(body)
                        if isinstance(data, dict):
                            t = data.get('access_token', '')
                            if t and t.startswith('eyJ'):
                                _captured['token'] = t
                    except Exception:
                        pass
                except Exception:
                    pass

            page.on("response", _on_response)

            _set(status="waiting_login")
            try:
                page.goto(config.OWA_URL, wait_until="domcontentloaded", timeout=30_000)
            except Exception:
                pass  # redirect chain may exceed domcontentloaded; keep going

            # Poll using Playwright's Python-side properties — no JS evaluation
            # needed, so mid-navigation exceptions can't swallow detection.
            _OWA_DOMAINS = ('webmail.medtronic.com', 'outlook.cloud.microsoft',
                            'outlook.office365.com', 'outlook.office.com')
            _AUTH_PATHS  = ('/auth/', '/logon', '/login', '/sso', '/saml', '/adfs/')
            _SIGNIN_RE   = re.compile(r'sign.?in|authenticat|verif|two.?factor|mfa', re.I)

            deadline = time.time() + 300
            logged_in = False
            while time.time() < deadline:
                try:
                    url   = page.url
                    title = page.title()
                    if (any(d in url for d in _OWA_DOMAINS) and
                            '/mail' in url and
                            not any(p in url for p in _AUTH_PATHS) and
                            not _SIGNIN_RE.search(title)):
                        logged_in = True
                        break
                except Exception:
                    pass
                time.sleep(1.5)

            if not logged_in:
                _set(status="error", error="Login timed out. Please try again.")
                context.close()
                return

            user = ""
            token = _captured.get("token", "")

            try:
                page.wait_for_timeout(3_000)
                user = page.evaluate("""() => {
                    try {
                        return (
                            document.querySelector('[aria-label*="@"]')
                                ?.getAttribute('aria-label') ||
                            document.querySelector('[title*="@"]')
                                ?.getAttribute('title') || ''
                        );
                    } catch(e) { return ''; }
                }""") or ""
            except Exception:
                pass

            # If the response interceptor didn't fire (e.g. session was already
            # valid from persistent context), read the MSAL access token from
            # sessionStorage / localStorage where MSAL.js caches credentials.
            if not token:
                try:
                    token = page.evaluate("""() => {
                        const now = Math.floor(Date.now() / 1000);
                        for (const s of [sessionStorage, localStorage]) {
                            try {
                                for (let i = 0; i < s.length; i++) {
                                    const key = s.key(i);
                                    if (!key) continue;
                                    let val;
                                    try { val = JSON.parse(s.getItem(key) || ''); }
                                    catch(e) { continue; }
                                    if (!val || val.credentialType !== 'AccessToken') continue;
                                    const t = val.secret || '';
                                    if (!t.startsWith('eyJ')) continue;
                                    const exp = parseInt(val.expiresOn || 0);
                                    if (!exp || exp > now) return t;
                                }
                            } catch(e) {}
                        }
                        return '';
                    }""") or ""
                except Exception:
                    pass

            _set(status="active", user=user, token=token)

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
