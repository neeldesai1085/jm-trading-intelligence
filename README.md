# JM Trading Intelligence

A private family trading-analysis app built around JM Financial contract notes. It replaces the spreadsheet workflow with a database-backed web dashboard while keeping deterministic FIFO accounting, charges, reconciliation, graphs, risk analysis and live market-data adapters.

## What it does

- Upload JM Financial contract-note PDFs; parse contracts, executions, securities and charges.
- Prevent duplicate imports and keep a historical source-of-truth ledger.
- Reproduce the Excel workbook's 22 analytical/reporting tabs through the Excel Replacement view.
- Calculate FIFO realized P&L, open holdings, brokerage/levy drag, reconciliation and performance statistics.
- Show daily/monthly/cumulative P&L, drawdown, concentration, turnover and charge graphs.
- Connect to Upstox or Zerodha for LTP/OHLC/volume and stream quote updates to the dashboard.
- Provide advanced trade-quality metrics, stress tests, quote freshness, MFE/MAE snapshots and optional strategy annotations.
- Optional benchmark snapshots can be collected for approximate beta/alpha-like analysis.
- Optional household access-code login keeps the shared workspace private.

## Family-first architecture

This is intentionally **not a commercial SaaS architecture**. It is designed for a small household: a static frontend on Vercel, one small FastAPI service on Render, and a small free PostgreSQL database. There is no paid infrastructure requirement in the repository.

Recommended deployment:

```text
Vercel Hobby frontend
        |
        | HTTPS / WebSocket
        v
Render Free FastAPI backend
        |
        +---- Supabase Free or Neon Free PostgreSQL
        |
        +---- Upstox / Zerodha API (optional)
```

Use an external PostgreSQL database for deployed data. Do not rely on local SQLite on Render for the production copy because Render web-service files are ephemeral. Uploaded PDFs are processed and then removed from the temporary server filesystem; the extracted trading ledger is what is retained.

## Free deployment

### 1. Create the database

Create a free PostgreSQL database with Supabase or Neon. Copy its PostgreSQL connection string.

### 2. Deploy backend to Render

The repository includes `render.yaml`. Create a Render Blueprint from this repository and select the Free web-service plan.

Set these Render environment variables:

```text
DATABASE_URL=<PostgreSQL connection string>
APP_ACCESS_CODE=<private family code>
AUTH_SECRET=<long random secret>
CORS_ORIGINS=https://YOUR-APP.vercel.app
MARKET_DATA_PROVIDER=mock
```

For live prices, choose `upstox` or `zerodha` and add the corresponding provider credentials. Keep those credentials only in Render environment variables; never commit them.

### 3. Deploy frontend to Vercel

Import the GitHub repository into Vercel. The included `vercel.json` builds `frontend/` and publishes `frontend/dist`.

Set:

```text
VITE_API_URL=https://YOUR-RENDER-SERVICE.onrender.com/api
VITE_WS_URL=wss://YOUR-RENDER-SERVICE.onrender.com/api/ws/quotes
```

### 4. Configure family access

When `APP_ACCESS_CODE` is set, users see a small login page. Every household member can use their own display name with the same shared family access code. This is intentionally a simple household gate, not enterprise identity management.

### 5. Upload the historical contract notes

After the app opens:

1. Sign in.
2. Open **Upload PDFs**.
3. Select your JM Financial contract-note PDFs.
4. Let the importer build the ledger.
5. Open **Excel Replacement** to inspect the workbook-equivalent analysis.
6. Configure **Market Data** mappings for the securities you want live prices for.
7. Open **Risk & Intelligence** and **Advanced Analytics** for the decision-support layer.

## Local run

```bash
docker compose up --build
```

Frontend: http://localhost:5173  
Backend/API docs: http://localhost:8000/docs

## Testing

```bash
python -m compileall -q backend/app scripts tests
pytest -q
```

The repository's CI also builds the frontend and validates Docker Compose configuration. The source JM Financial PDF and workbook are intentionally not committed because they contain private trading data.

## Important free-tier behavior

Free hosting is suitable for a small family, but it has limits. The Render service can sleep when idle, so the first request after inactivity can be slower. External free PostgreSQL services also have storage/usage limits and may pause or sleep under inactivity. The application therefore keeps the architecture small and avoids a paid Redis/worker/object-storage stack.

Live-market availability also depends on the API access and rate limits of your chosen broker/provider. If no provider credentials or instrument mapping exist, the app shows missing quotes rather than inventing prices.
