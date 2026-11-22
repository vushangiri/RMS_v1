# Development

Open this directory in VS Code from Ubuntu or WSL2. Python 3.12+, PostgreSQL 16, and Chromium are the development dependencies.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
export DATABASE_URL='postgresql+psycopg://rms:YOUR_DEV_PASSWORD@localhost:5432/rms_dev'
export SECRET_KEY="$(openssl rand -hex 48)"
export COOKIE_SECURE=0
alembic upgrade head
flask --app wsgi:app init-admin
flask --app wsgi:app run
```

Create the development database and role first, with ownership assigned to that role. The URL above assumes a native PostgreSQL listener; the Compose database is private. In Compose, use `docker compose exec app` for Flask commands. WSL2 supports the same commands as Ubuntu. Use the local browser to access the loopback port.

## Validation

```bash
export DATABASE_URL='postgresql+psycopg://rms:YOUR_TEST_PASSWORD@localhost:5432/rms_test'
alembic upgrade head
python -m playwright install chromium
ruff check .
mypy app
pytest -q
```

The database must end in `_test`. Tests truncate and reseed tables. Keep restaurant data in a separate database. Use `CHROMIUM_PATH` to select an already installed Chromium executable. Run `python scripts/benchmark.py` only against a newly migrated, empty test database. The benchmark writes 10,000 synthetic receipts.

## Changing the application

Keep financial writes inside one transaction and use the common serialization lock. Give each form its own UUID. Add SQL constraints and a versioned Alembic revision for schema changes. Preserve any correction and replay behavior affected by the change. Add independent expected balances to the integration suite. Exercise the real form and inspect the resulting journal and stock rows. Include new aggregate metrics in the business definitions and closing snapshot where applicable.

The migration SQL is a fresh-install baseline. For the next revision, use `alembic revision -m "describe the change"`, set the parent revision and implement the upgrade. The single `operator_user` bootstrap can later grow into permission grants without changing financial-event authorship. Public registration and role configuration are intentionally absent.
