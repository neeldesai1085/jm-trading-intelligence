from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
from io import StringIO
import csv, json, secrets
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.metrics import render_prometheus
from app.core.rate_limit import rate_limit
from app.db.session import SessionLocal, get_db
from app.models.entities import AuthSession, ContractNote, Execution, ImportBatch, ImportJob, InstrumentMapping, MarketQuote, Portfolio, SecurityLedger, TradeAnnotation, User
from app.services.advanced_analytics import advanced
from app.services.analytics import intelligence, overview
from app.services.auth import create_session, decode_token, get_current_user, hash_password, refresh_access_token, revoke_refresh_token, verify_password
from app.services.excel_parity import build_excel_parity
from app.services.importer import import_pdf
from app.services.market_data import YahooFinanceProvider
from app.services.portfolios import ensure_default_portfolio, get_user_portfolio

router = APIRouter()
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_FILES_PER_REQUEST = 25

def csv_response(rows, filename):
    stream = StringIO()
    if not rows: stream.write('No records\n')
    else:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys())); writer.writeheader(); writer.writerows(rows)
    stream.seek(0)
    return StreamingResponse(iter([stream.getvalue()]), media_type='text/csv', headers={'Content-Disposition': f'attachment; filename="{filename}"'})

def user_dict(user): return {'id': user.id, 'email': user.email, 'name': user.name}
def set_refresh_cookie(response, token): response.set_cookie(settings.auth_cookie_name, token, httponly=True, secure=settings.auth_cookie_secure, samesite=settings.auth_cookie_samesite, max_age=settings.auth_refresh_days * 86400, path='/api/auth')
def clear_refresh_cookie(response): response.delete_cookie(settings.auth_cookie_name, path='/api/auth')
def resolve_portfolio(db, user_id, portfolio_id): return get_user_portfolio(db, user_id, portfolio_id).id
def paginate(query, db, page, page_size):
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    return db.scalars(query.offset((page - 1) * page_size).limit(page_size)).all(), total

def _import_one(path: Path, user_id: int, portfolio_id: int, filename: str):
    with SessionLocal() as db:
        try:
            batch = import_pdf(db, path, user_id, portfolio_id)
            return {'status': batch.status, 'filename': filename, 'contract_notes_found': batch.contract_notes_found, 'contracts_added': batch.contracts_added, 'duplicates': batch.duplicates, 'executions_added': batch.executions_added, 'security_rows_added': batch.security_rows_added, 'errors': batch.errors.split('; ') if batch.errors else []}
        finally: path.unlink(missing_ok=True)

def _run_import_job(job_id, path, user_id, portfolio_id, filename):
    with SessionLocal() as db:
        job = db.get(ImportJob, job_id)
        if not job: return
        job.status = 'PROCESSING'; job.started_at = datetime.now(timezone.utc).replace(tzinfo=None); db.commit()
        try:
            result = _import_one(path, user_id, portfolio_id, filename)
            job.status = 'COMPLETED'; job.result_json = json.dumps(result); job.completed_at = datetime.now(timezone.utc).replace(tzinfo=None); db.commit()
        except Exception as exc:
            db.rollback(); job = db.get(ImportJob, job_id)
            if job: job.status = 'FAILED'; job.error = str(exc); job.completed_at = datetime.now(timezone.utc).replace(tzinfo=None); db.commit()
            path.unlink(missing_ok=True)

@router.get('/health')
def health(): return {'status': 'ok', 'market_provider': settings.market_data_provider}
@router.get('/health/ready')
def readiness(db: Session = Depends(get_db)):
    try: db.execute(select(1)); return {'status': 'ready'}
    except Exception as exc: raise HTTPException(503, 'Database is not ready') from exc
@router.get('/metrics', include_in_schema=False)
def metrics(): return PlainTextResponse(render_prometheus(), media_type='text/plain; version=0.0.4')

@router.post('/auth/register')
def register(request: Request, payload: dict, response: Response, db: Session = Depends(get_db)):
    rate_limit(request, 'auth'); email = str(payload.get('email', '')).strip().lower(); password = str(payload.get('password', '')); name = str(payload.get('name', '')).strip() or email.split('@')[0]
    if not email or '@' not in email or len(email) > 320: raise HTTPException(400, 'A valid email is required')
    if not 8 <= len(password) <= 256: raise HTTPException(400, 'Password must be 8-256 characters')
    if db.scalar(select(User).where(User.email == email)): raise HTTPException(409, 'An account with this email already exists')
    user = User(email=email, name=name[:120], password_hash=hash_password(password), is_active=True); db.add(user); db.commit(); db.refresh(user)
    portfolio = ensure_default_portfolio(db, user.id); access, refresh, expires_at = create_session(db, user); set_refresh_cookie(response, refresh)
    return {'access_token': access, 'token_type': 'bearer', 'refresh_expires_at': expires_at, 'user': user_dict(user), 'portfolio': {'id': portfolio.id, 'name': portfolio.name}}

@router.post('/auth/login')
def login(request: Request, payload: dict, response: Response, db: Session = Depends(get_db)):
    rate_limit(request, 'auth'); email = str(payload.get('email', '')).strip().lower(); password = str(payload.get('password', '')); user = db.scalar(select(User).where(User.email == email))
    if not user or not user.is_active or not verify_password(password, user.password_hash): raise HTTPException(401, 'Invalid email or password')
    portfolio = ensure_default_portfolio(db, user.id); access, refresh, expires_at = create_session(db, user); set_refresh_cookie(response, refresh)
    return {'access_token': access, 'token_type': 'bearer', 'refresh_expires_at': expires_at, 'user': user_dict(user), 'portfolio': {'id': portfolio.id, 'name': portfolio.name}}

@router.post('/auth/refresh')
def refresh(request: Request, response: Response, payload: dict | None = None, db: Session = Depends(get_db)):
    rate_limit(request, 'auth'); data = payload or {}; token = str(data.get('refresh_token', '')).strip() or request.cookies.get(settings.auth_cookie_name, '')
    if not token: raise HTTPException(400, 'refresh_token is required')
    access, new_refresh, expires_at = refresh_access_token(db, token); user_id = int(decode_token(new_refresh, 'refresh')['sub']); user = db.get(User, user_id)
    if not user or not user.is_active: raise HTTPException(401, 'User is not active')
    set_refresh_cookie(response, new_refresh); portfolio = ensure_default_portfolio(db, user.id)
    return {'access_token': access, 'token_type': 'bearer', 'refresh_expires_at': expires_at, 'user': user_dict(user), 'portfolio': {'id': portfolio.id, 'name': portfolio.name}}

@router.post('/auth/logout')
def logout(request: Request, response: Response, payload: dict | None = None, db: Session = Depends(get_db)):
    rate_limit(request, 'auth'); data = payload or {}; token = str(data.get('refresh_token', '')).strip() or request.cookies.get(settings.auth_cookie_name, '')
    if token: revoke_refresh_token(db, token)
    clear_refresh_cookie(response); return {'status': 'logged_out'}
@router.get('/auth/me')
def me(current_user: User = Depends(get_current_user)): return {**user_dict(current_user), 'created_at': current_user.created_at}
@router.patch('/auth/profile')
def profile(payload: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    name = str(payload.get('name', '')).strip()
    if not name or len(name) > 120: raise HTTPException(400, 'name must be 1-120 characters')
    current_user.name = name; db.commit(); db.refresh(current_user); return user_dict(current_user)
@router.get('/auth/sessions')
def sessions(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = db.scalars(select(AuthSession).where(AuthSession.user_id == current_user.id, AuthSession.revoked_at.is_(None)).order_by(AuthSession.created_at.desc())).all()
    return [{'id': r.id, 'created_at': r.created_at, 'expires_at': r.expires_at} for r in rows]
@router.post('/auth/change-password')
def change_password(payload: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    current = str(payload.get('current_password', '')); new = str(payload.get('new_password', ''))
    if not verify_password(current, current_user.password_hash): raise HTTPException(401, 'Current password is incorrect')
    if not 8 <= len(new) <= 256: raise HTTPException(400, 'New password must be 8-256 characters')
    if new == current: raise HTTPException(400, 'New password must be different from the current password')
    current_user.password_hash = hash_password(new); now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.query(AuthSession).filter(AuthSession.user_id == current_user.id, AuthSession.revoked_at.is_(None)).update({'revoked_at': now}, synchronize_session=False); db.commit()
    return {'status': 'password_changed', 'message': 'Sign in again on other devices.'}

@router.get('/portfolios')
def portfolios(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    default = ensure_default_portfolio(db, current_user.id); rows = db.scalars(select(Portfolio).where(Portfolio.user_id == current_user.id).order_by(Portfolio.created_at, Portfolio.id)).all()
    return [{'id': p.id, 'name': p.name, 'is_default': p.id == default.id, 'created_at': p.created_at} for p in rows]
@router.post('/portfolios')
def create_portfolio(payload: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    name = str(payload.get('name', '')).strip()
    if not name or len(name) > 120: raise HTTPException(400, 'Portfolio name must be 1-120 characters')
    if db.scalar(select(Portfolio).where(Portfolio.user_id == current_user.id, Portfolio.name == name)): raise HTTPException(409, 'Portfolio already exists')
    row = Portfolio(user_id=current_user.id, name=name, is_default=False); db.add(row); db.commit(); db.refresh(row)
    return {'id': row.id, 'name': row.name, 'is_default': False, 'created_at': row.created_at}

@router.post('/imports/upload')
async def upload_contract_notes(files: list[UploadFile] = File(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user), portfolio_id: int | None = None):
    if len(files) > MAX_FILES_PER_REQUEST: raise HTTPException(400, 'Maximum 25 files per import request')
    pid = resolve_portfolio(db, current_user.id, portfolio_id); out = []; upload_dir = Path(settings.upload_dir); upload_dir.mkdir(parents=True, exist_ok=True)
    for file in files:
        filename = Path(file.filename or 'upload.pdf').name
        if not filename.lower().endswith('.pdf'): raise HTTPException(400, 'Only PDF files are supported')
        content = await file.read()
        if len(content) > MAX_FILE_BYTES: raise HTTPException(413, f'{filename} exceeds the 25 MB upload limit')
        if not content.startswith(b'%PDF'): raise HTTPException(400, f'{filename} is not a valid PDF file')
        path = upload_dir / f'{current_user.id}_{pid}_{secrets.token_hex(6)}_{filename}'; path.write_bytes(content)
        try: out.append(_import_one(path, current_user.id, pid, filename))
        except Exception as exc: path.unlink(missing_ok=True); raise HTTPException(422, f'Could not import {filename}: {exc}') from exc
    return out

@router.post('/imports/upload/background')
async def upload_contract_notes_background(background_tasks: BackgroundTasks, files: list[UploadFile] = File(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user), portfolio_id: int | None = None):
    if len(files) > MAX_FILES_PER_REQUEST: raise HTTPException(400, 'Maximum 25 files per import request')
    pid = resolve_portfolio(db, current_user.id, portfolio_id); upload_dir = Path(settings.upload_dir); upload_dir.mkdir(parents=True, exist_ok=True); jobs = []
    for file in files:
        filename = Path(file.filename or 'upload.pdf').name; content = await file.read()
        if not filename.lower().endswith('.pdf') or not content.startswith(b'%PDF'): raise HTTPException(400, f'{filename} is not a valid PDF file')
        if len(content) > MAX_FILE_BYTES: raise HTTPException(413, f'{filename} exceeds the 25 MB upload limit')
        path = upload_dir / f'{current_user.id}_{pid}_{secrets.token_hex(6)}_{filename}'; path.write_bytes(content)
        job = ImportJob(user_id=current_user.id, portfolio_id=pid, filename=filename, status='QUEUED'); db.add(job); db.flush(); background_tasks.add_task(_run_import_job, job.id, path, current_user.id, pid, filename); jobs.append({'id': job.id, 'filename': filename, 'status': 'QUEUED'})
    db.commit(); return jobs

@router.get('/imports')
def imports(page: int = 1, page_size: int = 100, portfolio_id: int | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    pid = resolve_portfolio(db, current_user.id, portfolio_id); page = max(1, page); page_size = min(max(1, page_size), 500); q = select(ImportBatch).where(ImportBatch.user_id == current_user.id, ImportBatch.portfolio_id == pid).order_by(ImportBatch.created_at.desc()); rows, total = paginate(q, db, page, page_size)
    return {'items': [{'id': r.id, 'filename': r.filename, 'status': r.status, 'contracts_added': r.contracts_added, 'duplicates': r.duplicates, 'executions_added': r.executions_added, 'security_rows_added': r.security_rows_added, 'errors': r.errors} for r in rows], 'total': total, 'page': page, 'page_size': page_size}
@router.get('/imports/jobs/{job_id}')
def import_job(job_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    row = db.scalar(select(ImportJob).where(ImportJob.id == job_id, ImportJob.user_id == current_user.id))
    if not row: raise HTTPException(404, 'Import job not found')
    return {'id': row.id, 'filename': row.filename, 'status': row.status, 'error': row.error, 'result': json.loads(row.result_json) if row.result_json else None, 'created_at': row.created_at, 'started_at': row.started_at, 'completed_at': row.completed_at}

def annotation_rows(db, uid, pid): return db.scalars(select(TradeAnnotation).where(TradeAnnotation.user_id == uid, TradeAnnotation.portfolio_id == pid).order_by(TradeAnnotation.sell_date)).all()
@router.get('/trade-annotations')
def trade_annotations(page: int = 1, page_size: int = 100, portfolio_id: int | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    pid = resolve_portfolio(db, current_user.id, portfolio_id); q = select(TradeAnnotation).where(TradeAnnotation.user_id == current_user.id, TradeAnnotation.portfolio_id == pid).order_by(TradeAnnotation.sell_date); rows, total = paginate(q, db, max(1,page), min(max(1,page_size),500))
    return {'items': [{'security': r.security, 'buy_date': r.buy_date, 'sell_date': r.sell_date, 'strategy': r.strategy, 'setup': r.setup, 'regime': r.regime, 'note': r.note} for r in rows], 'total': total, 'page': max(1,page), 'page_size': min(max(1,page_size),500)}
@router.post('/trade-annotations')
def save_trade_annotation(payload: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from datetime import date as date_type
    try: security = str(payload.get('security','')).strip(); buy_date = date_type.fromisoformat(str(payload.get('buy_date',''))); sell_date = date_type.fromisoformat(str(payload.get('sell_date','')))
    except Exception as exc: raise HTTPException(400, 'security, buy_date and sell_date are required') from exc
    if not security or sell_date < buy_date: raise HTTPException(400, 'Invalid annotation')
    pid = resolve_portfolio(db, current_user.id, payload.get('portfolio_id')); row = db.scalar(select(TradeAnnotation).where(TradeAnnotation.user_id == current_user.id, TradeAnnotation.portfolio_id == pid, TradeAnnotation.security == security, TradeAnnotation.buy_date == buy_date, TradeAnnotation.sell_date == sell_date))
    values = {'strategy': str(payload.get('strategy','Unclassified')).strip() or 'Unclassified', 'setup': str(payload.get('setup','')).strip(), 'regime': str(payload.get('regime','')).strip(), 'note': str(payload.get('note','')).strip() or None}
    if row:
        for key, value in values.items(): setattr(row, key, value)
    else: db.add(TradeAnnotation(user_id=current_user.id, portfolio_id=pid, security=security, buy_date=buy_date, sell_date=sell_date, **values))
    db.commit(); return {'status':'saved'}

@router.get('/dashboard')
def dashboard(portfolio_id: int | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)): return overview(db, current_user.id, resolve_portfolio(db,current_user.id,portfolio_id))
@router.get('/intelligence')
def intel(portfolio_id: int | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)): return intelligence(db, current_user.id, resolve_portfolio(db,current_user.id,portfolio_id))
@router.get('/analytics/advanced')
def advanced_analytics(portfolio_id: int | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)): return advanced(db, current_user.id, resolve_portfolio(db,current_user.id,portfolio_id))
@router.get('/risk')
def risk(portfolio_id: int | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)): return dashboard(portfolio_id,db,current_user)['risk']
@router.get('/performance/daily')
def performance_daily(portfolio_id: int | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)): return dashboard(portfolio_id,db,current_user)['daily_pnl']
@router.get('/holdings')
def holdings(portfolio_id: int | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)): return dashboard(portfolio_id,db,current_user)['holdings']
@router.get('/realized')
def realized(portfolio_id: int | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)): return dashboard(portfolio_id,db,current_user)['realized_trades']
@router.get('/missing-dates')
def missing_dates(portfolio_id: int | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    pid = resolve_portfolio(db,current_user.id,portfolio_id); dates = set(db.scalars(select(ContractNote.trade_date).where(ContractNote.user_id==current_user.id,ContractNote.portfolio_id==pid)).all())
    if not dates:return []
    start,end=min(dates),max(dates); out=[]; day=start
    while day<=end:
        if day.weekday()<5 and day not in dates: out.append({'date':day,'status':'NO CONTRACT NOTE'})
        day += timedelta(days=1)
    return out

def contract_rows(db,uid,pid):
    rows=db.scalars(select(ContractNote).where(ContractNote.user_id==uid,ContractNote.portfolio_id==pid).order_by(ContractNote.trade_date)).all(); return [{'contract_note':r.contract_note,'trade_date':r.trade_date,'buy_qty':r.buy_qty,'sell_qty':r.sell_qty,'gross_buy_value':r.gross_buy_value,'gross_sell_value':r.gross_sell_value,'brokerage':r.displayed_brokerage,'net_amount':r.net_amount} for r in rows]
def execution_rows(db,uid,pid):
    rows=db.scalars(select(Execution).where(Execution.user_id==uid,Execution.portfolio_id==pid).order_by(Execution.trade_date,Execution.trade_time)).all(); return [{'contract_note':r.contract_note,'trade_date':r.trade_date,'trade_no':r.trade_no,'security':r.security,'side':r.side,'quantity':r.quantity,'rate':r.market_rate,'amount':r.amount,'exchange':r.exchange} for r in rows]
def charge_rows(db,uid,pid):
    rows=db.scalars(select(ContractNote).where(ContractNote.user_id==uid,ContractNote.portfolio_id==pid).order_by(ContractNote.trade_date)).all(); return [{'trade_date':r.trade_date,'contract_note':r.contract_note,'brokerage':r.displayed_brokerage,'stt':r.stt,'igst':r.igst,'exchange_charges':r.exchange_charges,'sebi_fees':r.sebi_fees,'stamp_duty':r.stamp_duty,'total_non_brokerage':r.stt+r.cgst+r.sgst+r.ugst+r.igst+r.exchange_charges+r.sebi_fees+r.stamp_duty+r.ipft,'net_amount':r.net_amount} for r in rows]
def security_rows(db,uid,pid):
    rows=db.scalars(select(SecurityLedger).where(SecurityLedger.user_id==uid,SecurityLedger.portfolio_id==pid).order_by(SecurityLedger.trade_date)).all(); return [{'trade_date':r.trade_date,'contract_note':r.contract_note,'isin':r.isin,'security':r.security,'buy_qty':r.buy_qty,'sell_qty':r.sell_qty,'buy_after_brokerage':-r.total_buy_value_after_brokerage,'sell_after_brokerage':r.total_sell_value_after_brokerage} for r in rows]
def mapping_rows(db,uid):
    rows=db.scalars(select(InstrumentMapping).where(InstrumentMapping.user_id==uid).order_by(InstrumentMapping.security)).all(); return [{'isin':r.isin,'security':r.security,'provider':'yahoo','instrument_key':r.instrument_key} for r in rows]
def paginated_dataset(model,builder,page,page_size,db,uid,pid):
    page=max(1,page);page_size=min(max(1,page_size),500);q=select(model).where(model.user_id==uid,model.portfolio_id==pid).order_by(model.id);rows,total=paginate(q,db,page,page_size);return {'items':[builder(r) for r in rows],'total':total,'page':page,'page_size':page_size}
@router.get('/tables/contracts')
def contracts(page:int=1,page_size:int=100,portfolio_id:int|None=None,db:Session=Depends(get_db),current_user:User=Depends(get_current_user)): return paginated_dataset(ContractNote,lambda r:{'contract_note':r.contract_note,'trade_date':r.trade_date,'buy_qty':r.buy_qty,'sell_qty':r.sell_qty,'gross_buy_value':r.gross_buy_value,'gross_sell_value':r.gross_sell_value,'brokerage':r.displayed_brokerage,'net_amount':r.net_amount},page,page_size,db,current_user.id,resolve_portfolio(db,current_user.id,portfolio_id))
@router.get('/tables/executions')
def executions(page:int=1,page_size:int=100,portfolio_id:int|None=None,db:Session=Depends(get_db),current_user:User=Depends(get_current_user)): return paginated_dataset(Execution,lambda r:{'contract_note':r.contract_note,'trade_date':r.trade_date,'trade_no':r.trade_no,'security':r.security,'side':r.side,'quantity':r.quantity,'rate':r.market_rate,'amount':r.amount,'exchange':r.exchange},page,page_size,db,current_user.id,resolve_portfolio(db,current_user.id,portfolio_id))
@router.get('/charges')
def charges(page:int=1,page_size:int=100,portfolio_id:int|None=None,db:Session=Depends(get_db),current_user:User=Depends(get_current_user)): return paginated_dataset(ContractNote,lambda r:{'trade_date':r.trade_date,'contract_note':r.contract_note,'brokerage':r.displayed_brokerage,'stt':r.stt,'igst':r.igst,'exchange_charges':r.exchange_charges,'sebi_fees':r.sebi_fees,'stamp_duty':r.stamp_duty,'total_non_brokerage':r.stt+r.cgst+r.sgst+r.ugst+r.igst+r.exchange_charges+r.sebi_fees+r.stamp_duty+r.ipft,'net_amount':r.net_amount},page,page_size,db,current_user.id,resolve_portfolio(db,current_user.id,portfolio_id))
@router.get('/securities')
def securities(page:int=1,page_size:int=100,portfolio_id:int|None=None,db:Session=Depends(get_db),current_user:User=Depends(get_current_user)): return paginated_dataset(SecurityLedger,lambda r:{'trade_date':r.trade_date,'contract_note':r.contract_note,'isin':r.isin,'security':r.security,'buy_qty':r.buy_qty,'sell_qty':r.sell_qty,'buy_after_brokerage':-r.total_buy_value_after_brokerage,'sell_after_brokerage':r.total_sell_value_after_brokerage},page,page_size,db,current_user.id,resolve_portfolio(db,current_user.id,portfolio_id))
@router.get('/instrument-mappings')
def mappings(page:int=1,page_size:int=100,db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    page=max(1,page);page_size=min(max(1,page_size),500);q=select(InstrumentMapping).where(InstrumentMapping.user_id==current_user.id).order_by(InstrumentMapping.security);rows,total=paginate(q,db,page,page_size);return {'items':[{'isin':r.isin,'security':r.security,'provider':'yahoo','instrument_key':r.instrument_key} for r in rows],'total':total,'page':page,'page_size':page_size}
@router.post('/instrument-mappings')
def set_mapping(payload:dict,db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    isin=str(payload.get('isin','')).strip();key=str(payload.get('instrument_key',payload.get('yahoo_symbol',''))).strip();security=str(payload.get('security','')).strip()
    if not isin or not key:raise HTTPException(400,'isin and yahoo_symbol are required')
    row=db.scalar(select(InstrumentMapping).where(InstrumentMapping.user_id==current_user.id,InstrumentMapping.isin==isin,InstrumentMapping.provider=='yahoo'))
    if row:row.instrument_key=key;row.security=security or row.security
    else:db.add(InstrumentMapping(user_id=current_user.id,isin=isin,security=security,provider='yahoo',instrument_key=key))
    db.commit();return {'status':'saved'}
@router.get('/quotes/latest')
def quotes_latest(db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    rows=db.scalars(select(MarketQuote).where(MarketQuote.user_id==current_user.id).order_by(MarketQuote.as_of.desc())).all();latest={}
    for row in rows:latest.setdefault(row.isin,row)
    return [{'isin':r.isin,'provider':r.provider,'symbol':r.symbol,'ltp':r.ltp,'open':r.open,'high':r.high,'low':r.low,'close':r.close,'volume':r.volume,'as_of':r.as_of} for r in latest.values()]
@router.get('/quotes/refresh')
def quotes_refresh(portfolio_id:int|None=None,db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    pid=resolve_portfolio(db,current_user.id,portfolio_id); holdings_data=overview(db,current_user.id,pid)['holdings']; maps={m.isin:m for m in db.scalars(select(InstrumentMapping).where(InstrumentMapping.user_id==current_user.id,InstrumentMapping.provider=='yahoo')).all()}; instruments=[{'isin':h['isin'],'symbol':maps[h['isin']].instrument_key if h['isin'] in maps else None,'security':h.get('security','')} for h in holdings_data]
    if settings.benchmark_isin and settings.benchmark_yahoo_symbol: instruments.append({'isin':settings.benchmark_isin,'symbol':settings.benchmark_yahoo_symbol,'security':'Benchmark'})
    quotes=YahooFinanceProvider().quotes(instruments)
    for quote in quotes:db.add(MarketQuote(user_id=current_user.id,**quote))
    db.commit();return quotes
@router.get('/excel-parity')
def excel_parity(portfolio_id:int|None=None,db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):return build_excel_parity(db,current_user.id,resolve_portfolio(db,current_user.id,portfolio_id))
@router.get('/export/full')
def export_full(portfolio_id:int|None=None,db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    pid=resolve_portfolio(db,current_user.id,portfolio_id);data={'user':user_dict(current_user),'portfolio':{'id':pid},'dashboard':overview(db,current_user.id,pid),'contracts':contract_rows(db,current_user.id,pid),'executions':execution_rows(db,current_user.id,pid),'holdings':overview(db,current_user.id,pid)['holdings'],'realized':overview(db,current_user.id,pid)['realized_trades'],'charges':charge_rows(db,current_user.id,pid),'securities':security_rows(db,current_user.id,pid),'instrument_mappings':mapping_rows(db,current_user.id),'trade_annotations':annotation_rows(db,current_user.id,pid)};return Response(content=json.dumps(data,default=lambda v:v.isoformat() if hasattr(v,'isoformat') else v),media_type='application/json',headers={'Content-Disposition':'attachment; filename="jm-trading-intelligence-export.json"'})
@router.get('/export/{dataset}')
def export_dataset(dataset:str,portfolio_id:int|None=None,db:Session=Depends(get_db),current_user:User=Depends(get_current_user)):
    pid=resolve_portfolio(db,current_user.id,portfolio_id)
    if dataset=='contracts':rows=contract_rows(db,current_user.id,pid)
    elif dataset=='executions':rows=execution_rows(db,current_user.id,pid)
    elif dataset=='realized':rows=overview(db,current_user.id,pid)['realized_trades']
    elif dataset=='holdings':rows=overview(db,current_user.id,pid)['holdings']
    elif dataset=='charges':rows=charge_rows(db,current_user.id,pid)
    elif dataset=='securities':rows=security_rows(db,current_user.id,pid)
    elif dataset=='missing-dates':rows=missing_dates(pid,db,current_user)
    elif dataset=='instrument-mappings':rows=mapping_rows(db,current_user.id)
    else:raise HTTPException(404,'Unknown export dataset')
    norm=[{k:(v.isoformat() if hasattr(v,'isoformat') else v) for k,v in row.items()} for row in rows];return csv_response(norm,f'{dataset}.csv')
@router.websocket('/ws/quotes')
async def quote_socket(websocket:WebSocket):
    await websocket.accept();db=SessionLocal()
    try:
        message=await websocket.receive_json();token=str(message.get('token','')) if isinstance(message,dict) else ''
        if not token:await websocket.send_json({'type':'error','detail':'Authentication required'});await websocket.close(code=4401);return
        payload=decode_token(token,'access');user_id=int(payload['sub']);user=db.get(User,user_id)
        if not user or not user.is_active:await websocket.send_json({'type':'error','detail':'Authentication required'});await websocket.close(code=4401);return
        requested=message.get('portfolio_id') if isinstance(message,dict) else None;pid=resolve_portfolio(db,user_id,int(requested) if requested is not None else None);await websocket.send_json({'type':'ready','portfolio_id':pid})
        import asyncio
        while True:
            try:await asyncio.wait_for(websocket.receive_text(),timeout=settings.quote_refresh_seconds)
            except asyncio.TimeoutError:pass
            current=overview(db,user_id,pid)['holdings'];maps={m.isin:m for m in db.scalars(select(InstrumentMapping).where(InstrumentMapping.user_id==user_id,InstrumentMapping.provider=='yahoo')).all()};instruments=[{'isin':h['isin'],'symbol':maps[h['isin']].instrument_key if h['isin'] in maps else None,'security':h.get('security','')} for h in current];quotes=YahooFinanceProvider().quotes(instruments)
            for quote in quotes:db.add(MarketQuote(user_id=user_id,**quote))
            db.commit();await websocket.send_json({'type':'quotes','count':len(quotes)})
    except Exception:pass
    finally:db.close()
