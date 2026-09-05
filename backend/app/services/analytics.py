from collections import defaultdict,deque
from datetime import date,datetime
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from app.models.entities import ContractNote,SecurityLedger,Execution,MarketQuote,InstrumentMapping

def _filter(q,model,user_id,portfolio_id):
    q=q.where(model.user_id==user_id)
    if portfolio_id is not None:q=q.where(model.portfolio_id==portfolio_id)
    return q

def fifo_lots(db:Session,user_id:int,portfolio_id:int|None=None):
    q=_filter(select(Execution),Execution,user_id,portfolio_id).order_by(Execution.trade_date,Execution.id); rows=db.scalars(q).all(); lots=defaultdict(deque); closed=[]
    for e in rows:
        if e.side.upper()=='BUY': lots[e.security].append({'qty':e.quantity,'unit_cost':e.amount/e.quantity if e.quantity else 0,'buy_date':e.trade_date})
        else:
            remain=e.quantity; proceeds=(e.amount/e.quantity if e.quantity else 0)
            while remain and lots[e.security]:
                lot=lots[e.security][0];take=min(remain,lot['qty']);pnl=(proceeds-lot['unit_cost'])*take;closed.append({'security':e.security,'qty':take,'buy_date':lot['buy_date'],'sell_date':e.trade_date,'pnl':pnl});lot['qty']-=take;remain-=take
                if lot['qty']==0: lots[e.security].popleft()
    open_lots=[]
    for sec,dq in lots.items():
        for lot in dq: open_lots.append({'security':sec,'qty':lot['qty'],'unit_cost':lot['unit_cost'],'buy_date':lot['buy_date']})
    return closed,open_lots

def overview(db:Session,user_id:int,portfolio_id:int|None=None):
    contracts=db.scalar(select(func.count()).select_from(_filter(select(ContractNote),ContractNote,user_id,portfolio_id).subquery())) or 0
    executions=db.scalar(select(func.count()).select_from(_filter(select(Execution),Execution,user_id,portfolio_id).subquery())) or 0
    rows=db.scalars(_filter(select(Execution),Execution,user_id,portfolio_id).order_by(Execution.trade_date,Execution.id)).all(); closed,lots=fifo_lots(db,user_id,portfolio_id);realized=sum(r['pnl'] for r in closed);gross_turnover=sum(abs(x.amount) for x in rows);open_qty=sum(x['qty'] for x in lots);book_cost=sum(x['qty']*x['unit_cost'] for x in lots);gross_realized=0
    return {'contracts':contracts,'executions':executions,'realized_pnl':realized,'gross_realized_pnl':gross_realized,'gross_turnover':gross_turnover,'open_qty':open_qty,'open_book_cost':book_cost,'round_trips':closed}

def realized_by_security(db,user_id,portfolio_id=None):
    closed,_=fifo_lots(db,user_id,portfolio_id);d=defaultdict(float)
    for x in closed:d[x['security']]+=x['pnl']
    return [{'security':k,'pnl':v} for k,v in sorted(d.items(),key=lambda kv:kv[1],reverse=True)]

def open_holdings(db,user_id,portfolio_id=None):
    _,lots=fifo_lots(db,user_id,portfolio_id);d=defaultdict(lambda:{'qty':0,'book_cost':0})
    for x in lots:d[x['security']]['qty']+=x['qty'];d[x['security']]['book_cost']+=x['qty']*x['unit_cost']
    return [{'security':k,**v} for k,v in sorted(d.items())]

def daily_performance(db,user_id,portfolio_id=None):
    closed,_=fifo_lots(db,user_id,portfolio_id);d=defaultdict(float)
    for x in closed:d[str(x['sell_date'])]+=x['pnl']
    return [{'date':k,'pnl':v} for k,v in sorted(d.items())]

def intelligence(db,user_id,portfolio_id=None):
    closed,lots=fifo_lots(db,user_id,portfolio_id); wins=[x['pnl'] for x in closed if x['pnl']>0]; losses=[x['pnl'] for x in closed if x['pnl']<0]
    return {'summary':{'closed_trades':len(closed),'wins':len(wins),'losses':len(losses),'win_rate':(len(wins)/len(closed)*100 if closed else 0),'expectancy':(sum(x['pnl'] for x in closed)/len(closed) if closed else 0),'open_positions':len(set(x['security'] for x in lots))},'alerts':[]}
