from __future__ import annotations
import base64,hashlib,hmac,secrets
import httpx
from app.core.config import settings

def sign_oauth_state(payload:str)->str:
    secret=settings.auth_secret.encode(); sig=hmac.new(secret,payload.encode(),hashlib.sha256).hexdigest(); return base64.urlsafe_b64encode((payload+'.'+sig).encode()).decode()
def verify_oauth_state(token:str)->str|None:
    try:raw=base64.urlsafe_b64decode(token.encode()).decode();payload,sig=raw.rsplit('.',1)
    except Exception:return None
    if hmac.compare_digest(sig,hmac.new(settings.auth_secret.encode(),payload.encode(),hashlib.sha256).hexdigest()):return payload
    return None
def build_upstox_authorize_url(state:str):
    return f'https://api.upstox.com/v2/login/authorization/dialog?response_type=code&client_id={settings.upstox_client_id}&redirect_uri={settings.upstox_redirect_uri}&state={state}'
async def exchange_upstox_code(code:str):
    data={'code':code,'client_id':settings.upstox_client_id,'client_secret':settings.upstox_client_secret,'redirect_uri':settings.upstox_redirect_uri,'grant_type':'authorization_code'}
    async with httpx.AsyncClient(timeout=20) as c:
        r=await c.post('https://api.upstox.com/v2/login/authorization/token',data=data);r.raise_for_status();return r.json()
def build_zerodha_login_url(state:str): return f'https://kite.zerodha.com/connect/login?v=3&api_key={settings.zerodha_api_key}&state={state}'
async def exchange_zerodha_request_token(request_token:str):
    checksum=hashlib.sha256((settings.zerodha_api_key+request_token+settings.zerodha_api_secret).encode()).hexdigest()
    async with httpx.AsyncClient(timeout=20) as c:
        r=await c.post('https://api.kite.trade/session/token',data={'api_key':settings.zerodha_api_key,'request_token':request_token,'checksum':checksum});r.raise_for_status();return r.json()
