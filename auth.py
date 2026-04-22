import secrets
from exchangelib import Credentials, Account, Configuration, DELEGATE
from exchangelib.errors import UnauthorizedError
import config

# In-memory session store: token -> {email, account}
# Credentials never touch disk.
_sessions: dict = {}


def _connect(email: str, password: str):
    """Try to connect to Exchange via autodiscovery, then direct config."""
    credentials = Credentials(username=email, password=password)

    # 1. Try autodiscovery (works when DNS SRV records or well-known URLs are set up)
    try:
        account = Account(
            primary_smtp_address=email,
            credentials=credentials,
            autodiscover=True,
            access_type=DELEGATE,
        )
        _ = account.inbox.total_count  # verify connection
        return account, None
    except UnauthorizedError:
        return None, "Invalid email or password."
    except Exception:
        pass  # autodiscovery failed, try direct config

    # 2. Fall back to the configured EWS server
    try:
        cfg = Configuration(server=config.EWS_SERVER, credentials=credentials)
        account = Account(
            primary_smtp_address=email,
            config=cfg,
            autodiscover=False,
            access_type=DELEGATE,
        )
        _ = account.inbox.total_count  # verify connection
        return account, None
    except UnauthorizedError:
        return None, "Invalid email or password."
    except Exception as exc:
        return None, f"Could not connect to mail server: {exc}"


def login(email: str, password: str):
    """Verify credentials and create a session. Returns (token, error)."""
    account, error = _connect(email, password)
    if error:
        return None, error
    token = secrets.token_urlsafe(32)
    _sessions[token] = {"email": email, "account": account}
    return token, None


def get_account(token: str):
    """Return the cached EWS Account for this session, or None."""
    entry = _sessions.get(token)
    return entry["account"] if entry else None


def get_email(token: str):
    entry = _sessions.get(token)
    return entry["email"] if entry else None


def logout(token: str):
    _sessions.pop(token, None)
