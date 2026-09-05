from __future__ import annotations
import hashlib
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.entities import ImportBatch,ContractNote,SecurityLedger,Execution
from app.services.pdf_parser import parse_pdf

def import_pdf(db:Session,path:Path,user_id:int,portfolio_id:int):
    data=path.read_bytes();h=hashlib.sha256(data).hexdigest(); existing=db.scalar(select(ImportBatch).where(ImportBatch.user_id==user_id,ImportBatch.file_hash==h))
    if existing: existing.duplicates+=1;db.commit();return existing
    batch=ImportBatch(user_id=user_id,portfolio_id=portfolio_id,filename=path.name,file_hash=h,status='PROCESSING');db.add(batch);db.flush(); parsed,errors=parse_pdf(path);batch.contract_notes_found=len(parsed);batch.errors='; '.join(errors) if errors else None
    for note in parsed:
        cn=str(note['contract_note']); dup=db.scalar(select(ContractNote).where(ContractNote.user_id==user_id,ContractNote.portfolio_id==portfolio_id,ContractNote.contract_note==cn))
        if dup:batch.duplicates+=1;continue
        db.add(ContractNote(user_id=user_id,portfolio_id=portfolio_id,**{k:note.get(k) for k in ['contract_note','trade_date','settlement_date','settlement_no','source_file','contract_note_page','annexure_page','buy_qty','sell_qty','gross_buy_value','gross_sell_value','displayed_brokerage','buy_value_after_brokerage','sell_value_after_brokerage','market_flow_after_brokerage','payin_obligation','taxable_value','stt','cgst','sgst','ugst','igst','exchange_charges','sebi_fees','stamp_duty','ipft','net_amount']}))
        batch.contracts_added+=1
        for s in note.get('securities',[]):db.add(SecurityLedger(user_id=user_id,portfolio_id=portfolio_id,**s));batch.security_rows_added+=1
        for e in note.get('executions',[]):db.add(Execution(user_id=user_id,portfolio_id=portfolio_id,**e));batch.executions_added+=1
    batch.status='COMPLETED' if not errors else 'COMPLETED_WITH_ERRORS';db.commit();return batch
