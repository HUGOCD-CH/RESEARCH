"""
Mail operations via Microsoft Graph API.

Fetch calls run inside the Playwright browser so they share the authenticated
browser context. The Bearer token captured from the Azure AD login flow is
passed explicitly in the Authorization header — no CORS tricks required.
"""
import json
import auth
import config

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"

_FETCH_JS = """
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
            "No Bearer token available — the session may have expired. "
            "Please sign out and sign in again."
        )
    call = (f"({_FETCH_JS})"
            f"({json.dumps(path)}, {json.dumps(method)}, {json.dumps(body)}, {json.dumps(token)})")
    return auth.evaluate(call)


def _require_ok(result: dict, context: str = ""):
    if not result.get("ok"):
        status = result.get("status", 0)
        data   = result.get("data", {})
        err_msg = ""
        if isinstance(data, dict):
            err = data.get("error", {})
            err_msg = err.get("message", "") if isinstance(err, dict) else str(err)
        raise RuntimeError(
            f"Graph API error{' (' + context + ')' if context else ''}: "
            f"HTTP {status} {err_msg}".strip()
        )
    return result["data"]


# ── Public API ────────────────────────────────────────────────────────────────

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
        f"&$orderby=receivedDateTime%20desc"
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
        next_link = data.get("@odata.nextLink", "")
        if next_link:
            # Strip the base URL so _fetch() can prepend it
            path = next_link.replace(_GRAPH_BASE, "")
        else:
            path = ""

    return messages
