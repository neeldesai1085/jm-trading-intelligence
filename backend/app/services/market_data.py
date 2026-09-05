from __future__ import annotations
import asyncio
from datetime import datetime, timezone
import httpx
YAHOO_BASE='https://query1.finance.yahoo.com'
class MarketDataProvider:
    name='base'
    async def quotes(self,instruments:list[dict]): raise NotImplementedError
class YahooFinanceProvider(MarketDataProvider):
    name='yahoo'
    @staticmethod
    async def _search(name:str):
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r=await c.get(f'{YAHOO_BASE}/v1/finance/search',params={'q':name,'quotesCount':10,'newsCount':0});r.raise_for_status();qs=r.json().get('quotes',[])
            eq=[q for q in qs if q.get('quoteType')=='EQUITY'];ns=[q for q in eq if str(q.get('symbol','')).endswith('.NS')]
            return (ns or eq or [{}])[0].get('symbol')
        except Exception:return None
    @staticmethod
    async def _one(x):
        symbol=x.get('symbol') or await YahooFinanceProvider._search(x.get('security') or x['isin'])
        if not symbol:return {'isin':x['isin'],'provider':'yahoo','symbol':None,'ltp':None,'open':None,'high':None,'low':None,'close':None,'volume':None,'as_of':datetime.now(timezone.utc)}
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r=await c.get(f'{YAHOO_BASE}/v8/finance/chart/{symbol}',params={'range':'1d','interval':'1m','includePrePost':'false'});r.raise_for_status();d=r.json()['chart']['result'][0]
            meta=d.get('meta',{});q=((d.get('indicators') or {}).get('quote') or [{}])[0];closes=[v for v in q.get('close',[]) if v is not None];opens=[v for v in q.get('open',[]) if v is not None];highs=[v for v in q.get('high',[]) if v is not None];lows=[v for v in q.get('low',[]) if v is not None];vols=[v for v in q.get('volume',[]) if v is not None]
            return {'isin':x['isin'],'provider':'yahoo','symbol':symbol,'ltp':meta.get('regularMarketPrice') or (closes[-1] if closes else None),'open':opens[0] if opens else None,'high':max(highs) if highs else None,'low':min(lows) if lows else None,'close':meta.get('previousClose'),'volume':vols[-1] if vols else None,'as_of':datetime.now(timezone.utc)}
        except Exception:return {'isin':x['isin'],'provider':'yahoo','symbol':symbol,'ltp':None,'open':None,'high':None,'low':None,'close':None,'volume':None,'as_of':datetime.now(timezone.utc)}
    async def quotes(self,instruments:list[dict]): return await asyncio.gather(*(self._one(x) for x in instruments))
class MockProvider(YahooFinanceProvider):
    name='yahoo'
class UpstoxProvider(YahooFinanceProvider):
    name='yahoo'
class ZerodhaProvider(YahooFinanceProvider):
    name='yahoo'
