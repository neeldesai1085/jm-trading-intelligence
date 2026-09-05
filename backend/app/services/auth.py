import base64
import hashlib
import hmac
import json
import time
from fastapi import HTTPException, Request, WebSocket
from app.core.config import settings


def auth_enabled() -> bool:
    return bool(settings.app_access_code)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip('=')


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


def issue_token(member_name: str) -> str:
    payload = {'sub': member_name, 'exp': int(time.time()) + settings.auth_session_hours * 3600}
    body = _b64(json.dumps(payload, separators=(',', ':')).encode())
    sig = hmac.new(settings.auth_secret.encode(), body.encode(), hashlib.sha256).digest()
    return f'{body}.{_b64(sig)}'


def verify_token(token: str | None) -> dict | None:
    if not token:
        return None
    try:
        body, sig = token.split('.', 1)
        expected = hmac.new(settings.auth_secret.encode(), body.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_unb64(sig), expected):
            return None
        payload = json.loads(_unb64(body).decode())
        if int(payload.get('exp', 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def extract_bearer(request: Request) -> str | None:
    value = request.headers.get('authorization', '')
    if value.lower().startswith('bearer '):
        return value[7:].strip()
    return None


def require_request_auth(request: Request) -> dict | None:
    if not auth_enabled():
        return {'sub': 'local'}
    payload = verify_token(extract_bearer(request))
    if payload is None:
        raise HTTPException(status_code=401, detail='Authentication required')
    return payload


def check_credentials(member_name: str, access_code: str) -> bool:
    if not auth_enabled():
        return True
    ok_name = 1 <= len(member_name.strip()) <= 40
    ok_code = hmac.compare_digest(access_code, settings.app_access_code)
    return ok_name and ok_code


def websocket_member(websocket: WebSocket) -> dict | None:
    if not auth_enabled():
        return {'sub': 'local'}
    token = websocket.query_params.get('token')
    return verify_token(token)
