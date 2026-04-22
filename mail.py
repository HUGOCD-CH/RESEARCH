import requests
import config


def _get(token, path, params=None):
    resp = requests.get(
        config.GRAPH_BASE + path,
        headers={"Authorization": f"Bearer {token}"},
        params=params,
    )
    resp.raise_for_status()
    return resp.json()


def _patch(token, path, body):
    resp = requests.patch(
        config.GRAPH_BASE + path,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=body,
    )
    resp.raise_for_status()


def get_user_profile(token):
    return _get(token, "/me", params={"$select": "displayName,mail,userPrincipalName"})


def get_messages(token, top=config.MESSAGES_PER_PAGE, skip=0):
    return _get(
        token,
        "/me/mailFolders/inbox/messages",
        params={
            "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview",
            "$orderby": "receivedDateTime desc",
            "$top": top,
            "$skip": skip,
        },
    )


def get_message(token, message_id):
    return _get(
        token,
        f"/me/messages/{message_id}",
        params={
            "$select": "id,subject,from,toRecipients,ccRecipients,receivedDateTime,body,isRead"
        },
    )


def mark_as_read(token, message_id):
    _patch(token, f"/me/messages/{message_id}", {"isRead": True})
