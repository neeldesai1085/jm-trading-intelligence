# JM Trading Intelligence

A small personal trading-analysis app built around JM Financial contract notes. It replaces the spreadsheet workflow with a database-backed web dashboard while keeping deterministic FIFO accounting, charges, reconciliation, graphs, risk analysis and live market-data adapters.

## What it does

- Upload JM Financial contract-note PDFs; parse contracts, executions, securities and charges.
- Prevent duplicate imports and keep a historical source-of-truth ledger.
- Reproduce the Excel workbook's 22 analytical/reporting tabs through the Excel Replacement view.
- Calculate FIFO realized P&L, open holdings, brokerage/levy drag, reconciliation and performance statistics.
- Show daily/monthly/cumulative P&L, drawdown, concentration, turnover and charge graphs.
- Connect to Upstox or Zerodha for LTP/OHLC/volume and stream quote updates to the dashboard.
- Provide advanced trade-quality metrics, stress tests, quote freshness, MFE/MAE snapshots and optional strategy annotations.
- Optional benchmark snapshots can be collected for approximate beta/alpha-like analysis.

## Small-user architecture

This is intentionally **not a commercial SaaS architecture**. It is designed for a very small number of trusted users: a static frontend on Vercel, one small FastAPI service on Render, and a small database. There is no account-management, multi-tenant, or family-login layer.

Recommended deployment:

```text
Vercel Hobby frontend
        |
        | HTTPS / WebSocket
        v
Render Free FastAPI backend
        |
        +---- SQLite for the simplest setup
        |     or free PostgreSQL for persistent cloud data
        |
        +---- Upstox / Zerodha API (optional)
```

Uploaded PDFs are processed and then removed from temporary server storage; the extracted trading ledger is what is retained.

## Free deployment

### Backend on Render

The repository includes `render.yaml`. Create a Render Blueprint from this repository and select the Free web-service plan.

For the simplest deployment you can use the default SQLite configuration. Be aware that a free Render web service has an ephemeral filesystem, so a SQLite database there is not a reliable permanent backup. For persistent cloud history, set `DATABASE_URL` to a free PostgreSQL provider such as Supabase or Neon.

Set:

```text
DATABASE_URL=<SQLite default or PostgreSQL connection string>
CORS_ORIGINS=https://YOUR-APP.vercel.app
MARKET_DATA_PROVIDER=mock
```

For live prices, choose `upstox` or `zerodha` and add the corresponding provider credentials. Keep those credentials only in Render environment variables; never commit them.

### Frontend on Vercel

Import the GitHub repository into Vercel. The included `vercel.json` builds `frontend/` and publishes `frontend/dist`.

Set:

```text
VITE_API_URL=https://YOUR-RENDER-SERVICE.onrender.com/api
VITE_WS_URL=wss://YOUR-RENDER-SERVICE.onrender.com/api/ws/quotes
```

### Upload the historical contract notes

After the app opens:

1. Open **Upload PDFs**.
2. Select your JM Financial contract-note PDFs.
3. Let the importer build the ledger.
4. Open **Excel Replacement** to inspect the workbook-equivalent analysis.
5. Configure **Market Data** mappings for the securities you want live prices for.
6. Open **Risk & Intelligence** and **Advanced Analytics** for the decision-support layer.

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

Free hosting is suitable for a small number of users, but it has limits. The Render service can sleep when idle, so the first request after inactivity can be slower. Free database services also have storage/usage limits. The application therefore keeps the architecture small and avoids a paid Redis/worker/object-storage stack.

Live-market availability depends on the API access and rate limits of your chosen broker/provider. If no provider credentials or instrument mapping exist, the app shows missing quotes rather than inventing prices.
