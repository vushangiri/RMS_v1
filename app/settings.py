from .db import balance, first, value
from .ledger import lock, need, today


def change(c, d):
    lock(c)
    k = d["action"]
    name = d.get("name", "").strip()
    if k in ("new_counter", "new_bank", "edit_bank", "new_item", "edit_item", "rename"):
        need(name, "Enter a name.")
    if k == "new_counter":
        aid = value(c, "insert into account(name,kind) values(:n,'cash') returning id", n=name + " cash")
        value(c, "insert into counter(name,cash_id) values(:n,:a) returning id", n=name, a=aid)
    elif k in ("new_bank", "edit_bank", "toggle_bank"):
        bank = None
        if k != "new_bank":
            bank = first(c, "select * from account where id=:i and kind='bank'", i=int(d["bank_id"]))
            need(bank, "Choose a bank account.")
        if k == "toggle_bank" and bank is not None:
            active = d.get("active", "off" if bank.active else "on") == "on"
            need(
                active or not bank.active or balance(c, bank.id, today()) == 0,
                "Transfer the remaining balance before archiving this bank.",
            )
            value(c, "update account set active=:active where id=:i returning id", i=bank.id, active=active)
        else:
            need(
                not value(
                    c,
                    "select 1 from account where lower(name)=lower(:n) and id<>:i",
                    n=name,
                    i=bank.id if bank else 0,
                ),
                "An account with this name already exists.",
            )
            if bank:
                value(c, "update account set name=:n where id=:i returning id", n=name, i=bank.id)
            else:
                value(c, "insert into account(name,kind) values(:n,'bank') returning id", n=name)
    elif k in ("new_item", "edit_item"):
        category = d.get("category", "").strip()
        variants = d.get("variants", [d]) if k == "new_item" else [d]
        need(variants, "Enter at least one product variation.")
        for variant in variants:
            variation = variant.get("variation", "").strip()
            need(len(variants) == 1 or variation, "Name each variation.")
            display_name = f"{name} · {variation}" if variation else name
            unit = variant.get("unit", "").strip()
            tracked = variant.get("tracked") == "on"
            need(category and unit, "Category and base unit are required.")
            need(
                len(display_name) <= 120 and len(variation) <= 80 and len(category) <= 80 and len(unit) <= 20,
                "Shorten the product name, variation, category or base unit.",
            )
            if k == "new_item":
                value(
                    c,
                    "insert into item(name,category,unit,tracked,variation) values(:n,:c,:u,:t,:v) returning id",
                    n=display_name,
                    c=category,
                    u=unit,
                    t=tracked,
                    v=variation,
                )
                continue
            item = first(c, "select * from item where id=:i", i=int(d["item_id"]))
            need(item, "Choose a product.")
            if unit != item.unit or tracked != item.tracked:
                need(
                    not value(
                        c,
                        """select exists(select 1 from line where item_id=:i and
                        (:unit or stock_delta<>0) union all select 1 from observation where item_id=:i)""",
                        i=item.id,
                        unit=unit != item.unit,
                    ),
                    "This product already has history in its current unit or stock policy. Add a new variation.",
                )
            value(
                c,
                "update item set name=:n,category=:c,unit=:u,tracked=:t,variation=:v where id=:i returning id",
                i=item.id,
                n=display_name,
                c=category,
                u=unit,
                t=tracked,
                v=variation,
            )
    elif k in ("rename", "toggle_counter"):
        ct = first(c, "select * from counter where id=:i", i=int(d["counter_id"]))
        need(ct, "Choose a counter.")
        if k == "rename":
            value(c, "update counter set name=:n where id=:i returning id", n=name, i=ct.id)
            value(c, "update account set name=:n where id=:i returning id", n=name + " cash", i=ct.cash_id)
        else:
            need(
                not ct.main and balance(c, ct.cash_id, today()) == 0,
                "Main must remain active. Transfer remaining cash first.",
            )
            value(c, "update counter set active=not active where id=:i returning id", i=ct.id)
            value(c, "update account set active=not active where id=:i returning id", i=ct.cash_id)
    elif k == "toggle_item":
        need(
            value(
                c,
                "update item set active=coalesce(:active,not active) where id=:i returning id",
                i=int(d["item_id"]),
                active=(d["active"] == "on") if "active" in d else None,
            ),
            "Choose a product.",
        )
    elif k == "tracking":
        iid = int(d["item_id"])
        has_history = value(
            c,
            "select exists(select 1 from line where item_id=:i and stock_delta<>0 union all select 1 from observation where item_id=:i)",
            i=iid,
        )
        need(
            not has_history,
            "This item has stock history. Keep its tracking policy and use a separate catalogue item for future sales-only entries.",
        )
        value(c, "update item set tracked=not tracked where id=:i returning id", i=iid)
    elif k == "physical":
        value(c, "update config set value=not value where key='physical_counts' returning value")
    else:
        need(False, "Unknown configuration change.")
