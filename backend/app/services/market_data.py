from __future__ import annotations
import asyncio
from datetime import datetime, timezone
import httpx

YAHOO_BASE = 'https://query1.finance.yahoo.com'

class MarketDataProvider:
    name = 'base'
    async def quotes(self, instruments: list[dict]):
        raise NotImplementedError

class YahooFinanceProvider(MarketDataProvider):
    name = 'yahoo'

    @staticmethod
    async def _search(name: str):
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f'{YAHOO_BASE}/v1/finance/search', params={'q': name, 'quotesCount': 10, 'newsCount': 0})
                r.raise_for_status()
                quotes = r.json().get('quotes', [])
            equities = [q for q in quotes if q.get('quoteType') == 'EQUITY']
            nse = [q for q in equities if str(q.get('symbol', '')).endswith('.NS')]
            return (nse or equities or [{}])[0].get('symbol')
        except Exception:
            return None

    @staticmethod
    async def _one(instrument: dict):
        symbol = instrument.get('symbol') or await YahooFinanceProvider._search(instrument.get('security') or instrument['isin'])
        empty = {'isin': instrument['isin'], 'provider': 'yahoo', 'symbol': symbol, 'ltp': None, 'open': None, 'high': None, 'low': None, 'close': None, 'volume': None, 'as_of': datetime.now(timezone.utc)}
        if not symbol:
            return empty
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f'{YAHOO_BASE}/v8/finance/chart/{symbol}', params={'range': '1d', 'interval': '1m', 'includePrePost': 'false'})
                r.raise_for_status()
                result = (r.json().get('chart') or {}).get('result') or []
                if not result:
                    return empty
                data = result[0]
            meta = data.get('meta', {})
            quote = ((data.get('indicators') or {}).get('quote') or [{}])[0]
            closes = [v for v in quote.get('close', []) if v is not None]
            opens = [v for v in quote.get('open', []) if v is not None]
            highs = [v for v in quote.get('high', []) if v is not None]
            lows = [v for v in quote.get('low', []) if v is not None]
            volumes = [v for v in quote.get('volume', []) if v is not None]
            return {
                'isin': instrument['isin'], 'provider': 'yahoo', 'symbol': symbol,
                'ltp': meta.get('regularMarketPrice') if meta.get('regularMarketPrice') is not None else (closes[-1] if closes else None),
                'open': opens[0] if opens else None,
                'high': max(highs) if highs else None,
                'low': min(lows) if lows else None,
                'close': meta.get('previousClose'),
                'volume': volumes[-1] if volumes else None,
                'as_of': datetime.now(timezone.utc),
            }
        except Exception:
            return empty

    async def quotes(self, instruments: list[dict]):
        return await asyncio.gather(*(self._one(x) for x in instruments))

# Backward-compatible names for older imports. They all resolve to Yahoo Finance.
class MockProvider(YahooFinanceProvider):
    pass
class UpstoxProvider(YahooFinanceProvider):
    pass
class ZerodhaProvider(YahooFinanceProvider):
    pass

def get_provider_for_user(*args, **kwargs):
    return YahooFinanceProvider()

async def refresh_quotes(instruments: list[dict], *args, **kwargs):
    return await YahooFinanceProvider().quotes(instruments)

async def latest_quotes(*args, **kwargs):
    return []
