from __future__ import annotations
from collections import defaultdict
from datetime import date
from statistics import mean,pstdev
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.entities import Execution
from app.services.analytics import fifo_lots

def _pct(x): return round(x*100,2)
def advanced_analytics(db:Session,user_id:int,portfolio_id:int|None=None):
    q=select(Execution).where(Execution.user_id==user_id)
    if portfolio_id is not None:q=q.where(Execution.portfolio_id==portfolio_id)
    executions=db.scalars(q.order_by(Execution.trade_date,Execution.id)).all(); closed,open_lots=fifo_lots(db,user_id,portfolio_id)
    pnls=[r['pnl'] for r in closed]; wins=[p for p in pnls if p>0];losses=[p for p in pnls if p<0]
    expectancy=(mean(pnls) if pnls else 0); profit_factor=(sum(wins)/abs(sum(losses)) if losses else None)
    dd=[];cum=0;peak=0;daily=defaultdict(float)
    for r in closed: daily[str(r['sell_date'])]+=r['pnl']
    for _,v in sorted(daily.items()): cum+=v;peak=max(peak,cum);dd.append(cum-peak)
    returns=list(daily.values());vol=pstdev(returns) if len(returns)>1 else 0;sharpe=(mean(returns)/vol if vol else None)
    holding=[(r['sell_date']-r['buy_date']).days for r in closed if isinstance(r['sell_date'],date) and isinstance(r['buy_date'],date)]
    return {'trades':len(closed),'wins':len(wins),'losses':len(losses),'win_rate':_pct(len(wins)/len(pnls)) if pnls else 0,'expectancy':expectancy,'profit_factor':profit_factor,'max_drawdown':min(dd) if dd else 0,'volatility':vol,'sharpe_like':sharpe,'avg_holding_days':mean(holding) if holding else None,'max_holding_days':max(holding) if holding else None,'min_holding_days':min(holding) if holding else None,'avg_trade_pnl':expectancy,'gross_profit':sum(wins),'gross_loss':sum(losses),'open_lots':sum(x['qty'] for x in open_lots)}

advanced = advanced_analytics
