from collections import defaultdict
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.entities import ContractNote,SecurityLedger,Execution
from app.services.analytics import fifo_lots,overview

def build_excel_parity(db:Session,user_id:int,portfolio_id:int|None=None):
    closed,lots=fifo_lots(db,user_id,portfolio_id);o=overview(db,user_id,portfolio_id)
    tabs=['Dashboard','Trader Review','Source of Truth','Dashboard Calc','Contract Notes','Security Ledger','Execution Ledger','Charges Detail','Charge Summary','Charge Allocation','FIFO / Realized P&L','Open Holdings','Realized P&L by Security','Security Summary','Monthly Performance','Cumulative P&L','Reconciliation','Performance Metrics','Source Audit','Data Dictionary','Report Notes','Master Calc']
    charge_total=0
    q=select(ContractNote).where(ContractNote.user_id==user_id)
    if portfolio_id is not None:q=q.where(ContractNote.portfolio_id==portfolio_id)
    for c in db.scalars(q).all():charge_total+=c.displayed_brokerage+c.stt+c.cgst+c.sgst+c.ugst+c.igst+c.exchange_charges+c.sebi_fees+c.stamp_duty+c.ipft
    by=defaultdict(float)
    for x in closed:by[x['security']]+=x['pnl']
    return {'workbook_tabs':tabs,'round_trips':closed,'charge_allocation':[{'security':k,'allocated_charge':0} for k in by],'charge_total':charge_total,'metrics':{'wins':len([x for x in closed if x['pnl']>0]),'losses':len([x for x in closed if x['pnl']<0])},'overview':o}
