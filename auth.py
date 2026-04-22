import json
import os
import msal
import config


def load_cache():
    cache = msal.SerializableTokenCache()
    if os.path.exists(config.TOKEN_CACHE_FILE):
        with open(config.TOKEN_CACHE_FILE, "r") as f:
            cache.deserialize(f.read())
    return cache


def save_cache(cache):
    if cache.has_state_changed:
        with open(config.TOKEN_CACHE_FILE, "w") as f:
            f.write(cache.serialize())


def get_msal_app(cache=None):
    return msal.PublicClientApplication(
        client_id=config.CLIENT_ID,
        authority=config.AUTHORITY,
        token_cache=cache,
    )


def get_token_from_cache():
    cache = load_cache()
    app = get_msal_app(cache)
    accounts = app.get_accounts()
    if not accounts:
        return None
    result = app.acquire_token_silent(config.SCOPES, account=accounts[0])
    save_cache(cache)
    if result and "access_token" in result:
        return result["access_token"]
    return None


def build_auth_url():
    cache = load_cache()
    app = get_msal_app(cache)
    flow = app.initiate_auth_code_flow(
        scopes=config.SCOPES,
        redirect_uri=config.REDIRECT_URI,
    )
    return flow


def acquire_token_by_auth_code_flow(auth_code_flow, auth_response):
    cache = load_cache()
    app = get_msal_app(cache)
    result = app.acquire_token_by_auth_code_flow(auth_code_flow, auth_response)
    save_cache(cache)
    return result


def clear_cache():
    if os.path.exists(config.TOKEN_CACHE_FILE):
        os.remove(config.TOKEN_CACHE_FILE)
