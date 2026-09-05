from __future__ import annotations
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Any
import hashlib, json, tempfile
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy import select, func, desc
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.metrics import render_prometheus
from app.core.rate_limit import rate_limit
from app.db.session import SessionLocal, get_db
from app.models.entities import User, Portfolio, ImportBatch, ImportJob, ContractNote, SecurityLedger, Execution, MarketQuote, InstrumentMapping, TradeAnnotation, BrokerConnection
from app.services.auth import hash_password, verify_password, create_session, get_current_user, refresh_access_token, revoke_refresh_token, decode_token
from app.services.analytics import overview, realized_by_security, open_holdings, daily_performance, intelligence
from app.services.advanced_analytics import advanced_analytics
from app.services.excel_parity import build_excel_parity
from app.services.importer import import_pdf
from app.services.market_data import get_provider_for_user, refresh_quotes, latest_quotes
from app.services.portfolios import ensure_default_portfolio, get_user_portfolio, get_user_portfolios
from app.services.storage import store_raw_pdf
from app.services.email import send_email, hash_token, new_token
from app.services.broker_auth import build_upstox_authorize_url, exchange_upstox_code, build_zerodha_login_url, exchange_zerodha_request_token, sign_oauth_state, verify_oauth_state

router = APIRouter()

ALLOWED_PDF_MAGIC = b'%PDF-'
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_FILES_PER_REQUEST = 25


def user_dict(user: User):
    return {'id': user.id, 'email': user.email, 'name': user.name, 'email_verified': bool(user.email_verified)}

def set_refresh_cookie(response: Response, token: str):
    response.set_cookie(settings.auth_cookie_name, token, httponly=True, secure=settings.auth_cookie_secure, samesite=settings.auth_cookie_samesite, max_age=settings.auth_refresh_days*86400, path='/api/auth')

def clear_refresh_cookie(response: Response):
    response.delete_cookie(settings.auth_cookie_name, path='/api/auth')

def resolve_portfolio(db: Session, user_id: int, portfolio_id: int|None):
    return get_user_portfolio(db,user_id,portfolio_id).id

def paginate(query, db: Session, page: int, page_size: int):
    total=db.scalar(select(func.count()).select_from(query.subquery())) or 0
    return db.scalars(query.offset((page-1)*page_size).limit(page_size)).all(), total

def _import_one(path: Path, user_id: int, portfolio_id: int, filename: str, source_uri: str|None=None):
    with SessionLocal() as db:
        try:
            batch=import_pdf(db,path,user_id,portfolio_id)
            if source_uri and getattr(batch,'source_uri',None) is None:
                batch.source_uri=source_uri; db.commit()
            return {'status':batch.status,'filename':filename,'contract_notes_found':batch.contract_notes_found,'contracts_added':batch.contracts_added,'duplicates':batch.duplicates,'executions_added':batch.executions_added,'security_rows_added':batch.security_rows_added,'errors':batch.errors.split('; ') if batch.errors else []}
        finally: path.unlink(missing_ok=True)

def _run_import_job(job_id: int, path: Path, user_id: int, portfolio_id: int, filename: str, source_uri: str|None):
    with SessionLocal() as db:
        job=db.get(ImportJob,job_id)
        if not job:return
        job.status='PROCESSING';job.started_at=datetime.now(timezone.utc).replace(tzinfo=None);db.commit()
        try:
            result=_import_one(path,user_id,portfolio_id,filename,source_uri); job.status='COMPLETED';job.result_json=json.dumps(result);job.completed_at=datetime.now(timezone.utc).replace(tzinfo=None);db.commit()
        except Exception as exc:
            db.rollback();job=db.get(ImportJob,job_id)
            if job:job.status='FAILED';job.error=str(exc);job.completed_at=datetime.now(timezone.utc).replace(tzinfo=None);db.commit()
            path.unlink(missing_ok=True)

@router.get('/health')
def health(): return {'status':'ok','market_provider':settings.market_data_provider}

@router.get('/health/ready')
def readiness(db: Session=Depends(get_db)):
    try: db.execute(select(1)); return {'status':'ready'}
    except Exception as exc: raise HTTPException(503,'Database is not ready') from exc

@router.get('/metrics',include_in_schema=False)
def metrics(): return PlainTextResponse(render_prometheus(),media_type='text/plain; version=0.0.4')

@router.post('/auth/register')
def register(request: Request,payload:dict,response:Response,db:Session=Depends(get_db)):
    rate_limit(request,'auth'); email=str(payload.get('email','')).strip().lower(); password=str(payload.get('password','')); name=str(payload.get('name','')).strip() or email.split('@')[0]
    if not email or '@' not in email or len(email)>320: raise HTTPException(400,'A valid email is required')
    if not 8<=len(password)<=256: raise HTTPException(400,'Password must be 8-256 characters')
    if db.scalar(select(User).where(User.email==email)): raise HTTPException(409,'An account with this email already exists')
    user=User(email=email,name=name[:120],password_hash=hash_password(password),is_active=True,email_verified=False); db.add(user);db.commit();db.refresh(user)
    portfolio=ensure_default_portfolio(db,user.id); access,refresh,expires=create_session(db,user); set_refresh_cookie(response,refresh)
    return {'access_token':access,'token_type':'bearer','refresh_expires_at':expires,'user':user_dict(user),'portfolio':{'id':portfolio.id,'name':portfolio.name}}

@router.post('/auth/login')
def login(request:Request,payload:dict,response:Response,db:Session=Depends(get_db)):
    rate_limit(request,'auth'); email=str(payload.get('email','')).strip().lower(); password=str(payload.get('password','')); user=db.scalar(select(User).where(User.email==email))
    if not user or not user.is_active or not verify_password(password,user.password_hash): raise HTTPException(401,'Invalid email or password')
    portfolio=ensure_default_portfolio(db,user.id); access,refresh,expires=create_session(db,user); set_refresh_cookie(response,refresh)
    return {'access_token':access,'token_type':'bearer','refresh_expires_at':expires,'user':user_dict(user),'portfolio':{'id':portfolio.id,'name':portfolio.name}}

@router.post('/auth/refresh')
def refresh(request:Request,response:Response,payload:dict|None=None,db:Session=Depends(get_db)):
    rate_limit(request,'auth'); data=payload or {}; token=str(data.get('refresh_token','')).strip() or request.cookies.get(settings.auth_cookie_name,'')
    if not token: raise HTTPException(400,'refresh_token is required')
    access,new_refresh,expires=refresh_access_token(db,token); user_id=int(decode_token(new_refresh,'refresh')['sub']); user=db.get(User,user_id)
    if not user: raise HTTPException(401,'User is not active')
    set_refresh_cookie(response,new_refresh); portfolio=ensure_default_portfolio(db,user.id)
    return {'access_token':access,'token_type':'bearer','refresh_expires_at':expires,'user':user_dict(user),'portfolio':{'id':portfolio.id,'name':portfolio.name}}

@router.post('/auth/logout')
def logout(request:Request,response:Response,payload:dict|None=None,db:Session=Depends(get_db)):
    rate_limit(request,'auth');data=payload or {};token=str(data.get('refresh_token','')).strip() or request.cookies.get(settings.auth_cookie_name,'')
    if token: revoke_refresh_token(db,token)
    clear_refresh_cookie(response); return {'status':'logged_out'}

@router.get('/auth/me')
def me(current_user:User=Depends(get_current_user)): return {**user_dict(current_user),'created_at':current_user.created_at}

@router.patch('/auth/profile')
def profile(payload:dict,db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    name=str(payload.get('name','')).strip()
    if not name or len(name)>120: raise HTTPException(400,'name must be 1-120 characters')
    current_user.name=name;current_user.updated_at=datetime.now(timezone.utc).replace(tzinfo=None);db.commit();db.refresh(current_user);return user_dict(current_user)

@router.get('/auth/sessions')
def sessions(db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    rows=db.scalars(select(AuthSession).where(AuthSession.user_id==current_user.id,AuthSession.revoked_at.is_(None)).order_by(AuthSession.created_at.desc())).all()
    return [{'id':r.id,'created_at':r.created_at,'expires_at':r.expires_at} for r in rows]

@router.post('/auth/change-password')
def change_password(payload:dict,db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    current=str(payload.get('current_password',''));new=str(payload.get('new_password',''))
    if not verify_password(current,current_user.password_hash): raise HTTPException(401,'Current password is incorrect')
    if not 8<=len(new)<=256: raise HTTPException(400,'New password must be 8-256 characters')
    if new==current: raise HTTPException(400,'New password must be different from the current password')
    current_user.password_hash=hash_password(new);db.query(AuthSession).filter(AuthSession.user_id==current_user.id,AuthSession.revoked_at.is_(None)).update({'revoked_at':datetime.now(timezone.utc).replace(tzinfo=None)},synchronize_session=False);db.commit();return {'status':'password_changed','message':'Sign in again on other devices.'}

# The remainder of the production routes is intentionally omitted from this abbreviated tree payload.
