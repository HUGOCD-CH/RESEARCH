# Outlook Local Viewer

A lightweight local web app that lets you read your Outlook or Microsoft 365 emails in a browser — running entirely on your own computer. Nothing is stored in the cloud beyond what Microsoft already holds.

## How it works

- Runs at `http://localhost:5000`
- Authenticates with Microsoft using OAuth2 (you sign in once; the token is saved locally)
- Fetches emails via the [Microsoft Graph API](https://learn.microsoft.com/en-us/graph/api/resources/mail-api-overview)
- Displays them in a clean, read-only interface

---

## Step 1 — Register the app in Azure (one-time setup)

You need to tell Microsoft about this local app so it can authenticate you. This is free and takes about 5 minutes.

1. Go to [https://portal.azure.com](https://portal.azure.com) and sign in with any Microsoft account (personal or work/school).

2. In the search bar at the top, type **App registrations** and click it.

3. Click **New registration**.

4. Fill in the form:
   - **Name**: `Outlook Local Viewer` (or anything you like)
   - **Supported account types**: Select **"Accounts in any organizational directory (Any Azure AD directory - Multitenant) and personal Microsoft accounts"**
     - This supports both personal Outlook.com and work/school Microsoft 365 accounts.
   - **Redirect URI**:
     - Platform: choose **"Public client/native (mobile & desktop)"**
     - URI: `http://localhost:5000/auth/callback`
   - Click **Register**.

5. On the overview page that appears, copy the **Application (client) ID** — you'll need it in Step 2.

6. In the left menu, click **Authentication**:
   - Confirm that `http://localhost:5000/auth/callback` appears under **Mobile and desktop applications**.
   - Under **Advanced settings**, set **"Allow public client flows"** to **Yes**.
   - Click **Save**.

7. In the left menu, click **API permissions** → **Add a permission** → **Microsoft Graph** → **Delegated permissions**:
   - Search for and add `Mail.Read`
   - Search for and add `User.Read`
   - Click **Add permissions**.

   > **Work/school accounts note**: If your organisation restricts third-party app access, an IT administrator may need to grant consent. Show them this list of permissions — both are read-only.

---

## Step 2 — Configure the app

```bash
# Copy the example config and open it in any text editor
cp .env.example .env
```

Edit `.env`:

```
AZURE_CLIENT_ID=paste-your-client-id-here
AZURE_TENANT_ID=common
FLASK_SECRET_KEY=paste-a-random-string-here
```

To generate a random secret key, run:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

---

## Step 3 — Install dependencies

```bash
# Create an isolated Python environment (recommended)
python3 -m venv .venv

# Activate it
source .venv/bin/activate        # macOS / Linux
.venv\Scripts\activate           # Windows (Command Prompt)

# Install packages
pip install -r requirements.txt
```

---

## Step 4 — Run the app

```bash
python3 app.py
```

Open your browser and go to **http://localhost:5000**.

Click **Sign in with Microsoft**, complete the login, and you'll see your inbox.

---

## Subsequent runs

After the first login, your token is saved to `token_cache.json` in the project folder. On future runs the app will open directly to your inbox — no login required.

If you want to switch accounts, sign out from within the app or delete `token_cache.json`.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `AADSTS50011: reply URL does not match` | The redirect URI in Azure must be exactly `http://localhost:5000/auth/callback` with platform set to "Mobile and desktop applications". |
| `KeyError: AZURE_CLIENT_ID` | You haven't created `.env` or forgot to fill in the client ID. |
| Port 5000 already in use (macOS) | AirPlay Receiver uses port 5000 on macOS Monterey+. Run `python3 app.py` after changing the port in `app.py` to `5001`, and update the redirect URI in both `.env`/`config.py` and Azure to match. |
| Token errors on restart | Delete `token_cache.json` and sign in again. |
| Work account: "Need admin approval" | Your IT admin needs to grant consent for `Mail.Read` and `User.Read` in your tenant. |

---

## Security notes

- `token_cache.json` contains a refresh token — treat it like a password. It is git-ignored by default.
- `.env` contains your client ID — also git-ignored.
- HTML email bodies are rendered inside a sandboxed `<iframe>` with scripts disabled, preventing malicious email content from running code in your browser.
- No data leaves your machine except the OAuth2 handshake with Microsoft and the Graph API calls to read your own mail.

---

## File overview

| File | Purpose |
|---|---|
| `app.py` | Flask web server and routes |
| `auth.py` | OAuth2 login flow and token cache management |
| `graph.py` | Microsoft Graph API calls |
| `config.py` | Configuration loaded from `.env` |
| `templates/` | HTML page templates |
| `static/style.css` | Stylesheet |
| `.env` | Your credentials (not committed to git) |
| `token_cache.json` | Saved login token (not committed to git) |
