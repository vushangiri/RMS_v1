# Release verification · 21 November 2026

## Executed checks

| Check | Outcome |
|---|---|
| Fresh Alembic migration | Completed on real PostgreSQL 16.2 |
| Pytest | 23 passed in 19.20 seconds. The installed AnyIO pytest plugin issued one deprecation warning |
| Playwright | Chromium headless shell 153 ran the accountant workflow at 390×844, 820×1180 and 1440×900 |
| Ruff and mypy | Passed; mypy checked untyped function bodies across seven application modules |
| Gunicorn | Two workers served login and database readiness |
| Nginx | 1.28.0 configuration validated; a live proxy forwarded health and login to Gunicorn using loopback addresses in place of Compose service DNS |
| Compose | v2.39.4 validated the resolved deployment configuration with `config --quiet` |
| Backup and recovery | PostgreSQL custom dump restored to a separate database; seven events survived, including a bill receipt, two counts and a closing snapshot |
| Restart | PostgreSQL restarted with the data directory preserved. Gunicorn returned ready again and all seven events remained |

The restore drill compared records, transfers, item lines, accounts, counters, bootstrap user, items, original inputs, observations, the closing snapshot and receipt bytes. The restored signed postings summed to zero.

## Independent reconciliation

The test starts with Main holding NPR 30,000 and distributes 10,000 to Counter 2. Two bills total 7,600; 5,500 remains payable. Sales total 10,700 across the two counters including 1,000 credit. After a deposit, withdrawal, partial handover and later receipt confirmation, the expected balances were calculated separately from application queries.

| Checkpoint | Main cash | Counter 2 ledger cash | Bank | Payable | Receivable |
|---|---:|---:|---:|---:|---:|
| First close | 32,100 | 1,000 | 4,500 | 5,500 | 1,000 |
| After day-two supplier payment and customer collection | 31,600 | 1,000 | 4,900 | 5,000 | 600 |

Counter 2 physically retained 990, preserving its recorded shortage of 10. The bank statement showed a difference of −50. Main received the remaining 100 of the handover before closing. Day two generated zero new sales and purchases. Pork purchases were entered as 10,000 g, three kg were sold across two counters, and approval of a physical variance left 6.5 kg. Five plates of momo appeared in sales quantities only.

## Coverage

* Integration checks exercise duplicate submissions under four concurrent callers, competing collections on one credit, transaction rollback, immutable money movements, linked reversals, duplicate opening prevention, partial transfers, missing counter counts, reopening, backdating and balance carry-forward.
* Financial cases include multiple bills and lines, mixed payment allocation, credit without a party, cash/bank transfers, separate bank accounts, stock adjustments and precision/range rejection.
* Web tests cover protected records, CSRF, expiring sessions, login throttling, receipt re-encoding/rejection, HTML escaping, special characters in bound search parameters, filtered report pages, full CSV/print output beyond the first page and catalogue/global lookup.
* Real browser tests log in, create a purchase with two lines, post mixed sales, make a supplier payment and customer collection, record a stock count, transfer cash, complete both counter counts and finalize the restaurant day. They open the saved close, check document width and collect JavaScript errors. The phone test also uses the mobile navigation, global lookup, static-only service worker cache and sign-out.

## Performance observations

Local loopback, 10,000 synthetic sales and item lines across 90 days and two counters. Ten warm Flask request measurements after two warmups. Query counts include the operator session lookup and remain independent of table row count.

| Request | Median | Maximum | SQL statements |
|---|---:|---:|---:|
| Overview | 49.6 ms | 102.2 ms | 9 |
| Monthly quantities sold | 7.5 ms | 9.7 ms | 6 |
| All-period reference search | 30.2 ms | 51.7 ms | 6 |

A Chromium phone viewport served by Gunicorn measured a median warm overview load of 66.1 ms and 7.6 ms from adding an expense line to the second animation frame. The measurements exclude a Nepal mobile network and production hardware. The implementation avoids querying account balances on unrelated report pages and uses grouped counter queries. Search by text fragment can still scan history; repeat the supplied benchmark at the restaurant's actual volume.

## Deployment verification boundary

No Docker daemon or public TLS endpoint was available here. Container image builds, Compose startup/restart, GitHub Actions execution, public certificate renewal and installation from an actual phone's home-screen prompt remain unverified. Native PostgreSQL, Gunicorn and Nginx were exercised together; the Compose smoke test is included in CI. Validate the exact container and HTTPS setup before putting the live restaurant ledger on it.

To reproduce the automated suite, follow DEVELOPMENT.md. To rehearse recovery with your deployment, follow DEPLOYMENT.md and restore into a new database.

## Desktop workspace and Settings update

* A fresh PostgreSQL 16.15 test database migrated successfully. Pytest passed all 23 tests in 23.87 seconds.
* Chromium exercised the daily workflow at 390×844, 820×1180 and 1440×900, including the expense shortcut, catalogue autofill, single-bank selection, product creation and duplicate-name feedback. The suite verified one product and one configuration audit event after the duplicate attempt.
* Ruff, mypy and JavaScript syntax checks passed. Docker Compose rebuilt and replaced the app container. The local proxy returned a ready health response and served the updated assets.

## Counter, stock, and split sales update

* Pytest passed all 26 tests in 46.42 seconds on isolated PostgreSQL 16.15. Chromium exercised split bank and credit sales and separate settlements at 390×844, 820×1180, and 1440×900. Desktop checks also covered product editing, archiving, bank renaming, form help, appearance persistence and the activity log.
* Integration checks verified that a retried split sale posts one set of stock lines and that settling one customer leaves the other balance intact. Duplicate banks and customers roll back the entire submission.
* Cash finalization carries the physical drawer balance forward. In the reconciliation above, new finalizations now carry Counter 2's 990 instead of 1,000. A separate test verified that reopening restores the pre-closing book balance and that a late stock count updates the live estimate while preserving the saved closing snapshot.
* A separate test database upgraded from `ledger_01` to `ledger_02` with an existing catalogue row. The product name and unit survived unchanged. Ruff, mypy, JavaScript syntax checks and Compose configuration validation passed.
* The live Compose upgrade completed at `ledger_02` after a validated PostgreSQL backup. The local proxy returned a ready health response and served the updated stylesheet.

## Counter settlement and catalogue entry · 22 November 2026

* Fresh migrations reached `ledger_02` on isolated PostgreSQL 16.10. Pytest passed all 30 tests in 35.96 seconds.
* Ledger regression tests covered a subordinate shortage and overage, mandatory variance notes, Main counting last, a historical receipt pending at Main's count, idempotent submission, finalization, reopening, and correct cash balances after reversal.
* Counter credit coverage verified an NPR 3,000 total with three party records, including a bank receipt, and excluded another counter's collection, a prior-day collection and a reversed collection from that breakdown. Browser tests opened both the collections and payments breakdowns and verified their record links.
* Chromium exercised the cash count, credit breakdowns, and searchable catalogue grid at 390×844, 820×1180 and 1440×900. The desktop workflow saved two product variations in one form. Integration coverage verified separate units and tracking settings, rollback of the entire batch on a duplicate variation, and an idempotent retry.
* Ruff formatting and lint, mypy, JavaScript syntax checks and Docker Compose configuration validation passed.

## Credit, cash and bank history · 22 November 2026

* All 32 tests passed in 31.43 seconds on isolated PostgreSQL 16.10 migrated to `ledger_02`. Ruff formatting and lint, mypy and Compose configuration validation passed.
* Integration checks verified the running balance from opening credit through full settlement, including a reversed collection, separate payable and receivable histories for the same name, and individual credit history. Cash and bank checks covered drawer transfers, both sides of a bank deposit, its reversal, the selected day, all dates, and counter or account filtering.
* Chromium opened the customer history and used the combined transaction report with the all-dates and account filters at 390×844, 820×1180, and 1440×900.

## Counter entry and workspace refresh · 22 November 2026

* All 32 tests passed in 34.29 seconds on isolated PostgreSQL 16.10 migrated to `ledger_02`. Ruff formatting and lint, mypy, JavaScript syntax checks, and Docker Compose configuration validation passed.
* Chromium verified the Overview chart, counter-prefilled income and expense dialogs, the expense history link, the stock picker and base unit, the combined cash and bank view, counter cash direction filters, and the Settings card order at 390×844, 820×1180, and 1440×900. A separate desktop visual check inspected the rendered Overview chart and Stock summary.
* The rebuilt app container became healthy. The reloaded local proxy served the updated versioned assets and returned a ready health response.

## Navigation, charts, and hosting port · 22 November 2026

* All 32 tests passed in 35.54 seconds on isolated PostgreSQL 16.10 at migration `ledger_02`. Ruff, mypy, JavaScript syntax checks, and Compose configuration validation passed.
* Chromium checked breadcrumbs, chart filters, grouped bar and line rendering, doughnut selection, pointer and keyboard tooltips, legends, and embedded 20-row pagination at 390×844, 820×1180, and 1440×900. The server report test showed 20, 20, and 13 rows on successive pages and verified that CSV and print included all 53 rows.
* The rebuilt app and recreated proxy became healthy. Compose published the proxy at `127.0.0.1:8090`, where the health endpoint and updated frontend assets responded successfully.

## Daily backup and fresh-volume restore · 22 November 2026

* Compose configuration and backup/restore shell syntax validated. The isolated PostgreSQL 16.15 project wrote a daily archive to a host bind mount with mode 0600 and a directory with mode 0700. Restarting with a recent archive skipped a duplicate. Restarting with an expired archive created and verified a replacement, pruned the old daily archive, and kept an equally old manual archive.
* A forced dump failure for a missing database published no archive and left no partial file. A manual dump returned the usable host path.
* The scheduled archive restored into a separate Compose project with a fresh PostgreSQL volume. The restored Alembic revision, seven ledger events, operator, closing snapshot, receipt checksum, balanced postings, and total drawer cash matched the test source. A second restore to the same database was rejected.
* The live local backup service generated its first daily archive. The app health endpoint remained ready.
