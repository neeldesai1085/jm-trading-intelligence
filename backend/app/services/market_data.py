from datetime import datetime, timezone
import httpx
class MarketDataProvider:
    name='base'
    async def quotes(self,instruments:list[dict]):raise NotImplementedError
class MockProvider(MarketDataProvider):
    name='mock'
    async def quotes(self,instruments):return [{**x,'provider':self.name,'symbol':x.get('symbol') or x['isin'],'ltp':None,'open':None,'high':None,'low':None,'close':None,'volume':None,'as_of':datetime.now(timezone.utc)} for x in instruments]
class UpstoxProvider(MarketDataProvider):
    name='upstox'
    def __init__(self,token):self.token=token
    async def quotes(self,instruments):
        keys=[x['symbol'] for x in instruments if x.get('symbol')]
        if not keys:return []
        async with httpx.AsyncClient(timeout=15) as c:
            r=await c.get('https://api.upstox.com/v3/market-quote/ohlc',headers={'Accept':'application/json','Authorization':f'Bearer {self.token}'},params={'instrument_key':','.join(keys),'interval':'1d'});r.raise_for_status();data=r.json().get('data',{})
        out=[]
        for x in instruments:
            d=data.get(x.get('symbol',''),{});live=d.get('live_ohlc') or d.get('ohlc') or {};prev=d.get('prev_ohlc') or {};out.append({'isin':x['isin'],'provider':self.name,'symbol':x.get('symbol'),'ltp':d.get('last_price'),'open':live.get('open'),'high':live.get('high'),'low':live.get('low'),'close':prev.get('close') or live.get('close'),'volume':live.get('volume'),'as_of':datetime.now(timezone.utc)})
        return out
class ZerodhaProvider(MarketDataProvider):
    name='zerodha'
    def __init__(self,api_key,access_token):self.api_key=api_key;self.access_token=access_token
    async def quotes(self,instruments):
        qs=[('i',x['symbol']) for x in instruments if x.get('symbol')]
        if not qs:return []
        async with httpx.AsyncClient(timeout=15) as c:
            r=await c.get('https://api.kite.trade/quote/ohlc',headers={'X-Kite-Version':'3','Authorization':f'token {self.api_key}:{self.access_token}'},params=qs);r.raise_for_status();data=r.json().get('data',{})
        out=[]
        for x in instruments:
            d=data.get(x.get('symbol',''),{});o=d.get('ohlc',{});out.append({'isin':x['isin'],'provider':self.name,'symbol':x.get('symbol'),'ltp':d.get('last_price'),'open':o.get('open'),'high':o.get('high'),'low':o.get('low'),'close':o.get('close'),'volume':d.get('volume'),'as_of':datetime.now(timezone.utc)})
        return out
