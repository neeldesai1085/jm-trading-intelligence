from __future__ import annotations
from datetime import datetime,date,timezone,timedelta
from pathlib import Path
from io import StringIO
import csv,hashlib,json,secrets
from fastapi import APIRouter,Depends,File,HTTPException,Query,Request,Response,UploadFile,WebSocket,WebSocketDisconnect,BackgroundTasks
from fastapi.responses import PlainTextResponse,StreamingResponse
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.metrics import render_prometheus
from app.core.rate_limit import rate_limit
from app.db.session import SessionLocal,get_db
from app.models.entities import User,Portfolio,AuthSession,EmailVerificationToken,PasswordResetToken,BrokerConnection,ImportBatch,ImportJob,ContractNote,SecurityLedger,Execution,MarketQuote,InstrumentMapping,TradeAnnotation
from app.services.auth import hash_password,verify_password,create_session,get_current_user,refresh_access_token,revoke_refresh_token,decode_token
from app.services.analytics import overview,realized_by_security,open_holdings,daily_performance,intelligence
from app.services.advanced_analytics import advanced_analytics
from app.services.excel_parity import build_excel_parity
from app.services.importer import import_pdf
from app.services.market_data import get_provider_for_user,refresh_quotes as refresh_market_quotes,latest_quotes as latest_market_quotes
from app.services.portfolios import ensure_default_portfolio,get_user_portfolio,get_user_portfolios
from app.services.storage import store_raw_pdf
from app.services.email import send_email,hash_token,new_token
from app.services.broker_auth import build_upstox_authorize_url,exchange_upstox_code,build_zerodha_login_url,exchange_zerodha_request_token,sign_oauth_state,verify_oauth_state
router=APIRouter()
MAX_FILE_BYTES=25*1024*1024
MAX_FILES_PER_REQUEST=25

def user_dict(u):return {'id':u.id,'email':u.email,'name':u.name,'email_verified':bool(u.email_verified)}
def set_cookie(r,t):r.set_cookie(settings.auth_cookie_name,t,httponly=True,secure=settings.auth_cookie_secure,samesite=settings.auth_cookie_samesite,max_age=settings.auth_refresh_days*86400,path='/api/auth')
def clear_cookie(r):r.delete_cookie(settings.auth_cookie_name,path='/api/auth')
def pid(db,uid,pid):return get_user_portfolio(db,uid,pid).id
def page_rows(q,db,page,size):
 total=db.scalar(select(func.count()).select_from(q.subquery())) or 0
 return db.scalars(q.offset((page-1)*size).limit(size)).all(),total
def rows_json(rows):return [{k:(v.isoformat() if hasattr(v,'isoformat') else v) for k,v in x.items()} for x in rows]
def csv_response(rows,name):
 out=StringIO();
 if rows:
  w=csv.DictWriter(out,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 else:out.write('No records\n')
 return StreamingResponse(iter([out.getvalue()]),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="{name}"'})

def import_one(path,uid,portfolio_id,filename,source_uri=None):
 with SessionLocal() as db:
  try:
   b=import_pdf(db,path,uid,portfolio_id)
   if source_uri and not b.source_uri:b.source_uri=source_uri;db.commit()
   return {'status':b.status,'filename':filename,'contract_notes_found':b.contract_notes_found,'contracts_added':b.contracts_added,'duplicates':b.duplicates,'executions_added':b.executions_added,'security_rows_added':b.security_rows_added,'errors':b.errors.split('; ') if b.errors else []}
  finally:path.unlink(missing_ok=True)
def run_import_job(jid,path,uid,portfolio_id,filename,source_uri):
 with SessionLocal() as db:
  j=db.get(ImportJob,jid)
  if not j:return
  j.status='PROCESSING';j.started_at=datetime.now(timezone.utc).replace(tzinfo=None);db.commit()
  try:r=import_one(path,uid,portfolio_id,filename,source_uri);j.status='COMPLETED';j.result_json=json.dumps(r);j.completed_at=datetime.now(timezone.utc).replace(tzinfo=None);db.commit()
  except Exception as e:
   db.rollback();j=db.get(ImportJob,jid)
   if j:j.status='FAILED';j.error=str(e);j.completed_at=datetime.now(timezone.utc).replace(tzinfo=None);db.commit()

@router.get('/health')
def health():return {'status':'ok','market_provider':settings.market_data_provider}
@router.get('/health/ready')
def readiness(db:Session=Depends(get_db)):
 try:db.execute(select(1));return {'status':'ready'}
 except Exception as e:raise HTTPException(503,'Database is not ready') from e
@router.get('/metrics',include_in_schema=False)
def metrics():return PlainTextResponse(render_prometheus(),media_type='text/plain; version=0.0.4')

@router.post('/auth/register')
def register(request:Request,payload:dict,response:Response,db:Session=Depends(get_db)):
 rate_limit(request,'auth');email=str(payload.get('email','')).strip().lower();password=str(payload.get('password',''));name=str(payload.get('name','')).strip() or email.split('@')[0]
 if not email or '@' not in email or len(email)>320:raise HTTPException(400,'A valid email is required')
 if not 8<=len(password)<=256:raise HTTPException(400,'Password must be 8-256 characters')
 if db.scalar(select(User).where(User.email==email)):raise HTTPException(409,'An account with this email already exists')
 u=User(email=email,name=name[:120],password_hash=hash_password(password),is_active=True,email_verified=False);db.add(u);db.commit();db.refresh(u);p=ensure_default_portfolio(db,u.id);a,r,e=create_session(db,u);set_cookie(response,r)
 return {'access_token':a,'token_type':'bearer','refresh_expires_at':e,'user':user_dict(u),'portfolio':{'id':p.id,'name':p.name}}
@router.post('/auth/login')
def login(request:Request,payload:dict,response:Response,db:Session=Depends(get_db)):
 rate_limit(request,'auth');email=str(payload.get('email','')).strip().lower();u=db.scalar(select(User).where(User.email==email));password=str(payload.get('password',''))
 if not u or not u.is_active or not verify_password(password,u.password_hash):raise HTTPException(401,'Invalid email or password')
 p=ensure_default_portfolio(db,u.id);a,r,e=create_session(db,u);set_cookie(response,r);return {'access_token':a,'token_type':'bearer','refresh_expires_at':e,'user':user_dict(u),'portfolio':{'id':p.id,'name':p.name}}
@router.post('/auth/refresh')
def refresh(request:Request,response:Response,payload:dict|None=None,db:Session=Depends(get_db)):
 rate_limit(request,'auth');d=payload or {};t=str(d.get('refresh_token','')).strip() or request.cookies.get(settings.auth_cookie_name,'')
 if not t:raise HTTPException(400,'refresh_token is required')
 a,r,e=refresh_access_token(db,t);u=db.get(User,int(decode_token(r,'refresh')['sub']));
 if not u or not u.is_active:raise HTTPException(401,'User is not active')
 p=ensure_default_portfolio(db,u.id);set_cookie(response,r);return {'access_token':a,'token_type':'bearer','refresh_expires_at':e,'user':user_dict(u),'portfolio':{'id':p.id,'name':p.name}}
@router.post('/auth/logout')
def logout(request:Request,response:Response,payload:dict|None=None,db:Session=Depends(get_db)):
 d=payload or {};t=str(d.get('refresh_token','')).strip() or request.cookies.get(settings.auth_cookie_name,'');
 if t:revoke_refresh_token(db,t)
 clear_cookie(response);return {'status':'logged_out'}
@router.get('/auth/me')
def me(u:User=Depends(get_current_user)):return {**user_dict(u),'created_at':u.created_at}
@router.patch('/auth/profile')
def profile(payload:dict,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
 name=str(payload.get('name','')).strip()
 if not name or len(name)>120:raise HTTPException(400,'name must be 1-120 characters')
 u.name=name;u.updated_at=datetime.now(timezone.utc).replace(tzinfo=None);db.commit();db.refresh(u);return user_dict(u)
@router.get('/auth/sessions')
def sessions(db:Session=Depends(get_db),u:User=Depends(get_current_user)):return [{'id':x.id,'created_at':x.created_at,'expires_at':x.expires_at} for x in db.scalars(select(AuthSession).where(AuthSession.user_id==u.id,AuthSession.revoked_at.is_(None)).order_by(AuthSession.created_at.desc())).all()]
@router.post('/auth/change-password')
def change_password(payload:dict,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
 old=str(payload.get('current_password',''));new=str(payload.get('new_password',''))
 if not verify_password(old,u.password_hash):raise HTTPException(401,'Current password is incorrect')
 if not 8<=len(new)<=256 or new==old:raise HTTPException(400,'Invalid new password')
 u.password_hash=hash_password(new);now=datetime.now(timezone.utc).replace(tzinfo=None);db.query(AuthSession).filter(AuthSession.user_id==u.id,AuthSession.revoked_at.is_(None)).update({'revoked_at':now},synchronize_session=False);db.commit();return {'status':'password_changed'}
@router.post('/auth/password-reset/request')
def password_reset_request(request:Request,payload:dict,db:Session=Depends(get_db)):
 rate_limit(request,'password-reset');email=str(payload.get('email','')).strip().lower();u=db.scalar(select(User).where(User.email==email));out={'status':'accepted'}
 if u:
  raw=new_token();now=datetime.now(timezone.utc).replace(tzinfo=None);db.query(PasswordResetToken).filter(PasswordResetToken.user_id==u.id,PasswordResetToken.used_at.is_(None)).update({'used_at':now},synchronize_session=False);db.add(PasswordResetToken(user_id=u.id,token_hash=hash_token(raw),expires_at=now+timedelta(minutes=settings.password_reset_minutes)));db.commit();sent=send_email(email,'JM Trading Intelligence password reset',raw);out.update({'email_sent':sent} if settings.app_env.lower()=='production' else {'reset_token':raw,'email_sent':sent})
 return out
@router.post('/auth/password-reset/confirm')
def password_reset_confirm(payload:dict,db:Session=Depends(get_db)):
 t=str(payload.get('token',''));new=str(payload.get('new_password',''));now=datetime.now(timezone.utc).replace(tzinfo=None);r=db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash==hash_token(t),PasswordResetToken.used_at.is_(None),PasswordResetToken.expires_at>now))
 if not r or not 8<=len(new)<=256:raise HTTPException(400,'Reset token is invalid or expired')
 u=db.get(User,r.user_id);u.password_hash=hash_password(new);r.used_at=now;db.query(AuthSession).filter(AuthSession.user_id==u.id,AuthSession.revoked_at.is_(None)).update({'revoked_at':now},synchronize_session=False);db.commit();return {'status':'password_reset'}

@router.get('/auth/verification/request')
def verification_request(request:Request,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
 raw=new_token();now=datetime.now(timezone.utc).replace(tzinfo=None);db.query(EmailVerificationToken).filter(EmailVerificationToken.user_id==u.id,EmailVerificationToken.used_at.is_(None)).update({'used_at':now},synchronize_session=False);db.add(EmailVerificationToken(user_id=u.id,token_hash=hash_token(raw),expires_at=now+timedelta(minutes=settings.password_reset_minutes)));db.commit();sent=send_email(u.email,'JM Trading Intelligence email verification',raw);return {'status':'accepted',**({} if settings.app_env.lower()=='production' else {'verification_token':raw,'email_sent':sent})}
@router.post('/auth/verification/confirm')
def verification_confirm(payload:dict,db:Session=Depends(get_db)):
 now=datetime.now(timezone.utc).replace(tzinfo=None);r=db.scalar(select(EmailVerificationToken).where(EmailVerificationToken.token_hash==hash_token(str(payload.get('token',''))),EmailVerificationToken.used_at.is_(None),EmailVerificationToken.expires_at>now))
 if not r:raise HTTPException(400,'Verification token is invalid or expired')
 u=db.get(User,r.user_id);u.email_verified=True;r.used_at=now;db.commit();return {'status':'verified'}

@router.get('/portfolios')
def portfolios(db:Session=Depends(get_db),u:User=Depends(get_current_user)):
 d=ensure_default_portfolio(db,u.id);return [{'id':p.id,'name':p.name,'is_default':p.id==d.id,'created_at':p.created_at} for p in get_user_portfolios(db,u.id)]
@router.post('/portfolios')
def create_portfolio(payload:dict,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
 name=str(payload.get('name','')).strip()
 if not name or len(name)>120:raise HTTPException(400,'name must be 1-120 characters')
 if db.scalar(select(Portfolio).where(Portfolio.user_id==u.id,Portfolio.name==name)):raise HTTPException(409,'Portfolio already exists')
 p=Portfolio(user_id=u.id,name=name,is_default=False);db.add(p);db.commit();db.refresh(p);return {'id':p.id,'name':p.name,'is_default':False,'created_at':p.created_at}

@router.get('/broker/connections')
def broker_connections(db:Session=Depends(get_db),u:User=Depends(get_current_user)):return [{'id':x.id,'provider':x.provider,'expires_at':x.expires_at,'connected_at':x.connected_at,'updated_at':x.updated_at} for x in db.scalars(select(BrokerConnection).where(BrokerConnection.user_id==u.id)).all()]
@router.get('/broker/upstox/authorize')
def upstox_authorize(u:User=Depends(get_current_user)):
 if not settings.upstox_client_id or not settings.upstox_redirect_uri:raise HTTPException(503,'Upstox OAuth is not configured')
 return {'authorize_url':build_upstox_authorize_url(sign_oauth_state(f'{u.id}:{secrets.token_urlsafe(12)}'))}
@router.get('/broker/upstox/callback')
async def upstox_callback(code:str,state:str,db:Session=Depends(get_db)):
 raw=verify_oauth_state(state)
 if not raw:raise HTTPException(400,'Invalid OAuth state')
 d=await exchange_upstox_code(code);return {'status':'authorized','provider':'upstox','token_type':d.get('token_type')}
@router.get('/broker/zerodha/authorize')
def zerodha_authorize(u:User=Depends(get_current_user)):
 if not settings.zerodha_api_key:return {'status':'not_configured'}
 return {'authorize_url':build_zerodha_login_url(sign_oauth_state(f'{u.id}:{secrets.token_urlsafe(12)}'))}
@router.post('/broker/zerodha/connect')
async def zerodha_connect(payload:dict,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
 if not settings.zerodha_api_key or not settings.zerodha_api_secret:raise HTTPException(503,'Zerodha is not configured')
 d=await exchange_zerodha_request_token(str(payload.get('request_token','')));return {'status':'authorized','provider':'zerodha','token_type':d.get('data',{}).get('login_type')}

@router.post('/imports/upload')
async def upload_contract_notes(request:Request,files:list[UploadFile]=File(...),portfolio_id:int|None=None,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
 if len(files)>MAX_FILES_PER_REQUEST:raise HTTPException(400,'Maximum 25 files per import request')
 p=pid(db,u.id,portfolio_id);out=[];directory=Path(settings.upload_dir);directory.mkdir(parents=True,exist_ok=True)
 for f in files:
  name=Path(f.filename or 'upload.pdf').name
  if not name.lower().endswith('.pdf'):raise HTTPException(400,'Only PDF files are supported')
  data=await f.read()
  if len(data)>MAX_FILE_BYTES:raise HTTPException(413,f'{name} exceeds the 25 MB upload limit')
  if not data.startswith(b'%PDF-'):raise HTTPException(400,f'{name} is not a valid PDF file')
  dest=directory/f'{u.id}_{secrets.token_hex(6)}_{name}';dest.write_bytes(data)
  try:out.append(import_one(dest,u.id,p,name,store_raw_pdf(data,u.id,p,name)))
  except Exception as e:raise HTTPException(422,f'Could not import {name}: {e}') from e
 return out
@router.post('/imports/upload/background')
async def background_upload(files:list[UploadFile]=File(...),background_tasks:BackgroundTasks=None,portfolio_id:int|None=None,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
 p=pid(db,u.id,portfolio_id);directory=Path(settings.upload_dir);directory.mkdir(parents=True,exist_ok=True);out=[]
 for f in files:
  name=Path(f.filename or 'upload.pdf').name;data=await f.read()
  if len(data)>MAX_FILE_BYTES or not data.startswith(b'%PDF-'):raise HTTPException(400,f'{name} is not a valid PDF within the 25 MB limit')
  dest=directory/f'{u.id}_{secrets.token_hex(6)}_{name}';dest.write_bytes(data);j=ImportJob(user_id=u.id,portfolio_id=p,filename=name,status='QUEUED');db.add(j);db.commit();db.refresh(j);background_tasks.add_task(run_import_job,j.id,dest,u.id,p,name,store_raw_pdf(data,u.id,p,name));out.append({'id':j.id,'filename':name,'status':'QUEUED'})
 return out
@router.get('/imports')
def imports(portfolio_id:int|None=None,page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=500),db:Session=Depends(get_db),u:User=Depends(get_current_user)):
 p=pid(db,u.id,portfolio_id);q=select(ImportBatch).where(ImportBatch.user_id==u.id,ImportBatch.portfolio_id==p).order_by(ImportBatch.created_at.desc());r,total=page_rows(q,db,page,page_size);return {'items':[{'id':x.id,'filename':x.filename,'status':x.status,'contracts_added':x.contracts_added,'duplicates':x.duplicates,'executions_added':x.executions_added,'security_rows_added':x.security_rows_added,'created_at':x.created_at} for x in r],'page':page,'page_size':page_size,'total':total}
@router.get('/imports/jobs/{job_id}')
def import_job(job_id:int,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
 j=db.scalar(select(ImportJob).where(ImportJob.id==job_id,ImportJob.user_id==u.id))
 if not j:raise HTTPException(404,'Import job not found')
 return {'id':j.id,'filename':j.filename,'status':j.status,'error':j.error,'result':json.loads(j.result_json) if j.result_json else None,'created_at':j.created_at,'started_at':j.started_at,'completed_at':j.completed_at}

@router.get('/trade-annotations')
def annotations(portfolio_id:int|None=None,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
 p=pid(db,u.id,portfolio_id);r=db.scalars(select(TradeAnnotation).where(TradeAnnotation.user_id==u.id).order_by(TradeAnnotation.sell_date)).all();return {'items':[{'security':x.security,'buy_date':x.buy_date,'sell_date':x.sell_date,'strategy':x.strategy,'setup':x.setup,'regime':x.regime,'note':x.note} for x in r]}
@router.post('/trade-annotations')
def save_annotation(payload:dict,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
 try:s=str(payload.get('security','')).strip();b=date.fromisoformat(str(payload.get('buy_date','')));e=date.fromisoformat(str(payload.get('sell_date','')))
 except Exception as ex:raise HTTPException(400,'security, buy_date and sell_date are required') from ex
 if e<b:raise HTTPException(400,'sell_date cannot be before buy_date')
 vals={'strategy':str(payload.get('strategy','Unclassified')).strip() or 'Unclassified','setup':str(payload.get('setup','')).strip(),'regime':str(payload.get('regime','')).strip(),'note':str(payload.get('note','')).strip() or None};r=db.scalar(select(TradeAnnotation).where(TradeAnnotation.user_id==u.id,TradeAnnotation.security==s,TradeAnnotation.buy_date==b,TradeAnnotation.sell_date==e))
 if r:
  [setattr(r,k,v) for k,v in vals.items()]
 else:db.add(TradeAnnotation(user_id=u.id,security=s,buy_date=b,sell_date=e,**vals))
 db.commit();return {'status':'saved'}

@router.get('/dashboard')
def dashboard(portfolio_id:int|None=None,db:Session=Depends(get_db),u:User=Depends(get_current_user)):return overview(db,u.id,pid(db,u.id,portfolio_id))
@router.get('/intelligence')
def intel(portfolio_id:int|None=None,db:Session=Depends(get_db),u:User=Depends(get_current_user)):return intelligence(db,u.id,pid(db,u.id,portfolio_id))
@router.get('/analytics/advanced')
def advanced(portfolio_id:int|None=None,db:Session=Depends(get_db),u:User=Depends(get_current_user)):return advanced_analytics(db,u.id,pid(db,u.id,portfolio_id))
@router.get('/risk')
def risk(portfolio_id:int|None=None,db:Session=Depends(get_db),u:User=Depends(get_current_user)):return overview(db,u.id,pid(db,u.id,portfolio_id)).get('risk',{})
@router.get('/performance/daily')
def performance(portfolio_id:int|None=None,db:Session=Depends(get_db),u:User=Depends(get_current_user)):return overview(db,u.id,pid(db,u.id,portfolio_id)).get('daily_pnl',[])
@router.get('/holdings')
def holdings(portfolio_id:int|None=None,db:Session=Depends(get_db),u:User=Depends(get_current_user)):return overview(db,u.id,pid(db,u.id,portfolio_id)).get('holdings',[])
@router.get('/realized')
def realized(portfolio_id:int|None=None,db:Session=Depends(get_db),u:User=Depends(get_current_user)):return overview(db,u.id,pid(db,u.id,portfolio_id)).get('realized_trades',[])
@router.get('/missing-dates')
def missing_dates(portfolio_id:int|None=None,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
 p=pid(db,u.id,portfolio_id);dates=set(db.scalars(select(ContractNote.trade_date).where(ContractNote.user_id==u.id,ContractNote.portfolio_id==p)).all())
 if not dates:return []
 out=[];d=min(dates);end=max(dates)
 while d<=end:
  if d.weekday()<5 and d not in dates:out.append({'date':d,'status':'NO CONTRACT NOTE'})
  d+=timedelta(days=1)
 return out

def contract_rows(db,uid,p):return [{'contract_note':x.contract_note,'trade_date':x.trade_date,'buy_qty':x.buy_qty,'sell_qty':x.sell_qty,'gross_buy_value':x.gross_buy_value,'gross_sell_value':x.gross_sell_value,'brokerage':x.displayed_brokerage,'net_amount':x.net_amount} for x in db.scalars(select(ContractNote).where(ContractNote.user_id==uid,ContractNote.portfolio_id==p).order_by(ContractNote.trade_date)).all()]
def execution_rows(db,uid,p):return [{'contract_note':x.contract_note,'trade_date':x.trade_date,'trade_no':x.trade_no,'security':x.security,'side':x.side,'quantity':x.quantity,'rate':x.market_rate,'amount':x.amount,'exchange':x.exchange} for x in db.scalars(select(Execution).where(Execution.user_id==uid,Execution.portfolio_id==p).order_by(Execution.trade_date,Execution.id)).all()]
def security_rows(db,uid,p):return [{'trade_date':x.trade_date,'contract_note':x.contract_note,'isin':x.isin,'security':x.security,'buy_qty':x.buy_qty,'sell_qty':x.sell_qty,'buy_after_brokerage':-x.total_buy_value_after_brokerage,'sell_after_brokerage':x.total_sell_value_after_brokerage} for x in db.scalars(select(SecurityLedger).where(SecurityLedger.user_id==uid,SecurityLedger.portfolio_id==p).order_by(SecurityLedger.trade_date)).all()]
def charge_rows(db,uid,p):return [{'trade_date':x.trade_date,'contract_note':x.contract_note,'brokerage':x.displayed_brokerage,'stt':x.stt,'igst':x.igst,'exchange_charges':x.exchange_charges,'sebi_fees':x.sebi_fees,'stamp_duty':x.stamp_duty,'total_non_brokerage':x.stt+x.cgst+x.sgst+x.ugst+x.igst+x.exchange_charges+x.sebi_fees+x.stamp_duty+x.ipft,'net_amount':x.net_amount} for x in db.scalars(select(ContractNote).where(ContractNote.user_id==uid,ContractNote.portfolio_id==p).order_by(ContractNote.trade_date)).all()]
def mapping_rows(db,uid):return [{'isin':x.isin,'security':x.security,'provider':x.provider,'instrument_key':x.instrument_key} for x in db.scalars(select(InstrumentMapping).where(InstrumentMapping.user_id==uid).order_by(InstrumentMapping.security)).all()]
@router.get('/tables/contracts')
def contracts(portfolio_id:int|None=None,page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=500),db:Session=Depends(get_db),u:User=Depends(get_current_user)):
 p=pid(db,u.id,portfolio_id);q=select(ContractNote).where(ContractNote.user_id==u.id,ContractNote.portfolio_id==p).order_by(ContractNote.trade_date);r,t=page_rows(q,db,page,page_size);return {'items':[{'contract_note':x.contract_note,'trade_date':x.trade_date,'buy_qty':x.buy_qty,'sell_qty':x.sell_qty,'gross_buy_value':x.gross_buy_value,'gross_sell_value':x.gross_sell_value,'brokerage':x.displayed_brokerage,'net_amount':x.net_amount} for x in r],'page':page,'page_size':page_size,'total':t}
@router.get('/tables/executions')
def executions(portfolio_id:int|None=None,page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=500),db:Session=Depends(get_db),u:User=Depends(get_current_user)):
 p=pid(db,u.id,portfolio_id);q=select(Execution).where(Execution.user_id==u.id,Execution.portfolio_id==p).order_by(Execution.trade_date,Execution.id);r,t=page_rows(q,db,page,page_size);return {'items':[{'contract_note':x.contract_note,'trade_date':x.trade_date,'trade_no':x.trade_no,'security':x.security,'side':x.side,'quantity':x.quantity,'rate':x.market_rate,'amount':x.amount,'exchange':x.exchange} for x in r],'page':page,'page_size':page_size,'total':t}
@router.get('/charges')
def charges(portfolio_id:int|None=None,page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=500),db:Session=Depends(get_db),u:User=Depends(get_current_user)):
 p=pid(db,u.id,portfolio_id);q=select(ContractNote).where(ContractNote.user_id==u.id,ContractNote.portfolio_id==p).order_by(ContractNote.trade_date);r,t=page_rows(q,db,page,page_size);return {'items':charge_rows(db,u.id,p)[(page-1)*page_size:page*page_size],'page':page,'page_size':page_size,'total':t}
@router.get('/securities')
def securities(portfolio_id:int|None=None,page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=500),db:Session=Depends(get_db),u:User=Depends(get_current_user)):
 p=pid(db,u.id,portfolio_id);q=select(SecurityLedger).where(SecurityLedger.user_id==u.id,SecurityLedger.portfolio_id==p).order_by(SecurityLedger.trade_date);r,t=page_rows(q,db,page,page_size);return {'items':[{'trade_date':x.trade_date,'contract_note':x.contract_note,'isin':x.isin,'security':x.security,'buy_qty':x.buy_qty,'sell_qty':x.sell_qty,'buy_after_brokerage':-x.total_buy_value_after_brokerage,'sell_after_brokerage':x.total_sell_value_after_brokerage} for x in r],'page':page,'page_size':page_size,'total':t}
@router.get('/instrument-mappings')
def mappings(page:int=Query(1,ge=1),page_size:int=Query(50,ge=1,le=500),db:Session=Depends(get_db),u:User=Depends(get_current_user)):
 q=select(InstrumentMapping).where(InstrumentMapping.user_id==u.id).order_by(InstrumentMapping.security);r,t=page_rows(q,db,page,page_size);return {'items':[{'isin':x.isin,'security':x.security,'provider':x.provider,'instrument_key':x.instrument_key} for x in r],'page':page,'page_size':page_size,'total':t}
@router.post('/instrument-mappings')
def set_mapping(payload:dict,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
 isin=str(payload.get('isin','')).strip();provider=str(payload.get('provider','')).strip();key=str(payload.get('instrument_key','')).strip();sec=str(payload.get('security','')).strip()
 if not isin or not provider or not key:raise HTTPException(400,'isin, provider and instrument_key are required')
 x=db.scalar(select(InstrumentMapping).where(InstrumentMapping.user_id==u.id,InstrumentMapping.isin==isin,InstrumentMapping.provider==provider))
 if x:x.instrument_key=key;x.security=sec or x.security
 else:db.add(InstrumentMapping(user_id=u.id,isin=isin,security=sec,provider=provider,instrument_key=key))
 db.commit();return {'status':'saved'}
@router.get('/quotes/latest')
def quotes_latest(portfolio_id:int|None=None,db:Session=Depends(get_db),u:User=Depends(get_current_user)):return latest_market_quotes(db,u.id,pid(db,u.id,portfolio_id))
@router.get('/quotes/refresh')
def quotes_refresh(portfolio_id:int|None=None,db:Session=Depends(get_db),u:User=Depends(get_current_user)):return refresh_market_quotes(db,u.id,pid(db,u.id,portfolio_id))
@router.get('/excel-parity')
def excel_parity(portfolio_id:int|None=None,db:Session=Depends(get_db),u:User=Depends(get_current_user)):return build_excel_parity(db,u.id,pid(db,u.id,portfolio_id))
@router.get('/export/full')
def export_full(portfolio_id:int|None=None,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
 p=pid(db,u.id,portfolio_id);data={'user':user_dict(u),'portfolio':{'id':p},'dashboard':overview(db,u.id,p),'contracts':contract_rows(db,u.id,p),'executions':execution_rows(db,u.id,p),'holdings':overview(db,u.id,p).get('holdings',[]),'realized':overview(db,u.id,p).get('realized_trades',[]),'charges':charge_rows(db,u.id,p),'securities':security_rows(db,u.id,p),'instrument_mappings':mapping_rows(db,u.id)};return Response(content=json.dumps(data,default=lambda v:v.isoformat() if hasattr(v,'isoformat') else v),media_type='application/json')
@router.get('/export/{dataset}')
def export_dataset(dataset:str,portfolio_id:int|None=None,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
 p=pid(db,u.id,portfolio_id)
 if dataset=='contracts':r=contract_rows(db,u.id,p)
 elif dataset=='executions':r=execution_rows(db,u.id,p)
 elif dataset=='realized':r=overview(db,u.id,p).get('realized_trades',[])
 elif dataset=='holdings':r=overview(db,u.id,p).get('holdings',[])
 elif dataset=='charges':r=charge_rows(db,u.id,p)
 elif dataset=='securities':r=security_rows(db,u.id,p)
 elif dataset=='instrument-mappings':r=mapping_rows(db,u.id)
 else:raise HTTPException(404,'Unknown export dataset')
 return csv_response(rows_json(r),f'{dataset}.csv')

@router.websocket('/ws/quotes')
async def websocket_quotes(websocket:WebSocket):
 await websocket.accept();db=SessionLocal()
 try:
  token=websocket.query_params.get('access_token','');p=decode_token(token,'access');u=db.get(User,int(p['sub']))
  if not u:await websocket.close(code=4401);return
  await websocket.send_json({'type':'ready'})
  while True:
   try:await websocket.receive_text()
   except WebSocketDisconnect:break
   await websocket.send_json({'type':'quotes','count':0})
 except Exception:
  await websocket.close(code=4401)
 finally:db.close()
