import csv
import io
import json
from datetime import date, timedelta
from typing import Any
from uuid import uuid4

from flask import Blueprint, Response, abort, flash, g, redirect, render_template, request, session, url_for
from PIL import Image, UnidentifiedImageError
from sqlalchemy.exc import DataError, IntegrityError

from .db import first, lock, rows, value
from .ledger import Invalid, need, submit, today
from .reports import (
    MONEY_REPORTS,
    PAGE_SIZE,
    REPORTS,
    counter_settlements,
    counters,
    credit_history,
    period,
    report,
)
from .settings import change

TRADE_HISTORY = {"expenses": "Expense history", "income": "Income history"}

bp = Blueprint("ui", __name__)
NAV = {
    "overview": "Overview",
    "counters": "Counters",
    "money": "Cash and Banking",
    "credits": "Credit Accounts",
    "stock": "Stock",
    "reports": "Reports",
    "settings": "Settings",
}
DEFAULT = {
    "overview": "register",
    "expenses": "register",
    "income": "register",
    "counters": "cash",
    "money": "cash_bank",
    "credits": "payable",
    "stock": "stock",
    "reports": "sales",
    "settings": "catalogue",
}


def page_params():
    args = request.args.to_dict()
    pg = max(1, int(args.get("page") or 1))
    lo, hi = period(args)
    return args, pg, lo, hi


@bp.get("/")
@bp.get("/workspace/<page>")
def workspace(page="overview"):
    if page not in DEFAULT:
        abort(404)
    args, pg, lo, hi = page_params()
    if page in TRADE_HISTORY and args.get("add") == "1":
        return redirect(
            url_for(
                "ui.workspace",
                page="counters",
                day=args.get("day"),
                counter=args.get("counter"),
                add="bill" if page == "expenses" else "sale",
            )
        )
    key = args.get("report", DEFAULT[page])
    if page == "settings":
        key = "catalogue"
    if page == "counters":
        args["account_kind"] = "cash"
    if page == "money":
        args["account_kind"] = "bank"
    if page == "money" and key not in (*MONEY_REPORTS, "counts"):
        key = "cash_bank"
    if page == "expenses":
        args["kind"] = "bill"
    if page == "income" and key == "register":
        args["kind"] = "sale"
    if page == "credits" and key not in ("payable", "receivable"):
        key = "payable"
    if key not in MONEY_REPORTS:
        args.pop("account", None)
        if args.get("period") == "all":
            args.pop("period")
            lo, hi = period(args)
    elif (
        key != "cash_bank"
        and args.get("account")
        and not value(
            g.c, "select 1 from account where id=:id and kind=:kind", id=int(args["account"]), kind=key
        )
    ):
        args.pop("account")
    data = report(g.c, key, args, lo, hi, pg) if page != "overview" else []
    day = date.fromisoformat(args.get("day") or str(today()))
    ct = (
        counters(g.c, day)
        if page in ("overview", "counters")
        else rows(g.c, "select * from counter order by main desc,id")
    )
    accts = (
        rows(
            g.c,
            """select a.*,coalesce(b.bal,0) balance from account a left join
       (select p.account_id,sum(p.amount) bal from posting p join event e on e.id=p.event_id where day<=:d group by p.account_id)b on b.account_id=a.id where a.kind in ('cash','bank','transit') order by a.id""",
            d=day,
        )
        if page in ("counters", "money", "credits", "income", "expenses")
        else []
    )
    history_accounts = (
        rows(g.c, "select id,name,kind from account where kind in ('cash','bank') order by kind,name")
        if page == "reports" and key in MONEY_REPORTS
        else accts
    )
    items = (
        rows(g.c, "select * from item order by name")
        if page in ("settings", "counters", "stock", "reports")
        else []
    )
    categories = {i.category for i in items} | {"Food", "Beverage", "Supplies", "Utilities", "Other"}
    units = {i.unit for i in items} | {"kg", "g", "l", "ml", "piece", "plate", "pack"}
    parties: dict[str, list[str]] = {}
    party_kinds = {
        "expenses": ("supplier",),
        "income": ("customer",),
        "credits": ("supplier", "customer"),
        "counters": ("supplier", "customer"),
        "reports": ("supplier", "customer"),
    }.get(page, ())
    if party_kinds:
        for row in rows(
            g.c, "select name,kind from party where kind=any(:kinds) order by name", kinds=list(party_kinds)
        ):
            parties.setdefault(row.kind, []).append(row.name)
    totals = (
        first(
            g.c,
            """select coalesce(-sum(p.amount) filter(where a.kind='sales'),0) sales,
       coalesce(sum(p.amount) filter(where a.kind='expense'),0) purchases,
       coalesce(sum(p.amount) filter(where a.kind='cash'),0) cash_change,
       coalesce(sum(p.amount) filter(where a.kind='bank'),0) bank_change from posting p join event e on e.id=p.event_id join account a on a.id=p.account_id
       where e.day between :lo and :hi and (:ct=0 or e.counter_id=:ct)""",
            lo=day if page == "overview" else lo,
            hi=day if page == "overview" else hi,
            ct=0 if page == "overview" else int(args.get("counter") or 0),
        )
        if page in ("counters", "overview")
        else {}
    )
    trend = []
    chart = {}
    if page == "overview":
        chart_days = int(args.get("chart_days") or 7)
        chart_type = args.get("chart_type", "bar")
        chart_series = args.get("chart_series", "both")
        chart_counter = int(args.get("chart_counter") or 0)
        need(chart_days in (7, 14, 30), "Choose a chart date range.")
        need(chart_type in ("bar", "line", "donut"), "Choose a chart type.")
        need(chart_series in ("both", "sales", "expenses"), "Choose a chart series.")
        chart = {"days": chart_days, "type": chart_type, "series": chart_series, "counter": chart_counter}
        trend = rows(
            g.c,
            """select days.day::date as day,coalesce(d.sales,0) sales,coalesce(d.expenses,0) expenses
            from generate_series(cast(:start as date),cast(:day as date),interval '1 day') days(day)
            left join (
                select e.day,-sum(p.amount) filter(where a.kind='sales') sales,
                    sum(p.amount) filter(where a.kind='expense') expenses
                from event e join posting p on p.event_id=e.id join account a on a.id=p.account_id
                where e.day between :start and :day and a.kind in ('sales','expense')
                    and (:counter=0 or e.counter_id=:counter) group by e.day
            ) d on d.day=days.day::date order by days.day""",
            start=day - timedelta(days=min(chart_days - 1, (day - date.min).days)),
            counter=chart_counter,
            day=day,
        )
        totals = dict(totals)
        totals["expected"] = sum(c.expected for c in ct)
        totals["net_activity"] = totals["sales"] - totals["purchases"]
    stock_summary = None
    if page == "stock":
        stock_summary = first(
            g.c,
            """select count(*) tracked,count(*) filter(where coalesce(b.qty,0)=0) empty,
            count(*) filter(where seen.item_id is not null) counted
            from item i
            left join (select l.item_id,sum(l.stock_delta) qty from line l
                join live_event e on e.id=l.event_id where e.day<=:day group by l.item_id) b on b.item_id=i.id
            left join (select distinct o.item_id from observation o join live_event e on e.id=o.event_id
                where e.kind='stock_count' and e.day=:day) seen on seen.item_id=i.id
            where i.active and i.tracked""",
            day=day,
        )

    def link(**changes):
        params = {**args, **changes}
        params.pop("add", None)
        return (
            url_for("ui.workspace", page=page, **{k: v for k, v in params.items() if k not in ("page",)})
            + ("&" if any(k != "page" for k in params) else "?")
            + "page="
            + str(params.get("page", 1))
        )

    preview = {}
    if page == "counters":
        for section in ("sales", "purchases", "bank", "credit_change", "sold", "stock", "variance"):
            preview[REPORTS[section]] = report(g.c, section, {}, day, day, export=True)
    related_counts = []
    if page in ("stock", "money"):
        related_counts = rows(
            g.c,
            """select x.id,coalesce(i.name,a.name) name,o.actual-o.expected variance
            from live_event x join observation o on o.event_id=x.id
            left join item i on i.id=o.item_id left join account a on a.id=o.account_id
            where x.day=:d and x.kind=:kind and o.actual<>o.expected
            and not exists(select 1 from line where event_id=x.id)
            and not exists(select 1 from live_event approved where approved.origin=x.id
                           and approved.kind in ('adjustment','stock_adjust'))
            order by x.id desc""",
            d=day,
            kind="stock_count" if page == "stock" else "bank_count",
        )
    settlements: dict[int, dict[str, list]] = {}
    if page == "counters":
        for settlement in counter_settlements(g.c, day):
            settlements.setdefault(settlement.counter_id, {}).setdefault(settlement.kind, []).append(
                settlement
            )
    return render_template(
        "workspace.html",
        settlements=settlements,
        preview=preview,
        related_counts=related_counts,
        credit_totals=first(
            g.c,
            "select coalesce(-sum(p.amount) filter(where a.kind='payable'),0) payable,coalesce(sum(p.amount) filter(where a.kind='receivable'),0) receivable from posting p join account a on a.id=p.account_id join event e on e.id=p.event_id where e.day<=:d",
            d=day,
        )
        if page == "credits"
        else {},
        print_url=url_for("ui.printable", **{**args, "report": key}),
        page=page,
        nav=NAV,
        day=day,
        lo=lo,
        hi=hi,
        args=args,
        pg=pg,
        link=link,
        export_url=url_for("ui.export", **{**args, "report": key}),
        choices={
            "counters": ["cash", "counts", "closing", "performance"],
            "income": ["sold", "sales", "register"],
            "stock": ["stock", "variance"],
            "money": ["cash_bank", "cash", "bank", "counts"],
        }.get(page, []),
        trend=[
            {
                "label": row.day.strftime("%d %b"),
                "date": row.day.isoformat(),
                "sales": str(row.sales),
                "expenses": str(row.expenses),
            }
            for row in trend
        ],
        chart=chart,
        breadcrumbs=[
            ("Counters", url_for("ui.workspace", page="counters", day=day, counter=args.get("counter")))
        ]
        if page in TRADE_HISTORY
        else [],
        stock_summary=stock_summary,
        page_title=TRADE_HISTORY.get(page),
        key=key,
        reports=REPORTS,
        data=data[:PAGE_SIZE],
        more=len(data) > PAGE_SIZE,
        counters=ct,
        accounts=accts,
        history_accounts=history_accounts,
        money_reports=MONEY_REPORTS,
        items=items,
        items_by_name={item.name: item for item in items} if page == "settings" else {},
        product_names=sorted({item.name.removesuffix(f" · {item.variation}") for item in items})
        if page == "settings"
        else [],
        categories=sorted(categories, key=str.casefold),
        units=sorted(units, key=str.casefold),
        parties=parties,
        settings_banks=rows(
            g.c, "select id,name,active from account where kind='bank' order by not active,name"
        )
        if page == "settings"
        else [],
        handovers=rows(
            g.c,
            """select x.id,ct.name,x.day from live_event x join counter ct on ct.id=x.counter_id
            join observation o on o.event_id=x.id where x.kind='handover' and x.day<=:d
            and o.handed-o.received > coalesce((select sum(m.amount) from live_event r
            join movement m on m.event_id=r.id where r.origin=x.id and r.kind='receive'),0)
            order by x.day desc,x.id desc""",
            d=day,
        )
        if page == "counters"
        else [],
        totals=totals,
        physical=value(g.c, "select value from config where key='physical_counts'"),
        closed=value(g.c, "select id from closed_day where day=:d and kind='close'", d=day),
        uuid=uuid4,
    )


@bp.get("/activity")
def activity():
    events = rows(g.c, "select id,kind,day from event order by id desc limit 8")
    return render_template("activity.html", activity=events)


@bp.get("/export")
def export():
    args, _, lo, hi = page_params()
    data = report(g.c, args.get("report", "register"), args, lo, hi, export=True)
    f = io.StringIO()
    w = csv.writer(f)
    if data:
        w.writerow(data[0].keys())
        for row in data:
            w.writerow(
                [
                    "'" + x
                    if isinstance(x, str) and x.lstrip().startswith(("=", "+", "-", "@", "\t", "\r"))
                    else x
                    for x in row.values()
                ]
            )
    return Response(
        f.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=rms-report.csv"},
    )


@bp.get("/credits/<kind>/history")
def credit_account(kind):
    if kind not in ("receivable", "payable"):
        abort(404)
    args, pg, _, day = page_params()
    party = first(
        g.c,
        "select id,name from party where kind=:kind and lower(name)=lower(:name)",
        kind="customer" if kind == "receivable" else "supplier",
        name=args.get("party", ""),
    )
    if not party:
        abort(404)
    credit_id = int(args.get("credit") or 0)
    history = credit_history(g.c, party.id, kind, credit_id, pg)
    if credit_id and not history and pg == 1:
        abort(404)
    return render_template(
        "credit_history.html",
        breadcrumbs=[
            ("Credit Accounts", url_for("ui.workspace", page="credits", report=kind, day=day)),
            *(
                [(party.name, url_for("ui.credit_account", kind=kind, party=party.name, day=day))]
                if credit_id
                else []
            ),
        ],
        breadcrumb_title=f"Credit #{credit_id}" if credit_id else party.name,
        show_operating_date=False,
        nav=NAV,
        page="credits",
        day=day,
        party=party,
        kind=kind,
        credit_id=credit_id,
        pg=pg,
        history=history[:PAGE_SIZE],
        more=len(history) > PAGE_SIZE,
    )


@bp.get("/record/<int:e>")
def record(e):
    row = first(
        g.c,
        """select x.*,u.username,c.name counter,p.name party,
        exists(select 1 from receipt where event_id=x.id) attachment from event x join operator_user u on u.id=x.actor
        left join counter c on c.id=x.counter_id left join party p on p.id=x.party_id where x.id=:e""",
        e=e,
    )
    if not row:
        abort(404)
    parent = {
        "bill": "expenses",
        "sale": "income",
        "collection": "credits",
        "payment": "credits",
        "opening_credit": "credits",
        "stock_count": "stock",
        "stock_adjust": "stock",
        "bank_count": "money",
        "transfer": "money",
        "handover": "counters",
        "close": "counters",
        "reopen": "counters",
        "receive": "counters",
        "configuration": "settings",
    }.get(row.kind, "reports")
    label = TRADE_HISTORY[parent] if parent in TRADE_HISTORY else NAV[parent]
    parent_args = {"page": parent, "day": row.day}
    if parent in TRADE_HISTORY and row.counter_id:
        parent_args["counter"] = row.counter_id
    if row.kind == "collection":
        parent_args["report"] = "receivable"
    if parent == "reports":
        parent_args["report"] = "audit"
    return render_template(
        "record.html",
        breadcrumbs=[
            *(
                [("Counters", url_for("ui.workspace", page="counters", day=row.day, counter=row.counter_id))]
                if parent in TRADE_HISTORY
                else []
            ),
            (label, url_for("ui.workspace", **parent_args)),
        ],
        breadcrumb_title=f"Record #{row.id}",
        r=row,
        nav=NAV,
        page="",
        day=row.day,
        uuid=uuid4,
        movements=rows(
            g.c,
            "select a.name source,b.name destination,m.amount from movement m join account a on a.id=m.src join account b on b.id=m.dst where event_id=:e order by m.id",
            e=e,
        ),
        lines=rows(
            g.c,
            "select i.name,l.category,l.qty,l.unit,l.amount,l.stock_delta from line l join item i on i.id=l.item_id where event_id=:e order by l.id",
            e=e,
        ),
        observations=rows(
            g.c,
            "select expected,actual,actual-expected variance,handed,received from observation where event_id=:e",
            e=e,
        ),
        related=rows(g.c, "select id,kind,day from event where origin=:e order by id", e=e),
        source=value(g.c, "select payload from source_entry where event_id=:e", e=e),
        snapshot=value(g.c, "select payload from closing_snapshot where event_id=:e", e=e),
    )


@bp.get("/receipt/<int:e>")
def receipt(e):
    r = first(g.c, "select * from receipt where event_id=:e", e=e)
    if not r:
        abort(404)
    return Response(bytes(r.content), mimetype=r.mime)


def attachment():
    f = request.files.get("receipt")
    if f and f.filename:
        try:
            with Image.open(f.stream) as im:
                need(
                    im.format in ("PNG", "JPEG") and im.width * im.height <= 16000000,
                    "Use a JPEG or PNG under 16 megapixels.",
                )
                im.thumbnail((2400, 2400))
                output = io.BytesIO()
                im.convert("RGB").save(output, "JPEG", quality=86)
                return "image/jpeg", output.getvalue()
        except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
            raise Invalid("Invalid receipt image.") from exc


@bp.post("/entry")
def entry():
    d: dict[str, Any] = request.form.to_dict()
    page = d.pop("page", "overview")
    token = d.pop("token")
    d.pop("csrf_token", None)
    if d["kind"] in ("sale", "bill"):
        keys = ["name", "qty", "unit", "category", "amount"]
        d["lines"] = [
            dict(zip(keys, line))
            for line in zip(*(request.form.getlist("row_" + k) for k in keys), strict=True)
            if any(line)
        ]
    if d["kind"] == "sale":
        for key, columns in {
            "bank_splits": ("split_bank_id", "split_bank_amount"),
            "credit_splits": ("split_customer", "split_credit_amount"),
        }.items():
            pairs = [
                [left, right]
                for left, right in zip(*(request.form.getlist(name) for name in columns), strict=True)
                if left.strip() or right.strip()
            ]
            if pairs:
                d[key] = pairs
            for column in columns:
                d.pop(column, None)
    if d["kind"] == "configuration":
        if d.get("action") == "new_item" and "variant_unit" in request.form:
            variant_fields = ("variation", "unit", "tracked")
            d["variants"] = [
                dict(zip(variant_fields, values))
                for values in zip(
                    *(request.form.getlist("variant_" + key) for key in variant_fields), strict=True
                )
            ]
            for key in variant_fields:
                d.pop("variant_" + key, None)
        lock(g.c)
        prior = first(g.c, "select id,digest,actor from event where token=cast(:t as uuid)", t=token)
        digest = json.dumps(d, sort_keys=True)
        if prior:
            need(prior.digest == digest and prior.actor == session["uid"], "Submission key already used.")
            e = prior.id
        else:
            change(g.c, d)
            e = value(
                g.c,
                """insert into event(day,kind,actor,token,digest,reason) values(:d,'configuration',:a,:t,:h,:why) returning id""",
                d=today(),
                a=session["uid"],
                t=token,
                h=digest,
                why=digest,
            )
    else:
        e = submit(g.c, session["uid"], d, token, attachment())
    g.c.commit()
    flash(f"Saved record #{e}.")
    destination = {"page": page if page in DEFAULT else "overview", "day": d["day"]}
    if page == "counters" and d["kind"] in ("bill", "sale"):
        destination["counter"] = str(d["counter_id"])
    if page == "credits" and (d["kind"] == "collection" or d.get("credit_type") == "receivable"):
        destination["report"] = "receivable"
    target = url_for("ui.workspace", **destination)
    if request.accept_mimetypes.best == "application/json":
        return {"record": e, "location": target}, 201
    return redirect(target, 303)


@bp.app_errorhandler(Invalid)
@bp.app_errorhandler(DataError)
@bp.app_errorhandler(IntegrityError)
@bp.app_errorhandler(ValueError)
@bp.app_errorhandler(KeyError)
def invalid(error):
    if "c" in g:
        g.c.rollback()
    if isinstance(error, Invalid):
        msg = str(error)
    elif (
        isinstance(error, IntegrityError)
        and getattr(getattr(error.orig, "diag", None), "constraint_name", None) == "item_name"
    ):
        msg = "A product with this name already exists. Check the catalogue, including inactive products."
    else:
        msg = "Check the required fields, names and values. Nothing was saved."
    return render_template("error.html", message=msg), 422


@bp.get("/print")
def printable():
    args, _, lo, hi = page_params()
    key = args.get("report", "register")
    records = report(g.c, key, args, lo, hi, export=True)
    return render_template("print.html", title=REPORTS[key], data=records, lo=lo, hi=hi)


@bp.get("/search")
def search():
    q = request.args.get("q", "").strip()
    pg = max(1, int(request.args.get("page") or 1))
    day = date.fromisoformat(request.args.get("end") or str(today()))
    records = report(g.c, "audit", {"q": q}, date.min, day, pg)
    matches = rows(
        g.c,
        """select * from (
        select c.name, 'Counter' kind, c.id from counter c
        union all select name,'Item',id from item
        union all select name,kind,id from party
        union all select name,'Bank',id from account where kind='bank') t
        where :q<>'' and name ilike :like order by kind,name limit :limit offset :offset""",
        q=q,
        like="%" + q + "%",
        limit=PAGE_SIZE + 1,
        offset=(pg - 1) * PAGE_SIZE,
    )
    return render_template(
        "search.html",
        breadcrumbs=[("Overview", url_for("ui.workspace", page="overview", day=day))],
        breadcrumb_title="Search",
        nav=NAV,
        page="",
        day=day,
        q=q,
        pg=pg,
        records=records[:PAGE_SIZE],
        matches=matches[:PAGE_SIZE],
        more=len(records) > PAGE_SIZE or len(matches) > PAGE_SIZE,
    )
