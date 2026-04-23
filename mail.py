"""
Mail operations executed as fetch() calls inside the Playwright browser.

The browser runs with --disable-web-security so fetch() calls from the
outlook.office365.com page can reach webmail.medtronic.com (Medtronic's
own Exchange server) with session cookies — bypassing CORS restrictions.
Exchange REST API v2 is still available at webmail.medtronic.com even
though Microsoft retired it from outlook.office365.com.

Responses are normalised to the Graph-API camelCase format the templates use.
"""
import json
import auth
import config

# ── JavaScript fetch helper ───────────────────────────────────────────────────
# Uses absolute URL to webmail.medtronic.com so the retired endpoint at
# outlook.office365.com is never hit.  credentials:'include' sends the
# Exchange session cookies that were set during the SSO redirect chain.

_FETCH_JS = """
async (path, method, body) => {
    const base = """ + json.dumps(config.OWA_URL) + """;
    const opts = {
        method: method || 'GET',
        credentials: 'include',
        headers: { 'Accept': 'application/json; odata=minimalmetadata' }
    };
    if (body) {
        opts.headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(body);
    }
    try {
        const r = await fetch(base + path, opts);
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
    call = f"""({_FETCH_JS})({json.dumps(path)}, {json.dumps(method)}, {json.dumps(body)})"""
    return auth.evaluate(call)


def _require_ok(result: dict, context: str = ""):
    if not result.get("ok"):
        status = result.get("status", 0)
        err = result.get("error", "")
        raise RuntimeError(
            f"Exchange API error{' (' + context + ')' if context else ''}: "
            f"HTTP {status} {err}".strip()
        )
    return result["data"]


# ── Candidate API paths ───────────────────────────────────────────────────────

def _inbox_path(top: int, skip: int) -> str:
    qs = (
        f"?$top={top}&$skip={skip}"
        f"&$orderby=ReceivedDateTime%20desc"
        f"&$select=Id,Subject,From,ReceivedDateTime,IsRead,BodyPreview"
    )
    return f"/api/v2.0/me/MailFolders/inbox/messages{qs}"


# ── Response normalisation ────────────────────────────────────────────────────
# Exchange REST API uses PascalCase; normalise to Graph camelCase.

def _addr(raw) -> dict:
    if isinstance(raw, dict) and "emailAddress" in raw:
        return raw   # already Graph format
    if isinstance(raw, dict):
        ea = raw.get("EmailAddress", raw)
        return {"emailAddress": {
            "name":    ea.get("Name", ""),
            "address": ea.get("Address", ""),
        }}
    return {"emailAddress": {"name": "", "address": ""}}


def _normalise(msg: dict) -> dict:
    if "id" in msg and "subject" in msg:
        return msg   # already Graph format
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


# ── Public API ────────────────────────────────────────────────────────────────

def get_user_profile() -> dict:
    try:
        data = _require_ok(_fetch("/api/v2.0/me?$select=DisplayName,EmailAddress"), "profile")
        if isinstance(data, dict):
            return {
                "displayName": data.get("DisplayName") or data.get("displayName", ""),
                "mail":        data.get("EmailAddress") or data.get("mail", ""),
            }
    except Exception:
        pass
    return {"displayName": auth.get_state().get("user", ""), "mail": ""}


def get_messages(top: int = config.MESSAGES_PER_PAGE, skip: int = 0) -> dict:
    result = _fetch(_inbox_path(top, skip))
    data = _require_ok(result, "list messages")
    if isinstance(data, dict):
        data["value"] = [_normalise(m) for m in data.get("value", [])]
    return data


def get_message(message_id: str) -> dict:
    qs = ("?$select=Id,Subject,From,ToRecipients,CcRecipients,"
          "ReceivedDateTime,Body,IsRead")
    result = _fetch(f"/api/v2.0/me/messages/{message_id}{qs}")
    return _normalise(_require_ok(result, "get message"))


def mark_as_read(message_id: str):
    try:
        _fetch(f"/api/v2.0/me/messages/{message_id}", "PATCH", {"IsRead": True})
    except Exception:
        pass   # non-critical


def get_todays_messages() -> list[dict]:
    """Return all inbox messages received today (local midnight → now), with body."""
    import datetime
    today = datetime.date.today().isoformat() + "T00:00:00Z"
    qs = (
        f"?$filter=ReceivedDateTime ge {today}"
        f"&$orderby=ReceivedDateTime desc"
        f"&$select=Id,Subject,From,ToRecipients,ReceivedDateTime,IsRead,Body"
        f"&$top=100"
    )
    messages: list[dict] = []
    path = f"/api/v2.0/me/MailFolders/inbox/messages{qs}"

    while path and len(messages) < 500:
        result = _fetch(path)
        data = _require_ok(result, "today's messages")
        if not isinstance(data, dict):
            break
        batch = [_normalise(m) for m in data.get("value", [])]
        messages.extend(batch)
        path = data.get("@odata.nextLink") or data.get("odata.nextLink")

    return messages
