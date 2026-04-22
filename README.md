# Outlook Local Viewer

Read your Medtronic emails locally at `http://localhost:5000` — **no Azure app registration, no IT approval, no client ID required**.

## How it works

1. You click **Open Webmail & Sign In** in the local app.
2. A browser window opens to `webmail.medtronic.com`.
3. You sign in normally (corporate SSO and MFA are handled by the browser as usual).
4. Once your inbox loads, the app intercepts the authentication token that OWA's own JavaScript sends to Microsoft's API.
5. The browser closes. The local app uses that token to fetch your emails via the Microsoft Graph API.

Your password never touches this app. The token is held in memory only and cleared when you sign out or stop the server.

---

## Setup

### Step 1 — Install Python 3.9+

Download from [python.org](https://www.python.org/downloads/) if needed.

### Step 2 — Install dependencies

```bash
# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
.venv\Scripts\activate           # Windows

# Install Python packages
pip install -r requirements.txt

# Install the Playwright browser (one-time download, ~150 MB)
playwright install chromium
```

> **Note:** If your company's Chrome is already installed, the app will try to use it first (better SSO support). `playwright install chromium` is a fallback if Chrome isn't found.

### Step 3 — Configure

```bash
cp .env.example .env
```

Open `.env` and set a random secret key:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
# Paste the output as FLASK_SECRET_KEY in .env
```

### Step 4 — Run

```bash
python3 app.py
```

Open your browser at **http://localhost:5000** and click **Open Webmail & Sign In**.

---

## Token expiry

Microsoft access tokens last approximately **1 hour**. When yours expires, you'll be redirected back to the sign-in page automatically. Just click the button again — if your corporate SSO session is still active in the browser, sign-in will be instant (no password entry required).

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Could not capture authentication token" | OWA may not have loaded its inbox before the browser closed. Try again and wait a few extra seconds after the inbox appears. |
| Browser opens but SSO doesn't work | Make sure you're on the corporate network or VPN. Try signing in manually and waiting for the full inbox to load. |
| "playwright install" fails behind a proxy | Set `HTTPS_PROXY=http://your-proxy:port` before running `playwright install chromium`. |
| Port 5000 already in use (macOS) | AirPlay Receiver uses port 5000. Change `port=5000` to `port=5001` in `app.py`. |
| App says "opening" but no browser appears | Chrome may not be installed. Run `playwright install chromium` to ensure the fallback browser is available. |

---

## Security notes

- Your credentials are entered directly on `webmail.medtronic.com` — this app never sees your password.
- The captured token is held in memory only; it is not written to disk.
- HTML emails render in a sandboxed `<iframe>` with JavaScript disabled.
- The app only listens on `127.0.0.1` — not accessible from other devices on your network.

---

## File overview

| File | Purpose |
|---|---|
| `app.py` | Flask routes |
| `auth.py` | Playwright browser session + token interception |
| `mail.py` | Microsoft API calls (Graph API or Exchange REST) |
| `config.py` | Settings from `.env` |
| `templates/` | HTML templates |
| `static/style.css` | Stylesheet |
