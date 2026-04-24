"""
Mail operations via the Playwright browser.

Two API paths are tried automatically:
  1. Microsoft Graph API (graph.microsoft.com/v1.0) — used when MSAL.js has
     stored a Graph-scoped token (aud=graph.microsoft.com) in sessionStorage.
  2. OWA REST API v2.0 (same-origin, outlook.office365.com/api/v2.0) — used
     when only an OWA-scoped token is available.  The call runs inside the
     browser which is already on outlook.office365.com, so session cookies
     are included automatically and CORS is not an issue.

Graph responses use camelCase (ready to render).
OWA REST v2 responses use PascalCase and are normalised to camelCase.
"""
import json
import auth
import config

# ── Dual-path JavaScript fetch helper ────────────────────────────────────────
# Decodes the JWT audience to pick the right endpoint at call time.

_FETCH_JS = """
async (graphPath, method, body, graphToken, owaToken) => {
    const decodeAud = (t) => {
        try {
            const p = JSON.parse(atob(t.split('.')[1].replace(/-/g,'+').replace(/_/g,'/')));
            const a = p.aud;
            return (Array.isArray(a) ? a.join(' ') : (a || '')).toLowerCase();
        } catch(e) { return ''; }
    };
    const GRAPH = ['graph.microsoft.com', '00000003-0000-0000-c000-000000000000'];
    const isGraphTok = graphToken && GRAPH.some(g => decodeAud(graphToken).includes(g));

    let url, opts;
    if (isGraphTok) {
        url = 'https://graph.microsoft.com/v1.0' + graphPath;
        opts = {
            method: method || 'GET',
            headers: {
                'Accept':        'application/json',
                'Authorization': 'Bearer ' + graphToken,
            }
        };
        if (body) {
            opts.headers['Content-Type'] = 'application/json';
            opts.body = JSON.stringify(body);
        }
    } else {
        // Same-origin OWA REST v2 — session cookies sent automatically
        url = '/api/v2.0' + graphPath;
        opts = {
            method: method || 'GET',
            credentials: 'include',
            headers: { 'Accept': 'application/json; odata=minimalmetadata' }
        };
        if (owaToken) opts.headers['Authorization'] = 'Bearer ' + owaToken;
        if (body) {
            opts.headers['Content-Type'] = 'application/json';
            opts.body = JSON.stringify(body);
        }
    }
    try {
        const r = await fetch(url, opts);
        const text = await r.text();
        let data;
        try { data = JSON.parse(text); } catch(e) { data = text; }
        return { ok: r.ok, status: r.status, data: data,
                 mode: isGraphTok ? 'graph' : 'owa' };
    } catch(e) {
        return { ok: false, status: 0, error: e.toString(),
                 mode: isGraphTok ? 'graph' : 'owa' };
    }
}
"""


def _fetch(path: str, method: str = "GET", body=None) -> dict:
    graph_tok = auth.get_token()
    owa_tok   = auth.get_owa_token()
    if not graph_tok and not owa_tok:
        raise RuntimeError(
            "No Bearer token available — MSAL.js has not yet acquired tokens. "
            "Wait a moment and reload, or sign out and sign in again."
        )
    call = (f"({_FETCH_JS})"
            f"({json.dumps(path)}, {json.dumps(method)}, {json.dumps(body)}, "
            f"{json.dumps(graph_tok)}, {json.dumps(owa_tok)})")
    return auth.evaluate(call)


def _require_ok(result: dict, context: str = "") -> object:
    if not result.get("ok"):
        status  = result.get("status", 0)
        mode    = result.get("mode", "?")
        data    = result.get("data", {})
        err_msg = result.get("error", "")
        if not err_msg and isinstance(data, dict):
            err = data.get("error", {})
            err_msg = (err.get("message", "") if isinstance(err, dict) else str(err))
        raise RuntimeError(
            f"{'Graph' if mode == 'graph' else 'OWA'} API error"
            f"{' (' + context + ')' if context else ''}: "
            f"HTTP {status} {err_msg}".strip()
        )
    return result["data"]


# ── Response normalisation ────────────────────────────────────────────────────
# OWA REST v2 uses PascalCase; Graph uses camelCase.  Normalise to camelCase.

def _addr(raw) -> dict:
    if isinstance(raw, dict) and "emailAddress" in raw:
        return raw   # already Graph / camelCase
    if isinstance(raw, dict):
        ea = raw.get("EmailAddress", raw)
        return {"emailAddress": {
            "name":    ea.get("Name", ""),
            "address": ea.get("Address", ""),
        }}
    return {"emailAddress": {"name": "", "address": ""}}


def _normalise(msg: dict) -> dict:
    """No-op for Graph responses; converts PascalCase OWA responses to camelCase."""
    if "id" in msg:
        return msg   # already camelCase (Graph)
    body_raw = msg.get("Body", {})
    return {
        "id":               msg.get("Id", ""),
        "subject":          msg.get("Subject", ""),
        "from":             _addr(msg.get("From", {})),
        "receivedDateTime": msg.get("ReceivedDateTime", ""),
        "isRead":           msg.get("IsRead", True),
        "bodyPreview":      msg.get("BodyPreview", ""),
        "body": {
            "contentType": body_raw.get("ContentType", "Text").lower(),
            "content":     body_raw.get("Content", ""),
        },
        "toRecipients": [_addr(r) for r in msg.get("ToRecipients", [])],
        "ccRecipients": [_addr(r) for r in msg.get("CcRecipients", [])],
    }


# ── Path helpers ──────────────────────────────────────────────────────────────

def _inbox_path(top: int, skip: int, owa_mode: bool = False) -> str:
    if owa_mode:
        # OWA REST v2 uses PascalCase field names in $select
        return (f"/me/mailFolders/inbox/messages"
                f"?$top={top}&$skip={skip}"
                f"&$orderby=ReceivedDateTime%20desc"
                f"&$select=Id,Subject,From,ReceivedDateTime,IsRead,BodyPreview")
    return (f"/me/mailFolders/inbox/messages"
            f"?$top={top}&$skip={skip}"
            f"&$orderby=receivedDateTime%20desc"
            f"&$select=id,subject,from,receivedDateTime,isRead,bodyPreview")


# ── Public API ────────────────────────────────────────────────────────────────

def get_user_profile() -> dict:
    try:
        # Graph uses camelCase select, OWA v2 uses PascalCase — try both
        result = _fetch("/me?$select=displayName,mail,DisplayName,EmailAddress")
        data = _require_ok(result, "profile")
        if isinstance(data, dict):
            return {
                "displayName": data.get("displayName") or data.get("DisplayName", ""),
                "mail":        data.get("mail") or data.get("EmailAddress", ""),
            }
    except Exception:
        pass
    return {"displayName": auth.get_state().get("user", ""), "mail": ""}


def get_messages(top: int = config.MESSAGES_PER_PAGE, skip: int = 0) -> dict:
    # Try Graph path first; fall back to OWA-style path on 4xx
    result = _fetch(_inbox_path(top, skip))
    if not result.get("ok") and result.get("status", 0) in (400, 401, 403, 404):
        result = _fetch(_inbox_path(top, skip, owa_mode=True))
    if not result.get("ok") and result.get("status", 0) in (400, 401, 403, 404):
        # Last resort: read what OWA already loaded into the page cache
        cached = auth.evaluate("() => window.__InboxData || null")
        if cached and isinstance(cached, dict) and cached.get("value"):
            cached["value"] = [_normalise(m) for m in cached["value"]]
            return cached
    data = _require_ok(result, "list messages")
    if isinstance(data, dict):
        data["value"] = [_normalise(m) for m in data.get("value", [])]
    return data


def get_message(message_id: str) -> dict:
    graph_qs = "?$select=id,subject,from,toRecipients,ccRecipients,receivedDateTime,body,isRead"
    owa_qs   = "?$select=Id,Subject,From,ToRecipients,CcRecipients,ReceivedDateTime,Body,IsRead"
    result = _fetch(f"/me/messages/{message_id}{graph_qs}")
    if not result.get("ok") and result.get("status", 0) in (400, 401, 403, 404):
        result = _fetch(f"/me/messages/{message_id}{owa_qs}")
    if not result.get("ok") and result.get("status", 0) in (400, 401, 403, 404):
        # Read from page-level cache populated by OWA's own fetch interceptor
        cached = auth.evaluate(
            f"() => window.__MessageData && window.__MessageData[{json.dumps(message_id)}] || null"
        )
        if cached and isinstance(cached, dict):
            return _normalise(cached)
    return _normalise(_require_ok(result, "get message"))


def mark_as_read(message_id: str):
    try:
        _fetch(f"/me/messages/{message_id}", "PATCH", {"isRead": True})
    except Exception:
        pass   # non-critical


def get_todays_messages() -> list[dict]:
    """Return all inbox messages received today (local midnight → now), with body."""
    import datetime
    today = datetime.date.today().isoformat() + "T00:00:00Z"

    graph_qs = (f"?$filter=receivedDateTime ge {today}"
                f"&$orderby=receivedDateTime desc"
                f"&$select=id,subject,from,toRecipients,receivedDateTime,isRead,body"
                f"&$top=100")
    owa_qs = (f"?$filter=ReceivedDateTime ge {today}"
              f"&$orderby=ReceivedDateTime desc"
              f"&$select=Id,Subject,From,ToRecipients,ReceivedDateTime,IsRead,Body"
              f"&$top=100")

    messages: list[dict] = []

    # Detect which mode we're in by trying the first page
    path = f"/me/mailFolders/inbox/messages{graph_qs}"
    result = _fetch(path)
    if not result.get("ok") and result.get("status", 0) in (400, 401, 403, 404):
        path = f"/me/mailFolders/inbox/messages{owa_qs}"
        result = _fetch(path)

    while path and len(messages) < 500:
        data = _require_ok(result, "today's messages")
        if not isinstance(data, dict):
            break
        messages.extend([_normalise(m) for m in data.get("value", [])])
        next_link = data.get("@odata.nextLink") or data.get("odata.nextLink", "")
        if next_link:
            # Strip base URL (Graph or OWA) so _fetch prepends correctly
            for base in ("https://graph.microsoft.com/v1.0",
                         "https://outlook.office365.com/api/v2.0"):
                next_link = next_link.replace(base, "")
            path = next_link
            result = _fetch(path)
        else:
            path = ""

    return messages
