import os
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.environ["AZURE_CLIENT_ID"]
TENANT_ID = os.getenv("AZURE_TENANT_ID", "common")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
REDIRECT_URI = "http://localhost:5000/auth/callback"
SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-insecure-key-change-me")

SCOPES = [
    "https://graph.microsoft.com/Mail.Read",
    "https://graph.microsoft.com/User.Read",
]

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_CACHE_FILE = "token_cache.json"
MESSAGES_PER_PAGE = 50
