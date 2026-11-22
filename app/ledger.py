"""One serialized transaction per submitted form. Financial pairs always balance."""

import hashlib
import json
import os
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .db import balance, first, lock, rows, stock, value


class Invalid(ValueError):
    pass


def need(ok, message):
    if not ok:
        raise Invalid(message)


def number(raw: object, scale: int = 2, minimum: Decimal | int | None = 0) -> Decimal:
    try:
        n = Decimal(str(raw or 0))
        need(
            n.is_finite() and abs(n) < 10**12 and n == n.quantize(Decimal(1).scaleb(-scale)),
            "Invalid amount or precision.",
        )
        need(minimum is None or n >= minimum, "Value below allowed minimum.")
        return n
    except InvalidOperation as exc:
        raise Invalid("Enter a valid number.") from exc


def operating_timezone() -> ZoneInfo:
    name = os.getenv("RMS_TIMEZONE", "Asia/Kathmandu")
    try:
        return ZoneInfo(name)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise Invalid(f"Invalid RMS_TIMEZONE {name!r}. Set an IANA name such as Asia/Kathmandu.") from exc


def today() -> date:
    return datetime.now(operating_timezone()).date()


def sysacc(c, kind):
    return value(c, "select id from account where kind=:k", k=kind)


def money_account(c, aid):
    a = first(c, "select * from account where id=:a and active and kind in ('bank','cash')", a=int(aid or 0))
    need(a, "Choose an active cash or bank account.")
    return a


def move(c, e, src, dst, amount):
    if amount:
        need(src != dst, "Choose different accounts.")
        value(
            c,
            "insert into movement(event_id,src,dst,amount) values(:e,:s,:d,:a) returning id",
            e=e,
            s=src,
            d=dst,
            a=amount,
        )


def party(c, name, kind):
    name = name.strip()
    if name:
        return value(
            c,
            "insert into party(name,kind) values(:n,:k) on conflict(lower(trim(name)),kind) do update set name=party.name returning id",
            n=name,
            k=kind,
        )


def catalogue(c, p):
    name = p["name"].strip()
    need(name, "Item name required.")
    row = first(c, "select * from item where lower(trim(name))=lower(:n)", n=name)
    need(row and row.active, "Choose an active catalogue item.")
    return row


def line(c, e, p, quantity, unit, amount, delta, category=None):
    value(
        c,
        """insert into line(event_id,item_id,category,qty,unit,amount,stock_delta)
          values(:e,:i,:c,:q,:u,:a,:s) returning id""",
        e=e,
        i=p.id,
        c=category or p.category,
        q=quantity,
        u=unit,
        a=amount,
        s=delta,
    )


def quantity(p, raw, unit):
    qty = number(raw, 3, Decimal(".001"))
    factors: dict[tuple[str, str], Decimal | int] = {
        ("g", "kg"): Decimal(".001"),
        ("kg", "g"): 1000,
        ("l", "ml"): 1000,
        ("ml", "l"): Decimal(".001"),
    }
    factor = 1 if unit == p.unit else factors.get((unit, p.unit))
    if factor is None:
        raise Invalid("Incompatible purchase and catalogue units.")
    return number(qty * factor, 3, Decimal(".001"))


def owed(c, e, day):
    return value(
        c,
        """select coalesce(abs(sum(p.amount)),0) from posting p join event x on x.id=p.event_id
        join account a on a.id=p.account_id where a.kind in ('payable','receivable') and x.day<=:d
        and (x.id=:e or (x.origin=:e and x.kind in ('payment','collection','reversal'))
       or (x.kind='reversal' and x.origin in (select id from event where origin=:e and kind in ('payment','collection'))))""",
        e=e,
        d=day,
    )


def trade(c, e, k, d, ct, pid, bank_splits):
    sale = k == "sale"
    total = Decimal(0)
    for r in d.get("lines", []):
        if not sale and not value(
            c, "select id from item where lower(trim(name))=lower(:n)", n=r["name"].strip()
        ):
            need(r["name"].strip() and r.get("category"), "Enter a category for a new expense item.")
            value(
                c,
                "insert into item(name,category,unit,tracked) values(:n,:c,:u,false) returning id",
                n=r["name"].strip(),
                c=r["category"],
                u=r.get("unit") or "entry",
            )
        p = catalogue(c, r)
        raw = r.get("qty")
        unit = r.get("unit") or p.unit
        qty = quantity(p, raw, unit) if raw else None
        need(qty or not (sale or p.tracked), "Enter quantity for a sale line or tracked item.")
        amount = None if sale else number(r["amount"], minimum=Decimal(".01"))
        line(
            c,
            e,
            p,
            qty,
            p.unit,
            amount,
            (-1 if sale else 1) * (qty or 0) if p.tracked else 0,
            r.get("category"),
        )
        total += amount or 0
    cash, bank = (number(d.get(key)) for key in ("cash", "bank"))
    if not sale and d.get("payment_mode") in ("cash", "bank", "credit"):
        cash = total if d["payment_mode"] == "cash" else Decimal(0)
        bank = total if d["payment_mode"] == "bank" else Decimal(0)
    credit = number(d.get("credit")) if sale else total - cash - bank
    need(credit >= 0, "Payments exceed the purchase total.")
    need(cash + bank + credit + sum(bank_splits.values()) > 0, "Enter a positive transaction total.")
    need(not credit or pid, "Enter the supplier or customer for this credit.")
    nominal = sysacc(c, "sales" if sale else "expense")
    accounts = [(ct.cash_id, cash), (sysacc(c, "receivable" if sale else "payable"), credit)]
    if bank:
        a = money_account(c, d.get("bank_id"))
        need(a.kind == "bank", "Select the receiving or paying bank.")
        accounts.append((a.id, bank))
    for aid, n in accounts + list(bank_splits.items()):
        move(c, e, nominal if sale else aid, aid if sale else nominal, n)


def observe(c, e, aid, iid, expected, actual, handed=0, received=0):
    value(
        c,
        """insert into observation values(:e,:a,:i,:x,:v,:h,:r) returning event_id""",
        e=e,
        a=aid,
        i=iid,
        x=expected,
        v=actual,
        h=handed,
        r=received,
    )


def check_history(c, e, day):
    bad = value(
        c,
        """with affected as(select distinct account_id from posting where event_id=:e),
    daily as(select a.id,x.day,sum(p.amount) n from affected f join account a on a.id=f.account_id
    join posting p on p.account_id=a.id join event x on x.id=p.event_id where a.kind in ('cash','transit','bank')
    group by a.id,x.day) select min(b) from (select sum(n) over(partition by id order by day) b from daily)s""",
        e=e,
    )
    need(bad is None or bad >= 0, "Insufficient account balance on this or a later date.")
    bad = value(
        c,
        """with daily as(select item_id,day,sum(stock_delta) n from line l join live_event x on x.id=l.event_id
    where item_id in(select item_id from line where event_id=:e or event_id=(select origin from event where id=:e))
    group by item_id,day) select min(b) from(select sum(n) over(partition by item_id order by day) b from daily)s""",
        e=e,
    )
    need(bad is None or bad >= 0, "This entry would make estimated stock negative.")
    conflict = value(
        c,
        """select o.event_id from observation o join live_event x on x.id=o.event_id
      where x.day>=:day and x.id<>:e and not (x.day=:day and exists(select 1 from event closing where closing.id=:e and closing.kind in ('close','reopen'))) and not exists(select 1 from event z where z.id=:e and ((z.kind in ('stock_adjust','adjustment') and z.origin=x.id) or (z.kind='reversal' and exists(select 1 from event approved where approved.id=z.origin and approved.kind in ('stock_adjust','adjustment') and approved.origin=x.id)))) and ((o.account_id in(select account_id from posting where event_id=:e))
      or (o.item_id in(select item_id from line where stock_delta<>0 and (event_id=:e or event_id=(select origin from event where id=:e))))) limit 1""",
        e=e,
        day=day,
    )
    need(not conflict, "Reverse the affected later count or handover before changing its inputs.")


def submit(c, actor, d, token, attachment=None, *, sale_parent=None):
    lock(c)
    token = str(UUID(str(token)))
    digest = hashlib.sha256(
        json.dumps(d, sort_keys=True).encode() + (attachment[1] if attachment else b"")
    ).hexdigest()
    existing = first(c, "select id,digest,actor from event where token=:t", t=token)
    if existing:
        need(existing.digest == digest and existing.actor == actor, "Submission key already used.")
        return existing.id
    k = d["kind"]
    day = date.fromisoformat(d["day"])
    need(day <= today(), "Choose today or an earlier operating date.")
    reason = d.get("reason", "").strip()
    closed = first(
        c, "select * from closed_day where kind='close' and day>=:d order by day desc limit 1", d=day
    )
    late_stock = k == "stock_count" or (
        k == "reversal"
        and value(c, "select kind='stock_count' from live_event where id=:i", i=int(d.get("origin") or 0))
    )
    if k == "reopen":
        need(
            closed and closed.day == day and reason, "Reopen the latest closed date first and give a reason."
        )
    else:
        need(
            not closed or (late_stock and closed.day == day),
            "Reopen this and later finalized days before posting.",
        )
    ct = first(c, "select * from counter where id=:i and active", i=int(d.get("counter_id") or 0))
    pid = None
    origin = int(d.get("origin") or 0) or None
    need(
        not origin or k in ("payment", "collection", "reversal", "receive", "stock_adjust", "adjustment"),
        "Unexpected originating record.",
    )
    original = first(c, "select * from live_event where id=:i", i=origin) if origin else None
    if k == "opening_credit":
        need(d.get("credit_type") in ("receivable", "payable"), "Choose a credit balance type.")
    bank_splits = {}
    credit_splits = {}
    trade_data = d
    if k == "sale" and ("bank_splits" in d or "credit_splits" in d):
        need(
            not any(d.get(key) for key in ("bank", "credit", "bank_id", "party")),
            "Use one sales allocation format.",
        )
        for bank_id, amount in d.get("bank_splits", []):
            account = money_account(c, bank_id)
            need(account.kind == "bank" and account.id not in bank_splits, "Choose each bank once.")
            bank_splits[account.id] = number(amount, minimum=Decimal(".01"))
        for name, amount in d.get("credit_splits", []):
            customer = party(c, name, "customer")
            need(customer and customer not in credit_splits, "Enter each credit customer once.")
            credit_splits[customer] = (name, number(amount, minimum=Decimal(".01")))
        if credit_splits:
            pid = next(iter(credit_splits))
            _, amount = credit_splits.pop(pid)
            trade_data = {**d, "credit": amount}
    if pid is None and k in ("sale", "bill", "opening_credit"):
        pid = party(
            c,
            d.get("party", ""),
            "customer"
            if k == "sale" or (k == "opening_credit" and d.get("credit_type") == "receivable")
            else "supplier",
        )
    if k in ("payment", "collection", "reversal", "receive"):
        if original is None or original.day > day:
            raise Invalid("Choose an active originating record.")
        pid = original.party_id
    if k in ("bill", "sale", "handover", "payment", "collection"):
        need(ct, "Choose an active counter.")
    e = value(
        c,
        """insert into event(day,kind,counter_id,party_id,reference,reason,origin,actor,token,digest)
       values(:day,:k,:ct,:p,:ref,:why,:o,:u,:t,:h) returning id""",
        day=day,
        k=k,
        ct=original.counter_id if k == "reversal" and original is not None else (ct.id if ct else None),
        p=pid,
        ref=d.get("reference", ""),
        why=reason,
        o=sale_parent or origin,
        u=actor,
        t=token,
        h=digest,
    )
    main = value(c, "select cash_id from counter where main")
    if k in ("sale", "bill"):
        trade(c, e, k, trade_data, ct, pid, bank_splits)
        for customer, (name, amount) in credit_splits.items():
            submit(
                c,
                actor,
                {"kind": "sale", "day": d["day"], "counter_id": ct.id, "party": name, "credit": str(amount)},
                uuid5(UUID(token), f"credit:{customer}"),
                sale_parent=e,
            )
        if attachment:
            need(k == "bill", "Receipts belong to purchase bills.")
            value(
                c,
                "insert into receipt values(:e,:mime,:data) returning event_id",
                e=e,
                mime=attachment[0],
                data=attachment[1],
            )
    elif k in ("payment", "collection"):
        assert original is not None  # Origin and operating date validated above.
        need(
            original.kind in (("bill", "opening_credit") if k == "payment" else ("sale", "opening_credit")),
            "Wrong credit account.",
        )
        ledger = sysacc(c, "payable" if k == "payment" else "receivable")
        need(
            value(c, "select count(*) from posting where account_id=:a and event_id=:e", a=ledger, e=origin),
            "No matching credit.",
        )
        n = number(d["amount"], minimum=Decimal(".01"))
        need(n <= min(owed(c, origin, day), owed(c, origin, date.max)), "Amount exceeds outstanding credit.")
        a = money_account(c, d["account_id"])
        need(a.kind == "bank" or a.id == ct.cash_id, "Select the paying or collecting counter.")
        move(c, e, a.id if k == "payment" else ledger, ledger if k == "payment" else a.id, n)
    elif k == "opening_credit":
        need(pid and reason, "Identify the party and explain the opening balance.")
        recv = d["credit_type"] == "receivable"
        ledger = sysacc(c, "receivable" if recv else "payable")
        equity = sysacc(c, "equity")
        move(
            c,
            e,
            equity if recv else ledger,
            ledger if recv else equity,
            number(d["amount"], minimum=Decimal(".01")),
        )
    elif k in ("opening", "adjustment", "transfer"):
        a = money_account(c, d["account_id"])
        if k == "opening":
            need(
                not value(
                    c,
                    "select 1 from live_event x join posting p on p.event_id=x.id where p.account_id=:a and (x.kind='opening' or x.day<:d) limit 1",
                    a=a.id,
                    d=day,
                ),
                "Opening balances precede activity and may be posted once per account.",
            )
        if k == "adjustment" and origin:
            obs = first(c, "select * from observation where event_id=:o and account_id=:a", o=origin, a=a.id)
            need(
                original
                and original.day == day
                and obs
                and not value(
                    c,
                    "select 1 from live_event where origin=:o and kind='adjustment' and id<>:e",
                    o=origin,
                    e=e,
                ),
                "Choose an unapplied account count from this date.",
            )
            need(
                number(d["amount"], minimum=None) == obs.actual - obs.expected,
                "Use the exact counted variance for this approval.",
            )
        if k == "transfer":
            destination = money_account(c, d["to_id"])
            if d.get("scope") == "cash":
                need(a.kind == destination.kind == "cash", "Choose two cash drawers.")
            if d.get("scope") == "bank":
                need("bank" in (a.kind, destination.kind), "Choose a bank for the source or destination.")
            move(c, e, a.id, destination.id, number(d["amount"], minimum=Decimal(".01")))
        else:
            need(reason, "Explain the opening or adjustment.")
            n = number(d["amount"], minimum=None if k == "adjustment" else Decimal(".01"))
            need(n, "Enter a nonzero amount.")
            eq = sysacc(c, "equity")
            move(c, e, eq if n > 0 else a.id, a.id if n > 0 else eq, abs(n))
    elif k in ("handover", "bank_count"):
        a = ct.cash_id if k == "handover" else money_account(c, d["account_id"]).id
        need(
            k == "handover" or value(c, "select kind='bank' from account where id=:i", i=a), "Choose a bank."
        )
        need(
            not value(
                c,
                "select 1 from observation join live_event on id=event_id where day=:d and account_id=:a",
                d=day,
                a=a,
            ),
            "Already counted today.",
        )
        expected = balance(c, a, day)
        actual = number(d["actual"])
        if k == "handover" and d.get("action") == "settle_counter":
            if a == main:
                need(
                    not value(
                        c,
                        """select 1 from counter ct where ct.active and not ct.main
                        and not exists(select 1 from live_event x where x.kind='handover'
                        and x.day=:d and x.counter_id=ct.id)""",
                        d=day,
                    ),
                    "Count all subordinate counters before Main.",
                )
                need(
                    balance(c, sysacc(c, "transit"), day) == 0,
                    "Confirm outstanding handover receipts before counting Main.",
                )
            need(actual == expected or reason, "Explain the discrepancy.")
            handed = actual if a != main else Decimal(0)
            received = handed
            if a != main:
                # Reconcile the physical drawer before moving its full contents to Main.
                delta = actual - expected
                equity = sysacc(c, "equity")
                move(c, e, equity if delta > 0 else a, a if delta > 0 else equity, abs(delta))
        else:
            handed, received = (number(d.get(key)) for key in ("handed", "received"))
        need(
            0 <= received <= handed <= actual,
            "Received must be within handed cash, and handed within counted cash.",
        )
        need(a != main and k == "handover" or handed == 0, "Only subordinate counters hand cash to Main.")
        need((actual == expected and handed == received) or reason, "Explain the discrepancy.")
        observe(c, e, a, None, expected, actual, handed, received)
        move(c, e, a, main, received)
        move(c, e, a, sysacc(c, "transit"), handed - received)
    elif k == "receive":
        assert original is not None  # Origin and operating date validated above.
        need(original.kind == "handover", "Choose a handover.")
        pending = value(
            c,
            """select handed-received-coalesce((select sum(m.amount) from movement m join live_event x on x.id=m.event_id where x.origin=:o and x.kind='receive'),0) from observation where event_id=:o""",
            o=origin,
        )
        n = number(d["amount"], minimum=Decimal(".01"))
        need(n <= pending, "Receipt exceeds cash in transit.")
        move(c, e, sysacc(c, "transit"), main, n)
    elif k in ("stock_adjust", "stock_count"):
        p = catalogue(c, d)
        need(p.tracked, "Select a stock-tracked item.")
        expected = stock(c, p.id, day)
        if k == "stock_count":
            need(
                value(c, "select value from config where key='physical_counts'"),
                "Physical counts are disabled.",
            )
            need(
                not value(
                    c,
                    "select 1 from observation join live_event on id=event_id where day=:d and item_id=:i",
                    d=day,
                    i=p.id,
                ),
                "Already counted today.",
            )
            actual = number(d["actual"], 3)
            observe(c, e, None, p.id, expected, actual)
            if d.get("apply_count") == "on" and actual != expected:
                line(c, e, p, None, p.unit, None, actual - expected)
        elif d.get("action") == "opening_stock":
            need(
                not value(
                    c,
                    """select exists(select 1 from line l join live_event x on x.id=l.event_id where l.item_id=:i)
                or exists(select 1 from observation o join live_event x on x.id=o.event_id where o.item_id=:i)""",
                    i=p.id,
                ),
                "Opening stock is for products with no activity. Use a physical count or stock adjustment.",
            )
            need(reason, "Explain the opening stock.")
            line(c, e, p, None, p.unit, None, number(d["qty"], 3))
        else:
            if origin:
                obs = first(c, "select * from observation where event_id=:i and item_id=:p", i=origin, p=p.id)
                need(
                    original
                    and original.day == day
                    and obs
                    and not value(c, "select 1 from line where event_id=:i and item_id=:p", i=origin, p=p.id)
                    and not value(
                        c,
                        "select id from live_event where origin=:i and id<>:e and kind='stock_adjust'",
                        i=origin,
                        e=e,
                    ),
                    "Choose an unapplied count from this day.",
                )
                n = obs.actual - obs.expected
            else:
                n = number(d["qty"], 3, None)
            need(n and reason, "Enter a signed quantity and a reason.")
            line(c, e, p, None, p.unit, None, n)
    elif k == "reversal":
        assert original is not None  # Origin and operating date validated above.
        need(
            original.kind not in ("close", "reopen", "configuration") and original.day == day and reason,
            "Reverse on the original date with a reason.",
        )
        need(
            not value(c, "select id from live_event where origin=:o", o=origin),
            "Reverse linked entries first.",
        )
        value(
            c,
            "insert into movement(event_id,src,dst,amount) select :e,dst,src,amount from movement where event_id=:o returning id",
            e=e,
            o=origin,
        )
    elif k == "close":
        missing = rows(
            c,
            """select name from counter where active and not exists(select 1 from live_event where kind='handover' and day=:d and counter_id=counter.id)""",
            d=day,
        )
        need(not missing, "Count cash at all active counters before closing.")
        need(
            balance(c, sysacc(c, "transit"), day) == 0,
            "Confirm outstanding handover receipts before closing.",
        )
        # Carry the physical count forward, including subsequent drawer movements that day.
        drawers = rows(
            c,
            """select o.account_id, o.actual-o.handed+coalesce((
              select sum(p.amount) from posting p join event a on a.id=p.event_id
              where p.account_id=o.account_id and a.day=x.day and a.id>x.id
                and not (a.kind='adjustment' and a.origin is not distinct from x.id)
                and a.kind not in ('close','reopen')
                and not exists(select 1 from event approved where a.kind='reversal' and a.origin=approved.id
                    and approved.kind='adjustment' and approved.origin=x.id)
            ),0) retained
            from observation o join live_event x on x.id=o.event_id join counter ct on ct.id=x.counter_id
            where x.day=:d and x.kind='handover' and ct.active""",
            d=day,
        )
        equity = sysacc(c, "equity")
        for drawer in drawers:
            delta = drawer.retained - balance(c, drawer.account_id, day)
            move(
                c,
                e,
                equity if delta > 0 else drawer.account_id,
                drawer.account_id if delta > 0 else equity,
                abs(delta),
            )

        from .reports import counters, report

        snapshot = {"counters": [dict(r) for r in counters(c, day)]}
        for section in (
            "sales",
            "purchases",
            "sold",
            "bank",
            "payable",
            "receivable",
            "credit_change",
            "stock",
            "variance",
            "counts",
        ):
            snapshot[section] = [dict(r) for r in report(c, section, {}, day, day, export=True)]
        snapshot["balances"] = [
            dict(r)
            for r in rows(
                c,
                "select a.name,coalesce(sum(p.amount) filter(where x.day<=:d),0) balance from account a left join posting p on p.account_id=a.id left join event x on x.id=p.event_id where a.kind in ('cash','bank','transit') group by a.id order by a.id",
                d=day,
            )
        ]
        value(
            c,
            "insert into closing_snapshot values(:e,cast(:v as jsonb)) returning event_id",
            e=e,
            v=json.dumps(snapshot, default=str),
        )
    elif k == "reopen":
        value(
            c,
            "insert into movement(event_id,src,dst,amount) select :e,dst,src,amount from movement where event_id=:o returning id",
            e=e,
            o=closed.id,
        )
    else:
        raise Invalid("Unknown operation.")
    value(c, "insert into source_entry values(:e,cast(:p as jsonb)) returning event_id", e=e, p=json.dumps(d))
    check_history(c, e, day)
    return e
