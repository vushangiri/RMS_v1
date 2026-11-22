# Restaurant Management System

A single-accountant ledger for a Nepalese restaurant with one Main Counter and separate counter drawers. Staff can enter a bill once, record daily cash, bank and credit sales, count cash and settle each drawer. PostgreSQL stores the source entries, paired financial movements, quantities, receipts and closing history. All amounts are NPR. Operating dates follow Asia/Kathmandu.

## Start a fresh installation

Use Docker Engine with the Compose v2 plugin. Extract the archive and run these commands from the directory containing `compose.yml`.

```sh
sh scripts/configure.sh
docker compose up -d --build
docker compose ps -a
docker compose exec app flask --app wsgi:app init-admin
```

The migration service exits successfully before Gunicorn starts. The administrator command prompts for credentials and runs once. Only the bundled Nginx listener is published, at 127.0.0.1:8090. Use the HTTPS setup in [DEPLOYMENT.md](DEPLOYMENT.md) for your VPS. For local HTTP development only, change `COOKIE_SECURE=0` in `.env` and recreate the app with `docker compose up -d`. Open http://localhost:8090.

This distribution uses a **fresh schema** and a separate default Compose project named `rms-ledger`. Keep an earlier RMS database and its volumes intact. There is no importer from the earlier schema or the browser prototype.

## First operating day

1. Open **Settings**. Name the counters, add bank accounts and enter items that need stock tracking. Use a single base unit per item, such as kg, bottle or plate.
2. In **Cash & Bank**, record actual starting balances once. Enter historical debts in **Credit Accounts**. Enter starting quantities as explained stock adjustments.
3. Use **Counters** to distribute Main's opening cash. The two drawer movements are linked.
4. In **Expenses**, enter the amount for each bill line. Choose fully paid cash, bank, unpaid, or partial/mixed. A familiar item fills its category and unit. A new free-text expense item is added to the catalogue with stock tracking off.
5. In **Income**, enter payment totals and any quantities sold. When several customers take credit, submit separate non-overlapping sales batches with each customer's own amounts.
6. In **Credit Accounts**, use the payment or collection action on the original record. Receipts and payments affect the outstanding balance automatically.
7. Count subordinate drawers before handover. Enter cash handed over and cash received separately. Confirm any later receipt, count Main last, review the restaurant totals and finalize the date.

For a disposable trial, run `docker compose exec app flask --app wsgi:app seed-demo` immediately after bootstrap. It adds yesterday's example transactions. Production starts with empty balances.

## Project guide

| File | Contents |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | UI mapping, research, schema, locking and posting design |
| [BUSINESS_RULES.md](BUSINESS_RULES.md) | Metric definitions, corrections and accounting assumptions |
| [DEVELOPMENT.md](DEVELOPMENT.md) | VS Code / Codex workflow, commands and extension points |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Ubuntu deployment, TLS, backup, recovery and updates |
| [TESTING.md](TESTING.md) | Executed checks, independent reconciliation, performance and unverified deployment steps |
| [CHANGELOG.md](CHANGELOG.md) | Release changes |

For native development use Python 3.12 and PostgreSQL 16. Install `requirements-dev.txt`, set `DATABASE_URL` and `SECRET_KEY`, run `alembic upgrade head`, then `flask --app wsgi:app run`. The test commands and dedicated database requirement are in DEVELOPMENT.md.
