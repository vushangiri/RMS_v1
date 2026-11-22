"""Bound report filters; accounting totals come from server-side aggregates."""

import calendar
from datetime import date, timedelta

from .db import rows
from .ledger import need, today

PAGE_SIZE = 20


def period(args):
    end = date.fromisoformat(args.get("day") or str(today()))
    start = end
    mode = args.get("period", "daily")
    if mode == "all":
        start, end = date.min, today()
    elif mode == "weekly":
        start = end - timedelta(days=end.weekday())
        end = start + timedelta(days=6)
    elif mode == "monthly":
        start = end.replace(day=1)
        end = end.replace(day=calendar.monthrange(end.year, end.month)[1])
    elif mode == "yearly":
        start, end = end.replace(month=1, day=1), end.replace(month=12, day=31)
    elif mode == "custom":
        start = date.fromisoformat(args.get("start") or str(end))
        end = date.fromisoformat(args.get("end") or str(end))
    need(start <= end, "Start date must precede end date.")
    return start, end


REPORTS = {
    "register": "Transaction register",
    "audit": "Audit history",
    "catalogue": "Item catalogue",
    "payments": "Purchase payment breakdown",
    "credit_change": "Credit movements",
    "sales": "Sales by counter",
    "purchases": "Purchases by item",
    "sold": "Quantities sold",
    "supplier": "Supplier purchases",
    "cash": "Cash transactions",
    "cash_bank": "Cash and bank transactions",
    "bank": "Bank transactions",
    "performance": "Counter performance",
    "payable": "Payables",
    "receivable": "Receivables",
    "stock": "Stock balances",
    "variance": "Stock discrepancies",
    "closing": "Daily closing history",
    "counts": "Cash and bank counts",
}
BASE = """with selected as (
 select e.*,coalesce(c.name,'Restaurant') counter,coalesce(p.name,'') party
 from live_event e left join counter c on c.id=e.counter_id left join party p on p.id=e.party_id
 where e.day between :lo and :hi and (:ct=0 or e.counter_id=:ct)
 and (:who='' or lower(p.name)=lower(:who))
 and (:method='' or exists(select 1 from posting z join account a on a.id=z.account_id where z.event_id=e.id and a.kind=:method))
 and (:q='' or concat_ws(' ',e.id,e.day,e.kind,e.reason,e.reference,c.name,p.name) ilike :like
 or exists(select 1 from line l join item i on i.id=l.item_id where l.event_id=e.id and concat_ws(' ',i.name,l.category,l.amount) ilike :like)
 or exists(select 1 from observation o left join item i on i.id=o.item_id left join account a on a.id=o.account_id where o.event_id=e.id and concat_ws(' ',i.name,a.name,o.actual) ilike :like)
 or exists(select 1 from movement m join account a on a.id=m.src join account b on b.id=m.dst where m.event_id=e.id and concat_ws(' ',a.name,b.name,m.amount) ilike :like))
), entries as (select p.*,a.kind,a.name from posting p join account a on a.id=p.account_id)
"""
QUERIES = {
    "catalogue": """select name item,category,unit,case when tracked then 'Tracked' else 'Sales only' end stock_policy,case when active then 'Active' else 'Inactive' end status from item where :q='' or concat_ws(' ',name,category,unit) ilike :like order by not active,name""",
    "audit": "select e.id record,e.day,e.kind,e.counter,e.party,e.reference,e.reason,e.origin from selected e order by e.id desc",
    "payments": """select e.id record,e.day,e.party supplier,sum(-p.amount) purchase,
    coalesce(sum(-p.amount) filter(where p.kind='cash'),0) cash_paid,coalesce(sum(-p.amount) filter(where p.kind='bank'),0) bank_paid,
    coalesce(sum(-p.amount) filter(where p.kind='payable'),0) billed_on_credit from selected e join entries p on p.event_id=e.id where e.kind='bill' and p.kind<>'expense' group by e.id,e.day,e.party order by e.day desc,e.id desc""",
    "credit_change": """select e.id record,e.day,e.counter,e.party,e.kind,p.kind account,case when p.kind='payable' then -p.amount else p.amount end change from selected e join entries p on p.event_id=e.id where p.kind in ('receivable','payable') order by e.day desc,e.id desc""",
    "register": """select e.id record,e.day,e.kind,e.counter,e.party,e.reference,coalesce(sum(m.amount),0) moved from selected e left join movement m on m.event_id=e.id group by e.id,e.day,e.kind,e.counter,e.party,e.reference order by e.day desc,e.id desc""",
    "sales": """select e.counter,sum(p.amount) sales,sum(case when p.kind='cash' then p.amount else 0 end) cash,sum(case when p.kind='bank' then p.amount else 0 end) bank,sum(case when p.kind='receivable' then p.amount else 0 end) credit from selected e join entries p on p.event_id=e.id where e.kind='sale' and p.kind<>'sales' group by e.counter order by e.counter""",
    "performance": """select e.counter,coalesce(-sum(amount) filter(where p.kind='sales'),0) sales,coalesce(sum(amount) filter(where p.kind='expense'),0) expenses from selected e join entries p on p.event_id=e.id group by e.counter order by e.counter""",
    "purchases": """select i.name item,l.category,l.unit,sum(qty) quantity,sum(l.amount) purchased from selected e join line l on l.event_id=e.id join item i on i.id=l.item_id where e.kind='bill' and (:item='' or lower(i.name)=lower(:item)) and (:cat='' or lower(l.category)=lower(:cat)) group by i.name,l.category,l.unit order by i.name,l.category""",
    "sold": """select i.name item,l.unit,sum(l.qty) sold from selected e join line l on l.event_id=e.id join item i on i.id=l.item_id where e.kind='sale' and (:item='' or lower(i.name)=lower(:item)) and (:cat='' or lower(l.category)=lower(:cat)) group by i.name,l.unit order by i.name""",
    "supplier": """select coalesce(nullif(e.party,''),'Unspecified') supplier,sum(p.amount) purchases from selected e join entries p on p.event_id=e.id where e.kind='bill' and p.kind='expense' group by e.party order by supplier""",
    "variance": """select e.id record,e.day,i.name item,i.unit,o.expected,o.actual,o.actual-o.expected variance from selected e join observation o on o.event_id=e.id join item i on i.id=o.item_id order by e.day desc,e.id desc""",
    "counts": """select e.id record,e.day,a.name account,o.expected,o.actual,o.actual-o.expected variance,o.handed,o.received,o.actual-o.handed retained from selected e join observation o on o.event_id=e.id join account a on a.id=o.account_id where (:account_kind='' or a.kind=:account_kind) order by e.day desc,e.id desc""",
    "closing": """select e.id record,e.day,e.kind,e.reason from selected e where kind in ('close','reopen') order by e.day desc,e.id desc""",
    "stock": """select i.name item,i.unit,coalesce(sum(l.stock_delta) filter(where e.day<:lo),0) opening,coalesce(sum(l.stock_delta) filter(where e.day between :lo and :hi),0) change,coalesce(sum(l.stock_delta) filter(where e.day<=:hi),0) estimated from item i left join line l on l.item_id=i.id left join live_event e on e.id=l.event_id where i.tracked and (:q='' or i.name ilike :like) group by i.id order by i.name""",
}
MONEY_REPORTS = ("cash", "bank", "cash_bank")
for kind in MONEY_REPORTS:
    QUERIES[kind] = """select e.id record,e.day,e.kind,e.counter,p.name account,
    coalesce(sum(p.amount) filter(where p.amount>0),0) money_in,
    coalesce(-sum(p.amount) filter(where p.amount<0),0) money_out,sum(p.amount) change,e.party,e.reference
    from selected e join entries p on p.event_id=e.id
    where (p.kind=:report or (:report='cash_bank' and p.kind in ('cash','bank')))
    and (:account=0 or p.account_id=:account)
    and (:drawer=0 or (p.kind='cash' and p.account_id=(select cash_id from counter where id=:drawer))
        or (p.kind='bank' and e.counter_id=:drawer))
    group by e.id,e.day,e.kind,e.counter,p.account_id,p.name,e.party,e.reference
    having :direction='' or (:direction='in' and bool_or(p.amount>0))
        or (:direction='out' and bool_or(p.amount<0))
    order by e.day desc,e.id desc,p.name,p.account_id"""
for kind in ("payable", "receivable"):
    QUERIES[
        kind
    ] = """select e.id record,e.day,e.counter,e.party,abs(orig.amount) original,abs(orig.amount)-coalesce(x.paid,0) outstanding from selected e join entries orig on orig.event_id=e.id and orig.kind=:report
    left join lateral (select sum(abs(p.amount)) paid from live_event s join entries p on p.event_id=s.id and p.kind=:report where s.origin=e.id and s.kind in ('payment','collection') and s.day<=:hi) x on true
    where e.kind in ('sale','bill','opening_credit') order by e.day,e.id"""


def report(c, key, args, lo, hi, page=1, export=False):
    need(key in QUERIES, "Unknown report.")
    q = args.get("q", "").strip()
    counter = int(args.get("counter") or 0)
    params = {
        "q": q,
        "like": "%" + q + "%",
        "ct": 0 if key in MONEY_REPORTS else counter,
        "drawer": counter,
        "direction": args.get("direction", "") if key in MONEY_REPORTS else "",
        "account": int(args.get("account") or 0) if key in MONEY_REPORTS else 0,
        "who": args.get("party", ""),
        "method": args.get("method", ""),
        "item": args.get("item", ""),
        "cat": args.get("category", ""),
        "account_kind": args.get("account_kind", ""),
        "report": key,
        "lo": date.min if key in ("payable", "receivable") else lo,
        "hi": hi,
    }
    source = BASE.replace("from live_event e", "from event e") if key in (*MONEY_REPORTS, "audit") else BASE
    query = source + QUERIES[key]
    if key == "register" and args.get("kind"):
        query = "select * from (" + query + ") filtered where kind=:wanted order by day desc,record desc"
        params["wanted"] = args["kind"]
    if not export:
        query += " limit :limit offset :offset"
        params["limit"] = PAGE_SIZE + 1
        params["offset"] = max(page - 1, 0) * PAGE_SIZE
    return rows(c, query, **params)


def counters(c, day):
    return rows(
        c,
        """with daily as(select p.account_id,
     coalesce(sum(p.amount) filter(where e.day<:d or e.kind='opening' or (e.kind='reversal' and exists(select 1 from event o where o.id=e.origin and o.kind='opening'))),0) opening,
     coalesce(sum(p.amount) filter(where e.day=:d and e.kind<>'opening' and not (e.kind='reversal' and exists(select 1 from event o where o.id=e.origin and o.kind='opening')) and p.amount>0),0) inflows,
     coalesce(-sum(p.amount) filter(where e.day=:d and e.kind<>'opening' and not (e.kind='reversal' and exists(select 1 from event o where o.id=e.origin and o.kind='opening')) and p.amount<0),0) outflows,
     sum(p.amount) expected from posting p join event e on e.id=p.event_id where day<=:d group by p.account_id),
     counts as(select x.id,o.* from live_event x join observation o on o.event_id=x.id where x.day=:d)
     select c.id,c.name,c.main,c.active,c.cash_id,coalesce(d.opening,0) opening,coalesce(d.inflows,0) inflows,coalesce(d.outflows,0) outflows,coalesce(d.expected,0) expected,o.expected counted_expected,o.actual,o.handed,o.received,o.actual-o.expected variance,o.actual-o.handed retained from counter c left join daily d on d.account_id=c.cash_id left join counts o on o.account_id=c.cash_id order by c.main desc,c.id""",
        d=day,
    )


def counter_settlements(c, day):
    return rows(
        c,
        """select x.id, x.counter_id, x.kind, party.name party,
        a.name account, m.amount
        from live_event x join movement m on m.event_id=x.id
        join account a on a.id=case when x.kind='collection' then m.dst else m.src end
        left join party on party.id=x.party_id
        where x.day=:d and x.kind in ('collection','payment')
        order by x.id""",
        d=day,
    )


def credit_history(c, party_id, kind, credit_id, page):
    return rows(
        c,
        """with movements as (
            select e.id record,e.day,e.kind,
                case
                    when e.kind in ('payment','collection') then e.origin
                    when e.kind='reversal' and original.kind in ('payment','collection') then original.origin
                    when e.kind='reversal' then e.origin
                    else e.id
                end credit_record,
                case when :kind='payable' then -sum(p.amount) else sum(p.amount) end change
            from event e join posting p on p.event_id=e.id join account a on a.id=p.account_id
            left join event original on original.id=e.origin
            where e.party_id=:party and a.kind=:kind
            group by e.id,original.kind,original.origin
        )
        select *,sum(change) over(order by day,record) balance from movements
        where (:credit=0 or credit_record=:credit)
        order by day,record limit :limit offset :offset""",
        party=party_id,
        kind=kind,
        credit=credit_id,
        limit=PAGE_SIZE + 1,
        offset=(page - 1) * PAGE_SIZE,
    )
