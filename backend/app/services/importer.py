import hashlib
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.entities import ImportBatch, ContractNote, SecurityLedger, Execution
from app.services.pdf_parser import parse_pdf

def import_pdf(db: Session, path: Path, user_id: int):
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    existing=db.scalar(select(ImportBatch).where(ImportBatch.user_id==user_id,ImportBatch.file_hash==digest))
    if existing:return existing
    batch=ImportBatch(user_id=user_id,filename=path.name,file_hash=digest,status='PROCESSING');db.add(batch);db.flush()
    parsed,parse_errors=parse_pdf(path);batch.contract_notes_found=len(parsed);notes_added=dups=exec_added=sec_added=0;errors=list(parse_errors)
    try:
        for p in parsed:
            note=db.scalar(select(ContractNote).where(ContractNote.user_id==user_id,ContractNote.contract_note==p['contract_note']))
            if note:dups+=1
            else:
                c=p['charges'];note=ContractNote(user_id=user_id,contract_note=p['contract_note'],trade_date=p['trade_date'],settlement_date=p['settlement_date'],settlement_no=p.get('settlement_no'),source_file=path.name,buy_qty=sum(s['buy_qty'] for s in p['securities']),sell_qty=sum(s['sell_qty'] for s in p['securities']),gross_buy_value=sum(s['buy_qty']*s['buy_wap'] for s in p['securities']),gross_sell_value=sum(s['sell_qty']*s['sell_wap'] for s in p['securities']),displayed_brokerage=sum(s['buy_qty']*s['buy_brokerage_share']+s['sell_qty']*s['sell_brokerage_share'] for s in p['securities']),buy_value_after_brokerage=sum(-s['total_buy_value_after_brokerage'] for s in p['securities']),sell_value_after_brokerage=sum(s['total_sell_value_after_brokerage'] for s in p['securities']),payin_obligation=sum(s['net_obligation_before_levies'] for s in p['securities']),taxable_value=c['taxable_value'],stt=c['stt'],cgst=c['cgst'],sgst=c['sgst'],ugst=c['ugst'],igst=c['igst'],exchange_charges=c['exchange_charges'],sebi_fees=c['sebi_fees'],stamp_duty=c['stamp_duty'],ipft=c['ipft'],net_amount=c['net_amount'])
                note.market_flow_after_brokerage=note.sell_value_after_brokerage+note.buy_value_after_brokerage;db.add(note);db.flush();notes_added+=1
            for s in p['securities']:
                q=select(SecurityLedger).where(SecurityLedger.user_id==user_id,SecurityLedger.contract_note==s['contract_note'],SecurityLedger.isin==s['isin'],SecurityLedger.buy_qty==s['buy_qty'],SecurityLedger.sell_qty==s['sell_qty'],SecurityLedger.total_buy_value_after_brokerage==s['total_buy_value_after_brokerage'],SecurityLedger.total_sell_value_after_brokerage==s['total_sell_value_after_brokerage'])
                if db.scalar(q):continue
                data={k:v for k,v in s.items() if k!='settlement_date'};db.add(SecurityLedger(user_id=user_id,**data));sec_added+=1
            for e in p['executions']:
                if db.scalar(select(Execution).where(Execution.user_id==user_id,Execution.contract_note==e['contract_note'],Execution.trade_no==e['trade_no'])):continue
                db.add(Execution(user_id=user_id,**e));exec_added+=1
        batch.contracts_added=notes_added;batch.duplicates=dups;batch.executions_added=exec_added;batch.security_rows_added=sec_added;batch.errors='; '.join(errors) if errors else None;batch.status='ERROR' if errors else 'ADDED';db.commit();return batch
    except Exception:db.rollback();raise
