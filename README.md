# JM Trading Intelligence

Full-stack trading analytics platform for JM Financial contract notes.

## Architecture

Upload Contract PDF -> PDF Extraction + Validation -> Historical Database -> Market Data API -> Analytics Engine -> Master Dashboard.

## Stack

React + Vite + TypeScript frontend; FastAPI + SQLAlchemy backend; SQLite by default and PostgreSQL-ready; deterministic FIFO analytics; Recharts; pdfplumber; provider adapters for Upstox and Zerodha.

## Features

- JM Financial PDF ingestion with idempotent duplicate detection
- Historical contracts, executions, security ledger and charges
- FIFO realized P&L and open holdings
- Live LTP/OHLC/volume market-data layer
- Instrument mapping for broker/provider identifiers
- WebSocket quote stream
- Performance, concentration and charge analytics
- Drawdown, volatility, Sharpe-like metric, VaR/CVaR and intelligence alerts
- CSV export endpoints
- Docker Compose and GitHub Actions CI

## Run

```bash
docker compose up --build
```

Frontend: http://localhost:5173
Backend/API docs: http://localhost:8000/docs

For broker credentials, configure environment variables from `.env.example`. Secrets stay on the backend.
