from exchangelib.items import Message, HTMLBody
import config

_LIST_FIELDS = (
    "id",
    "changekey",
    "subject",
    "sender",
    "datetime_received",
    "is_read",
)


def get_messages(account, skip: int = 0, top: int = config.MESSAGES_PER_PAGE):
    items = (
        account.inbox.only(*_LIST_FIELDS)
        .order_by("-datetime_received")[skip : skip + top]
    )
    return list(items)


def get_message(account, item_id: str, changekey: str):
    msg = Message(item_id=item_id, changekey=changekey, account=account)
    msg.refresh()
    return msg


def mark_as_read(msg):
    if not msg.is_read:
        msg.is_read = True
        msg.save(update_fields=["is_read"])


def body_parts(msg):
    """Return (body_content: str, body_is_html: bool)."""
    body = msg.body
    if body is None:
        return "", False
    return str(body), isinstance(body, HTMLBody)
