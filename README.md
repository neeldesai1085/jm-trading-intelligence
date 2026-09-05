# JM Trading Intelligence

A multi-user full-stack trading analytics application built around JM Financial contract notes and the Master Trader workbook concept.

## What it does

- Upload JM Financial contract-note PDFs and parse contracts, executions, securities and charges.
- Keep a historical source-of-truth ledger with idempotent imports.
- Reproduce the Master Trader workbook through the Excel Replacement view with 22 reporting/analysis areas.
- Calculate deterministic FIFO realized P&L, open holdings, brokerage/levy drag, reconciliation and performance statistics.
- Show daily/monthly/cumulative P&L, drawdown, concentration, turnover and charge analysis.
- Connect to Upstox or Zerodha for LTP/OHLC/volume and stream authenticated quote updates.
- Provide advanced trade-quality metrics, stress tests, quote freshness, MFE/MAE and optional strategy annotations.
- Support optional benchmark snapshots for approximate beta/alpha-like analysis.

## Authentication and user isolation

The application uses ordinary account authentication, not family or household access codes.

```text
Email + password
      ↓
 Argon2 password hash
      ↓
 JWT access token + rotating database-backed refresh token
      ↓
 FastAPI authorization
      ↓
 current_user.id
      ↓
 user-scoped trading data
```

Every business record is associated with a `user_id`, and API queries are scoped to the authenticated user. There is no family code, family membership, family role, or shared-family workspace.

## Architecture

```text
React / Vite SPA
        |
        | HTTPS + authenticated WebSocket
        v
FastAPI API
  |     |      |       |
 Auth  Import  FIFO   Market data
  |     |      |       |
  +-----+------+-------+
              |
          SQLAlchemy
              |
      SQLite / PostgreSQL
```

SQLite is convenient for local development. PostgreSQL is the recommended persistent database for cloud deployment and future growth.

## Master Trader / Excel replacement

The Excel Replacement endpoint represents these 22 workbook areas:

1. Dashboard
2. Trader Review
3. Source of Truth
4. Dashboard Calc
5. Contract Notes
6. Security Ledger
7. Execution Ledger
8. Charges Detail
9. Charge Summary
10. Charge Allocation
11. FIFO / Realized P&L
12. Open Holdings
13. Realized P&L by Security
14. Security Summary
15. Monthly Performance
16. Cumulative P&L
17. Reconciliation
18. Performance Metrics
19. Source Audit
20. Data Dictionary
21. Report Notes
22. Master Calc

## Local run

```bash
docker compose up --build
```

Frontend: http://localhost:5173  
Backend/API docs: http://localhost:8000/docs

Native development:

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend
npm install
npm run dev
```

## Database migrations

Alembic is included. Container startup runs `alembic upgrade head` before Uvicorn. For future schema changes, create an incremental revision and deploy it with the application.

## Cloud deployment

The repository includes `render.yaml` and `vercel.json`.

Recommended low-cost architecture:

```text
Vercel frontend
      |
      v
Render FastAPI service
      |
      v
Managed PostgreSQL
```

Set `AUTH_SECRET` to a long random secret, `DATABASE_URL` to the managed PostgreSQL connection string, and `CORS_ORIGINS` to the exact frontend origin. Broker credentials remain backend environment secrets.

The Render Blueprint uses a Docker build context of `./backend`, so the backend Dockerfile can reliably copy its application and migration files in the monorepo. Render's free filesystem is ephemeral; do not use free-service SQLite as permanent trading-data storage.

For larger public usage, the next scaling layer is a managed Redis/pub-sub service, background workers for large PDF imports, object storage for source documents, encrypted broker-token storage, provider OAuth flows, and centralized observability/rate limiting.

## Data workflow

1. Create an account.
2. Sign in.
3. Upload JM Financial contract-note PDFs.
4. Review import/audit results.
5. Inspect the Excel Replacement dashboard.
6. Configure provider instrument mappings for live quotes.
7. Review Risk & Intelligence and Advanced Analytics.
8. Export user-scoped datasets when needed.

The source JM Financial PDF and workbook are not committed to the repository because they contain private trading information.

## Testing

```bash
python -m compileall -q backend/app scripts tests
pytest -q
```

CI also builds the frontend and validates Docker Compose configuration. Live-market results depend on the selected broker/provider's access and rate limits; the application does not invent prices when a quote is unavailable.
