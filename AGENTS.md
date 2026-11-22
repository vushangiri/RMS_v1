# RMS development context

Use PostgreSQL and the shared posting service for financial writes. Read BUSINESS_RULES.md before changing date locks, credit allocation, cash handovers or stock movements. Preserve the supplied UI hierarchy and keep day-to-day entry forms short. Every write needs a server-generated form token, one database transaction and an auditable result.

Use an isolated database ending in _test for automated tests. Fixtures clear and reseed that database. Existing migration revisions and closed snapshots are historical records. Add migrations for later schema changes. Update TESTING.md with executed results when changing the posting model or a release gate.
