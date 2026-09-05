from __future__ import annotations
from datetime import datetime, timezone
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.entities import InstrumentMapping, MarketQuote

YAHOO_BASE = 'https://query1.finance.yahoo.com'

def _empty(isin: str, symbol: str | None = None):
    return {'isin': isin, 'provider': 'yahoo', 'symbol': symbol, 'ltp': None, 'open': None, 'high': None, 'low': None, 'close': None, 'volume': None, 'as_of': datetime.now(timezone.utc).replace(tzinfo=None)}

def _search_symbol(client: httpx.Client, name: str) -> str | None:
    try:
        r = client.get(f'{YAHOO_BASE}/v1/finance/search', params={'q': name, 'quotesCount': 10, 'newsCount': 0})
        r.raise_for_status()
        quotes = r.json().get('quotes', [])
        equities = [q for q in quotes if q.get('quoteType') == 'EQUITY']
        nse = [q for q in equities if str(q.get('symbol', '')).endswith('.NS')]
        return (nse or equities or [{}])[0].get('symbol')
    except Exception:
        return None

def quote_one(instrument: dict) -> dict:
    isin = str(instrument['isin']); symbol = (instrument.get('symbol') or '').strip() or None
    try:
        with httpx.Client(timeout=10) as client:
            if not symbol:
                symbol = _search_symbol(client, str(instrument.get('security') or isin))
            result = _empty(isin, symbol)
            if not symbol:
                return result
            r = client.get(f'{YAHOO_BASE}/v8/finance/chart/{symbol}', params={'range': '1d', 'interval': '1m', 'includePrePost': 'false'})
            r.raise_for_status()
            results = (r.json().get('chart') or {}).get('result') or []
            if not results:
                return result
            data = results[0]; meta = data.get('meta') or {}; quote = ((data.get('indicators') or {}).get('quote') or [{}])[0]
            closes = [v for v in quote.get('close', []) if v is not None]; opens = [v for v in quote.get('open', []) if v is not None]; highs = [v for v in quote.get('high', []) if v is not None]; lows = [v for v in quote.get('low', []) if v is not None]; volumes = [v for v in quote.get('volume', []) if v is not None]
            result.update({'ltp': meta.get('regularMarketPrice') if meta.get('regularMarketPrice') is not None else (closes[-1] if closes else None), 'open': opens[0] if opens else None, 'high': max(highs) if highs else None, 'low': min(lows) if lows else None, 'close': meta.get('previousClose'), 'volume': volumes[-1] if volumes else None, 'as_of': datetime.now(timezone.utc).replace(tzinfo=None)})
            return result
    except Exception:
        return _empty(isin, symbol)

class YahooFinanceProvider:
    name = 'yahoo'
    def quotes(self, instruments: list[dict]) -> list[dict]:
        return [quote_one(instrument) for instrument in instruments]

def get_provider_for_user(*args, **kwargs):
    return YahooFinanceProvider()

def latest_quotes(db: Session, user_id: int, portfolio_id: int | None = None):
    q = select(MarketQuote).where(MarketQuote.user_id == user_id)
    if portfolio_id is not None:
        q = q.where(MarketQuote.isin.in_(select(InstrumentMapping.isin).where(InstrumentMapping.user_id == user_id, InstrumentMapping.provider == 'yahoo')))
    rows = db.scalars(q.order_by(MarketQuote.as_of.desc())).all(); latest = {}
    for row in rows: latest.setdefault(row.isin, row)
    return [{'isin': row.isin, 'provider': row.provider, 'symbol': row.symbol, 'ltp': row.ltp, 'open': row.open, 'high': row.high, 'low': row.low, 'close': row.close, 'volume': row.volume, 'as_of': row.as_of} for row in latest.values()]

def refresh_quotes(db: Session, user_id: int, portfolio_id: int | None = None):
    q = select(InstrumentMapping).where(InstrumentMapping.user_id == user_id, InstrumentMapping.provider == 'yahoo')
    mappings = db.scalars(q).all(); instruments = [{'isin': m.isin, 'security': m.security, 'symbol': m.instrument_key} for m in mappings]
    quotes = YahooFinanceProvider().quotes(instruments)
    for quote in quotes: db.add(MarketQuote(user_id=user_id, **quote))
    db.commit(); return quotes
