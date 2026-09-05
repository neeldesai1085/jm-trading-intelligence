from collections import defaultdict
from statistics import mean, median
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.entities import MarketQuote, SecurityLedger, TradeAnnotation
from app.services.analytics import overview
from app.core.config import settings

def _quote_history(db:Session,user_id:int):
    rows=db.scalars(select(MarketQuote).where(MarketQuote.user_id==user_id).order_by(MarketQuote.as_of)).all();grouped=defaultdict(list)
    for q in rows:
        if q.ltp is not None:grouped[q.isin].append({'as_of':q.as_of,'ltp':q.ltp,'high':q.high,'low':q.low,'close':q.close})
    return grouped

def advanced(db:Session,user_id:int):
    o=overview(db,user_id);trades=o['realized_trades'];wins=[x['pnl'] for x in trades if x['pnl']>0];losses=[x['pnl'] for x in trades if x['pnl']<0];gross_profit=sum(wins);gross_loss=abs(sum(losses));pf=gross_profit/gross_loss if gross_loss else None;avg_win=mean(wins) if wins else None;avg_loss=mean(losses) if losses else None;payoff=avg_win/abs(avg_loss) if avg_win is not None and avg_loss else None
    book=o['open_book_cost'] or 0;scenarios=[{'shock_pct':s*100,'estimated_pnl':-book*s,'estimated_market_value':(o['portfolio_market_value'] or book)*(1-s)} for s in (.05,.10,.20)]
    current=None;length=0;max_win=max_loss=0
    for t in trades:
        sign='W' if t['pnl']>0 else 'L' if t['pnl']<0 else 'F';length=length+1 if sign==current else 1;current=sign;max_win=max(max_win,length) if sign=='W' else max_win;max_loss=max(max_loss,length) if sign=='L' else max_loss
    quote_map=_quote_history(db,user_id);security_isins={r.security:r.isin for r in db.scalars(select(SecurityLedger).where(SecurityLedger.user_id==user_id)).all()};excursions=[]
    for t in trades:
        hist=[q for q in quote_map.get(security_isins.get(t['security']),[]) if t['buy_date']<=q['as_of'].date()<=t['sell_date']]
        if hist:
            start=hist[0]['ltp'];highs=[q['high'] or q['ltp'] for q in hist];lows=[q['low'] or q['ltp'] for q in hist];mfe=max(highs)-start;mae=min(lows)-start
            excursions.append({'security':t['security'],'buy_date':t['buy_date'],'sell_date':t['sell_date'],'observations':len(hist),'mfe_abs':mfe,'mae_abs':mae,'mfe_pct':mfe/start if start else None,'mae_pct':mae/start if start else None})
    staleness=[];now=datetime.now(timezone.utc)
    for h in o['holdings']:
        age=None
        if h['quote_as_of']:
            try:
                dt=datetime.fromisoformat(h['quote_as_of']);dt=dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc);age=max(0,(now-dt).total_seconds()/60)
            except ValueError:pass
        staleness.append({'security':h['security'],'age_minutes':age,'weight':h['weight'],'unrealized_pnl':h['unrealized_pnl']})
    benchmark={'configured':bool(settings.benchmark_isin and settings.benchmark_instrument_key),'points':0,'beta':None,'alpha_like':None,'message':None}
    if benchmark['configured']:
        bh=quote_map.get(settings.benchmark_isin,[]);isins=[h['isin'] for h in o['holdings']]
        if len(bh)>=3 and isins:
            timestamps=sorted({q['as_of'] for i in isins for q in quote_map.get(i,[])});pvals=[];bvals=[]
            for ts in timestamps:
                pvalue=0;complete=True
                for h in o['holdings']:
                    hist=[q for q in quote_map.get(h['isin'],[]) if q['as_of']<=ts]
                    if not hist:complete=False;break
                    pvalue+=hist[-1]['ltp']*h['quantity']
                bhist=[q for q in bh if q['as_of']<=ts]
                if complete and bhist:pvals.append(pvalue);bvals.append(bhist[-1]['ltp'])
            pr=[b/a-1 for a,b in zip(pvals,pvals[1:]) if a];br=[b/a-1 for a,b in zip(bvals,bvals[1:]) if a];paired=list(zip(pr,br));benchmark['points']=len(paired)
            if len(paired)>=3:
                pm=mean(x for x,_ in paired);bm=mean(y for _,y in paired);cov=mean((x-pm)*(y-bm) for x,y in paired);varb=mean((y-bm)**2 for _,y in paired);beta=cov/varb if varb else None;benchmark['beta']=beta;benchmark['alpha_like']=pm-beta*bm if beta is not None else None;benchmark['message']='Approximate beta/alpha-like estimates use synchronized quote snapshots.'
            else:benchmark['message']='Collect more synchronized portfolio and benchmark quote snapshots.'
        else:benchmark['message']='Configure benchmark instrument and collect quote history before beta/alpha can be estimated.'
    annotations={(a.security,a.buy_date,a.sell_date):a for a in db.scalars(select(TradeAnnotation).where(TradeAnnotation.user_id==user_id)).all()};by=defaultdict(lambda:{'trades':0,'pnl':0.0,'wins':0})
    for t in trades:
        a=annotations.get((t['security'],t['buy_date'],t['sell_date']));label=a.strategy if a else 'Unclassified';by[label]['trades']+=1;by[label]['pnl']+=t['pnl'];by[label]['wins']+=int(t['pnl']>0)
    strategy=[{'strategy':k,'trades':v['trades'],'pnl':v['pnl'],'win_rate':v['wins']/v['trades'] if v['trades'] else None} for k,v in sorted(by.items())]
    return {'trade_quality':{'trade_count':len(trades),'wins':len(wins),'losses':len(losses),'win_rate':o['win_rate'],'avg_win':avg_win,'avg_loss':avg_loss,'payoff_ratio':payoff,'profit_factor':pf,'expectancy_per_trade':mean([t['pnl'] for t in trades]) if trades else None,'median_pnl':median([x['pnl'] for x in trades]) if trades else None,'max_consecutive_wins':max_win,'max_consecutive_losses':max_loss,'avg_holding_days':o['avg_holding_days']},'stress_tests':scenarios,'trade_excursions':excursions,'quote_staleness':staleness,'benchmark':benchmark,'strategy_summary':strategy,'portfolio':{'book_cost':o['open_book_cost'],'market_value':o['portfolio_market_value'],'unrealized_pnl':o['unrealized_pnl'],'top2_concentration':o['top2_concentration'],'top3_concentration':o['top3_concentration'],'quote_coverage':sum(1 for x in o['holdings'] if x['ltp'] is not None)/len(o['holdings']) if o['holdings'] else 1}}
