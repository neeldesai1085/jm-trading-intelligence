from datetime import timedelta
from io import StringIO
import csv, asyncio
from pathlib import Path
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.session import get_db, SessionLocal
from app.models.entities import ImportBatch, ContractNote, Execution, SecurityLedger, MarketQuote, InstrumentMapping
from app.services.importer import import_pdf
from app.services.analytics import overview, intelligence
from app.services.excel_parity import build_excel_parity
from app.services.market_data import MockProvider, UpstoxProvider, ZerodhaProvider
from app.core.config import settings
router=APIRouter()
def provider():
    p=settings.market_data_provider.lower()
    if p=='upstox' and settings.upstox_access_token:return UpstoxProvider(settings.upstox_access_token)
    if p=='zerodha' and settings.zerodha_api_key and settings.zerodha_access_token:return ZerodhaProvider(settings.zerodha_api_key,settings.zerodha_access_token)
    return MockProvider()
@router.get('/health')
def health():return {'status':'ok','market_provider':settings.market_data_provider}
@router.post('/imports/upload')
async def upload_contract_notes(files:list[UploadFile]=File(...),db:Session=Depends(get_db)):
    out=[]; upload_dir=Path(settings.upload_dir); upload_dir.mkdir(parents=True,exist_ok=True)
    for f in files:
        if not f.filename.lower().endswith('.pdf'):raise HTTPException(400,'Only PDF files are supported')
        dest=upload_dir/f.filename; dest.write_bytes(await f.read()); b=import_pdf(db,dest)
        out.append({'status':b.status,'filename':b.filename,'contract_notes_found':b.contract_notes_found,'contracts_added':b.contracts_added,'duplicates':b.duplicates,'executions_added':b.executions_added,'security_rows_added':b.security_rows_added,'errors':b.errors.split('; ') if b.errors else []})
    return out
@router.get('/imports')
def imports(db:Session=Depends(get_db)):
    rows=db.scalars(select(ImportBatch).order_by(ImportBatch.created_at.desc())).all(); return [{'id':r.id,'filename':r.filename,'status':r.status,'contracts_added':r.contracts_added,'duplicates':r.duplicates,'executions_added':r.executions_added,'security_rows_added':r.security_rows_added,'created_at':r.created_at} for r in rows]
@router.get('/dashboard')
def dashboard(db:Session=Depends(get_db)):return overview(db)
@router.get('/intelligence')
def intel(db:Session=Depends(get_db)):return intelligence(db)
@router.get('/excel-parity')
def excel_parity(db:Session=Depends(get_db)):return build_excel_parity(db)
@router.get('/risk')
def risk(db:Session=Depends(get_db)):return overview(db)['risk']
@router.get('/performance/daily')
def performance_daily(db:Session=Depends(get_db)):return overview(db)['daily_pnl']
@router.get('/holdings')
def holdings(db:Session=Depends(get_db)):return overview(db)['holdings']
@router.get('/realized')
def realized(db:Session=Depends(get_db)):return overview(db)['realized_trades']
@router.get('/missing-dates')
def missing_dates(db:Session=Depends(get_db)):
    dates={n.trade_date for n in db.scalars(select(ContractNote)).all()}
    if not dates:return []
    start,end=min(dates),max(dates); out=[]; d=start
    while d<=end:
        if d.weekday()<5 and d not in dates:out.append({'date':d,'status':'NO CONTRACT NOTE'})
        d+=timedelta(days=1)
    return out
@router.get('/tables/contracts')
def contracts(db:Session=Depends(get_db)):
    rows=db.scalars(select(ContractNote).order_by(ContractNote.trade_date)).all(); return [{'contract_note':r.contract_note,'trade_date':r.trade_date,'buy_qty':r.buy_qty,'sell_qty':r.sell_qty,'gross_buy_value':r.gross_buy_value,'gross_sell_value':r.gross_sell_value,'brokerage':r.displayed_brokerage,'net_amount':r.net_amount} for r in rows]
@router.get('/tables/executions')
def executions(db:Session=Depends(get_db)):
    rows=db.scalars(select(Execution).order_by(Execution.trade_date,Execution.trade_time)).all(); return [{'contract_note':r.contract_note,'trade_date':r.trade_date,'trade_no':r.trade_no,'security':r.security,'side':r.side,'quantity':r.quantity,'rate':r.market_rate,'amount':r.amount,'exchange':r.exchange} for r in rows]
@router.get('/charges')
def charges(db:Session=Depends(get_db)):
    rows=db.scalars(select(ContractNote).order_by(ContractNote.trade_date)).all(); return [{'trade_date':r.trade_date,'contract_note':r.contract_note,'brokerage':r.displayed_brokerage,'stt':r.stt,'igst':r.igst,'exchange_charges':r.exchange_charges,'sebi_fees':r.sebi_fees,'stamp_duty':r.stamp_duty,'total_non_brokerage':r.stt+r.cgst+r.sgst+r.ugst+r.igst+r.exchange_charges+r.sebi_fees+r.stamp_duty+r.ipft,'net_amount':r.net_amount} for r in rows]
@router.get('/securities')
def securities(db:Session=Depends(get_db)):
    rows=db.scalars(select(SecurityLedger).order_by(SecurityLedger.trade_date)).all(); return [{'trade_date':r.trade_date,'contract_note':r.contract_note,'isin':r.isin,'security':r.security,'buy_qty':r.buy_qty,'sell_qty':r.sell_qty,'buy_after_brokerage':-r.total_buy_value_after_brokerage,'sell_after_brokerage':r.total_sell_value_after_brokerage} for r in rows]
@router.get('/instrument-mappings')
def mappings(db:Session=Depends(get_db)):
    rows=db.scalars(select(InstrumentMapping).order_by(InstrumentMapping.security)).all(); return [{'isin':r.isin,'security':r.security,'provider':r.provider,'instrument_key':r.instrument_key} for r in rows]
@router.post('/instrument-mappings')
def set_mapping(payload:dict,db:Session=Depends(get_db)):
    isin=str(payload.get('isin','')).strip(); pn=str(payload.get('provider','')).strip(); key=str(payload.get('instrument_key','')).strip(); sec=str(payload.get('security','')).strip()
    if not isin or not pn or not key:raise HTTPException(400,'isin, provider and instrument_key are required')
    row=db.scalar(select(InstrumentMapping).where(InstrumentMapping.isin==isin))
    if row:row.provider=pn;row.instrument_key=key;row.security=sec or row.security
    else:db.add(InstrumentMapping(isin=isin,provider=pn,instrument_key=key,security=sec))
    db.commit();return {'status':'saved'}
@router.get('/quotes/latest')
def latest_quotes(db:Session=Depends(get_db)):
    rows=db.scalars(select(MarketQuote).order_by(MarketQuote.as_of.desc())).all(); latest={}
    for q in rows:latest.setdefault(q.isin,q)
    return [{'isin':q.isin,'provider':q.provider,'symbol':q.symbol,'ltp':q.ltp,'open':q.open,'high':q.high,'low':q.low,'close':q.close,'volume':q.volume,'as_of':q.as_of} for q in latest.values()]
@router.get('/quotes/refresh')
async def refresh_quotes(db:Session=Depends(get_db)):
    h=overview(db)['holdings'];p=provider();m={x.isin:x for x in db.scalars(select(InstrumentMapping).where(InstrumentMapping.provider==p.name)).all()}; qs=await p.quotes([{'isin':x['isin'],'symbol':m[x['isin']].instrument_key if x['isin'] in m else None} for x in h])
    for q in qs:db.add(MarketQuote(**q))
    db.commit();return qs
@router.get('/export/{kind}')
def export_data(kind:str,db:Session=Depends(get_db)):
    data={'contracts':contracts(db),'executions':executions(db),'charges':charges(db),'securities':securities(db),'realized':realized(db),'holdings':holdings(db)}
    if kind not in data:raise HTTPException(404,'Unknown export')
    rows=data[kind];out=StringIO();w=csv.writer(out)
    if rows:w.writerow(rows[0].keys());[w.writerow([r[k] for k in rows[0].keys()]) for r in rows]
    return {'filename':f'{kind}.csv','content':out.getvalue()}
@router.websocket('/ws/quotes')
async def quote_socket(websocket:WebSocket):
    await websocket.accept()
    try:
        while True:
            with SessionLocal() as db: await refresh_quotes(db); qs=latest_quotes(db)
            await websocket.send_json({'type':'quotes','data':qs}); await asyncio.sleep(max(5,settings.quote_refresh_seconds))
    except WebSocketDisconnect:return
