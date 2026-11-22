import csv
import io
import re
from uuid import uuid4

from PIL import Image
from werkzeug.datastructures import MultiDict

from app.db import value
from app.demo import seed
from app.ledger import submit
from app.reports import REPORTS
from app.settings import change


def token(page):
    return re.search(r'name="csrf_token" value="([^"]+)', page.get_data(as_text=True)).group(1)


def login(client):
    return client.post(
        "/login",
        data={
            "username": "tester",
            "password": "test-password-1234",
            "csrf_token": token(client.get("/login")),
        },
    )


def test_security_and_pages(app, engine):
    client = app.test_client()
    assert client.get("/").status_code == 302
    assert client.get("/record/1").status_code == 302
    assert client.post("/entry", data={"kind": "sale"}).status_code == 400
    csrf = token(client.get("/login"))
    for i in range(11):
        r = client.post("/login", data={"username": "absent", "password": "test", "csrf_token": csrf})
        assert r.status_code == (429 if i == 10 else 401)
    assert login(client).status_code == 302
    with engine.begin() as c:
        seed(c)
    for pg in [
        "overview",
        "expenses",
        "income",
        "counters",
        "money",
        "credits",
        "stock",
        "reports",
        "settings",
    ]:
        r = client.get("/workspace/" + pg)
        assert r.status_code == 200, pg
        assert r.headers["Cache-Control"] == "no-store"
    for report in REPORTS:
        assert (
            client.get("/workspace/reports", query_string={"report": report, "q": "'<script>"}).status_code
            == 200
        )
        assert client.get("/export", query_string={"report": report}).status_code == 200
    assert client.get("/record/1").status_code == 200
    assert client.post("/logout", data={"csrf_token": token(client.get("/"))}).status_code == 302
    assert client.get("/workspace/settings").status_code == 302


def test_upload_and_xss(app, engine):
    client = app.test_client()
    login(client)
    csrf = token(client.get("/"))
    data = {
        "kind": "bill",
        "page": "expenses",
        "day": "2025-11-01",
        "token": str(uuid4()),
        "csrf_token": csrf,
        "row_name": "<script>alert(1)</script>",
        "row_category": "Food",
        "row_amount": "5",
        "row_unit": "",
        "row_qty": "",
        "counter_id": "1",
        "party": "Test Co",
        "payment_mode": "credit",
    }
    r = client.post("/entry", data={**data, "receipt": (io.BytesIO(b"not an image"), "test.png")})
    assert r.status_code == 422
    im = io.BytesIO()
    Image.new("RGB", (20, 20)).save(im, "PNG")
    im.seek(0)
    assert client.post("/entry", data={**data, "receipt": (im, "scan.png")}).status_code == 303
    with engine.begin() as c:
        eid = value(c, "select id from event")
    detail = client.get("/record/" + str(eid)).get_data(as_text=True)
    assert "&lt;script&gt;alert(1)" in detail and "<script>alert" not in detail
    assert client.get("/receipt/" + str(eid)).mimetype == "image/jpeg"
    assert client.post("/entry", data={**data, "token": str(uuid4()), "row_amount": "-5"}).status_code == 422


def test_global_lookup(app, engine):
    with engine.begin() as c:
        seed(c)
    client = app.test_client()
    login(client)
    search = client.get("/search?q=Pork")
    assert (
        search.status_code == 200 and b"/record/" in search.data and b"Catalogue and accounts" in search.data
    )
    assert client.get("/workspace/settings?q=Momo").status_code == 200


def test_product_variants_are_atomic_and_idempotent(app, engine):
    client = app.test_client()
    login(client)
    form = MultiDict(
        {
            "kind": "configuration",
            "action": "new_item",
            "page": "settings",
            "day": "2025-11-01",
            "token": str(uuid4()),
            "csrf_token": token(client.get("/workspace/settings")),
            "name": "Juice",
            "category": "Beverage",
            "variant_variation": ["Glass", "Glass"],
            "variant_unit": ["ml", "l"],
            "variant_tracked": ["off", "on"],
        }
    )
    assert client.post("/entry", data=form).status_code == 422
    with engine.begin() as c:
        assert value(c, "select count(*) from item where name like 'Juice%'") == 0
        assert value(c, "select count(*) from event where kind='configuration'") == 0
    form.setlist("variant_variation", ["Glass", "Pitcher"])
    headers = {"Accept": "application/json"}
    saved = client.post("/entry", data=form, headers=headers)
    assert saved.status_code == 201
    assert client.post("/entry", data=form, headers=headers).json == saved.json
    with engine.begin() as c:
        assert value(c, "select count(*) from item where name like 'Juice%'") == 2
        assert value(c, "select unit from item where name='Juice · Glass' and not tracked") == "ml"
        assert value(c, "select unit from item where name='Juice · Pitcher' and tracked") == "l"
        assert value(c, "select count(*) from event where kind='configuration'") == 1


def test_counter_settlement_breakdown_filters_party_records(app, engine):
    day = "2025-11-02"
    with engine.begin() as c:
        sub = value(c, "select cash_id from counter where not main")
        main = value(c, "select cash_id from counter where main")
        change(c, {"action": "new_bank", "name": "Test Bank"})
        bank = value(c, "select id from account where kind='bank'")

        def post(kind, on=day, **details):
            return submit(c, 1, {"day": on, "kind": kind, **details}, uuid4())

        for customer in ("Alice", "Bob", "Charlie", "Reversed", "Main customer", "Earlier customer"):
            sale = post("sale", on="2025-11-01", counter_id=1, party=customer, credit=1000)
            account_id = {"Main customer": main, "Charlie": bank}.get(customer, sub)
            collection = post(
                "collection",
                on="2025-11-01" if customer == "Earlier customer" else day,
                counter_id=1 if customer == "Main customer" else 2,
                account_id=account_id,
                origin=sale,
                amount=1000,
            )
            if customer == "Reversed":
                post("reversal", origin=collection, reason="Incorrect collection")

    client = app.test_client()
    login(client)
    result = client.get("/workspace/counters", query_string={"day": day, "counter": 2})
    assert result.status_code == 200
    breakdowns = re.findall(
        r'<details class="settlement-detail">(.*?)</details>', result.get_data(as_text=True), re.DOTALL
    )
    assert len(breakdowns) == 2
    body = breakdowns[0]
    assert "Receivables collected · NPR 3,000.00" in body
    assert "<td>Test Bank</td>" in body
    for customer in ("Alice", "Bob", "Charlie"):
        assert f"<td>{customer}</td>" in body
    for customer in ("Reversed", "Main customer", "Earlier customer"):
        assert f"<td>{customer}</td>" not in body


def test_credit_account_history_tracks_opening_settlements_and_reversals(app, engine):
    with engine.begin() as c:

        def post(kind, day="2025-11-01", **details):
            return submit(c, 1, {"day": day, "kind": kind, **details}, uuid4())

        drawer = value(c, "select cash_id from counter where main")
        post("opening", account_id=drawer, amount=200, reason="Float")
        customer = {"counter_id": 1, "credit_type": "receivable", "party": "River & Co"}
        opening = post("opening_credit", **customer, amount=100, reason="Imported balance")
        other = post("opening_credit", **customer, amount=20, reason="Second credit")
        supplier = post(
            "opening_credit", **{**customer, "credit_type": "payable"}, amount=40, reason="Supplier balance"
        )
        for origin, amount in [(opening, 30), (other, 20), (opening, 100)]:
            collection = post(
                "collection", day="2025-11-02", origin=origin, account_id=drawer, counter_id=1, amount=amount
            )
            if amount == 30:
                post("reversal", day="2025-11-02", origin=collection, reason="Wrong amount")
        post("payment", day="2025-11-02", origin=supplier, account_id=drawer, counter_id=1, amount=40)

    client = app.test_client()
    login(client)
    path = "/credits/receivable/history"
    response = client.get(path, query_string={"party": "River & Co"})
    assert response.status_code == 200
    entries = re.findall(r"<tr>\s*<td>.*?</tr>", response.get_data(as_text=True), re.DOTALL)
    assert [re.findall(r"<td>([^<]+)</td>", entry)[1:] for entry in entries] == [
        ["Opening balance", "+100.00", "100.00"],
        ["Opening balance", "+20.00", "120.00"],
        ["Collection", "-30.00", "90.00"],
        ["Reversal", "+30.00", "120.00"],
        ["Collection", "-20.00", "100.00"],
        ["Collection", "-100.00", "0.00"],
    ]
    detail = client.get(path, query_string={"party": "River & Co", "credit": opening}).get_data(as_text=True)
    assert "Full account history" in detail
    assert "-100.00</td>" in detail and "0.00</td>" in detail
    assert "-20.00</td>" not in detail
    assert client.get(path, query_string={"party": "River & Co", "credit": supplier}).status_code == 404
    payable = client.get("/credits/payable/history", query_string={"party": "River & Co"})
    assert "Payment</td>" in payable.get_data(as_text=True)
    assert "Collection</td>" not in payable.get_data(as_text=True)


def test_money_history_filters_and_includes_transfer_and_reversal_postings(app, engine):
    with engine.begin() as c:

        def post(kind, day="2025-11-01", **details):
            return submit(c, 1, {"day": day, "kind": kind, **details}, uuid4())

        change(c, {"action": "new_bank", "name": "Test Bank"})
        bank = value(c, "select id from account where kind='bank'")
        drawer = value(c, "select cash_id from counter where main")
        sub = value(c, "select cash_id from counter where not main")
        post("opening", account_id=drawer, amount=200, reason="Float")
        post("transfer", day="2025-11-02", account_id=drawer, to_id=sub, amount=30)
        deposit = post("transfer", day="2025-11-02", account_id=drawer, to_id=bank, amount=70)
        reversal = post("reversal", day="2025-11-02", origin=deposit, reason="Failed deposit")

    client = app.test_client()
    login(client)

    def ledger(kind, **filters):
        result = client.get("/export", query_string={"report": kind, "day": "2025-11-02", **filters})
        assert result.status_code == 200
        return list(csv.DictReader(io.StringIO(result.get_data(as_text=True))))

    assert [(x["account"], x["money_in"], x["money_out"]) for x in ledger("bank")] == [
        ("Test Bank", "0", "70.00"),
        ("Test Bank", "70.00", "0"),
    ]
    assert [int(x["record"]) for x in ledger("bank")] == [reversal, deposit]
    assert {x["account"] for x in ledger("cash")} == {"Main Counter cash", "Counter 2 cash"}
    assert [x["account"] for x in ledger("cash", counter=2)] == ["Counter 2 cash"]
    assert {x["account"] for x in ledger("cash_bank")} == {"Main Counter cash", "Counter 2 cash", "Test Bank"}
    assert ledger("cash_bank", account=bank) == ledger("bank")
    assert [int(x["record"]) for x in ledger("bank", direction="in")] == [deposit]
    assert [int(x["record"]) for x in ledger("bank", direction="out")] == [reversal]
    assert ledger("cash", counter=2, direction="out") == []
    assert len(ledger("cash", period="all")) == len(ledger("cash")) + 1
    assert all(x["day"] == "2025-11-02" for x in ledger("cash"))
