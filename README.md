# Outlook Local Viewer

A lightweight local web app to read your corporate Outlook emails at `http://localhost:5000` — no Azure app registration or IT admin approval required.

It connects directly to your company's Exchange server via **Exchange Web Services (EWS)** using your regular email and password. Nothing is stored on disk except a `.env` file you create yourself.

## How it works

- Runs at `http://localhost:5000` — only your computer can access it
- You log in with your corporate email and password via a local form
- The app connects to `webmail.medtronic.com` using the Exchange Web Services protocol (the same protocol Outlook desktop uses)
- Your password is held in memory only; it is never written to disk
- Closes the connection when you sign out or stop the app

---

## Setup (5 minutes)

### Step 1 — Install Python 3

Python 3.9 or newer is required. Download it from [python.org](https://www.python.org/downloads/) if you don't have it.

### Step 2 — Download or clone this project

If you have git:
```bash
git clone <repo-url>
cd RESEARCH
```

Or download and extract the ZIP from GitHub.

### Step 3 — Create a virtual environment and install dependencies

```bash
python3 -m venv .venv

# Activate it:
source .venv/bin/activate        # macOS / Linux
.venv\Scripts\activate           # Windows (Command Prompt)

pip install -r requirements.txt
```

### Step 4 — Configure

```bash
cp .env.example .env
```

Open `.env` in any text editor and set a random secret key:

```bash
# Run this to generate a key, then paste the output into .env
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Your `.env` should look like:
```
EWS_SERVER=webmail.medtronic.com
FLASK_SECRET_KEY=abc123...your-random-key-here
```

### Step 5 — Run

```bash
python3 app.py
```

Open your browser and go to **http://localhost:5000**.

Enter your corporate email (`you@medtronic.com`) and your Windows/Outlook password. The app will connect to the mail server and display your inbox.

---

## Subsequent runs

```bash
source .venv/bin/activate   # if not already active
python3 app.py
```

You will need to sign in each time you start the app (no token is stored between runs).

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `Could not connect to mail server` | Check you're on the corporate network or VPN. EWS is usually blocked from outside the network. |
| `Invalid email or password` | Double-check your credentials. Try logging in to `https://webmail.medtronic.com` in a browser first to confirm they work. |
| Port 5000 already in use (macOS) | AirPlay Receiver uses port 5000 on macOS Monterey+. Change `port=5000` in `app.py` to `5001` and restart. |
| Slow initial connection | The first connection triggers autodiscovery (DNS lookups). Subsequent requests in the same session are faster. |
| `KeyError: FLASK_SECRET_KEY` | You haven't created `.env` or it's missing the key. Re-run Step 4. |

---

## Security notes

- Your password is **never written to disk**. It lives in the Flask app's memory only and is cleared when you sign out or stop the server.
- The `.env` file contains only your secret key — not your password.
- HTML emails are rendered in a sandboxed `<iframe>` with JavaScript disabled, preventing malicious email content from executing code in your browser.
- The app only binds to `127.0.0.1` (localhost) — it is not accessible from other devices on your network.
- Stop the app (`Ctrl+C`) when you're done to clear credentials from memory.

---

## File overview

| File | Purpose |
|---|---|
| `app.py` | Flask web server and routes |
| `auth.py` | EWS login and in-memory session management |
| `mail.py` | Exchange Web Services API calls via `exchangelib` |
| `config.py` | Configuration loaded from `.env` |
| `templates/` | HTML page templates |
| `static/style.css` | Stylesheet |
| `.env` | Your secret key (not committed to git) |
