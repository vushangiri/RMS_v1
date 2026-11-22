from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from test_web import login, token

from app.db import first, value
from app.ledger import Invalid, submit, today
from app.reports import period, report
from app.settings import change


def test_master_data(engine):
    with engine.begin() as c:
        change(c, {"action": "new_counter", "name": "Garden"})
        ct = first(c, "select * from counter where name='Garden'")
        change(c, {"action": "rename", "name": "Terrace", "counter_id": ct.id})
        change(c, {"action": "toggle_counter", "counter_id": ct.id})
        assert not value(c, "select active from account where id=:a", a=ct.cash_id)
        with pytest.raises(Invalid):
            submit(c, 1, {"kind": "sale", "day": str(today()), "counter_id": ct.id, "cash": "1"}, uuid4())
        change(c, {"action": "toggle_counter", "counter_id": ct.id})
        change(c, {"action": "new_item", "name": "Momo", "category": "Food", "unit": "plate"})
        change(c, {"action": "tracking", "item_id": 1})
        change(c, {"action": "toggle_item", "item_id": 1})
        assert not value(c, "select active from item where id=1")
    with pytest.raises(IntegrityError), engine.begin() as c:
        change(c, {"action": "new_item", "name": " mOMO ", "category": "Food", "unit": "plate"})


def test_export_pagination_and_filters(app, engine):
    with engine.begin() as c:
        for i in range(53):
            submit(
                c,
                1,
                {
                    "kind": "sale",
                    "day": "2025-11-05",
                    "counter_id": 1,
                    "cash": "3",
                    "reference": "Day " + str(i),
                },
                uuid4(),
            )
        assert len(report(c, "register", {}, "2025-11-01", "2025-11-30", page=3)) == 13
        assert period({"day": "2024-02-14", "period": "monthly"})[1].day == 29
        assert period({"day": "2025-01-01", "period": "weekly"})[0].isoformat() == "2024-12-30"
    client = app.test_client()
    login(client)
    query = {"day": "2025-11-05", "report": "register"}
    for page, count in [(1, 20), (2, 20), (3, 13)]:
        result = client.get("/workspace/reports", query_string={**query, "page": page})
        assert result.data.count(b"/record/") == count
    assert len(client.get("/export", query_string=query).data.splitlines()) == 54
    assert client.get("/print", query_string=query).data.count(b"<tr>") == 54
    assert (
        client.get("/workspace/reports", query_string={**query, "q": "Day 52"}).data.count(b"/record/") == 1
    )


def test_session_and_replay(app, engine):
    client = app.test_client()
    login(client)
    csrf = token(client.get("/"))
    form = {
        "token": str(uuid4()),
        "day": str(today()),
        "kind": "configuration",
        "action": "new_bank",
        "name": "Local bank",
        "csrf_token": csrf,
    }
    assert client.post("/entry", data=form).status_code == 303
    assert client.post("/entry", data=form).status_code == 303
    assert client.post("/entry", data={**form, "name": "Different bank"}).status_code == 422
    with engine.begin() as c:
        assert value(c, "select count(*) from account where kind='bank'") == 1
        c.exec_driver_sql("update login_session set expires=now()-interval '1 hour'")
    assert client.get("/").status_code == 302


def test_invalid_and_atomic(engine):
    for data in [
        {"kind": "sale", "cash": "0"},
        {"kind": "sale", "credit": "1"},
        {"kind": "bill", "lines": []},
        {"kind": "transfer", "account_id": 7, "to_id": 7, "amount": 1},
        {"kind": "sale", "cash": 10, "day": str(today() + timedelta(days=1))},
    ]:
        with pytest.raises(Invalid), engine.begin() as c:
            submit(c, 1, {"counter_id": 1, "day": str(today()), **data}, uuid4())
    with engine.begin() as c:
        assert value(c, "select count(*) from event") == 0
