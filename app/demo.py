from datetime import timedelta
from uuid import uuid4

from .db import lock, value
from .ledger import need, submit, today
from .settings import change


def seed(c):
    lock(c)
    actor = value(c, "select id from operator_user limit 1")
    need(
        actor and not value(c, "select count(*) from event") and not value(c, "select count(*) from item"),
        "Demo seeding requires an initialized empty ledger.",
    )
    for name, category, unit, tracked in [
        ("Pork", "Food", "kg", "on"),
        ("Momo", "Food", "plate", ""),
        ("Tuborg Beer", "Beverage", "bottle", "on"),
    ]:
        change(
            c, {"action": "new_item", "name": name, "category": category, "unit": unit, "tracked": tracked}
        )
    change(c, {"action": "new_bank", "name": "Demo Bank"})
    main = value(c, "select cash_id from counter where main")
    day = str(today() - timedelta(days=1))
    for payload in [
        {"kind": "opening", "account_id": main, "amount": "25000", "reason": "Demo float"},
        {
            "kind": "bill",
            "counter_id": 1,
            "lines": [{"name": "Pork", "qty": "10", "amount": "7000"}],
            "payment_mode": "cash",
        },
        {
            "kind": "sale",
            "counter_id": 1,
            "cash": "3500",
            "lines": [{"name": "Pork", "qty": "3"}, {"name": "Momo", "qty": "6"}],
        },
    ]:
        submit(c, actor, {"day": day, **payload}, str(uuid4()))
