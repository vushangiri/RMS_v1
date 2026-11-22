from pathlib import Path

import pytest
from sqlalchemy import text
from werkzeug.security import generate_password_hash

from app import create_app


@pytest.fixture(scope="session")
def app():
    app = create_app()
    db = app.extensions["database"]
    if not db.url.database.endswith("_test"):
        pytest.exit("Use a dedicated database ending in _test.")
    return app


@pytest.fixture
def engine(app):
    db = app.extensions["database"]
    with db.begin() as c:
        c.exec_driver_sql(
            "truncate operator_user,throttle,counter,item,account,party,config,event restart identity cascade"
        )
        seed = (
            Path("migrations/versions/0001_ledger.sql")
            .read_text()
            .split("INSERT INTO account", 1)[1]
            .split("CREATE TABLE closing_snapshot")[0]
        )
        c.exec_driver_sql("INSERT INTO account" + seed)
        c.execute(
            text("insert into operator_user(username,password_hash) values('tester',:p)"),
            {"p": generate_password_hash("test-password-1234")},
        )
    return db
