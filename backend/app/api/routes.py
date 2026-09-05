from datetime import datetime, timedelta, timezone
from pathlib import Path
from io import StringIO
import csv, json, secrets
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.session import get_db, SessionLocal
from app.models.entities import User, AuthSession, ImportBatch, ContractNote, Execution, SecurityLedger, MarketQuote, InstrumentMapping, TradeAnnotation
from app.services.auth import get_current_user, hash_password, verify_password, create_session, refresh_access_token, revoke_refresh_token, decode_token
from app.services.importer import import_pdf
from app.services.analytics import overview, intelligence
from app.services.excel_parity import build_excel_parity
from app.services.market_data import MockProvider, UpstoxProvider, ZerodhaProvider
from app.services.advanced_analytics import advanced
from app.core.config import settings
router=APIRouter()

def provider():
    p=settings.market_data_provider.lower()
    if p=='upstox' and settings.upstox_access_token:return UpstoxProvider(settings.upstox_access_token)
    if p=='zerodha' and settings.zerodha_api_key and settings.zerodha_access_token:return ZerodhaProvider(settings.zerodha_api_key,settings.zerodha_access_token)
    return MockProvider()

def clean_email(v):
    e=str(v).strip().lower()
    if not e or '@' not in e or len(e)>320:raise HTTPException(400,'A valid email is required')
    return e

def user_dict(u):return {'id':u.id,'email':u.email,'name':u.name}

def csv_response(rows,filename):
    out=StringIO()
    if rows:
        w=csv.DictWriter(out,fieldnames=list(rows[0].keys()));w.writeheader();w.writerows(rows)
    else:out.write('No records\n')
    out.seek(0);return StreamingResponse(iter([out.getvalue()]),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="{filename}"'})

@router.get('/health')
def health():return {'status':'ok','market_provider':settings.market_data_provider}

@router.post('/auth/register')
def register(payload:dict,db:Session=Depends(get_db)):
    email=clean_email(payload.get('email','')); password=str(payload.get('password','')); name=str(payload.get('name','')).strip() or email.split('@')[0]
    if not 8<=len(password)<=256:raise HTTPException(400,'Password must be 8-256 characters')
    if db.scalar(select(User).where(User.email==email)):raise HTTPException(409,'An account with this email already exists')
    u=User(email=email,name=name[:120],password_hash=hash_password(password),is_active=True);db.add(u);db.commit();db.refresh(u);a,r,e=create_session(db,u)
    return {'access_token':a,'refresh_token':r,'token_type':'bearer','refresh_expires_at':e,'user':user_dict(u)}

@router.post('/auth/login')
def login(payload:dict,db:Session=Depends(get_db)):
    u=db.scalar(select(User).where(User.email==clean_email(payload.get('email',''))));password=str(payload.get('password',''))
    if not u or not u.is_active or not verify_password(password,u.password_hash):raise HTTPException(401,'Invalid email or password')
    a,r,e=create_session(db,u);return {'access_token':a,'refresh_token':r,'token_type':'bearer','refresh_expires_at':e,'user':user_dict(u)}

@router.post('/auth/refresh')
def refresh(payload:dict,db:Session=Depends(get_db)):
    token=str(payload.get('refresh_token','')).strip()
    if not token:raise HTTPException(400,'refresh_token is required')
    a,r,e=refresh_access_token(db,token);u=db.get(User,int(decode_token(r,'refresh')['sub']));return {'access_token':a,'refresh_token':r,'token_type':'bearer','refresh_expires_at':e,'user':user_dict(u)}

@router.post('/auth/logout')
def logout(payload:dict,db:Session=Depends(get_db)):revoke_refresh_token(db,str(payload.get('refresh_token','')));return {'status':'logged_out'}

@router.get('/auth/me')
def me(u:User=Depends(get_current_user)):return {**user_dict(u),'created_at':u.created_at}

@router.get('/auth/sessions')
def sessions(db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    return [{'id':x.id,'created_at':x.created_at,'expires_at':x.expires_at} for x in db.scalars(select(AuthSession).where(AuthSession.user_id==u.id,AuthSession.revoked_at.is_(None)).order_by(AuthSession.created_at.desc())).all()]

@router.post('/auth/change-password')
def change_password(payload:dict,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    old=str(payload.get('current_password',''));new=str(payload.get('new_password',''))
    if not verify_password(old,u.password_hash):raise HTTPException(401,'Current password is incorrect')
    if not 8<=len(new)<=256:raise HTTPException(400,'New password must be 8-256 characters')
    if new==old:raise HTTPException(400,'New password must be different from the current password')
    u.password_hash=hash_password(new);now=datetime.now(timezone.utc).replace(tzinfo=None);db.query(AuthSession).filter(AuthSession.user_id==u.id,AuthSession.revoked_at.is_(None)).update({'revoked_at':now},synchronize_session=False);db.commit();return {'status':'password_changed'}

@router.post('/imports/upload')
async def upload_contract_notes(files:list[UploadFile]=File(...),db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    if len(files)>25:raise HTTPException(400,'Maximum 25 files per import request')
    out=[];directory=Path(settings.upload_dir);directory.mkdir(parents=True,exist_ok=True)
    for f in files:
        filename=Path(f.filename or 'upload.pdf').name
        if not filename.lower().endswith('.pdf'):raise HTTPException(400,'Only PDF files are supported')
        content=await f.read()
        if len(content)>25*1024*1024:raise HTTPException(413,f'{filename} exceeds the 25 MB upload limit')
        if not content.startswith(b'%PDF'):raise HTTPException(400,f'{filename} is not a valid PDF file')
        dest=directory/f'{u.id}_{secrets.token_hex(6)}_{filename}';dest.write_bytes(content)
        try:b=import_pdf(db,dest,u.id)
        except Exception as exc:db.rollback();raise HTTPException(422,f'Could not import {filename}: {exc}') from exc
        finally:dest.unlink(missing_ok=True)
        out.append({'status':b.status,'filename':filename,'contract_notes_found':b.contract_notes_found,'contracts_added':b.contracts_added,'duplicates':b.duplicates,'executions_added':b.executions_added,'security_rows_added':b.security_rows_added,'errors':b.errors.split('; ') if b.errors else []})
    return out

@router.get('/imports')
def imports(db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    rows=db.scalars(select(ImportBatch).where(ImportBatch.user_id==u.id).order_by(ImportBatch.created_at.desc())).all();return [{'id':r.id,'filename':r.filename,'status':r.status,'contracts_added':r.contracts_added,'duplicates':r.duplicates,'executions_added':r.executions_added,'security_rows_added':r.security_rows_added,'created_at':r.created_at} for r in rows]

@router.get('/dashboard')
def dashboard(db:Session=Depends(get_db),u:User=Depends(get_current_user)):return overview(db,u.id)
@router.get('/intelligence')
def intel(db:Session=Depends(get_db),u:User=Depends(get_current_user)):return intelligence(db,u.id)
@router.get('/analytics/advanced')
def advanced_analytics(db:Session=Depends(get_db),u:User=Depends(get_current_user)):return advanced(db,u.id)
@router.get('/risk')
def risk(db:Session=Depends(get_db),u:User=Depends(get_current_user)):return overview(db,u.id)['risk']
@router.get('/performance/daily')
def performance_daily(db:Session=Depends(get_db),u:User=Depends(get_current_user)):return overview(db,u.id)['daily_pnl']
@router.get('/holdings')
def holdings(db:Session=Depends(get_db),u:User=Depends(get_current_user)):return overview(db,u.id)['holdings']
@router.get('/realized')
def realized(db:Session=Depends(get_db),u:User=Depends(get_current_user)):return overview(db,u.id)['realized_trades']

@router.get('/missing-dates')
def missing_dates(db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    dates=set(db.scalars(select(ContractNote.trade_date).where(ContractNote.user_id==u.id)).all())
    if not dates:return []
    out=[];d=min(dates);end=max(dates)
    while d<=end:
        if d.weekday()<5 and d not in dates:out.append({'date':d,'status':'NO CONTRACT NOTE'})
        d+=timedelta(days=1)
    return out

@router.get('/tables/contracts')
def contracts(db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    rows=db.scalars(select(ContractNote).where(ContractNote.user_id==u.id).order_by(ContractNote.trade_date)).all();return [{'contract_note':r.contract_note,'trade_date':r.trade_date,'buy_qty':r.buy_qty,'sell_qty':r.sell_qty,'gross_buy_value':r.gross_buy_value,'gross_sell_value':r.gross_sell_value,'brokerage':r.displayed_brokerage,'net_amount':r.net_amount} for r in rows]

@router.get('/tables/executions')
def executions(db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    rows=db.scalars(select(Execution).where(Execution.user_id==u.id).order_by(Execution.trade_date,Execution.trade_time)).all();return [{'contract_note':r.contract_note,'trade_date':r.trade_date,'trade_no':r.trade_no,'security':r.security,'side':r.side,'quantity':r.quantity,'rate':r.market_rate,'amount':r.amount,'exchange':r.exchange} for r in rows]

@router.get('/charges')
def charges(db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    rows=db.scalars(select(ContractNote).where(ContractNote.user_id==u.id).order_by(ContractNote.trade_date)).all();return [{'trade_date':r.trade_date,'contract_note':r.contract_note,'brokerage':r.displayed_brokerage,'stt':r.stt,'igst':r.igst,'exchange_charges':r.exchange_charges,'sebi_fees':r.sebi_fees,'stamp_duty':r.stamp_duty,'total_non_brokerage':r.stt+r.cgst+r.sgst+r.ugst+r.igst+r.exchange_charges+r.sebi_fees+r.stamp_duty+r.ipft,'net_amount':r.net_amount} for r in rows]

@router.get('/securities')
def securities(db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    rows=db.scalars(select(SecurityLedger).where(SecurityLedger.user_id==u.id).order_by(SecurityLedger.trade_date)).all();return [{'trade_date':r.trade_date,'contract_note':r.contract_note,'isin':r.isin,'security':r.security,'buy_qty':r.buy_qty,'sell_qty':r.sell_qty,'buy_after_brokerage':-r.total_buy_value_after_brokerage,'sell_after_brokerage':r.total_sell_value_after_brokerage} for r in rows]

@router.get('/instrument-mappings')
def mappings(db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    rows=db.scalars(select(InstrumentMapping).where(InstrumentMapping.user_id==u.id).order_by(InstrumentMapping.security)).all();return [{'isin':r.isin,'security':r.security,'provider':r.provider,'instrument_key':r.instrument_key} for r in rows]

@router.post('/instrument-mappings')
def set_mapping(payload:dict,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    isin=str(payload.get('isin','')).strip();pn=str(payload.get('provider','')).strip();key=str(payload.get('instrument_key','')).strip();sec=str(payload.get('security','')).strip()
    if not isin or not pn or not key:raise HTTPException(400,'isin, provider and instrument_key are required')
    row=db.scalar(select(InstrumentMapping).where(InstrumentMapping.user_id==u.id,InstrumentMapping.isin==isin,InstrumentMapping.provider==pn))
    if row:row.instrument_key=key;row.security=sec or row.security
    else:db.add(InstrumentMapping(user_id=u.id,isin=isin,provider=pn,instrument_key=key,security=sec))
    db.commit();return {'status':'saved'}

@router.get('/quotes/latest')
def latest_quotes(db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    rows=db.scalars(select(MarketQuote).where(MarketQuote.user_id==u.id).order_by(MarketQuote.as_of.desc())).all();latest={}
    for q in rows:latest.setdefault(q.isin,q)
    return [{'isin':q.isin,'provider':q.provider,'symbol':q.symbol,'ltp':q.ltp,'open':q.open,'high':q.high,'low':q.low,'close':q.close,'volume':q.volume,'as_of':q.as_of} for q in latest.values()]

@router.get('/quotes/refresh')
async def refresh_quotes(db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    h=overview(db,u.id)['holdings'];p=provider();maps={m.isin:m for m in db.scalars(select(InstrumentMapping).where(InstrumentMapping.user_id==u.id,InstrumentMapping.provider==p.name)).all()};ins=[{'isin':x['isin'],'symbol':maps[x['isin']].instrument_key if x['isin'] in maps else None} for x in h]
    if settings.benchmark_isin and settings.benchmark_instrument_key:ins.append({'isin':settings.benchmark_isin,'symbol':settings.benchmark_instrument_key})
    qs=await p.quotes(ins)
    for q in qs:db.add(MarketQuote(user_id=u.id,**q))
    db.commit();return qs

@router.get('/trade-annotations')
def trade_annotations(db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    rows=db.scalars(select(TradeAnnotation).where(TradeAnnotation.user_id==u.id).order_by(TradeAnnotation.sell_date)).all();return [{'security':r.security,'buy_date':r.buy_date,'sell_date':r.sell_date,'strategy':r.strategy,'setup':r.setup,'regime':r.regime,'note':r.note} for r in rows]

@router.post('/trade-annotations')
def save_trade_annotation(payload:dict,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    from datetime import date
    try:security=str(payload.get('security','')).strip();buy=date.fromisoformat(str(payload.get('buy_date','')));sell=date.fromisoformat(str(payload.get('sell_date','')))
    except Exception as exc:raise HTTPException(400,'security, buy_date and sell_date are required') from exc
    if sell<buy:raise HTTPException(400,'sell_date cannot be before buy_date')
    values={'strategy':str(payload.get('strategy','Unclassified')).strip() or 'Unclassified','setup':str(payload.get('setup','')).strip(),'regime':str(payload.get('regime','')).strip(),'note':str(payload.get('note','')).strip() or None}
    row=db.scalar(select(TradeAnnotation).where(TradeAnnotation.user_id==u.id,TradeAnnotation.security==security,TradeAnnotation.buy_date==buy,TradeAnnotation.sell_date==sell))
    if row:
        for k,v in values.items():setattr(row,k,v)
    else:db.add(TradeAnnotation(user_id=u.id,security=security,buy_date=buy,sell_date=sell,**values))
    db.commit();return {'status':'saved'}

@router.get('/excel-parity')
def excel_parity(db:Session=Depends(get_db),u:User=Depends(get_current_user)):return build_excel_parity(db,u.id)

@router.get('/export/full')
def export_full(db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    data={'user':user_dict(u),'dashboard':overview(db,u.id),'contracts':contracts(db,u),'executions':executions(db,u),'holdings':holdings(db,u),'realized':realized(db,u),'charges':charges(db,u),'securities':securities(db,u),'instrument_mappings':mappings(db,u),'trade_annotations':trade_annotations(db,u)}
    return Response(content=json.dumps(data,default=lambda x:x.isoformat() if hasattr(x,'isoformat') else x),media_type='application/json',headers={'Content-Disposition':'attachment; filename="jm-trading-intelligence-export.json"'})

@router.get('/export/{dataset}')
def export_dataset(dataset:str,db:Session=Depends(get_db),u:User=Depends(get_current_user)):
    if dataset=='contracts':rows=contracts(db,u)
    elif dataset=='executions':rows=executions(db,u)
    elif dataset=='realized':rows=realized(db,u)
    elif dataset=='holdings':rows=holdings(db,u)
    elif dataset=='charges':rows=charges(db,u)
    elif dataset=='securities':rows=securities(db,u)
    elif dataset=='missing-dates':rows=missing_dates(db,u)
    elif dataset=='instrument-mappings':rows=mappings(db,u)
    else:raise HTTPException(404,'Unknown export dataset')
    return csv_response([{k:(v.isoformat() if hasattr(v,'isoformat') else v) for k,v in row.items()} for row in rows],f'{dataset}.csv')

@router.websocket('/ws/quotes')
async def quote_socket(websocket:WebSocket):
    await websocket.accept();db=SessionLocal()
    try:
        message=await websocket.receive_json();token=str(message.get('token','')) if isinstance(message,dict) else ''
        if not token:await websocket.close(code=4401);return
        payload=decode_token(token,'access');uid=int(payload['sub']);u=db.get(User,uid)
        if not u or not u.is_active:await websocket.close(code=4401);return
        await websocket.send_json({'type':'ready'})
        import asyncio
        while True:
            try:await asyncio.wait_for(websocket.receive_text(),timeout=settings.quote_refresh_seconds)
            except asyncio.TimeoutError:pass
            h=overview(db,uid)['holdings'];p=provider();maps={m.isin:m for m in db.scalars(select(InstrumentMapping).where(InstrumentMapping.user_id==uid,InstrumentMapping.provider==p.name)).all()};ins=[{'isin':x['isin'],'symbol':maps[x['isin']].instrument_key if x['isin'] in maps else None} for x in h];qs=await p.quotes(ins)
            for q in qs:db.add(MarketQuote(user_id=uid,**q))
            if qs:db.commit()
            await websocket.send_json({'type':'quotes','count':len(qs)})
    except WebSocketDisconnect:pass
    except Exception:pass
    finally:db.close()
