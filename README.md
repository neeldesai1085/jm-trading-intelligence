# JM Trading Intelligence

JM Trading Intelligence is a multi-user, multi-portfolio trading analytics platform built to replace the operational workflow of the JM Financial Excel "Master Trader" workbook with a web application.

The application ingests JM Financial contract-note PDFs, builds a normalized trading ledger, calculates deterministic FIFO realized P&L and open holdings, reproduces the workbook's analytical views, adds live-market enrichment, and exposes the complete dataset through searchable/paginated tables and exports.

The repository is designed for local development, Docker deployment, and production deployment with PostgreSQL. The production architecture uses JWT access tokens plus an HttpOnly refresh cookie, strict user and portfolio scoping, encrypted broker credentials, optional object storage, rate limiting, readiness checks, and Prometheus-style application metrics.

## What is included

### Core trading workflow

1. Upload one or more JM Financial contract-note PDFs.
2. Validate the PDF signature and size before processing.
3. Parse contract notes, security-level rows, executions, settlement information, and charges.
4. Deduplicate imports by user, portfolio, file hash, contract note, security row, and execution trade number.
5. Persist normalized historical data in SQLAlchemy models.
6. Calculate FIFO realized P&L and remaining open lots.
7. Calculate charge drag, turnover, concentration, drawdown, volatility, Sharpe-like measures, VaR/CVaR, streaks, expectancy, profit factor, holding periods, and trade-quality analytics.
8. Optionally enrich open positions with market quotes through a configurable provider.
9. Present the data through the web dashboard, Excel-parity views, risk/intelligence views, advanced analytics, and exports.

### Authentication and tenancy

The application is intended for private accounts rather than shared household access codes.

Each account has:

- Email/password authentication.
- Argon2 password hashing.
- Short-lived JWT access tokens.
- Rotating refresh sessions stored server-side and delivered to the browser in an HttpOnly cookie.
- Sign-out and session revocation.
- Password change with session invalidation.
- Password-reset tokens stored as hashes and invalidated after use.
- Optional email-verification workflow.
- Profile editing.
- Multiple portfolios per user.

Every trading object is scoped to both the authenticated user and, where applicable, the selected portfolio. A user cannot read or modify another user's portfolio data through the API.

## Architecture

```text
                            +----------------------+
                            |   React + Vite UI     |
                            | Dashboard / Parity /  |
                            | Risk / Advanced / CSV |
                            +----------+-----------+
                                       |
                                  HTTPS / JSON
                                       |
                            +----------v-----------+
                            |   FastAPI API        |
                            | Auth / Imports /     |
                            | Analytics / Quotes   |
                            +----+---------+-------+
                                 |         |
                    +------------+         +------------------+
                    |                                   |
             +------v------+                     +------v-------+
             | PostgreSQL / |                     | Market Data  |
             | SQLite       |                     | Upstox /     |
             | normalized   |                     | Zerodha /    |
             | ledger       |                     | Mock         |
             +------+-------+                     +--------------+
                    |
              +-----v------+     optional
              | FIFO + Risk|--------------------+
              | Analytics   |                    |
              +-----+-------+             +------v-------+
                    |                     | Object Store |
             +------v---------+           | S3 / local   |
             | Excel Parity   |           | PDF archive  |
             | 22 workbook    |           +--------------+
             | views/charts   |
             +----------------+
```

## Repository layout

```text
jm-trading-intelligence/
├── backend/
│   ├── app/
│   │   ├── api/routes.py
│   │   ├── core/config.py
│   │   ├── core/metrics.py
│   │   ├── core/rate_limit.py
│   │   ├── db/session.py
│   │   ├── models/entities.py
│   │   └── services/
│   │       ├── advanced_analytics.py
│   │       ├── analytics.py
│   │       ├── auth.py
│   │       ├── broker_auth.py
│   │       ├── email.py
│   │       ├── excel_parity.py
│   │       ├── importer.py
│   │       ├── market_data.py
│   │       ├── pdf_parser.py
│   │       ├── portfolios.py
│   │       └── storage.py
│   ├── alembic/
│   │   └── versions/
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── lib/api.ts
│   │   └── pages/
│   ├── Dockerfile
│   ├── nginx.conf
│   └── package.json
├── scripts/
│   ├── seed_from_workbook.py
│   └── verify_app.py
├── tests/test_backend.py
├── .github/workflows/ci.yml
├── alembic.ini
├── docker-compose.yml
├── render.yaml
├── vercel.json
└── README.md
```

## Excel parity

The workbook parity implementation intentionally preserves the source workbook's operating model instead of replacing it with a simplified dashboard.

The application exposes the following 22 workbook tabs:

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

The parity endpoint also exposes chart-ready series used by the frontend, including:

- Cumulative realized P&L.
- Open-position concentration.
- Monthly realized P&L.
- Monthly buy versus sell turnover.
- Monthly turnover.
- Monthly charges.
- Daily realized P&L.
- Drawdown.
- Round-trip P&L.
- Holding period.
- Open book cost.
- Average cost.
- Charge mix.
- Charges as a percentage of turnover.

The Charge Allocation view is populated rather than left as a placeholder. Allocation follows the source ledger's side/value logic so brokerage can be traced from contract-note level to security-level calculations.

## Source data lineage

The parser is specifically hardened for JM Financial contract-note bundles in which the legal/annexure pages are separate from the trade-detail page.

The parser combines the relevant page context before extracting the security and execution rows, normalizes contract-note identifiers, supports both `INE...` and `INF...` ISIN forms, and validates the resulting structure before import.

For the currently supplied source PDF, the established source counts are:

- 99 PDF pages.
- 33 contract notes.
- 65 security rows.
- 92 execution rows.
- 14 unique securities.
- Trade dates from 22-Apr-2026 through 13-Aug-2026.
- Settlement date 14-Aug-2026.

The parser is not hard-coded to those values; they are documented here as the verified baseline for the supplied source workbook/PDF.

## FIFO accounting model

The analytics engine uses deterministic FIFO matching at execution level.

For each security:

```text
BUY execution -> FIFO lot added
SELL execution -> oldest open lot(s) consumed
```

The system keeps the brokerage-adjusted buy cost and sell proceeds needed to calculate after-brokerage realized P&L.

For a matched quantity:

```text
FIFO P&L = net sell proceeds after brokerage
          - allocated buy cost after brokerage
```

Remaining FIFO lots become open holdings. Open-book cost is derived from the remaining buy lots rather than treating current holdings as a simple quantity multiplied by an arbitrary average price.

## Database model

Key tables:

| Table | Purpose |
| --- | --- |
| `users` | Account identity and password hash. |
| `portfolios` | Per-user trading account/book separation. |
| `auth_sessions` | Rotating server-side refresh sessions. |
| `password_reset_tokens` | Hashed, expiring password-reset tokens. |
| `email_verification_tokens` | Hashed, expiring email-verification tokens. |
| `broker_connections` | Encrypted per-user broker credentials. |
| `import_batches` | Upload-level import audit. |
| `import_jobs` | Background import lifecycle. |
| `contract_notes` | One normalized row per contract note. |
| `security_ledger` | Contract-note security-level detail. |
| `executions` | Execution-level trade history. |
| `market_quotes` | Provider-enriched latest quote history. |
| `instrument_mappings` | ISIN-to-provider instrument mapping. |
| `trade_annotations` | Strategy/setup/regime notes linked to round trips. |

The schema is managed by Alembic migrations. New migrations are additive and include a portfolio backfill for existing users/data.

## API overview

All application endpoints are under `/api`.

### Health and operations

- `GET /api/health`
- `GET /api/health/ready`
- `GET /api/metrics`

### Authentication

- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/refresh`
- `POST /api/auth/logout`
- `GET /api/auth/me`
- `PATCH /api/auth/profile`
- `GET /api/auth/sessions`
- `POST /api/auth/change-password`
- `POST /api/auth/password-reset/request`
- `POST /api/auth/password-reset/confirm`
- `POST /api/auth/verification/request`
- `POST /api/auth/verification/confirm`

### Portfolios and brokers

- `GET /api/portfolios`
- `POST /api/portfolios`
- `GET /api/broker/connections`
- `GET /api/broker/upstox/authorize`
- `GET /api/broker/upstox/callback`
- `GET /api/broker/zerodha/authorize`
- `POST /api/broker/zerodha/connect`

### Imports

- `POST /api/imports/upload`
- `POST /api/imports/upload/background`
- `GET /api/imports`
- `GET /api/imports/jobs/{job_id}`

### Analytics and intelligence

- `GET /api/dashboard`
- `GET /api/intelligence`
- `GET /api/analytics/advanced`
- `GET /api/risk`
- `GET /api/performance/daily`
- `GET /api/holdings`
- `GET /api/realized`
- `GET /api/missing-dates`
- `GET /api/excel-parity`

### Data and exports

- `GET /api/tables/contracts`
- `GET /api/tables/executions`
- `GET /api/charges`
- `GET /api/securities`
- `GET /api/instrument-mappings`
- `POST /api/instrument-mappings`
- `GET /api/trade-annotations`
- `POST /api/trade-annotations`
- `GET /api/quotes/latest`
- `GET /api/quotes/refresh`
- `GET /api/export/{dataset}`

## Market data providers

The market layer has three modes:

- `mock`: deterministic data for development and CI.
- `upstox`: daily API access token mode or OAuth connection mode.
- `zerodha`: Kite Connect token mode or the login/request-token exchange flow.

Market quote failures do not prevent the historical ledger or analytics from working. Unmapped securities are surfaced through the mapping view rather than silently discarded.

## Production deployment

### Render

`render.yaml` provisions:

- A PostgreSQL 17 database.
- A Docker-based FastAPI service.
- Production cookie/CORS configuration.
- Environment-variable placeholders for broker OAuth and SMTP.
- A `/api/health/ready` health check.

Set at minimum:

```text
APP_ENV=production
AUTH_SECRET=<random 32+ character secret>
AUTH_COOKIE_SECURE=true
CORS_ORIGINS=https://your-frontend.example
DATABASE_URL=<managed postgres URL>
TOKEN_ENCRYPTION_KEY=<Fernet key when broker connections are enabled>
```

The application refuses to start in production with a weak JWT secret or with `AUTH_COOKIE_SECURE=false`.

### Docker Compose

For local development:

```bash
docker compose up --build
```

The backend runs migrations before starting Uvicorn and the frontend is served by Nginx.

### Local development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
DATABASE_URL=sqlite:///./jm_trading.db alembic upgrade head
uvicorn backend.app.main:app --reload --port 8000
```

In a frontend terminal:

```bash
cd frontend
npm install
npm run dev
```

## Testing

The backend suite exercises:

- protected route behavior;
- cookie-based refresh rotation;
- PDF parser source regression when the private source files are available;
- Excel-parity source metrics;
- real PDF import and idempotency when the private source PDF is available;
- authentication, profile update, password reset, session rotation, and user isolation;
- portfolio creation and isolation;
- paginated tables and exports;
- instrument mappings and trade annotations;
- background import job creation;
- readiness and application metrics.

The CI workflow separately validates Python compilation, a fresh Alembic migration chain, backend pytest, frontend TypeScript/Vite build, and Docker Compose configuration.

## Data and privacy

The supplied JM Financial PDF and workbook are treated as local/private reference data. They are intentionally ignored by Git and are not required for CI because CI creates deterministic synthetic data when the private sources are absent.

Broker access tokens are never returned to the frontend after storage and are encrypted at rest using a Fernet key. The application uses server-side ownership checks for user and portfolio IDs on all trading endpoints.

## Known operational constraints

The current background import implementation uses FastAPI `BackgroundTasks`. The job record is persisted in PostgreSQL/SQLite, but the in-process worker is not a durable queue: a process restart during an active job can require re-submission. The architecture is intentionally structured so this can later be replaced by Celery, RQ, a managed queue, or another durable worker without changing the HTTP API.

Live broker providers still require real provider credentials, redirect URIs, and instrument mappings to return live quotes. CI deliberately uses `mock` market data so builds and regression tests remain deterministic.

The platform is designed for operational trading analysis and accounting reconciliation; it is not a broker execution engine and does not place live orders.
