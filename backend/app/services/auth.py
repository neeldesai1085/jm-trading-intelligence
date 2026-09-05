from datetime import datetime, timedelta, timezone
import secrets
import jwt
from argon2 import PasswordHasher
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.session import get_db
from app.models.entities import User, AuthSession

_password_hash = PasswordHasher()
bearer = HTTPBearer(auto_error=False)

def _now(): return datetime.now(timezone.utc).replace(tzinfo=None)
def _secret():
    if settings.app_env.lower() == 'production' and (not settings.auth_secret or len(settings.auth_secret) < 32 or settings.auth_secret == 'change-this-secret'):
        raise RuntimeError('AUTH_SECRET must be set to a strong secret in production')
    return settings.auth_secret

def hash_password(password): return _password_hash.hash(password)
def verify_password(password, password_hash):
    try: return _password_hash.verify(password_hash, password)
    except Exception: return False

def _jwt(user_id, token_type, expires, jti=None):
    now=_now(); return jwt.encode({'sub':str(user_id),'type':token_type,'iat':now,'exp':now+expires,'jti':jti or secrets.token_urlsafe(24)},_secret(),algorithm='HS256')

def create_session(db: Session, user: User):
    jti=secrets.token_urlsafe(24); expires=_now()+timedelta(days=settings.auth_refresh_days)
    db.add(AuthSession(jti=jti,user_id=user.id,expires_at=expires)); db.commit()
    return _jwt(user.id,'access',timedelta(minutes=settings.auth_access_minutes)), _jwt(user.id,'refresh',timedelta(days=settings.auth_refresh_days),jti), expires

def decode_token(token, expected_type):
    try: payload=jwt.decode(token,_secret(),algorithms=['HS256'])
    except jwt.PyJWTError as exc: raise HTTPException(status_code=401,detail='Invalid or expired token') from exc
    if payload.get('type') != expected_type or not payload.get('sub'): raise HTTPException(status_code=401,detail='Invalid token type')
    return payload

def get_current_user(credentials: HTTPAuthorizationCredentials=Depends(bearer), db: Session=Depends(get_db)):
    if credentials is None: raise HTTPException(status_code=401,detail='Authentication required')
    payload=decode_token(credentials.credentials,'access')
    try: uid=int(payload['sub'])
    except (TypeError,ValueError): raise HTTPException(status_code=401,detail='Invalid token subject')
    user=db.get(User,uid)
    if not user or not user.is_active: raise HTTPException(status_code=401,detail='User is not active')
    return user

def refresh_access_token(db: Session, refresh_token):
    payload=decode_token(refresh_token,'refresh'); jti=payload.get('jti')
    session=db.scalar(select(AuthSession).where(AuthSession.jti==jti)) if jti else None
    if not session or session.revoked_at is not None or session.expires_at <= _now(): raise HTTPException(status_code=401,detail='Refresh session is invalid or expired')
    user=db.get(User,session.user_id)
    if not user or not user.is_active: raise HTTPException(status_code=401,detail='User is not active')
    session.revoked_at=_now(); db.commit()
    return create_session(db,user)

def revoke_refresh_token(db: Session, refresh_token):
    try: payload=decode_token(refresh_token,'refresh')
    except HTTPException: return
    jti=payload.get('jti')
    session=db.scalar(select(AuthSession).where(AuthSession.jti==jti)) if jti else None
    if session and session.revoked_at is None: session.revoked_at=_now(); db.commit()
