# Architecture

The two principal entry forms correspond to the restaurant's handwritten bill and income records. A server-rendered Flask application retains the supplied responsive navigation, green cards, counter tabs, collapsed entry forms, tables and mobile menu. The Overview combines daily metrics, counter summaries, quick actions and shared stock. The eight other screens cover Expenses, Income, Counters, Cash & Bank, Credit Accounts, Stock, Reports and Settings.

## Transaction path

A form carries a CSRF token and a new UUID. The handler validates the upload, opens the request transaction, takes one PostgreSQL transaction-scoped advisory lock and checks the UUID. A repeated matching request returns its previous record. A different payload with the same key is rejected. The original input, dated event, linked journal pairs, item lines and receipt commit together. Failures roll back on the request connection.

The lock serializes financial writes across workers, including closing and settlement. This trades peak write throughput for simpler correctness at a single-accountant restaurant. Reader requests use repeatable read so the components of a report share a snapshot. The read model uses indexed SQL aggregations through SQLAlchemy Core. No summary cache needs to be kept in sync.

| Module or table | Responsibility |
|---|---|
| app/__init__.py | Bootstrap, login, CSRF, signed cookies, expiring server-side sessions and route protection |
| app/web.py and templates | Daily forms, validated receipt upload, linked record details, print and CSV |
| app/settings.py | Counter and account configuration, item catalogue and counting policy |
| app/ledger.py | Expense and sales posting, credit allocation, transfers, observations, reversals and closing |
| app/reports.py | Date ranges, filtered database aggregates, reconciliation and pagination |
| event and source_entry | Actor, date, type, original document, reason, unique retry key and submitted fields |
| movement and posting view | Each positive amount moves from one account to another. The view emits both signed entries |
| line | Base-unit quantity, purchase amount, category at entry and signed stock movement |
| observation | Expected and counted values, cash handed and cash received |
| receipt | Validated and re-encoded receipt image, included in database backups |
| closing_snapshot | Immutable review totals and counts at the instant of finalization |
| live_event and closed_day views | Effective records after reversals and latest closing status |

## Design decisions and sources

* PostgreSQL transaction-level advisory locks release at transaction end. A standalone process mutex cannot coordinate two Gunicorn workers. The application lock also prevents simultaneous payments against the same outstanding invoice. [PostgreSQL locking](https://www.postgresql.org/docs/16/explicit-locking.html)
* Each credit sale identifies a customer. Collections reduce that receivable, while credit purchases and supplier settlements use a separate payable account. [Accounts receivable entries and collection examples](https://www.accountingcoach.com/accounts-receivable-and-bad-debts-expense/explanation)
* The browser uses locally bundled HTMX, ordinary HTML forms and a small script for dynamic rows, payment controls and retry-safe submission. The original stylesheet is the design source. Alpine and Tailwind add no required behavior to these forms. Runtime asset loading stays local. Server-calculated Decimal values determine every posting.
* Password hashing, output escaping, same-origin scripts, CSRF validation, upload size limits and secure cookies protect the public entry point. Operational data stays out of the service worker cache. [Flask web security](https://flask.palletsprojects.com/en/stable/web-security/)
* Two Gunicorn workers serve the web application behind Nginx. A separate one-shot migration completes before startup. Custom-format PostgreSQL backups include receipts and support restores to a fresh database. [Gunicorn deployment](https://flask.palletsprojects.com/en/stable/deploying/gunicorn/) · [PostgreSQL dump and restore](https://www.postgresql.org/docs/16/backup-dump.html)

Future POS imports can call the same posting service with stable source IDs mapped to idempotency UUIDs. Recipe depletion would require a separately versioned recipe model. Existing sales-only quantities carry no ingredient assumptions.
