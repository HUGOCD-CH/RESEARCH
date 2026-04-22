import os
from dotenv import load_dotenv

load_dotenv()

OWA_URL = os.getenv("OWA_URL", "https://webmail.medtronic.com")
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-insecure-key-change-me")
MESSAGES_PER_PAGE = 50
