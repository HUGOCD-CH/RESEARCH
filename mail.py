"""
Mail fetching via Microsoft API.

Supports both Graph API (graph.microsoft.com/v1.0) and the Exchange REST API
(outlook.office.com/api/v2.0). Both return OData JSON; the Exchange REST API
uses PascalCase field names which we normalise to the Graph API (camelCase) format
so that templates don't need to care which backend is active.
"""
import requests
import config


def _get(token: str, api_base: str, path: str, params: dict | None = None) -> dict:
    resp = requests.get(
        api_base + path,
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _patch(token: str, api_base: str, path: str, body: dict):
    resp = requests.patch(
        api_base + path,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=15,
    )
    resp.raise_for_status()


# ── Response normalisation ───────────────────────────────────────────────────
# Graph API uses camelCase; Exchange REST API uses PascalCase.
# We convert everything to Graph API's camelCase format.

def _addr(raw: dict) -> dict:
    """Normalise an emailAddress dict from either API."""
    if "emailAddress" in raw:               # already Graph format
        return raw
    addr = raw.get("EmailAddress", raw)
    return {"emailAddress": {"name": addr.get("Name", ""), "address": addr.get("Address", "")}}


def _normalise(msg: dict) -> dict:
    """Return a Graph-format message dict regardless of which API returned it."""
    if "id" in msg:                         # already Graph format
        return msg

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


# ── Public API ───────────────────────────────────────────────────────────────

def get_user_profile(token: str, api_base: str) -> dict:
    try:
        return _get(token, api_base, "/me",
                    params={"$select": "displayName,mail,userPrincipalName"})
    except Exception:
        return {}


def get_messages(token: str, api_base: str, top: int = config.MESSAGES_PER_PAGE, skip: int = 0) -> dict:
    raw = _get(
        token, api_base,
        "/me/mailFolders/inbox/messages",
        params={
            "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview,"
                       "Id,Subject,From,ReceivedDateTime,IsRead,BodyPreview",
            "$orderby": "receivedDateTime desc,ReceivedDateTime desc",
            "$top": top,
            "$skip": skip,
        },
    )
    raw["value"] = [_normalise(m) for m in raw.get("value", [])]
    return raw


def get_message(token: str, api_base: str, message_id: str) -> dict:
    raw = _get(
        token, api_base,
        f"/me/messages/{message_id}",
        params={
            "$select": "id,subject,from,toRecipients,ccRecipients,"
                       "receivedDateTime,body,isRead,"
                       "Id,Subject,From,ToRecipients,CcRecipients,"
                       "ReceivedDateTime,Body,IsRead",
        },
    )
    return _normalise(raw)


def mark_as_read(token: str, api_base: str, message_id: str):
    try:
        _patch(token, api_base, f"/me/messages/{message_id}", {"isRead": True, "IsRead": True})
    except Exception:
        pass  # non-critical
