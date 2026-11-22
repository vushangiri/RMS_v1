from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError

from app.db import balance, stock, value
from app.ledger import Invalid, number, owed, submit
from app.reports import report
from app.settings import change

DAY = "2025-11-01"
NEXT = "2025-11-02"


def write(engine, k, day=DAY, token=None, **data):
    with engine.begin() as c:
        return submit(c, 1, dict(kind=k, day=day, **data), token or uuid4())


def accounts(engine):
    with engine.begin() as c:
        change(c, {"action": "new_bank", "name": "Bank A"})
        change(c, {"action": "new_item", "name": "Pork", "category": "Food", "unit": "kg", "tracked": "on"})
        change(c, {"action": "new_item", "name": "Momo", "category": "Food", "unit": "plate"})
        return [
            value(c, q)
            for q in (
                "select cash_id from counter where main",
                "select cash_id from counter where not main",
                "select id from account where kind='bank'",
            )
        ]


def test_multi_day(engine):
    main, sub, bank = accounts(engine)
    write(engine, "opening", account_id=main, amount="30000", reason="Float")
    write(engine, "transfer", account_id=main, to_id=sub, amount="10000")
    bill = write(
        engine,
        "bill",
        counter_id=2,
        party="Meat Co",
        cash=2000,
        bank=0,
        lines=[
            {"name": "Pork", "qty": 10000, "unit": "g", "amount": 7000},
            {"name": "Soap", "category": "Supplies", "amount": 500},
        ],
    )
    write(engine, "bill", counter_id=1, payment_mode="cash", lines=[{"name": "Soap", "amount": 100}])
    sale = write(
        engine,
        "sale",
        counter_id=2,
        cash=5000,
        bank=4000,
        bank_id=bank,
        credit=1000,
        party="Asha",
        lines=[{"name": "Pork", "qty": 2}, {"name": "Momo", "qty": 5}],
    )
    write(engine, "sale", counter_id=1, cash=700, lines=[{"name": "Pork", "qty": 1}])
    write(engine, "transfer", account_id=sub, to_id=bank, amount=1000)
    write(engine, "transfer", account_id=bank, to_id=main, amount=500)
    write(engine, "bank_count", account_id=bank, actual=4450, reason="Pending fee")
    count = write(engine, "stock_count", name="Pork", actual="6.5")
    write(engine, "stock_adjust", name="Pork", origin=count, reason="Approved waste")
    hand = write(
        engine,
        "handover",
        counter_id=2,
        actual=11990,
        handed=11000,
        received=10900,
        reason="Short 10, receipt outstanding 100",
    )
    with pytest.raises(Invalid, match="outstanding handover receipts"):
        write(engine, "handover", action="settle_counter", counter_id=1, actual=32000)
    write(engine, "receive", origin=hand, amount=100)
    write(engine, "handover", action="settle_counter", counter_id=1, actual=32100)
    close = write(engine, "close")
    with engine.begin() as c:
        assert [balance(c, a, DAY) for a in [main, sub, bank]] == [32100, 990, 4500]
        assert [owed(c, e, DAY) for e in (bill, sale)] == [5500, 1000]
        assert stock(c, 1, DAY) == Decimal("6.5")
        assert report(c, "stock", {}, DAY, DAY)[0]["estimated"] == Decimal("6.5")
        assert len(report(c, "stock", {}, DAY, DAY)) == 1
        assert sum(r["sales"] for r in report(c, "sales", {}, DAY, DAY)) == 10700
        assert sum(r["purchased"] for r in report(c, "purchases", {}, DAY, DAY)) == 7600
        assert {r["item"]: r["sold"] for r in report(c, "sold", {}, DAY, DAY)} == {"Pork": 3, "Momo": 5}
        assert value(c, "select payload from closing_snapshot where event_id=:e", e=close)["counts"]
    for k, args in [("close", {}), ("sale", {"counter_id": 1, "cash": 1})]:
        with pytest.raises(Invalid):
            write(engine, k, **args)
    write(engine, "payment", NEXT, origin=bill, counter_id=1, account_id=main, amount=500)
    write(engine, "collection", NEXT, origin=sale, counter_id=1, account_id=bank, amount=400)
    with engine.begin() as c:
        assert owed(c, bill, NEXT) == 5000 and owed(c, sale, NEXT) == 600
        assert report(c, "sales", {}, NEXT, NEXT) == [] and report(c, "purchases", {}, NEXT, NEXT) == []
        assert [balance(c, a, NEXT) for a in [main, sub, bank]] == [31600, 990, 4900]
    with pytest.raises(Invalid):
        write(engine, "payment", NEXT, origin=bill, counter_id=1, account_id=main, amount=5001)
    write(engine, "reopen", reason="Check variance")
    with pytest.raises(Invalid):
        write(engine, "reversal", origin=bill, reason="Wrong purchase")


def test_atomic_retry_concurrent(engine):
    main, sub, _ = accounts(engine)
    write(engine, "opening", account_id=main, amount=50, reason="Float")
    t = uuid4()

    def transfer(_):
        return write(engine, "transfer", token=t, account_id=main, to_id=sub, amount=30)

    with ThreadPoolExecutor(4) as pool:
        assert len(set(pool.map(transfer, range(4)))) == 1
    with pytest.raises(Invalid):
        write(engine, "transfer", token=t, account_id=main, to_id=sub, amount=20)
    with pytest.raises(Invalid):
        write(
            engine,
            "bill",
            counter_id=1,
            lines=[{"name": "Pork", "amount": 10, "qty": 1}, {"name": "Pork", "amount": -1, "qty": 1}],
        )
    with engine.begin() as c:
        assert value(c, "select count(*) from event") == 2 and stock(c, 1, DAY) == 0
        assert balance(c, main, DAY) == 20


def test_openings_correction(engine):
    main, _sub, _bank = accounts(engine)
    opening = write(
        engine, "opening_credit", party="Harry", credit_type="receivable", reason="Old account", amount=80
    )
    collection = write(engine, "collection", origin=opening, counter_id=1, account_id=main, amount=60)
    write(engine, "reversal", origin=collection, reason="Incorrect amount")
    with engine.begin() as c:
        assert owed(c, opening, DAY) == 80 and balance(c, main, DAY) == 0
    with pytest.raises(Invalid):
        write(engine, "reversal", origin=collection, reason="Again")
    with pytest.raises(DBAPIError), engine.begin() as c:
        c.exec_driver_sql("delete from movement")
    with pytest.raises(Invalid):
        write(engine, "stock_count", name="Momo", actual=2)


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "1.005", "-1", "9e100", "abc"])
def test_invalid_money(raw):
    with pytest.raises(Invalid):
        number(raw)


def test_reconcile_reverse_and_rollover(engine):
    main, sub, _bank = accounts(engine)
    write(engine, "opening", account_id=main, amount=10, reason="start")
    with pytest.raises(Invalid):
        write(engine, "opening", account_id=main, amount=10, reason="again")
    with pytest.raises(Invalid):
        write(engine, "close")
    count = write(engine, "handover", counter_id=1, actual=9, reason="Short")
    adjustment = write(
        engine, "adjustment", origin=count, account_id=main, amount=-1, reason="Approve shortage"
    )
    write(engine, "reversal", origin=adjustment, reason="Review")
    write(engine, "adjustment", origin=count, account_id=main, amount=-1, reason="Reapprove")
    write(engine, "handover", counter_id=2, actual=0)
    write(engine, "close")
    with engine.begin() as c:
        from app.reports import counters

        assert counters(c, NEXT)[0].opening == 9
    with pytest.raises(Invalid):
        write(engine, "transfer", "2025-10-01", account_id=main, to_id=sub, amount=1)


def test_competing_credit_collections(engine):
    main, _sub, _bank = accounts(engine)
    sale = write(engine, "sale", counter_id=1, credit=100, party="Hari")

    def collect(_):
        try:
            write(engine, "collection", origin=sale, counter_id=1, account_id=main, amount=75)
            return True
        except Invalid:
            return False

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(collect, range(2))) == [False, True]
    with engine.begin() as c:
        assert owed(c, sale, DAY) == 25


def test_stock_corrections(engine):
    accounts(engine)
    write(engine, "stock_adjust", name="Pork", qty="5", reason="Opening")
    obs = write(engine, "stock_count", name="Pork", actual="4")
    adj = write(engine, "stock_adjust", name="Pork", origin=obs, reason="Variance")
    write(engine, "reversal", origin=adj, reason="Recount")
    write(engine, "reversal", origin=obs, reason="Recount")
    with engine.begin() as c:
        assert stock(c, 1, DAY) == 5
        change(c, {"action": "physical"})
    with pytest.raises(Invalid):
        write(engine, "stock_count", name="Pork", actual=4)


def test_bank_to_bank_and_reverse_attribution(engine):
    _main, _sub, bank = accounts(engine)
    with engine.begin() as c:
        change(c, {"action": "new_bank", "name": "Bank B"})
        other = value(c, "select id from account where name='Bank B'")
    sale = write(engine, "sale", counter_id=2, bank_id=bank, bank="30.15")
    tx = write(engine, "transfer", account_id=bank, to_id=other, amount="10.05")
    with pytest.raises(Invalid):
        write(engine, "reversal", origin=sale, reason="Reenter")
    write(engine, "reversal", origin=tx, reason="Wrong bank")
    write(engine, "reversal", origin=sale, reason="Reenter")
    with engine.begin() as c:
        assert balance(c, bank, DAY) == balance(c, other, DAY) == 0
        assert report(c, "sales", {}, DAY, DAY) == []
        assert len(report(c, "audit", {"counter": 2}, DAY, DAY)) == 2


def test_split_sales_and_separate_credit_settlement(engine):
    main, _, bank = accounts(engine)
    with engine.begin() as c:
        change(c, {"action": "new_bank", "name": "Bank B"})
        other = value(c, "select id from account where name='Bank B'")
    sale_data = {
        "counter_id": 1,
        "cash": "100",
        "bank_splits": [[bank, "500"], [other, "1500"]],
        "credit_splits": [["Asha", "20"], ["Ram", "30"]],
        "lines": [{"name": "Momo", "qty": "2"}],
    }
    token = uuid4()
    parent = write(engine, "sale", token=token, **sale_data)
    assert write(engine, "sale", token=token, **sale_data) == parent
    with pytest.raises(Invalid, match="each bank once"):
        write(engine, "sale", **{**sale_data, "bank_splits": [[bank, "10"], [bank, "20"]]})
    with pytest.raises(Invalid, match="each credit customer once"):
        write(engine, "sale", **{**sale_data, "credit_splits": [["Asha", "10"], [" asha ", "20"]]})
    with engine.begin() as c:
        child = value(c, "select id from event where origin=:e and kind='sale'", e=parent)
        assert [balance(c, a, DAY) for a in (main, bank, other)] == [100, 500, 1500]
        assert [owed(c, e, DAY) for e in (parent, child)] == [20, 30]
        assert report(c, "sales", {}, DAY, DAY)[0]["sales"] == 2150
        assert report(c, "sold", {}, DAY, DAY)[0]["sold"] == 2
        assert value(c, "select count(*) from event") == 2
    write(engine, "collection", origin=child, counter_id=1, account_id=main, amount=25)
    with engine.begin() as c:
        assert [owed(c, e, DAY) for e in (parent, child)] == [20, 5]


def test_late_stock_count_and_cash_rollover(engine):
    main, sub, _ = accounts(engine)
    write(engine, "stock_adjust", action="opening_stock", name="Pork", qty="5", reason="Go live")
    with pytest.raises(Invalid, match="no activity"):
        write(engine, "stock_adjust", action="opening_stock", name="Pork", qty="5", reason="Duplicate")
    write(engine, "opening", account_id=main, amount=100, reason="Go live")
    write(engine, "handover", counter_id=2, actual=0)
    write(engine, "handover", counter_id=1, actual=96, reason="Short 4")
    closing = write(engine, "close")
    late = write(engine, "stock_count", name="Pork", actual="4", apply_count="on")
    with engine.begin() as c:
        from app.reports import counters

        assert counters(c, NEXT)[0].opening == 96
        assert balance(c, sub, DAY) == 0
        assert stock(c, 1, NEXT) == 4
        original = value(c, "select payload from closing_snapshot where event_id=:e", e=closing)
        assert Decimal(original["stock"][0]["estimated"]) == 5
    write(engine, "reversal", origin=late, reason="Recount")
    write(engine, "reopen", reason="Review opening")
    with engine.begin() as c:
        assert stock(c, 1, DAY) == 5
        assert balance(c, main, NEXT) == 100


def test_archive_and_edit_master_data(engine):
    _, _, bank = accounts(engine)
    with engine.begin() as c:
        change(
            c, {"action": "new_item", "name": "Pork", "variation": "Sliced", "unit": "g", "category": "Food"}
        )
        variant = value(c, "select id from item where name='Pork · Sliced'")
        change(
            c,
            {
                "action": "edit_item",
                "item_id": variant,
                "name": "Pork",
                "variation": "Portion",
                "unit": "plate",
                "category": "Food",
            },
        )
        change(c, {"action": "toggle_item", "item_id": variant, "active": "off"})
        change(c, {"action": "toggle_item", "item_id": variant, "active": "off"})
        assert not value(c, "select active from item where id=:i", i=variant)
        change(c, {"action": "toggle_item", "item_id": variant, "active": "on"})
        assert value(c, "select unit from item where name='Pork · Portion' and active") == "plate"
        change(c, {"action": "edit_bank", "bank_id": bank, "name": "Daily deposits"})
        change(c, {"action": "toggle_bank", "bank_id": bank, "active": "off"})
        assert not value(c, "select active from account where id=:i", i=bank)
        change(c, {"action": "toggle_bank", "bank_id": bank, "active": "on"})
    write(engine, "sale", counter_id=1, bank=10, bank_id=bank, lines=[{"name": "Pork · Portion", "qty": "1"}])
    with engine.begin() as c:
        with pytest.raises(Invalid, match="remaining balance"):
            change(c, {"action": "toggle_bank", "bank_id": bank, "active": "off"})
        with pytest.raises(Invalid, match="current unit"):
            change(
                c,
                {
                    "action": "edit_item",
                    "item_id": variant,
                    "name": "Pork",
                    "variation": "Portion",
                    "unit": "kg",
                    "category": "Food",
                },
            )


@pytest.mark.parametrize("actual", [90, 110])
def test_actual_only_counter_settlement(engine, actual):
    main, sub, _ = accounts(engine)
    write(engine, "opening", account_id=main, amount=500, reason="Float")
    write(engine, "transfer", account_id=main, to_id=sub, amount=100)
    with pytest.raises(Invalid, match="subordinate counters"):
        write(engine, "handover", action="settle_counter", counter_id=1, actual=400)
    with pytest.raises(Invalid, match="Explain the discrepancy"):
        write(engine, "handover", action="settle_counter", counter_id=2, actual=actual)
    token = uuid4()
    data = {"action": "settle_counter", "counter_id": 2, "actual": actual, "reason": "Physical count"}
    original = write(engine, "handover", token=token, **data)
    assert write(engine, "handover", token=token, **data) == original
    with engine.begin() as c:
        assert balance(c, sub, DAY) == 0
        assert balance(c, main, DAY) == 400 + actual
        assert (
            value(c, "select actual-expected from observation where event_id=:e", e=original) == actual - 100
        )
    write(engine, "handover", action="settle_counter", counter_id=1, actual=399 + actual, reason="Short")
    closed = write(engine, "close")
    with engine.begin() as c:
        assert balance(c, main, NEXT) == 399 + actual
        assert balance(c, sub, NEXT) == 0
        assert value(c, "select count(*) from closing_snapshot where event_id=:e", e=closed) == 1
    write(engine, "reopen", reason="Correct count")
    with engine.begin() as c:
        assert balance(c, main, DAY) == 400 + actual
    with pytest.raises(Invalid, match="later count"):
        write(engine, "reversal", origin=original, reason="Correct count")
    with engine.begin() as c:
        main_count = value(c, "select id from live_event where kind='handover' and counter_id=1")
    write(engine, "reversal", origin=main_count, reason="Correct count")
    write(engine, "reversal", origin=original, reason="Correct count")
    with engine.begin() as c:
        assert balance(c, main, DAY) == 400
        assert balance(c, sub, DAY) == 100
