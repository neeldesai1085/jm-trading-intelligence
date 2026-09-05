from datetime import datetime,timedelta,timezone
import secrets,jwt
from argon2 import PasswordHasher
from fastapi import Depends,HTTPException
from fastapi.security import HTTPAuthorizationCredentials,HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.session import get_db
from app.models.entities import User,AuthSession
_password_hash=PasswordHasher();bearer=HTTPBearer(auto_error=False)
def _now(): return datetime.now(timezone.utc).replace(tzinfo=None)
def _secret():
    if settings.app_env.lower()=='production' and (not settings.auth_secret or len(settings.auth_secret)<32 or settings.auth_secret=='change-this-secret'): raise RuntimeError('AUTH_SECRET must be set to a strong secret in production')
    return settings.auth_secret
def hash_password(password): return _password_hash.hash(password)
def verify_password(password,password_hash):
    try:return _password_hash.verify(password_hash,password)
    except Exception:return False
def _jwt(user_id,token_type,expires,jti=None):
    now=_now();return jwt.encode({'sub':str(user_id),'type':token_type,'iat':now,'exp':now+expires,'jti':jti or secrets.token_urlsafe(24)},_secret(),algorithm='HS256')
def create_session(db:Session,user:User):
    jti=secrets.token_urlsafe(24);expires=_now()+timedelta(days=settings.auth_refresh_days);db.add(AuthSession(jti=jti,user_id=user.id,expires_at=expires));db.commit();return _jwt(user.id,'access',timedelta(minutes=settings.auth_access_minutes)),_jwt(user.id,'refresh',timedelta(days=settings.auth_refresh_days),jti),expires
def decode_token(token,expected_type):
    try:p=jwt.decode(token,_secret(),algorithms=['HS256'])
    except jwt.PyJWTError as exc:raise HTTPException(401,'Invalid or expired token') from exc
    if p.get('type')!=expected_type or not p.get('sub'):raise HTTPException(401,'Invalid token type')
    return p
def get_current_user(credentials:HTTPAuthorizationCredentials=Depends(bearer),db:Session=Depends(get_db)):
    if credentials is None:raise HTTPException(401,'Authentication required')
    p=decode_token(credentials.credentials,'access')
    try:uid=int(p['sub'])
    except (TypeError,ValueError):raise HTTPException(401,'Invalid token subject')
    user=db.get(User,uid)
    if not user or not user.is_active:raise HTTPException(401,'User is not active')
    return user
def refresh_access_token(db,refresh_token):
    p=decode_token(refresh_token,'refresh');jti=p.get('jti');s=db.scalar(select(AuthSession).where(AuthSession.jti==jti)) if jti else None
    if not s or s.revoked_at is not None or s.expires_at<=_now():raise HTTPException(401,'Refresh session is invalid or expired')
    user=db.get(User,s.user_id)
    if not user or not user.is_active:raise HTTPException(401,'User is not active')
    s.revoked_at=_now();db.commit();return create_session(db,user)
def revoke_refresh_token(db,refresh_token):
    try:p=decode_token(refresh_token,'refresh')
    except HTTPException:return
    jti=p.get('jti');s=db.scalar(select(AuthSession).where(AuthSession.jti==jti)) if jti else None
    if s and s.revoked_at is None:s.revoked_at=_now();db.commit()
