"""
Browser session manager — two modes:

  CONNECT mode  Connect to an already-running Chrome that has webmail open.
                Chrome must be started with --remote-debugging-port=9222.
                The user is already logged in; no MFA required.

  LAUNCH mode   Playwright launches its own browser and the user logs in.
                Uses a persistent profile so MFA is only needed once.
"""
import base64
import json as _json
import os
import queue
import re
import threading
import time
import config

_SESSION_DIR = os.path.join(os.path.dirname(__file__), ".playwright_session")
CDP_URL = "http://localhost:9222"

_OWA_DOMAINS = ('webmail.medtronic.com', 'outlook.cloud.microsoft',
                'outlook.office365.com', 'outlook.office.com')


def _token_has_mail_scope(token: str) -> bool:
    """Return True if the JWT's scp/scope claim includes mail-related permissions."""
    try:
        payload = _json.loads(
            base64.b64decode(token.split('.')[1] + '==').decode('utf-8', errors='replace')
        )
        scp = (payload.get('scp', '') or payload.get('scope', '')).lower()
        return 'mail' in scp or 'message' in scp
    except Exception:
        return False


# ── Shared state ──────────────────────────────────────────────────────────────
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
    """Return a Graph Bearer token with mail scope (live read from browser)."""
    if not is_ready():
        return ""
    try:
        t = evaluate("() => window.__MailToken || ''") or ""
        if t and t.startswith("eyJ"):
            return t
    except Exception:
        pass
    return get_state().get("token", "")


def get_owa_token() -> str:
    if not is_ready():
        return ""
    return _read_tokens().get("owaToken", "")


# ── MSAL sessionStorage fallback ─────────────────────────────────────────────

_MSAL_TOKEN_JS = """() => {
    const now = Math.floor(Date.now() / 1000);
    const decodeAud = (t) => {
        try {
            const p = JSON.parse(atob(t.split('.')[1].replace(/-/g,'+').replace(/_/g,'/')));
            const a = p.aud;
            return (Array.isArray(a) ? a.join(' ') : (a || '')).toLowerCase();
        } catch(e) { return ''; }
    };
    const GRAPH = ['graph.microsoft.com', '00000003-0000-0000-c000-000000000000'];
    const OWA   = ['outlook.office365.com', 'outlook.office.com'];
    let graphToken = '', owaToken = '';
    for (const s of [sessionStorage, localStorage]) {
        try {
            for (let i = 0; i < s.length; i++) {
                const key = s.key(i);
                if (!key) continue;
                let val;
                try { val = JSON.parse(s.getItem(key) || ''); } catch(e) { continue; }
                if (!val || val.credentialType !== 'AccessToken') continue;
                const t = val.secret || '';
                if (!t.startsWith('eyJ') || t.length < 100) continue;
                const exp = parseInt(val.expiresOn || 0);
                if (exp && exp <= now) continue;
                const aud = decodeAud(t);
                if (!graphToken && GRAPH.some(g => aud.includes(g))) graphToken = t;
                if (!owaToken  && OWA.some(o => aud.includes(o)))   owaToken  = t;
            }
        } catch(e) {}
    }
    return { graphToken: graphToken, owaToken: owaToken };
}"""


def _read_tokens() -> dict:
    try:
        result = evaluate(_MSAL_TOKEN_JS)
        if isinstance(result, dict):
            return result
    except Exception:
        pass
    return {"graphToken": "", "owaToken": ""}


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


# ── JavaScript injected into every page ──────────────────────────────────────
# Intercepts fetch() calls to graph.microsoft.com to:
#   1. Capture mail-scoped Bearer tokens into window.__MailToken
#   2. Cache mail API responses in window.__InboxData / window.__MessageData
#      so we can read what OWA already fetched without making new API calls.

_INTERCEPT_JS = """
navigator.registerProtocolHandler = () => {};
window.__MailToken  = window.__MailToken  || '';
window.__InboxData  = window.__InboxData  || null;
window.__MessageData= window.__MessageData|| {};

(function() {
    if (window.__interceptInstalled) return;
    window.__interceptInstalled = true;

    const _hasMail = (token) => {
        try {
            const p = JSON.parse(atob(token.split('.')[1].replace(/-/g,'+').replace(/_/g,'/')));
            const scp = (p.scp || p.scope || '').toLowerCase();
            return scp.includes('mail') || scp.includes('message');
        } catch(e) { return false; }
    };

    const _grabToken = (url, hdrs) => {
        try {
            const s = typeof url === 'string' ? url : (url && url.url) || '';
            if (!s.includes('graph.microsoft.com')) return;
            const h = hdrs instanceof Headers ? hdrs :
                      new Headers(typeof hdrs === 'object' ? hdrs : {});
            const a = h.get('authorization') || h.get('Authorization') || '';
            if (!a.toLowerCase().startsWith('bearer ')) return;
            const token = a.slice(7);
            if (_hasMail(token) || !window.__MailToken)
                window.__MailToken = token;
        } catch(e) {}
    };

    const _f = window.fetch;
    window.fetch = async function(input, init) {
        _grabToken(input, (init && init.headers) || {});

        const url = typeof input === 'string' ? input : (input && input.url) || '';
        const isMailUrl = url.includes('graph.microsoft.com') &&
            (url.includes('/mailFolders') || url.includes('/messages'));

        const promise = _f.apply(this, arguments);

        if (isMailUrl) {
            promise.then(r => {
                if (!r.ok) return;
                r.clone().json().then(data => {
                    if (data && data.value && Array.isArray(data.value) && data.value.length > 0
                            && data.value[0].subject !== undefined) {
                        // Message list response — cache as inbox data
                        window.__InboxData = data;
                    } else if (data && data.id && data.subject !== undefined) {
                        // Single message response
                        window.__MessageData[data.id] = data;
                    }
                }).catch(() => {});
            }).catch(() => {});
        }

        return promise;
    };

    const _open = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function() {
        this.__url = arguments[1] || '';
        return _open.apply(this, arguments);
    };
    const _sh = XMLHttpRequest.prototype.setRequestHeader;
    XMLHttpRequest.prototype.setRequestHeader = function(n, v) {
        if (n && n.toLowerCase() === 'authorization')
            _grabToken(this.__url, {Authorization: v});
        return _sh.apply(this, arguments);
    };
})();
"""


# ── Shared post-connection setup ──────────────────────────────────────────────

def _setup_page(page, _captured: dict, token_deadline: float):
    """Inject interceptor, read user display name, and wait for a mail token."""
    try:
        page.evaluate(_INTERCEPT_JS)
    except Exception:
        pass

    user = ""
    try:
        user = page.evaluate("""() => {
            try {
                return (
                    document.querySelector('[aria-label*="@"]')?.getAttribute('aria-label') ||
                    document.querySelector('[title*="@"]')?.getAttribute('title') || ''
                );
            } catch(e) { return ''; }
        }""") or ""
    except Exception:
        pass

    graph_token = _captured.get("token", "")
    owa_token = ""

    while time.time() < token_deadline:
        try:
            t = page.evaluate("() => window.__MailToken || ''") or ""
            if t and t.startswith("eyJ"):
                graph_token = t
            tokens = page.evaluate(_MSAL_TOKEN_JS)
            if isinstance(tokens, dict):
                graph_token = graph_token or tokens.get("graphToken", "")
                owa_token   = owa_token   or tokens.get("owaToken", "")
        except Exception:
            pass

        if owa_token:
            break
        if graph_token and _token_has_mail_scope(graph_token):
            break
        # Also break if OWA has already loaded inbox data into the page cache —
        # in that case the fallback path in mail.py can serve the response even
        # without a token we can use directly.
        try:
            inbox_ready = page.evaluate(
                "() => !!(window.__InboxData && window.__InboxData.value && "
                "window.__InboxData.value.length > 0)"
            )
            if inbox_ready:
                break
        except Exception:
            pass
        time.sleep(1)

    return user, graph_token, owa_token


def _task_loop(page, q: queue.Queue):
    """Process evaluate tasks from Flask threads until shutdown signal."""
    consecutive_nav_errors = 0
    while True:
        try:
            task: _Task | None = q.get(timeout=1)
        except queue.Empty:
            try:
                page.evaluate("() => true")
                consecutive_nav_errors = 0
            except Exception:
                consecutive_nav_errors += 1
                if consecutive_nav_errors >= 8:
                    _set(status="error",
                         error="Browser was closed. Please sign in again.")
                    return
            continue

        if task is None:
            return

        consecutive_nav_errors = 0
        try:
            task.complete(result=page.evaluate(task.js))
        except Exception as exc:
            task.complete(error=str(exc))


# ── CONNECT mode worker ───────────────────────────────────────────────────────

def _connect_worker(q: queue.Queue):
    """Attach to an already-running Chrome on CDP_URL."""
    _set(status="opening", error=None, user=None)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.connect_over_cdp(CDP_URL)
            except Exception as e:
                _set(status="error",
                     error=f"Cannot connect to Chrome on {CDP_URL}. "
                           f"Start Chrome with --remote-debugging-port=9222 first. ({e})")
                return

            # Find the OWA tab
            page = None
            target_ctx = None
            for ctx in browser.contexts:
                for p in ctx.pages:
                    try:
                        if any(d in p.url for d in _OWA_DOMAINS):
                            page = p
                            target_ctx = ctx
                            break
                    except Exception:
                        pass
                if page:
                    break

            if not page:
                _set(status="error",
                     error="No webmail tab found in Chrome. "
                           "Open webmail.medtronic.com in Chrome first, then try again.")
                return

            _set(status="waiting_login")

            # ── CDP-level response capture ─────────────────────────────────────
            # page.on("response") hooks into Chrome's network layer, catching
            # responses from service workers and all frames — more reliable than
            # patching window.fetch in JavaScript.
            _cdp_inbox: dict = {}
            _cdp_token: dict = {"token": ""}

            def _on_cdp_response(response):
                try:
                    url = response.url
                    if "graph.microsoft.com" not in url:
                        return
                    if not response.ok:
                        return
                    # Capture mail-scoped Bearer token from request headers
                    auth_hdr = response.request.headers.get("authorization", "")
                    if auth_hdr.lower().startswith("bearer "):
                        t = auth_hdr[7:]
                        if t.startswith("eyJ") and _token_has_mail_scope(t):
                            _cdp_token["token"] = t
                    # Capture inbox message list
                    if "/mailFolders" in url or "/messages" in url:
                        if _cdp_inbox.get("data"):
                            return  # already have it
                        data = _json.loads(response.text())
                        if (isinstance(data, dict) and
                                isinstance(data.get("value"), list) and
                                data["value"] and
                                "subject" in data["value"][0]):
                            _cdp_inbox["data"] = data
                except Exception:
                    pass

            page.on("response", _on_cdp_response)

            # Register init script so the JS interceptor persists across reloads
            for target in ([page] + ([target_ctx] if target_ctx else [])):
                try:
                    target.add_init_script(_INTERCEPT_JS)
                except Exception:
                    pass

            # Always reload so the interceptor is active from page start and
            # OWA's fresh Graph API calls are captured by both the CDP listener
            # above and the JS window.fetch patch in _INTERCEPT_JS.
            try:
                page.reload(wait_until="domcontentloaded", timeout=30_000)
            except Exception:
                pass

            # Poll until we have either inbox data (via CDP) or a usable token
            deadline = time.time() + 45
            while time.time() < deadline:
                if _cdp_inbox.get("data") or _cdp_token.get("token"):
                    break
                # Also check JS-level captures
                try:
                    tokens = page.evaluate(_MSAL_TOKEN_JS)
                    if isinstance(tokens, dict):
                        if tokens.get("graphToken") or tokens.get("owaToken"):
                            break
                except Exception:
                    pass
                time.sleep(1.5)

            # Push CDP-captured inbox data into the page so mail.py can read it
            if _cdp_inbox.get("data"):
                try:
                    page.evaluate(
                        "(d) => { window.__InboxData = d; }",
                        _cdp_inbox["data"]
                    )
                except Exception:
                    pass

            if _cdp_token.get("token"):
                try:
                    page.evaluate(
                        "(t) => { window.__MailToken = t; }",
                        _cdp_token["token"]
                    )
                except Exception:
                    pass

            user, graph_token, owa_token = _setup_page(
                page, {"token": _cdp_token.get("token", "")}, time.time() + 10
            )

            _set(status="active", user=user,
                 token=graph_token, owa_token=owa_token)

            _task_loop(page, q)

    except Exception as exc:
        _set(status="error", error=f"Browser error: {exc}")


# ── LAUNCH mode worker ────────────────────────────────────────────────────────

def _launch_worker(q: queue.Queue):
    """Launch a Playwright browser and wait for the user to log in."""
    _set(status="opening", error=None, user=None)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            os.makedirs(_SESSION_DIR, exist_ok=True)

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
                context = pw.chromium.launch_persistent_context(
                    _SESSION_DIR, **launch_kwargs
                )

            context.add_init_script(_INTERCEPT_JS)

            page = context.pages[0] if context.pages else context.new_page()

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
                    body = response.text()
                    data = _json.loads(body)
                    if isinstance(data, dict):
                        t = data.get('access_token', '')
                        if t and t.startswith('eyJ'):
                            _captured['token'] = t
                except Exception:
                    pass

            context.on("response", _on_response)

            _set(status="waiting_login")
            try:
                page.goto(config.OWA_URL, wait_until="domcontentloaded", timeout=30_000)
            except Exception:
                pass

            _AUTH_PATHS = ('/auth/', '/logon', '/login', '/sso', '/saml', '/adfs/')
            _SIGNIN_RE  = re.compile(r'sign.?in|authenticat|verif|two.?factor|mfa', re.I)

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

            user, graph_token, owa_token = _setup_page(
                page, _captured, time.time() + 30
            )

            _set(status="active", user=user,
                 token=graph_token, owa_token=owa_token)

            _task_loop(page, q)

            try:
                context.close()
            except Exception:
                pass

    except Exception as exc:
        _set(status="error", error=f"Browser error: {exc}")


# ── Public control ────────────────────────────────────────────────────────────

def start_login():
    """Launch a new browser and wait for the user to log in (LAUNCH mode)."""
    global _task_queue
    if _task_queue:
        _task_queue.put(None)
    _task_queue = queue.Queue()
    _set(status="idle", error=None, user=None)
    threading.Thread(target=_launch_worker, args=(_task_queue,), daemon=True).start()


def connect_browser():
    """Connect to an already-running Chrome (CONNECT mode)."""
    global _task_queue
    if _task_queue:
        _task_queue.put(None)
    _task_queue = queue.Queue()
    _set(status="idle", error=None, user=None)
    threading.Thread(target=_connect_worker, args=(_task_queue,), daemon=True).start()


def clear():
    global _task_queue
    if _task_queue:
        _task_queue.put(None)
    _task_queue = None
    _set(status="idle", error=None, user=None)
