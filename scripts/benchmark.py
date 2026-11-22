"""Run only on a migrated, empty RMS test database. Produces a disposable workload."""

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import event

from app import create_app
from app.db import value
from app.ledger import today


def main():
    app = create_app()
    db = app.extensions["database"]
    if not db.url.database.endswith("_test"):
        raise SystemExit("Requires a disposable _test database")
    with db.begin() as c:
        if value(c, "select count(*) from event") or value(c, "select count(*) from operator_user"):
            raise SystemExit("Use an empty migrated test database.")
        c.exec_driver_sql("insert into operator_user(username,password_hash) values('benchmark','disabled')")
        c.exec_driver_sql("""insert into event(day,kind,counter_id,actor,token,digest,reference)
           select current_date-(mod(n,90)),'sale',1+mod(n,2),1,gen_random_uuid(),'fixture','Day batch '||n from generate_series(1,10000)n""")
        c.exec_driver_sql(
            """insert into movement(event_id,src,dst,amount) select e.id,a.id,c.cash_id,25.50 from event e join counter c on c.id=e.counter_id cross join account a where a.kind='sales'"""
        )
        c.exec_driver_sql("insert into item(name,category,unit,tracked) values('Momo','Food','plate',false)")
        c.exec_driver_sql(
            "insert into line(event_id,item_id,category,qty,unit) select id,1,'Food',1,'plate' from event"
        )
        sid = value(
            c, "insert into login_session values(gen_random_uuid(),1,now()+interval '1 hour') returning token"
        )
        c.exec_driver_sql("analyze")
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(uid=1, sid=str(sid))
    statements = []

    def count(*args):
        statements.append(1)

    event.listen(db, "before_cursor_execute", count)
    day = str(today())
    for path in [
        "/",
        "/workspace/reports?period=monthly&report=sold",
        "/workspace/reports?period=custom&start=2020-01-01&end=" + day + "&report=register&q=9999",
    ]:
        measurements = []
        for i in range(12):
            statements.clear()
            start = time.perf_counter()
            result = client.get(path)
            assert result.status_code == 200
            measurements.append((time.perf_counter() - start) * 1000)
        print(
            path,
            "median_ms",
            round(statistics.median(measurements[2:]), 1),
            "max_ms",
            round(max(measurements[2:]), 1),
            "queries",
            len(statements),
            "html_bytes",
            len(result.data),
        )


if __name__ == "__main__":
    main()
