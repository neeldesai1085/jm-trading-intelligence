# JM Trading Intelligence

JM Trading Intelligence is a multi-user, multi-portfolio trading analytics platform designed to replace the JM Financial Master Trader Excel workflow with a secure web application.

## Capabilities

- JM Financial contract-note PDF ingestion and validation.
- Contract-note, security-ledger and execution-ledger normalization.
- Idempotent import handling and source auditability.
- Deterministic FIFO realized P&L and open-lot accounting.
- Brokerage, statutory levy, charge-drag and reconciliation analysis.
- Daily, monthly and cumulative performance analytics.
- Concentration, drawdown, volatility, Sharpe-like, VaR/CVaR and trading-quality analytics.
- Advanced expectancy, profit factor, streak, holding-period, MFE/MAE and stress analysis.
- Full Excel Replacement coverage across all 22 workbook areas.
- Searchable/paginated data views and CSV/JSON exports.
- Upstox and Zerodha market-data adapters plus a mock provider.
- Authenticated market WebSocket updates.
- Multiple private portfolios per user.
- Argon2 passwords, JWT access tokens and rotating HttpOnly refresh cookies.
- Password change, password reset, profile and optional email verification flows.
- Rate limiting, readiness checks and Prometheus-style metrics.
- Optional encrypted broker-token storage.
- Optional SMTP email and S3-compatible raw-PDF archival.
- Background PDF-import jobs for larger files.

## Architecture

```text
React/Vite
   |
   | HTTPS / JSON / authenticated WebSocket
   v
FastAPI
   |-- authentication + sessions
   |-- portfolio/user isolation
   |-- PDF import + audit
   |-- FIFO + analytics + Excel parity
   |-- market-data adapters
   v
SQLAlchemy
   |-- PostgreSQL (recommended production)
   `-- SQLite (local/testing)

Optional services:
  S3-compatible object storage
  SMTP email
  Redis/worker queue for future horizontal scaling
```

## Account model

This application uses ordinary accounts. It does **not** use family codes, household membership, shared-family roles, or shared access codes.

Each user can own multiple portfolios. Business records are associated with the authenticated user and, for trading records, the selected portfolio. Portfolio lookup verifies ownership before analytics or writes are performed.

## Excel Replacement

The `/api/excel-parity` endpoint and the Excel Replacement UI represent these 22 workbook areas:

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

The parity layer also exposes chart-ready series for cumulative P&L, drawdown, concentration, monthly performance, turnover, charges, round trips, holding periods, open book cost, average cost and charge mix.

Charge Allocation is an analytical allocation of contract-level non-brokerage levies; it is explicitly separated from the source tax/charge fields and is not presented as a tax computation.

## Historical source baseline

The supplied JM Financial source bundle used during verification contains:

- 99 PDF pages.
- 33 contract notes.
- 65 security-level rows.
- 92 execution rows.
- 14 unique securities.
- Trade dates from 22-Apr-2026 through 13-Aug-2026.
- Final settlement date 14-Aug-2026.

Verified baseline analytics include approximately ₹1,015,224.87 gross turnover, ₹16,815.42 realized P&L after brokerage, ₹18,283.91 gross realized P&L and ₹248,440.32 open book cost.

These figures are a verification baseline for the supplied source files, not hard-coded application outputs.

## FIFO model

The engine orders executions by trade date, trade time and database ID. BUY executions create FIFO lots; SELL executions consume the oldest lots first.

Gross FIFO P&L uses execution-level amounts. After-brokerage realized P&L uses contract-note security-level after-brokerage values. Remaining FIFO lots become open holdings.

No current market price is invented when a provider quote is unavailable.

## Authentication

Endpoints include:

```text
POST /api/auth/register
POST /api/auth/login
POST /api/auth/refresh
POST /api/auth/logout
GET  /api/auth/me
PATCH /api/auth/profile
GET  /api/auth/sessions
POST /api/auth/change-password
POST /api/auth/password-reset/request
POST /api/auth/password-reset/confirm
POST /api/auth/verification/request
POST /api/auth/verification/confirm
```

Passwords are hashed with Argon2. Access JWTs are short-lived. Refresh sessions are stored by JTI, rotated and revocable. The refresh credential is placed in an HttpOnly cookie instead of browser localStorage.

Production startup rejects a weak `AUTH_SECRET` and rejects `AUTH_COOKIE_SECURE=false`.

## Portfolio API

```text
GET  /api/portfolios
POST /api/portfolios
```

A `Main Portfolio` is created automatically for new users. Analytics and trading data endpoints accept `portfolio_id` and verify ownership.

## Import API

Synchronous import:

```text
POST /api/imports/upload
```

Background import:

```text
POST /api/imports/upload/background
GET  /api/imports/jobs/{job_id}
```

Uploads are limited to 25 MB per file and 25 files per request. The server checks the PDF signature, sanitizes filenames, uses generated temporary paths and removes temporary files after processing. Import transactions roll back on failure.

Duplicate detection is scoped by user and portfolio and uses file hashes plus contract/security/execution keys.

## Pagination and exports

Large ledger endpoints return:

```json
{"items": [], "total": 0, "page": 1, "page_size": 100}
```

Supported paginated datasets include contracts, executions, charges, securities, mappings, annotations and imports.

Authenticated CSV exports are available for the major datasets, and `/api/export/full` returns a complete user/portfolio JSON snapshot.

## Market data

Supported providers:

```text
mock
upstox
zerodha
```

Provider mappings are stored per user. Broker access tokens can be stored encrypted with Fernet using `TOKEN_ENCRYPTION_KEY`.

The WebSocket requires the access JWT in its initial JSON message and accepts the selected portfolio ID. It never reads another user's mappings or holdings.

Broker OAuth/session behavior remains subject to the broker's current API rules. The application does not assume perpetual broker sessions.

## Security and operations

### Rate limiting

Authentication-sensitive flows use a sliding-window in-process limiter. Set:

```text
RATE_LIMIT_PER_MINUTE=30
```

For multiple API replicas, move rate limiting to a shared gateway or Redis-backed limiter.

### Health

```text
GET /api/health
GET /api/health/ready
```

The readiness endpoint verifies database connectivity.

### Metrics

```text
GET /api/metrics
```

The endpoint exposes request counts and accumulated request duration in Prometheus text format. It is intentionally lightweight; centralized metrics collection should be added at the deployment layer for larger installations.

## Optional raw-PDF storage

Raw PDF retention is disabled by default:

```text
STORE_RAW_PDF=false
```

It can be enabled with local storage or an S3-compatible object store. Objects are partitioned by user and portfolio and are addressed with content-hash-prefixed filenames.

Required S3 settings:

```text
OBJECT_STORAGE_PROVIDER=s3
STORE_RAW_PDF=true
S3_BUCKET=...
S3_ENDPOINT_URL=...
S3_REGION=...
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...
```

## Optional email

SMTP can be configured for password reset and verification messages:

```text
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=
```

Development responses expose generated reset/verification tokens to make local testing possible. Production responses do not expose reset tokens or disclose whether an email belongs to an account.

## Local development

### Backend

Python 3.12 is the CI runtime.

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
# source .venv/bin/activate
pip install -r backend/requirements.txt
```

Copy `.env.example` to `.env`, then start:

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

API docs: `http://127.0.0.1:8000/docs`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend defaults to port 5173. Use `VITE_API_URL` when the API is not served through the same origin.

## Docker

```bash
docker compose up --build
```

The backend Docker image runs `alembic upgrade head` before Uvicorn. The frontend is compiled and served by nginx.

## Database migrations

Alembic is the production schema mechanism. The migration chain is explicit and includes the multi-user schema, portfolio/job/auth hardening, encrypted broker connections and dedicated email-verification storage.

```bash
alembic upgrade head
```

For future model changes:

```bash
alembic revision -m "describe change"
alembic upgrade head
```

Production does not call SQLAlchemy `create_all()`; this prevents startup from silently masking schema drift.

## Seed/demo data

For local verification, the source workbook can be seeded into a private demo account:

```bash
python scripts/seed_from_workbook.py /path/to/JM_Financial_Master_Trader_Dashboard.xlsx demo@example.com DemoPass123!
```

The seed script creates or reuses the user's Main Portfolio and writes all seeded records with user/portfolio ownership.

## CI

GitHub Actions validates:

- Python compilation.
- Fresh Alembic migration upgrade.
- Backend pytest suite.
- Frontend TypeScript/Vite production build with pinned dependencies.
- Docker Compose configuration.

The backend tests cover parser counts, workbook parity, FIFO/P&L, charge allocation, real PDF import, import idempotency, authentication, cookie rotation, password reset, portfolio isolation, pagination, CRUD, exports, background import jobs and health endpoints.

## Production deployment

Recommended architecture:

```text
Vercel/static frontend
        |
        v
Render/containerized FastAPI
        |
        +---- managed PostgreSQL
        +---- optional S3 object storage
        +---- optional SMTP
        `---- future Redis + worker tier
```

`render.yaml` is configured to use a managed PostgreSQL database rather than ephemeral SQLite for persistent cloud trading history.

Required production configuration includes:

```text
APP_ENV=production
AUTH_SECRET=<random secret, >=32 characters>
AUTH_COOKIE_SECURE=true
CORS_ORIGINS=https://your-frontend.example
DATABASE_URL=<managed PostgreSQL URL>
```

When frontend and API are on different sites, use the configured cross-site cookie policy and HTTPS.

Do not commit database passwords, JWT secrets, broker credentials, SMTP passwords, S3 credentials or encryption keys.

## Current scaling boundaries

The repository now contains the production-oriented interfaces for the previously missing areas, but three components are intentionally lightweight:

1. **Rate limiting** is in-process. A multi-replica deployment needs shared limiting.
2. **Background imports** use FastAPI BackgroundTasks. A durable queue/worker is recommended when import volume or reliability requirements increase.
3. **Quote fan-out** is process-local. High-frequency multi-user deployments should use a shared quote worker and pub/sub layer.

These are infrastructure scaling boundaries, not placeholders in the core trading calculations.

## Troubleshooting

### 401 errors

Check `VITE_API_URL`, CORS, HTTPS and refresh-cookie configuration. Cross-site deployment requires the correct Secure/SameSite cookie settings.

### Empty live quotes

Check the selected market-data provider and the provider-specific instrument mappings. Missing mappings intentionally produce no fabricated price.

### Migration failure

Run `alembic upgrade head` against a clean local database and inspect the database URL/driver. Production startup intentionally relies on Alembic.

### Empty portfolio

Verify the selected `portfolio_id` and import into that portfolio. User and portfolio isolation is intentional.

## Repository hygiene

Private source PDFs, contract notes and workbooks should remain outside git. Only code, configuration templates, migrations, documentation and tests belong in the repository.

## Verification status

The local backend suite has been run successfully after the stabilization work. The final production confidence check is the GitHub Actions run generated by the new commit/PR, including the frontend build and migration job. Live broker behavior also requires real provider credentials and provider-side authorization, so it cannot be fully validated with the mock provider alone.
