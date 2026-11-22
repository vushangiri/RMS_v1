import hashlib
import os
from datetime import timedelta
from uuid import uuid4

import click
from flask import Flask, g, redirect, render_template, request, session
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import create_engine
from werkzeug.security import check_password_hash, generate_password_hash

from .db import first, lock, value
from .ledger import need


def create_app():
    app = Flask(__name__)
    app.jinja_env.trim_blocks = True
    app.jinja_env.lstrip_blocks = True
    app.config.update(
        SECRET_KEY=os.environ["SECRET_KEY"],
        SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "1") == "1",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        SESSION_REFRESH_EACH_REQUEST=False,
        MAX_CONTENT_LENGTH=6 * 1024**2,
        WTF_CSRF_TIME_LIMIT=28800,
    )
    need(len(app.secret_key or "") >= 32, "Generate a longer SECRET_KEY.")
    db = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    need(db.dialect.name == "postgresql", "PostgreSQL is required.")
    app.extensions["database"] = db
    CSRFProtect(app)

    @app.before_request
    def authorize():
        if request.endpoint in ("static", "worker", None):
            return
        if request.endpoint not in ("login", "health") and not session.get("uid"):
            return redirect("/login")
        g.c = db.connect()
        if request.method == "GET":
            g.c = g.c.execution_options(isolation_level="REPEATABLE READ")
        if request.endpoint not in ("login", "health") and not value(
            g.c,
            "select 1 from login_session where token=:t and user_id=:u and expires>now()",
            t=session.get("sid"),
            u=session.get("uid"),
        ):
            session.clear()
            return redirect("/login")

    @app.teardown_request
    def release(error):
        if "c" in g:
            g.c.close()

    @app.after_request
    def headers(res):
        res.headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "same-origin",
                "Content-Security-Policy": "default-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'; img-src 'self' data:",
                "Cache-Control": "public, max-age=3600" if request.endpoint == "static" else "no-store",
            }
        )
        return res

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            name = request.form["username"].strip().lower()
            lock(g.c)
            key = hashlib.sha256(name.encode()).hexdigest()
            tries = value(
                g.c,
                """insert into throttle(name,attempts) values(:k,1) on conflict(name) do update
              set attempts=case when throttle.since<now()-interval '15 minutes' then 1 else throttle.attempts+1 end,
              since=case when throttle.since<now()-interval '15 minutes' then now() else throttle.since end returning attempts""",
                k=key,
            )
            u = first(g.c, "select * from operator_user where username=:n", n=name)
            if tries <= 10 and u and check_password_hash(u.password_hash, request.form["password"]):
                value(g.c, "delete from throttle where name=:k returning name", k=key)
                session.clear()
                sid = str(uuid4())
                g.c.exec_driver_sql("delete from login_session where expires<=now()")
                value(
                    g.c,
                    "insert into login_session values(:t,:u,now()+interval '8 hours') returning user_id",
                    t=sid,
                    u=u.id,
                )
                session.update(uid=u.id, sid=sid)
                session.permanent = True
                g.c.commit()
                return redirect("/")
            g.c.commit()
            error = "Sign-in failed." if tries <= 10 else "Try again in 15 minutes."
            return render_template("login.html", error=error), 401 if tries <= 10 else 429
        return render_template("login.html", error=error)

    @app.post("/logout")
    def logout():
        value(g.c, "delete from login_session where token=:t returning user_id", t=session["sid"])
        g.c.commit()
        session.clear()
        return redirect("/login")

    @app.get("/health")
    def health():
        return {"ready": value(g.c, "select version_num from alembic_version") == "ledger_02"}

    @app.get("/sw.js")
    def worker():
        return app.send_static_file("sw.js")

    @app.cli.command("init-admin")
    @click.option("--username", prompt=True)
    @click.password_option()
    def init_admin(username, password):
        with db.begin() as c:
            lock(c)
            if value(c, "select count(*) from operator_user") or len(password) < 12 or not username.strip():
                raise click.ClickException(
                    "Requires a fresh database, a username and a 12-character or longer password."
                )
            value(
                c,
                "insert into operator_user(username,password_hash) values(:u,:p) returning id",
                u=username.strip().lower(),
                p=generate_password_hash(password),
            )
        click.echo("Administrator created.")

    @app.cli.command("seed-demo")
    def seed_demo():
        from .demo import seed

        with db.begin() as c:
            seed(c)
        click.echo("Demo ledger created.")

    from .web import bp

    app.register_blueprint(bp)
    return app
