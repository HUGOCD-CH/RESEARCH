"""
Mail operations via Microsoft Graph API, executed as fetch() calls inside
the Playwright browser. The Bearer token is intercepted from OWA's own
Graph API requests (window.__MailToken) and reused for our calls.

Graph API endpoint: https://graph.microsoft.com/v1.0/me/...
CORS is supported by Graph API, so cross-origin requests from
outlook.office365.com work fine with Authorization headers.
"""
import json
import auth
import config

# ── Graph API fetch helper ────────────────────────────────────────────────────

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"

_GRAPH_FETCH_JS = """
async (path, method, body, token) => {
    const opts = {
        method: method || 'GET',
        headers: {
            'Accept':        'application/json',
            'Authorization': 'Bearer ' + token,
        }
    };
    if (body) {
        opts.headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(body);
    }
    try {
        const r = await fetch('https://graph.microsoft.com/v1.0' + path, opts);
        const text = await r.text();
        let data;
        try { data = JSON.parse(text); } catch(e) { data = text; }
        return { ok: r.ok, status: r.status, data: data };
    } catch(e) {
        return { ok: false, status: 0, error: e.toString() };
    }
}
"""

def _fetch(path: str, method: str = "GET", body=None) -> dict:
    token = auth.get_token()
    if not token:
        raise RuntimeError(
            "No Bearer token available. The browser session may not be fully loaded. "
            "Please sign out and sign in again."
        )
    call = (f"({_GRAPH_FETCH_JS})"
            f"({json.dumps(path)}, {json.dumps(method)}, {json.dumps(body)}, {json.dumps(token)})")
    return auth.evaluate(call)


def _require_ok(result: dict, context: str = ""):
    if not result.get("ok"):
        status = result.get("status", 0)
        err = result.get("error", "")
        raise RuntimeError(
            f"Graph API error{' (' + context + ')' if context else ''}: "
            f"HTTP {status} {err}".strip()
        )
    return result["data"]


# ── Public API ────────────────────────────────────────────────────────────────
# Graph API already returns camelCase keys matching our templates, so no
# normalisation needed.  toRecipients/ccRecipients use the same shape too.

def get_user_profile() -> dict:
    try:
        data = _require_ok(_fetch("/me?$select=displayName,mail"), "profile")
        if isinstance(data, dict):
            return {
                "displayName": data.get("displayName", ""),
                "mail":        data.get("mail", ""),
            }
    except Exception:
        pass
    return {"displayName": auth.get_state().get("user", ""), "mail": ""}


def get_messages(top: int = config.MESSAGES_PER_PAGE, skip: int = 0) -> dict:
    qs = (
        f"?$top={top}&$skip={skip}"
        f"&$orderby=receivedDateTime desc"
        f"&$select=id,subject,from,receivedDateTime,isRead,bodyPreview"
    )
    result = _fetch(f"/me/mailFolders/inbox/messages{qs}")
    return _require_ok(result, "list messages")


def get_message(message_id: str) -> dict:
    qs = "?$select=id,subject,from,toRecipients,ccRecipients,receivedDateTime,body,isRead"
    result = _fetch(f"/me/messages/{message_id}{qs}")
    return _require_ok(result, "get message")


def mark_as_read(message_id: str):
    try:
        _fetch(f"/me/messages/{message_id}", "PATCH", {"isRead": True})
    except Exception:
        pass   # non-critical


def get_todays_messages() -> list[dict]:
    """Return all inbox messages received today (local midnight → now), with body."""
    import datetime
    today = datetime.date.today().isoformat() + "T00:00:00Z"
    qs = (
        f"?$filter=receivedDateTime ge {today}"
        f"&$orderby=receivedDateTime desc"
        f"&$select=id,subject,from,toRecipients,receivedDateTime,isRead,body"
        f"&$top=100"
    )
    messages: list[dict] = []
    path = f"/me/mailFolders/inbox/messages{qs}"

    while path and len(messages) < 500:
        result = _fetch(path)
        data = _require_ok(result, "today's messages")
        if not isinstance(data, dict):
            break
        messages.extend(data.get("value", []))
        path = data.get("@odata.nextLink") or data.get("odata.nextLink")
        # nextLink from Graph API is absolute — strip the base for _fetch
        if path and path.startswith("https://graph.microsoft.com/v1.0"):
            path = path[len("https://graph.microsoft.com/v1.0"):]

    return messages
