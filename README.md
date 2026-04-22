# Outlook Local Viewer

A lightweight local web app to read your Medtronic/Microsoft 365 emails at `http://localhost:5000`.

Uses **OAuth2 Modern Authentication** (the same method used by Outlook desktop) — no basic-auth, no IT approval needed for the app itself. You sign in through Microsoft's own login page, which handles SSO, MFA, and Conditional Access automatically.

---

## How sign-in works (Device Code Flow)

1. You click "Sign in with Microsoft" in the app.
2. The app shows a short code (e.g. `ABCD1234`) and a link to `https://microsoft.com/devicelogin`.
3. You open that link in your browser, enter the code, and sign in with your Medtronic credentials — just like you would at `webmail.medtronic.com`.
4. The app detects your completed sign-in and loads your inbox automatically.

Your password never touches this app. Authentication goes directly between your browser and Microsoft.

---

## Step 1 — Register the app in Azure (one-time, ~5 minutes)

You register this app yourself using your own Medtronic account — no IT ticket needed.

> **Note:** Some Medtronic tenants may block self-registered apps from accessing mail. If sign-in succeeds but you get a "Need admin approval" screen, you will need to ask IT to consent to `Mail.Read` and `User.Read` for your registered app. These are read-only, delegated permissions (they only access your own mailbox).

1. Go to [https://portal.azure.com](https://portal.azure.com) and sign in with your Medtronic account.

2. Search for **App registrations** → **New registration**.

3. Fill in:
   - **Name**: `Outlook Local Viewer` (or anything you like)
   - **Supported account types**: `Accounts in any organizational directory (Any Azure AD directory - Multitenant) and personal Microsoft accounts`
   - **Redirect URI**: leave blank (device code flow does not need one)
   - Click **Register**.

4. On the Overview page, copy the **Application (client) ID** — you'll need it in Step 2.

5. Click **Authentication** in the left menu:
   - Under **Advanced settings**, set **Allow public client flows** → **Yes**
   - Click **Save**

6. Click **API permissions** → **Add a permission** → **Microsoft Graph** → **Delegated permissions**:
   - Add `Mail.Read`
   - Add `User.Read`
   - Click **Add permissions**

---

## Step 2 — Configure

```bash
cp .env.example .env
```

Open `.env` and fill in:
- `AZURE_CLIENT_ID` — the client ID you copied in Step 1
- `FLASK_SECRET_KEY` — generate one with:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

---

## Step 3 — Install and run

```bash
# Create virtual environment
python3 -m venv .venv

# Activate it
source .venv/bin/activate        # macOS / Linux
.venv\Scripts\activate           # Windows

# Install dependencies
pip install -r requirements.txt

# Run the app
python3 app.py
```

Open your browser at **http://localhost:5000** and click **Sign in with Microsoft**.

---

## Subsequent runs

After the first sign-in, your token is saved to `token_cache.json`. The next time you run `python3 app.py`, you'll be taken directly to your inbox — no re-authentication needed (tokens refresh automatically for up to 90 days).

To force a fresh sign-in, delete `token_cache.json` or click **Sign out** in the app.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Need admin approval" screen during sign-in | Your tenant requires IT consent. Ask IT to approve `Mail.Read` + `User.Read` (delegated, read-only) for your app's client ID. |
| `KeyError: AZURE_CLIENT_ID` | You haven't created `.env` or the client ID is missing. |
| "Could not start device flow" | Double-check the client ID in `.env` and confirm "Allow public client flows" is enabled in Azure. |
| Port 5000 already in use (macOS) | AirPlay Receiver uses port 5000. Change `port=5000` in `app.py` to `5001` and restart. |
| Code expires before you enter it | The device code is valid for 15 minutes. Click "Sign in" again to get a new one. |

---

## Security notes

- Your password is entered at `https://microsoft.com/devicelogin` — a Microsoft-owned page. This app never sees it.
- The access token and refresh token are saved locally to `token_cache.json` — git-ignored, never committed.
- HTML emails render in a sandboxed `<iframe>` with JavaScript disabled.
- The app only listens on `127.0.0.1` (localhost) — not accessible from other devices.

---

## File overview

| File | Purpose |
|---|---|
| `app.py` | Flask routes: landing, device code flow, inbox, email view, logout |
| `auth.py` | MSAL token cache, device code flow, background polling |
| `mail.py` | Microsoft Graph API wrappers (list/read mail) |
| `config.py` | Settings loaded from `.env` |
| `templates/` | HTML templates |
| `static/style.css` | Stylesheet |
| `token_cache.json` | Saved OAuth2 tokens (git-ignored) |
