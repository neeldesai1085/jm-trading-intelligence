from collections import defaultdict, deque
from datetime import date
from math import sqrt
from statistics import mean, pstdev
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.models.entities import ContractNote, SecurityLedger, Execution

def _filter(q, model, user_id, portfolio_id):
    q = q.where(model.user_id == user_id)
    if portfolio_id is not None: q = q.where(model.portfolio_id == portfolio_id)
    return q

def fifo_lots(db: Session, user_id: int, portfolio_id: int | None = None):
    q = _filter(select(Execution), Execution, user_id, portfolio_id).order_by(Execution.trade_date, Execution.trade_time, Execution.id)
    rows = db.scalars(q).all(); lots = defaultdict(deque); closed = []
    for e in rows:
        if e.side.upper() == 'BUY': lots[e.security].append({'qty': e.quantity, 'unit_cost': e.amount / e.quantity if e.quantity else 0, 'buy_date': e.trade_date})
        else:
            remain = e.quantity; proceeds = e.amount / e.quantity if e.quantity else 0
            while remain and lots[e.security]:
                lot = lots[e.security][0]; take = min(remain, lot['qty']); pnl = (proceeds - lot['unit_cost']) * take
                closed.append({'security': e.security, 'qty': take, 'buy_date': lot['buy_date'], 'sell_date': e.trade_date, 'pnl': pnl, 'return': pnl/(take*lot['unit_cost']) if lot['unit_cost'] else 0, 'holding_days': (e.trade_date-lot['buy_date']).days})
                lot['qty'] -= take; remain -= take
                if lot['qty'] == 0: lots[e.security].popleft()
    open_lots = [dict(security=sec, **lot) for sec,dq in lots.items() for lot in dq]
    return closed, open_lots

def _risk(daily):
    values=[x['pnl'] for x in daily]
    if not values: return {'mean_daily_pnl':None,'volatility':None,'sharpe_like':None,'max_drawdown':0,'var_95':None,'cvar_95':None}
    curve=peak=mdd=0.0
    for value in values:
        curve += value; peak=max(peak,curve); mdd=min(mdd,curve-peak)
    vol=pstdev(values) if len(values)>1 else 0.0
    sharpe=mean(values)/vol*sqrt(252) if vol else None
    ordered=sorted(values); cutoff=ordered[max(0,int((len(ordered)-1)*.05))]; tail=[v for v in values if v<=cutoff] or [cutoff]
    return {'mean_daily_pnl':mean(values),'volatility':vol,'sharpe_like':sharpe,'max_drawdown':abs(mdd),'var_95':-cutoff,'cvar_95':-mean(tail)}

def overview(db: Session, user_id: int, portfolio_id: int | None = None):
    notes=db.scalars(_filter(select(ContractNote),ContractNote,user_id,portfolio_id)).all()
    rows=db.scalars(_filter(select(Execution),Execution,user_id,portfolio_id).order_by(Execution.trade_date,Execution.trade_time,Execution.id)).all()
    closed,lots=fifo_lots(db,user_id,portfolio_id)
    realized=sum(r['pnl'] for r in closed); gross_turnover=sum(abs(x.amount) for x in rows); open_qty=sum(x['qty'] for x in lots); book_cost=sum(x['qty']*x['unit_cost'] for x in lots)
    daily_map=defaultdict(float)
    for row in closed: daily_map[str(row['sell_date'])]+=row['pnl']
    daily_pnl=[{'date':k,'pnl':round(v,2)} for k,v in sorted(daily_map.items())]
    holdings_map=defaultdict(lambda:{'qty':0,'book_cost':0.0})
    for lot in lots: holdings_map[lot['security']]['qty']+=lot['qty']; holdings_map[lot['security']]['book_cost']+=lot['qty']*lot['unit_cost']
    holdings=[{'security':k,**v} for k,v in sorted(holdings_map.items())]
    realized_trades=sorted(closed,key=lambda x:(x['sell_date'],x['buy_date'],x['security']))
    return {'contracts':len(notes),'executions':len(rows),'realized_pnl':realized,'gross_realized_pnl':sum(r['pnl'] for r in closed),'gross_turnover':gross_turnover,'open_qty':open_qty,'open_book_cost':book_cost,'round_trips':realized_trades,'daily_pnl':daily_pnl,'risk':_risk(daily_pnl),'holdings':holdings,'realized_trades':realized_trades,'portfolio_market_value':book_cost}

def realized_by_security(db,user_id,portfolio_id=None):
    closed,_=fifo_lots(db,user_id,portfolio_id);d=defaultdict(float)
    for x in closed:d[x['security']]+=x['pnl']
    return [{'security':k,'pnl':v} for k,v in sorted(d.items(),key=lambda kv:kv[1],reverse=True)]

def open_holdings(db,user_id,portfolio_id=None):
    return overview(db,user_id,portfolio_id)['holdings']
def daily_performance(db,user_id,portfolio_id=None):
    return overview(db,user_id,portfolio_id)['daily_pnl']
def intelligence(db,user_id,portfolio_id=None):
    closed,lots=fifo_lots(db,user_id,portfolio_id);wins=[x['pnl'] for x in closed if x['pnl']>0];losses=[x['pnl'] for x in closed if x['pnl']<0]
    return {'summary':{'closed_trades':len(closed),'wins':len(wins),'losses':len(losses),'win_rate':len(wins)/len(closed)*100 if closed else 0,'expectancy':sum(x['pnl'] for x in closed)/len(closed) if closed else 0,'profit_factor':sum(wins)/abs(sum(losses)) if losses else None,'open_positions':len(set(x['security'] for x in lots))},'alerts':[]}
