# Release 1.0 candidate · 21 November 2026

* Implemented the supplied multi-counter workflow in a fresh Flask/PostgreSQL project. Adapted the approved visual reference to server-rendered screens and mobile navigation.
* Added daily sales batches without item-level pricing, multi-line purchases, mixed payment allocation, invoice-specific credit settlement, shared stock, printable reports and receipt storage.
* Recorded expected, counted, handed and received cash independently. Added an in-transit account and explicit receipt confirmation for partial handovers.
* Added atomic paired movements, retry validation, immutable originals and explicit reversal records. Closing snapshots retain the evidence available at finalization.
* Added PostgreSQL integration and concurrency tests, browser workflows at three viewport sizes, backup/recovery instructions and a disposable performance workload.
