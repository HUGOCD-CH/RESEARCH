from flask import Flask, jsonify, redirect, render_template, request, url_for
import auth
import config
import mail

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


def _require_auth():
    if not auth.is_ready():
        return redirect(url_for("index"))
    return None


@app.route("/")
def index():
    state = auth.get_state()
    if state["status"] == "active":
        return redirect(url_for("inbox"))
    return render_template("index.html", state=state)


# ── Auth flow ─────────────────────────────────────────────────────────────────

@app.route("/auth/start")
def auth_start():
    auth.start_login()
    return render_template("waiting.html")


@app.route("/auth/poll")
def auth_poll():
    state = auth.get_state()
    return jsonify({
        "status": state["status"],
        "error":  state.get("error"),
        "user":   state.get("user"),
    })


@app.route("/auth/logout")
def logout():
    auth.clear()
    return redirect(url_for("index"))


# ── Mail views ────────────────────────────────────────────────────────────────

@app.route("/inbox")
def inbox():
    redir = _require_auth()
    if redir:
        return redir

    page_num = max(int(request.args.get("page", 1)), 1)
    skip = (page_num - 1) * config.MESSAGES_PER_PAGE

    try:
        data = mail.get_messages(top=config.MESSAGES_PER_PAGE, skip=skip)
        user = mail.get_user_profile()
    except Exception as exc:
        return render_template("error.html", message=str(exc))

    messages = data.get("value", []) if isinstance(data, dict) else []
    return render_template(
        "inbox.html",
        messages=messages,
        page=page_num,
        has_next=len(messages) == config.MESSAGES_PER_PAGE,
        has_prev=page_num > 1,
        user=user,
    )


@app.route("/email/<message_id>")
def view_email(message_id):
    redir = _require_auth()
    if redir:
        return redir

    try:
        message = mail.get_message(message_id)
        user = mail.get_user_profile()
        mail.mark_as_read(message_id)
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
    app.run(debug=False, port=5000, threaded=True)
