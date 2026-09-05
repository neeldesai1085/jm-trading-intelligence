from collections import defaultdict
from statistics import mean, median
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.entities import MarketQuote, SecurityLedger, TradeAnnotation
from app.services.analytics import overview
from app.core.config import settings


def _quote_history(db: Session):
    rows = db.scalars(select(MarketQuote).order_by(MarketQuote.as_of)).all()
    grouped = defaultdict(list)
    for q in rows:
        if q.ltp is not None:
            grouped[q.isin].append({'as_of': q.as_of, 'ltp': q.ltp, 'high': q.high, 'low': q.low, 'close': q.close})
    return grouped


def advanced(db: Session):
    o = overview(db)
    trades = o['realized_trades']
    wins = [x['pnl'] for x in trades if x['pnl'] > 0]
    losses = [x['pnl'] for x in trades if x['pnl'] < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    pf = gross_profit / gross_loss if gross_loss else None
    avg_win = mean(wins) if wins else None
    avg_loss = mean(losses) if losses else None
    payoff = (avg_win / abs(avg_loss)) if avg_win is not None and avg_loss else None

    current_book = o['open_book_cost'] or 0
    scenarios = []
    for shock in (0.05, 0.10, 0.20):
        scenarios.append({'shock_pct': shock * 100, 'estimated_pnl': -current_book * shock, 'estimated_market_value': (o['portfolio_market_value'] or current_book) * (1 - shock)})

    current_sign = None
    current_len = 0
    max_win = max_loss = 0
    for t in trades:
        sign = 'W' if t['pnl'] > 0 else 'L' if t['pnl'] < 0 else 'F'
        if sign == current_sign: current_len += 1
        else: current_sign, current_len = sign, 1
        if sign == 'W': max_win = max(max_win, current_len)
        if sign == 'L': max_loss = max(max_loss, current_len)

    quote_map = _quote_history(db)
    security_isins = {r.security: r.isin for r in db.scalars(select(SecurityLedger)).all()}
    excursions = []
    for t in trades:
        isin = security_isins.get(t['security'])
        if not isin: continue
        hist = quote_map.get(isin, [])
        window = [q for q in hist if q['as_of'].date() >= t['buy_date'] and q['as_of'].date() <= t['sell_date']]
        if window:
            start_price = window[0]['ltp']
            highs = [q['high'] or q['ltp'] for q in window]
            lows = [q['low'] or q['ltp'] for q in window]
            favorable = max(highs) - start_price
            adverse = min(lows) - start_price
            excursions.append({'security': t['security'], 'buy_date': t['buy_date'], 'sell_date': t['sell_date'], 'observations': len(window), 'mfe_abs': favorable, 'mae_abs': adverse, 'mfe_pct': favorable / start_price if start_price else None, 'mae_pct': adverse / start_price if start_price else None})

    quote_staleness = []
    now = datetime.now(timezone.utc)
    for h in o['holdings']:
        age_minutes = None
        if h['quote_as_of']:
            try:
                dt = datetime.fromisoformat(h['quote_as_of'])
                if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
                age_minutes = max(0, (now - dt).total_seconds() / 60)
            except ValueError: pass
        quote_staleness.append({'security': h['security'], 'age_minutes': age_minutes, 'weight': h['weight'], 'unrealized_pnl': h['unrealized_pnl']})

    benchmark = {'configured': bool(settings.benchmark_isin and settings.benchmark_instrument_key), 'points': 0, 'beta': None, 'alpha_like': None, 'message': None}
    if benchmark['configured']:
        bh = quote_map.get(settings.benchmark_isin, [])
        portfolio_isins = [h['isin'] for h in o['holdings']]
        if len(bh) >= 3 and portfolio_isins:
            timestamps = sorted({q['as_of'] for isin in portfolio_isins for q in quote_map.get(isin, [])})
            pvals, bvals = [], []
            for ts in timestamps:
                pvalue = 0.0; complete = True
                for h in o['holdings']:
                    hist = [q for q in quote_map.get(h['isin'], []) if q['as_of'] <= ts]
                    if not hist: complete = False; break
                    pvalue += hist[-1]['ltp'] * h['quantity']
                bhist = [q for q in bh if q['as_of'] <= ts]
                if complete and bhist: pvals.append(pvalue); bvals.append(bhist[-1]['ltp'])
            pr = [(b/a)-1 for a,b in zip(pvals,pvals[1:]) if a]
            br = [(b/a)-1 for a,b in zip(bvals,bvals[1:]) if a]
            paired = [(x,y) for x,y in zip(pr,br)]
            benchmark['points'] = len(paired)
            if len(paired) >= 3:
                pm = mean(x for x,_ in paired); bm = mean(y for _,y in paired)
                cov = mean((x-pm)*(y-bm) for x,y in paired); varb = mean((y-bm)**2 for _,y in paired)
                beta = cov/varb if varb else None
                benchmark['beta'] = beta; benchmark['alpha_like'] = (pm - beta*bm) if beta is not None else None
                benchmark['message'] = 'Approximate beta/alpha-like estimates use the current open-book weights and synchronized quote snapshots.'
            else: benchmark['message'] = 'Collect more synchronized portfolio and benchmark quote snapshots.'
        else: benchmark['message'] = 'Configure benchmark instrument and collect quote history before beta/alpha can be estimated.'

    annotations = {(a.security, a.buy_date, a.sell_date): a for a in db.scalars(select(TradeAnnotation)).all()}
    by_strategy = defaultdict(lambda: {'trades': 0, 'pnl': 0.0, 'wins': 0})
    for t in trades:
        a = annotations.get((t['security'], t['buy_date'], t['sell_date']))
        label = a.strategy if a else 'Unclassified'
        by_strategy[label]['trades'] += 1; by_strategy[label]['pnl'] += t['pnl']; by_strategy[label]['wins'] += int(t['pnl'] > 0)
    strategy_summary = [{'strategy': k, 'trades': v['trades'], 'pnl': v['pnl'], 'win_rate': v['wins']/v['trades'] if v['trades'] else None} for k,v in sorted(by_strategy.items())]
    return {
        'trade_quality': {'trade_count': len(trades), 'wins': len(wins), 'losses': len(losses), 'win_rate': o['win_rate'], 'avg_win': avg_win, 'avg_loss': avg_loss, 'payoff_ratio': payoff, 'profit_factor': pf, 'expectancy_per_trade': mean([x['pnl'] for x in trades]) if trades else None, 'median_pnl': median([x['pnl'] for x in trades]) if trades else None, 'max_consecutive_wins': max_win, 'max_consecutive_losses': max_loss, 'avg_holding_days': o['avg_holding_days']},
        'stress_tests': scenarios, 'trade_excursions': excursions, 'quote_staleness': quote_staleness, 'benchmark': benchmark, 'strategy_summary': strategy_summary,
        'portfolio': {'book_cost': o['open_book_cost'], 'market_value': o['portfolio_market_value'], 'unrealized_pnl': o['unrealized_pnl'], 'top2_concentration': o['top2_concentration'], 'top3_concentration': o['top3_concentration'], 'quote_coverage': (sum(1 for x in o['holdings'] if x['ltp'] is not None) / len(o['holdings'])) if o['holdings'] else 1},
    }
