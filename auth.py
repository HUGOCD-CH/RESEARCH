"""
Browser-based authentication via Playwright.

Opens a real Chrome/Chromium browser to webmail.medtronic.com and intercepts
the Bearer tokens that OWA's own JavaScript sends to graph.microsoft.com.
No Azure app registration or IT approval required.
"""
import base64
import json
import threading
import time

import requests
import config

# ── Shared auth state ────────────────────────────────────────────────────────
# status: idle | opening | waiting_login | capturing | done | error
_state: dict = {"status": "idle", "token": None, "api_base": None, "error": None, "user": None}
_lock = threading.Lock()


def _update(**kwargs):
    with _lock:
        _state.update(kwargs)


def get_state() -> dict:
    with _lock:
        return dict(_state)


def get_token() -> str | None:
    return get_state().get("token")


def get_api_base() -> str:
    return get_state().get("api_base") or config.GRAPH_BASE


# ── JWT helpers ──────────────────────────────────────────────────────────────

def _jwt_audience(token: str) -> str:
    """Decode the JWT payload (no signature verification) and return the 'aud' claim."""
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)  # fix padding
        return json.loads(base64.b64decode(payload_b64)).get("aud", "")
    except Exception:
        return ""


def _jwt_upn(token: str) -> str:
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        data = json.loads(base64.b64decode(payload_b64))
        return data.get("upn") or data.get("preferred_username") or data.get("email", "")
    except Exception:
        return ""


# ── Token verification ───────────────────────────────────────────────────────

_CANDIDATE_BASES = [
    "https://graph.microsoft.com/v1.0",
    "https://outlook.office.com/api/v2.0",
    "https://outlook.office365.com/api/v2.0",
]


def _verify_token(token: str) -> str | None:
    """
    Try the token against known Microsoft mail API bases.
    Returns the working base URL, or None if the token doesn't work anywhere.
    """
    aud = _jwt_audience(token)

    # Prefer the API that matches the token's audience
    if "graph.microsoft.com" in aud:
        ordered = _CANDIDATE_BASES
    else:
        ordered = _CANDIDATE_BASES[1:] + [_CANDIDATE_BASES[0]]

    for base in ordered:
        try:
            r = requests.get(
                f"{base}/me/messages?$top=1&$select=id",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if r.status_code == 200:
                return base
        except Exception:
            continue
    return None


# ── Playwright browser worker ────────────────────────────────────────────────

def _browser_worker():
    _update(status="opening", token=None, api_base=None, error=None, user=None)

    # Candidates keyed by which Microsoft host the request was sent to
    captured: dict[str, str] = {}  # host_key -> token

    def _on_request(request):
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return
        token = auth[7:]
        url = request.url
        for host_key, fragment in [
            ("graph", "graph.microsoft.com"),
            ("office365", "outlook.office365.com"),
            ("office", "outlook.office.com"),
            ("substrate", "substrate.office.com"),
        ]:
            if fragment in url and host_key not in captured:
                captured[host_key] = token

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

        with sync_playwright() as pw:
            # Prefer Chrome for corporate SSO; fall back to bundled Chromium
            try:
                browser = pw.chromium.launch(headless=False, channel="chrome")
            except Exception:
                browser = pw.chromium.launch(headless=False)

            # ignore_https_errors bypasses corporate SSL-inspection cert errors.
            # Medtronic's proxy re-signs traffic with its own root CA which is
            # trusted by Windows/Chrome but not by Playwright's bundled Chromium.
            context = browser.new_context(ignore_https_errors=True)
            context.on("request", _on_request)
            page = context.new_page()

            _update(status="waiting_login")
            page.goto(config.OWA_URL, wait_until="domcontentloaded", timeout=30_000)

            # Wait until the user is past the login page (OWA inbox loaded)
            try:
                page.wait_for_function(
                    """() => {
                        const url = window.location.href;
                        const notLogin = !url.toLowerCase().includes('logon') &&
                                         !url.toLowerCase().includes('login') &&
                                         !url.toLowerCase().includes('sso');
                        const hasContent = document.querySelector(
                            '[role="main"], [aria-label="Message list"], #app'
                        ) !== null;
                        return notLogin && hasContent;
                    }""",
                    timeout=300_000,  # 5-minute login window
                )
            except PWTimeout:
                _update(status="error", error="Login timed out. Please try again.")
                browser.close()
                return

            # Give OWA a moment to fire its initial API requests
            _update(status="capturing")
            page.wait_for_timeout(4_000)

            # If no token yet, scroll or hover to trigger mail API calls
            if not captured:
                try:
                    page.keyboard.press("F5")
                    page.wait_for_timeout(4_000)
                except Exception:
                    pass

            browser.close()

    except Exception as exc:
        _update(status="error", error=f"Browser error: {exc}")
        return

    # Try captured tokens in priority order
    for key in ("graph", "office365", "office", "substrate"):
        token = captured.get(key)
        if not token:
            continue
        api_base = _verify_token(token)
        if api_base:
            user = _jwt_upn(token)
            _update(status="done", token=token, api_base=api_base, user=user)
            return

    _update(
        status="error",
        error=(
            "Signed in successfully, but could not capture a usable API token. "
            "OWA may not have made any mail API calls yet. "
            "Try clicking an email in the OWA window before it closes, then sign in again."
        ),
    )


def start_login():
    _update(status="idle", token=None, api_base=None, error=None, user=None)
    t = threading.Thread(target=_browser_worker, daemon=True)
    t.start()


def clear():
    _update(status="idle", token=None, api_base=None, error=None, user=None)
