from flask import Flask, redirect, render_template, request, session, url_for
import auth
import config
import graph

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


def _require_token():
    token = auth.get_token_from_cache()
    if not token:
        return None, redirect(url_for("index"))
    return token, None


@app.route("/")
def index():
    token = auth.get_token_from_cache()
    if token:
        return redirect(url_for("inbox"))
    return render_template("index.html")


@app.route("/auth/login")
def login():
    flow = auth.build_auth_url()
    session["auth_code_flow"] = flow
    return redirect(flow["auth_uri"])


@app.route("/auth/callback")
def auth_callback():
    flow = session.pop("auth_code_flow", None)
    if not flow:
        return render_template("error.html", message="Session expired. Please sign in again.")
    result = auth.acquire_token_by_auth_code_flow(flow, request.args)
    if "error" in result:
        return render_template(
            "error.html",
            message=f"{result.get('error')}: {result.get('error_description', '')}",
        )
    return redirect(url_for("inbox"))


@app.route("/inbox")
def inbox():
    token, redir = _require_token()
    if redir:
        return redir

    page = max(int(request.args.get("page", 1)), 1)
    skip = (page - 1) * config.MESSAGES_PER_PAGE

    try:
        data = graph.get_messages(token, top=config.MESSAGES_PER_PAGE, skip=skip)
        user = graph.get_user_profile(token)
    except Exception as exc:
        return render_template("error.html", message=str(exc))

    messages = data.get("value", [])
    has_next = "@odata.nextLink" in data or len(messages) == config.MESSAGES_PER_PAGE
    has_prev = page > 1

    return render_template(
        "inbox.html",
        messages=messages,
        page=page,
        has_next=has_next,
        has_prev=has_prev,
        user=user,
    )


@app.route("/email/<message_id>")
def view_email(message_id):
    token, redir = _require_token()
    if redir:
        return redir

    try:
        message = graph.get_message(token, message_id)
        user = graph.get_user_profile(token)
        if not message.get("isRead"):
            graph.mark_as_read(token, message_id)
    except Exception as exc:
        return render_template("error.html", message=str(exc))

    body = message.get("body", {})
    body_content = body.get("content", "")
    body_type = body.get("contentType", "text")

    return render_template(
        "email.html",
        message=message,
        body_content=body_content,
        body_type=body_type,
        user=user,
    )


@app.route("/auth/logout")
def logout():
    session.clear()
    auth.clear_cache()
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=False, port=5000)
