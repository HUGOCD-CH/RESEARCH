import uuid
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
import auth
import config
import mail

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


def _require_token():
    token = auth.get_token()
    if not token:
        return None, redirect(url_for("index"))
    return token, None


@app.route("/")
def index():
    if auth.get_token():
        return redirect(url_for("inbox"))
    return render_template("index.html")


# ── Device code flow ─────────────────────────────────────────────────────────

@app.route("/auth/start")
def auth_start():
    try:
        flow = auth.start_device_flow()
    except RuntimeError as exc:
        return render_template("error.html", message=str(exc))

    poll_id = str(uuid.uuid4())
    auth.start_polling(flow, poll_id)
    session["poll_id"] = poll_id

    return render_template(
        "device_code.html",
        user_code=flow["user_code"],
        verification_uri=flow["verification_uri"],
        expires_in=flow.get("expires_in", 900),
    )


@app.route("/auth/poll")
def auth_poll():
    """AJAX endpoint polled by the device-code page every few seconds."""
    poll_id = session.get("poll_id")
    if not poll_id:
        return jsonify({"status": "error", "error": "No pending sign-in."}), 400
    return jsonify(auth.check_poll(poll_id))


@app.route("/auth/logout")
def logout():
    session.clear()
    auth.clear_cache()
    return redirect(url_for("index"))


# ── Mail views ────────────────────────────────────────────────────────────────

@app.route("/inbox")
def inbox():
    token, redir = _require_token()
    if redir:
        return redir

    page = max(int(request.args.get("page", 1)), 1)
    skip = (page - 1) * config.MESSAGES_PER_PAGE

    try:
        data = mail.get_messages(token, top=config.MESSAGES_PER_PAGE, skip=skip)
        user = mail.get_user_profile(token)
    except Exception as exc:
        return render_template("error.html", message=str(exc))

    messages = data.get("value", [])
    return render_template(
        "inbox.html",
        messages=messages,
        page=page,
        has_next="@odata.nextLink" in data or len(messages) == config.MESSAGES_PER_PAGE,
        has_prev=page > 1,
        user=user,
    )


@app.route("/email/<message_id>")
def view_email(message_id):
    token, redir = _require_token()
    if redir:
        return redir

    try:
        message = mail.get_message(token, message_id)
        user = mail.get_user_profile(token)
        if not message.get("isRead"):
            mail.mark_as_read(token, message_id)
    except Exception as exc:
        return render_template("error.html", message=str(exc))

    body = message.get("body", {})
    return render_template(
        "email.html",
        message=message,
        body_content=body.get("content", ""),
        body_is_html=body.get("contentType", "text").lower() == "html",
        user=user,
    )


if __name__ == "__main__":
    app.run(debug=False, port=5000)
