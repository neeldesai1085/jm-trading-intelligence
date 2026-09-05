from collections import defaultdict, deque
from math import sqrt
from statistics import mean, pstdev
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.entities import SecurityLedger, Execution, ContractNote, MarketQuote

def fifo(db: Session, user_id: int):
    execs=db.scalars(select(Execution).where(Execution.user_id==user_id).order_by(Execution.trade_date,Execution.trade_time,Execution.id)).all();lots=defaultdict(deque);realized=[]
    for e in execs:
        if e.side=='BUY': lots[e.security].append({'qty':e.quantity,'price':e.amount/e.quantity if e.quantity else 0,'date':e.trade_date})
        else:
            rem=e.quantity
            while rem and lots[e.security]:
                lot=lots[e.security][0];q=min(rem,lot['qty']);cost=q*lot['price'];sale=(e.amount/e.quantity)*q if e.quantity else 0;pnl=sale-cost
                realized.append({'security':e.security,'buy_date':lot['date'],'sell_date':e.trade_date,'qty':q,'pnl':pnl,'return':pnl/cost if cost else 0,'holding_days':(e.trade_date-lot['date']).days});lot['qty']-=q;rem-=q
                if lot['qty']==0:lots[e.security].popleft()
    return realized,lots

def round_trip_groups(db: Session,user_id:int,realized=None):
    realized=realized if realized is not None else fifo(db,user_id)[0];secs=db.scalars(select(SecurityLedger).where(SecurityLedger.user_id==user_id)).all();buy_after={};sell_after={}
    for s in secs:
        if s.buy_qty:buy_after[(s.security,s.trade_date)]=(-s.total_buy_value_after_brokerage)/s.buy_qty
        if s.sell_qty:sell_after[(s.security,s.trade_date)]=s.total_sell_value_after_brokerage/s.sell_qty
    groups=defaultdict(lambda:{'qty':0,'gross_pnl':0.0,'pnl':0.0,'cost':0.0})
    for x in realized:
        g=groups[(x['security'],x['buy_date'],x['sell_date'])];g['qty']+=x['qty'];g['gross_pnl']+=x['pnl'];br=buy_after.get((x['security'],x['buy_date']));sr=sell_after.get((x['security'],x['sell_date']))
        if br is not None and sr is not None:g['cost']+=x['qty']*br;g['pnl']+=x['qty']*(sr-br)
        else:g['pnl']+=x['pnl']
    return sorted([{'security':s,'buy_date':b,'sell_date':d,'qty':g['qty'],'pnl':g['pnl'],'gross_pnl':g['gross_pnl'],'return':g['pnl']/g['cost'] if g['cost'] else 0,'holding_days':(d-b).days} for (s,b,d),g in groups.items()],key=lambda x:(x['sell_date'],x['buy_date'],x['security']))

def _daily_pnl(realized):
    by=defaultdict(float)
    for x in realized:by[x['sell_date'].isoformat()]+=x['pnl']
    return [{'date':k,'pnl':round(v,2)} for k,v in sorted(by.items())]

def _risk(daily):
    vals=[x['pnl'] for x in daily]
    if not vals:return {'mean_daily_pnl':None,'volatility':None,'sharpe_like':None,'max_drawdown':0,'var_95':None,'cvar_95':None}
    curve=peak=mdd=0.0
    for x in vals:curve+=x;peak=max(peak,curve);mdd=min(mdd,curve-peak)
    vol=pstdev(vals) if len(vals)>1 else 0.0;sharpe=(mean(vals)/vol*sqrt(252)) if vol else None;sv=sorted(vals);idx=max(0,int((len(sv)-1)*.05));var=-sv[idx];tail=[v for v in vals if v<=sv[idx]] or [sv[idx]]
    return {'mean_daily_pnl':mean(vals),'volatility':vol,'sharpe_like':sharpe,'max_drawdown':abs(mdd),'var_95':var,'cvar_95':-mean(tail)}

def _open_holdings_after_brokerage(db:Session,user_id:int):
    execs=db.scalars(select(Execution).where(Execution.user_id==user_id).order_by(Execution.trade_date,Execution.trade_time,Execution.id)).all();secs=db.scalars(select(SecurityLedger).where(SecurityLedger.user_id==user_id)).all();buy_rates={(s.security,s.trade_date):(-s.total_buy_value_after_brokerage)/s.buy_qty for s in secs if s.buy_qty};lots=defaultdict(deque)
    for e in execs:
        if e.side=='BUY':lots[e.security].append({'qty':e.quantity,'cost':buy_rates.get((e.security,e.trade_date),e.amount/e.quantity if e.quantity else 0),'date':e.trade_date})
        else:
            rem=e.quantity
            while rem and lots[e.security]:
                lot=lots[e.security][0];used=min(rem,lot['qty']);lot['qty']-=used;rem-=used
                if lot['qty']==0:lots[e.security].popleft()
    return lots,{s.security:s.isin for s in secs}

def overview(db:Session,user_id:int):
    notes=db.scalars(select(ContractNote).where(ContractNote.user_id==user_id)).all();secs=db.scalars(select(SecurityLedger).where(SecurityLedger.user_id==user_id)).all();execs=db.scalars(select(Execution).where(Execution.user_id==user_id)).all();realized,lots=fifo(db,user_id);round_trips=round_trip_groups(db,user_id,realized);gross_realized=sum(x['pnl'] for x in realized);realized_after=sum(x['pnl'] for x in round_trips)
    open_lots,isin_map=_open_holdings_after_brokerage(db,user_id);remaining={}
    for security,q in open_lots.items():
        qty=sum(x['qty'] for x in q);value=sum(x['qty']*x['cost'] for x in q)
        if qty>0:remaining[security]={'qty':qty,'value':value,'isin':isin_map.get(security)}
    quotes={q.isin:q for q in db.scalars(select(MarketQuote).where(MarketQuote.user_id==user_id).order_by(MarketQuote.as_of)).all()};holdings=[]
    for security,v in remaining.items():
        avg=v['value']/v['qty'] if v['qty'] else 0;mq=quotes.get(v['isin']);ltp=mq.ltp if mq else None;mv=ltp*v['qty'] if ltp is not None else None
        holdings.append({'isin':v['isin'],'security':security,'quantity':int(v['qty']),'book_cost':v['value'],'avg_cost':avg,'ltp':ltp,'market_value':mv,'unrealized_pnl':mv-v['value'] if mv is not None else None,'quote_as_of':mq.as_of.isoformat() if mq else None})
    total_open=sum(h['book_cost'] for h in holdings)
    for h in holdings:h['weight']=h['book_cost']/total_open if total_open else 0
    holdings.sort(key=lambda x:x['book_cost'],reverse=True);fully_quoted=bool(holdings) and all(h['market_value'] is not None for h in holdings);portfolio_value=sum(h['market_value'] for h in holdings) if fully_quoted else None;unrealized=sum(h['unrealized_pnl'] for h in holdings) if fully_quoted else None;wins=sum(x['pnl']>0 for x in round_trips);closed=[x for x in round_trips if x['qty']>0];non_brokerage=sum(n.stt+n.cgst+n.sgst+n.ugst+n.igst+n.exchange_charges+n.sebi_fees+n.stamp_duty+n.ipft for n in notes);daily=_daily_pnl(round_trips);risk=_risk(daily)
    brokerage=sum(s.displayed_buy_brokerage+s.displayed_sell_brokerage for s in secs)
    return {'trade_start':min((n.trade_date for n in notes),default=None),'trade_end':max((n.trade_date for n in notes),default=None),'contracts':len(notes),'executions':len(execs),'unique_securities':len({s.isin for s in secs}),'buy_qty':sum(e.quantity for e in execs if e.side=='BUY'),'sell_qty':sum(e.quantity for e in execs if e.side=='SELL'),'gross_turnover':sum(e.amount for e in execs),'gross_buy_turnover':sum(e.amount for e in execs if e.side=='BUY'),'gross_sell_turnover':sum(e.amount for e in execs if e.side=='SELL'),'brokerage':brokerage,'non_brokerage_charges':non_brokerage,'total_charges':brokerage+non_brokerage,'realized_pnl':realized_after,'gross_realized_pnl':gross_realized,'charge_drag':gross_realized-realized_after,'open_book_cost':total_open,'open_qty':sum(h['quantity'] for h in holdings),'portfolio_market_value':portfolio_value,'unrealized_pnl':unrealized,'win_rate':wins/len(round_trips) if round_trips else None,'top2_concentration':sum(h['weight'] for h in holdings[:2]),'top3_concentration':sum(h['weight'] for h in holdings[:3]),'holdings':holdings,'realized_trades':round_trips,'fifo_fragments':realized,'daily_pnl':daily,'risk':risk,'avg_holding_days':mean(x['holding_days'] for x in closed) if closed else None,'wins':wins,'losses':len(closed)-wins}

def intelligence(db:Session,user_id:int):
    o=overview(db,user_id);alerts=[]
    if o['top2_concentration']>.75:alerts.append({'severity':'HIGH','title':'Concentration risk','detail':f"Top 2 holdings represent {o['top2_concentration']*100:.1f}% of open book."})
    if o['top3_concentration']>.90:alerts.append({'severity':'HIGH','title':'Top-3 concentration','detail':f"Top 3 holdings represent {o['top3_concentration']*100:.1f}% of open book."})
    if o['risk']['max_drawdown'] and o['risk']['max_drawdown']>max(.05*max(o['open_book_cost'],1),10000):alerts.append({'severity':'MEDIUM','title':'Drawdown watch','detail':f"Historical realized drawdown is ₹{o['risk']['max_drawdown']:,.0f}."})
    unmapped=[h['security'] for h in o['holdings'] if h['ltp'] is None]
    if unmapped:alerts.append({'severity':'INFO','title':'Live quotes missing','detail':f"{len(unmapped)} open position(s) have no mapped live quote."})
    return {'alerts':alerts,'metrics':{'realized_pnl':o['realized_pnl'],'unrealized_pnl':o['unrealized_pnl'],'max_drawdown':o['risk']['max_drawdown'],'volatility':o['risk']['volatility'],'sharpe_like':o['risk']['sharpe_like'],'var_95':o['risk']['var_95'],'cvar_95':o['risk']['cvar_95'],'avg_holding_days':o['avg_holding_days'],'charge_drag':o['charge_drag']},'daily_pnl':o['daily_pnl'],'holdings':o['holdings']}
