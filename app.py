from flask import Flask, redirect, render_template, request, session, url_for
import auth
import mail
import config

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


def _get_account():
    token = session.get("token")
    if not token:
        return None, redirect(url_for("index"))
    account = auth.get_account(token)
    if not account:
        session.clear()
        return None, redirect(url_for("index"))
    return account, None


@app.route("/")
def index():
    if session.get("token") and auth.get_account(session.get("token")):
        return redirect(url_for("inbox"))
    return render_template("index.html")


@app.route("/auth/login", methods=["POST"])
def login():
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    if not email or not password:
        return render_template("index.html", error="Please enter your email and password.")

    token, error = auth.login(email, password)
    if error:
        return render_template("index.html", error=error)

    session["token"] = token
    return redirect(url_for("inbox"))


@app.route("/inbox")
def inbox():
    account, redir = _get_account()
    if redir:
        return redir

    page = max(int(request.args.get("page", 1)), 1)
    skip = (page - 1) * config.MESSAGES_PER_PAGE

    try:
        messages = mail.get_messages(account, skip=skip, top=config.MESSAGES_PER_PAGE)
    except Exception as exc:
        return render_template("error.html", message=str(exc))

    return render_template(
        "inbox.html",
        messages=messages,
        page=page,
        has_next=len(messages) == config.MESSAGES_PER_PAGE,
        has_prev=page > 1,
        user_email=auth.get_email(session.get("token")),
    )


@app.route("/email")
def view_email():
    account, redir = _get_account()
    if redir:
        return redir

    item_id = request.args.get("id")
    changekey = request.args.get("ck")
    if not item_id or not changekey:
        return redirect(url_for("inbox"))

    try:
        msg = mail.get_message(account, item_id, changekey)
        mail.mark_as_read(msg)
        body_content, body_is_html = mail.body_parts(msg)
    except Exception as exc:
        return render_template("error.html", message=str(exc))

    return render_template(
        "email.html",
        message=msg,
        body_content=body_content,
        body_is_html=body_is_html,
        user_email=auth.get_email(session.get("token")),
    )


@app.route("/auth/logout")
def logout():
    token = session.pop("token", None)
    if token:
        auth.logout(token)
    session.clear()
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=False, port=5000)
