from sqlalchemy import text


def rows(c, query, /, **params):
    return c.execute(text(query), params).mappings().all()


def first(c, query, /, **params):
    return c.execute(text(query), params).mappings().first()


def value(c, query, /, **params):
    return c.execute(text(query), params).scalar()


def lock(c):
    value(c, "select pg_advisory_xact_lock(728401)")


def balance(c, aid, day):
    return value(
        c,
        """select coalesce(sum(p.amount),0) from posting p join event e on e.id=p.event_id
                     where p.account_id=:a and day<=:d""",
        a=aid,
        d=day,
    )


def stock(c, iid, day):
    return value(
        c,
        """select coalesce(sum(l.stock_delta),0) from line l join live_event e on e.id=l.event_id
                      where item_id=:i and day<=:d""",
        i=iid,
        d=day,
    )
