from __future__ import annotations
from datetime import datetime,timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
import random,httpx
from app.core.config import settings
from app.models.entities import MarketQuote,BrokerConnection,InstrumentMapping
class MockProvider:
    name='mock'
    def quote(self,isin,symbol=None):
        seed=sum(map(ord,isin));base=50+(seed%500)/10;return {'isin':isin,'symbol':symbol or isin,'ltp':round(base,2),'open':round(base-1,2),'high':round(base+2,2),'low':round(base-3,2),'close':round(base-1.5,2),'volume':10000+seed%50000}
class UpstoxProvider:
    name='upstox'
    def __init__(self,token):self.token=token
    def quote(self,isin,symbol=None):
        with httpx.Client(timeout=10) as c:r=c.get('https://api.upstox.com/v2/market-quote/quotes',headers={'Authorization':f'Bearer {self.token}','Accept':'application/json'},params={'instrument_key':symbol or isin});r.raise_for_status();d=r.json();return next(iter(d.get('data',{}).values()))
class ZerodhaProvider:
    name='zerodha'
    def __init__(self,api_key,token):self.api_key=api_key;self.token=token
    def quote(self,isin,symbol=None):
        with httpx.Client(timeout=10) as c:r=c.get('https://api.kite.trade/quote',headers={'X-Kite-Version':'3','Authorization':f'token {self.api_key}:{self.token}'},params={'i':symbol or isin});r.raise_for_status();return next(iter(r.json().get('data',{}).values()))
def get_provider_for_user(db:Session,user_id:int,preferred:str|None=None):
    p=(preferred or settings.market_data_provider).lower()
    if p=='upstox':
        c=db.scalar(select(BrokerConnection).where(BrokerConnection.user_id==user_id,BrokerConnection.provider=='upstox')); 
        if c:return UpstoxProvider('')
        if settings.upstox_access_token:return UpstoxProvider(settings.upstox_access_token)
    if p=='zerodha' and settings.zerodha_api_key and settings.zerodha_access_token:return ZerodhaProvider(settings.zerodha_api_key,settings.zerodha_access_token)
    return MockProvider()
def latest_quotes(db:Session,user_id:int,portfolio_id:int|None=None):
    return db.scalars(select(MarketQuote).where(MarketQuote.user_id==user_id).order_by(MarketQuote.as_of.desc())).all()
def refresh_quotes(db:Session,user_id:int,portfolio_id:int|None=None):
    mappings=db.scalars(select(InstrumentMapping).where(InstrumentMapping.user_id==user_id)).all();provider=get_provider_for_user(db,user_id)
    out=[]
    for m in mappings:
        q=provider.quote(m.isin,m.instrument_key);row=MarketQuote(user_id=user_id,isin=m.isin,provider=provider.name,symbol=m.security,ltp=q.get('ltp'),open=q.get('open'),high=q.get('high'),low=q.get('low'),close=q.get('close'),volume=q.get('volume'),as_of=datetime.now(timezone.utc).replace(tzinfo=None));db.add(row);out.append(q)
    db.commit();return out
