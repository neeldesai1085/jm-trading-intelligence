# JM Trading Intelligence

JM Trading Intelligence is a multi-user, multi-portfolio trading analytics platform for JM Financial contract-note PDFs. It replaces the operational workflow of the JM Financial Excel "Master Trader" workbook with a web application.

## What the application does

1. A user registers and signs in with email/password.
2. The user uploads JM Financial contract-note PDFs.
3. The backend validates and parses the PDFs.
4. Contract notes, security rows, executions and charges are normalized into the database.
5. The original PDF is deleted after processing; it is never archived by the application.
6. Imports are idempotent using file hashes and database uniqueness rules.
7. FIFO realized P&L and remaining open holdings are calculated from the stored execution ledger.
8. Dashboard, risk, intelligence, advanced analytics, charges, missing dates and Excel-parity views are generated from database data.
9. Yahoo Finance can enrich open holdings with informational market prices.
10. Advanced analytics use NIFTY 50 (`^NSEI`) as the built-in market benchmark.

The database is the long-lived source of truth. No S3 bucket, object-storage service, email service, broker connection, or broker API is required.

## Features

- JM Financial contract-note PDF ingestion.
- Contract-note, security-ledger, execution and charge storage.
- Deterministic FIFO realized P&L and open holdings.
- Multiple user-owned portfolios with strict data isolation.
- JWT access authentication and rotating HttpOnly refresh cookies.
- Authenticated password change.
- Yahoo Finance market-data enrichment with ISIN-to-ticker mappings.
- Fixed NIFTY 50 benchmark for advanced relative-performance analytics.
- Dashboard, Excel parity, risk, intelligence and advanced analytics.
- Paginated historical tables and CSV/full JSON exports.
- Background PDF import status tracking.
- Health/readiness endpoints, rate limiting and Prometheus-style metrics.

## Authentication

Authentication does not require email verification. Registration immediately creates an active account and default portfolio.

```text
POST /api/auth/register
POST /api/auth/login
POST /api/auth/refresh
POST /api/auth/logout
GET  /api/auth/me
PATCH /api/auth/profile
GET  /api/auth/sessions
POST /api/auth/change-password
```

There is intentionally no SMTP configuration and no email-based password-reset flow.

## PDF import and storage

The upload endpoints are:

```text
POST /api/imports/upload
POST /api/imports/upload/background
```

The backend writes each upload to a temporary working path, parses it, persists the extracted trading information, and deletes the temporary PDF in a cleanup path. No raw PDF archive is maintained.

The import stores the filename and SHA-256 file hash as import metadata so that uploading the same document again does not duplicate its database records. The PDF itself is not required after successful analysis.

All imported records are scoped to the authenticated user and selected portfolio.

## Market data

Yahoo Finance is the only market-data provider. No broker account or market-data API key is required.

```env
MARKET_DATA_PROVIDER=yahoo
QUOTE_REFRESH_SECONDS=60
```

NIFTY 50 is the built-in benchmark for advanced analytics. Its Yahoo Finance symbol is hardcoded as `^NSEI`; there is no benchmark environment variable or user configuration.

Explicit security mappings can be supplied through:

```text
GET  /api/instrument-mappings
POST /api/instrument-mappings
GET  /api/quotes/latest
GET  /api/quotes/refresh
WS   /api/ws/quotes
```

Market prices are informational and should not be treated as broker-grade execution prices.

## Database model

| Table | Purpose |
|---|---|
| `users` | Account identity and password hash |
| `auth_sessions` | Rotating refresh sessions |
| `portfolios` | User-owned trading portfolios |
| `import_jobs` | Background PDF import status |
| `import_batches` | Import hashes and processing metadata |
| `contract_notes` | Contract-note totals and charges |
| `security_ledger` | Security-level buy/sell rows |
| `executions` | Execution-level trade ledger |
| `market_quotes` | Timestamped quote observations |
| `instrument_mappings` | ISIN-to-Yahoo ticker mappings |
| `trade_annotations` | Strategy/setup/regime notes |

## API surface

```text
GET  /api/health
GET  /api/health/ready
GET  /api/metrics

POST /api/auth/register
POST /api/auth/login
POST /api/auth/refresh
POST /api/auth/logout
GET  /api/auth/me
PATCH /api/auth/profile
GET  /api/auth/sessions
POST /api/auth/change-password

GET  /api/portfolios
POST /api/portfolios

POST /api/imports/upload
POST /api/imports/upload/background
GET  /api/imports
GET  /api/imports/jobs/{job_id}

GET  /api/trade-annotations
POST /api/trade-annotations
GET  /api/dashboard
GET  /api/intelligence
GET  /api/analytics/advanced
GET  /api/risk
GET  /api/performance/daily
GET  /api/holdings
GET  /api/realized
GET  /api/missing-dates
GET  /api/tables/contracts
GET  /api/tables/executions
GET  /api/charges
GET  /api/securities
GET  /api/instrument-mappings
POST /api/instrument-mappings
GET  /api/quotes/latest
GET  /api/quotes/refresh
GET  /api/excel-parity
GET  /api/export/full
GET  /api/export/{dataset}
WS   /api/ws/quotes
```

## Configuration

Copy `.env.example` to `.env` for local use. The benchmark is intentionally not configurable: NIFTY 50 is built into the application.

### Local

```env
DATABASE_URL=sqlite:///./jm_trading.db
APP_ENV=development
CORS_ORIGINS=http://localhost:5173
UPLOAD_DIR=../data/incoming
MARKET_DATA_PROVIDER=yahoo
QUOTE_REFRESH_SECONDS=60
AUTH_SECRET=replace-with-a-long-random-secret-at-least-32-characters
AUTH_ACCESS_MINUTES=20
AUTH_REFRESH_DAYS=30
AUTH_COOKIE_NAME=jmti_refresh
AUTH_COOKIE_SECURE=false
AUTH_COOKIE_SAMESITE=lax
RATE_LIMIT_PER_MINUTE=30
```

### Production

```env
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DBNAME
APP_ENV=production
CORS_ORIGINS=https://your-frontend.example
UPLOAD_DIR=/tmp/jmti
MARKET_DATA_PROVIDER=yahoo
QUOTE_REFRESH_SECONDS=60
AUTH_SECRET=<long-random-secret>
AUTH_ACCESS_MINUTES=20
AUTH_REFRESH_DAYS=30
AUTH_COOKIE_NAME=jmti_refresh
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_SAMESITE=none
RATE_LIMIT_PER_MINUTE=30
```

No `SMTP_*`, `PASSWORD_RESET_*`, `S3_*`, `OBJECT_STORAGE_*`, broker, Upstox or Zerodha variables are required.

## Database schema lifecycle

SQLAlchemy ORM models are the schema definition. The application runs `Base.metadata.create_all()` at startup so a fresh database receives all required tables automatically. There is no separate database migration command or migration tool in the repository.

This intentionally favors a simple single-application deployment model. When an existing production schema requires a structural change, the application schema and deployment should be updated together; `create_all()` creates missing objects but does not alter existing columns or constraints.

## Deployment

`render.yaml` provisions a PostgreSQL database and Dockerized FastAPI service. The database connection is supplied by Render. Production secrets that must be entered manually are primarily `AUTH_SECRET` and `CORS_ORIGINS`.

The backend uses `/tmp/jmti` only as temporary PDF working storage. Files are deleted after import. Because raw documents are not retained, no S3 or other object-storage bucket is needed.

For the frontend, set:

```env
VITE_API_URL=https://<your-render-api-host>/api
```

## Local development

### Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cd ..
uvicorn backend.app.main:app --reload
```

The application creates the SQLite schema automatically at startup.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Docker

```bash
docker compose up --build
```

## Verification and CI

The CI workflow compiles the backend, verifies that the SQLAlchemy schema can be created on a fresh database, runs the backend tests, builds the frontend and validates Docker Compose configuration.

Run the backend tests locally with:

```bash
DATABASE_URL=sqlite:///./tests/ci_test.db APP_ENV=test AUTH_SECRET=unit-test-secret-change-me-abcdefghijklmnopqrstuvwxyz pytest -q
```

The backend test suite contains 8 tests in the current baseline, including the real JM Financial PDF checks when the private source files are available.

## Architecture notes

- PostgreSQL is recommended for production; SQLite is useful for development and CI.
- The database is the permanent trading-data store.
- PDFs are temporary input documents, not stored assets.
- Password reset is intentionally limited to authenticated password change; there is no email delivery path.
- Yahoo Finance is an informational market-data source and does not execute trades.
- NIFTY 50 (`^NSEI`) is the fixed benchmark used by advanced analytics.
