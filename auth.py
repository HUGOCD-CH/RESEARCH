import os
import threading
import msal
import config

_cache_lock = threading.Lock()

# In-memory registry of in-progress device flows: poll_id -> status dict
_pending: dict = {}


# ── Token cache (persisted to disk so login survives restarts) ──────────────

def _load_cache():
    cache = msal.SerializableTokenCache()
    if os.path.exists(config.TOKEN_CACHE_FILE):
        with open(config.TOKEN_CACHE_FILE, "r") as f:
            cache.deserialize(f.read())
    return cache


def _save_cache(cache):
    if cache.has_state_changed:
        with _cache_lock:
            with open(config.TOKEN_CACHE_FILE, "w") as f:
                f.write(cache.serialize())


def _msal_app(cache=None):
    return msal.PublicClientApplication(
        client_id=config.CLIENT_ID,
        authority=config.AUTHORITY,
        token_cache=cache,
    )


# ── Silent token acquisition (used on every request) ────────────────────────

def get_token():
    """Return a valid access token from cache, or None if the user must re-auth."""
    cache = _load_cache()
    app = _msal_app(cache)
    accounts = app.get_accounts()
    if not accounts:
        return None
    result = app.acquire_token_silent(config.SCOPES, account=accounts[0])
    _save_cache(cache)
    if result and "access_token" in result:
        return result["access_token"]
    return None


def get_display_name():
    """Return the cached account's display name/email for the nav bar."""
    cache = _load_cache()
    app = _msal_app(cache)
    accounts = app.get_accounts()
    if accounts:
        return accounts[0].get("username", "")
    return ""


# ── Device code flow ─────────────────────────────────────────────────────────

def start_device_flow():
    """
    Initiate a device code flow.
    Returns the flow dict (contains user_code, verification_uri, expires_in).
    """
    cache = _load_cache()
    app = _msal_app(cache)
    flow = app.initiate_device_flow(scopes=config.SCOPES)
    if "user_code" not in flow:
        raise RuntimeError("Could not start device flow: " + str(flow.get("error_description", flow)))
    return flow


def _poll_worker(flow: dict, poll_id: str):
    """Background thread: blocks until the user completes auth or flow expires."""
    cache = _load_cache()
    app = _msal_app(cache)
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" in result:
        _save_cache(cache)
        _pending[poll_id] = {"status": "done"}
    else:
        _pending[poll_id] = {
            "status": "error",
            "error": result.get("error_description") or result.get("error", "Authentication failed"),
        }


def start_polling(flow: dict, poll_id: str):
    """Launch the background polling thread for the given device flow."""
    _pending[poll_id] = {"status": "pending"}
    t = threading.Thread(target=_poll_worker, args=(flow, poll_id), daemon=True)
    t.start()


def check_poll(poll_id: str) -> dict:
    return _pending.get(poll_id, {"status": "unknown"})


# ── Logout ───────────────────────────────────────────────────────────────────

def clear_cache():
    if os.path.exists(config.TOKEN_CACHE_FILE):
        os.remove(config.TOKEN_CACHE_FILE)
