import os
from dotenv import load_dotenv

load_dotenv()

# EWS server hostname — defaults to the Medtronic webmail server.
EWS_SERVER = os.getenv("EWS_SERVER", "webmail.medtronic.com")

SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-insecure-key-change-me")

MESSAGES_PER_PAGE = 50
