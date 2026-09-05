# Architecture

The system separates ingestion, normalization, FIFO analytics, market enrichment, and presentation. Authentication and portfolio ownership checks are enforced at the API boundary.

Production runs FastAPI against PostgreSQL and serves the React application through Nginx. Local development uses SQLite. Background PDF imports persist their lifecycle in `import_jobs`; the worker itself remains an in-process FastAPI background task until a durable queue is introduced.
