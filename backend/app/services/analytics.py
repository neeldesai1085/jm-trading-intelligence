from collections import defaultdict, deque
from datetime import date
from math import sqrt
from statistics import mean, pstdev
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.entities import SecurityLedger, Execution, ContractNote, MarketQuote


def fifo(db: Session):
    execs = db.scalars(select(Execution).order_by(Execution.trade_date, Execution.trade_time, Execution.id)).all()
    lots = defaultdict(deque)
    realized = []
    for e in execs:
        if e.side == 'BUY':
            lots[e.security].append({'qty': e.quantity, 'price': e.amount / e.quantity if e.quantity else 0, 'date': e.trade_date})
        else:
            remaining = e.quantity
            while remaining and lots[e.security]:
                lot = lots[e.security][0]
                q = min(remaining, lot['qty'])
                cost = q * lot['price']
                sale = (e.amount / e.quantity) * q if e.quantity else 0
                pnl = sale - cost
                realized.append({'security': e.security, 'buy_date': lot['date'], 'sell_date': e.trade_date,
                                 'qty': q, 'pnl': pnl, 'return': pnl / cost if cost else 0,
                                 'holding_days': (e.trade_date - lot['date']).days})
                lot['qty'] -= q
                remaining -= q
                if lot['qty'] == 0:
                    lots[e.security].popleft()
    return realized, lots


def round_trip_groups(db: Session, realized=None):
    realized = realized if realized is not None else fifo(db)[0]
    secs = db.scalars(select(SecurityLedger)).all()
    buy_after = {}
    sell_after = {}
    for s in secs:
        if s.buy_qty:
            buy_after[(s.security, s.trade_date)] = (-s.total_buy_value_after_brokerage) / s.buy_qty
        if s.sell_qty:
            sell_after[(s.security, s.trade_date)] = s.total_sell_value_after_brokerage / s.sell_qty
    groups = defaultdict(lambda: {'qty': 0, 'gross_pnl': 0.0, 'pnl': 0.0, 'cost': 0.0})
    for x in realized:
        g = groups[(x['security'], x['buy_date'], x['sell_date'])]
        g['qty'] += x['qty']
        g['gross_pnl'] += x['pnl']
        br = buy_after.get((x['security'], x['buy_date']))
        sr = sell_after.get((x['security'], x['sell_date']))
        if br is not None and sr is not None:
            g['cost'] += x['qty'] * br
            g['pnl'] += x['qty'] * (sr - br)
        else:
            g['pnl'] += x['pnl']
    rows = []
    for (security, buy_date, sell_date), g in groups.items():
        rows.append({'security': security, 'buy_date': buy_date, 'sell_date': sell_date, 'qty': g['qty'],
                     'pnl': g['pnl'], 'gross_pnl': g['gross_pnl'],
                     'return': g['pnl'] / g['cost'] if g['cost'] else 0,
                     'holding_days': (sell_date - buy_date).days})
    return sorted(rows, key=lambda x: (x['sell_date'], x['buy_date'], x['security']))


def _daily_pnl(realized):
    by_day = defaultdict(float)
    for x in realized:
        by_day[x['sell_date'].isoformat()] += x['pnl']
    return [{'date': k, 'pnl': round(v, 2)} for k, v in sorted(by_day.items())]


def _risk(daily):
    vals = [x['pnl'] for x in daily]
    if not vals:
        return {'mean_daily_pnl': None, 'volatility': None, 'sharpe_like': None, 'max_drawdown': 0, 'var_95': None, 'cvar_95': None}
    curve = peak = 0.0
    mdd = 0.0
    for v in vals:
        curve += v
        peak = max(peak, curve)
        mdd = min(mdd, curve - peak)
    vol = pstdev(vals) if len(vals) > 1 else 0.0
    sharpe = (mean(vals) / vol * sqrt(252)) if vol else None
    ordered = sorted(vals)
    q = ordered[max(0, int((len(ordered) - 1) * 0.05))]
    tail = [v for v in vals if v <= q] or [q]
    return {'mean_daily_pnl': mean(vals), 'volatility': vol, 'sharpe_like': sharpe,
            'max_drawdown': abs(mdd), 'var_95': -q, 'cvar_95': -mean(tail)}


def overview(db: Session):
    notes = db.scalars(select(ContractNote)).all()
    secs = db.scalars(select(SecurityLedger)).all()
    execs = db.scalars(select(Execution)).all()
    realized, _ = fifo(db)
    round_trips = round_trip_groups(db, realized)
    gross_realized = sum(x['pnl'] for x in realized)

    cost, proceeds = {}, {}
    for s in secs:
        cost.setdefault(s.security, {'qty': 0, 'value': 0, 'isin': s.isin})
        proceeds.setdefault(s.security, {'qty': 0, 'value': 0})
        cost[s.security]['qty'] += s.buy_qty
        cost[s.security]['value'] += -s.total_buy_value_after_brokerage
        proceeds[s.security]['qty'] += s.sell_qty
        proceeds[s.security]['value'] += s.total_sell_value_after_brokerage
    realized_after = sum(proceeds[k]['value'] - cost[k]['value'] for k in cost if proceeds[k]['qty'] >= cost[k]['qty'])

    holdings = []
    quotes = {q.isin: q for q in db.scalars(select(MarketQuote)).all()}
    for security, v in cost.items():
        q = v['qty'] - proceeds[security]['qty']
        if q <= 0:
            continue
        mq = quotes.get(v['isin'])
        ltp = mq.ltp if mq else None
        mv = ltp * q if ltp is not None else None
        holdings.append({'isin': v['isin'], 'security': security, 'quantity': q, 'book_cost': v['value'],
                         'avg_cost': v['value'] / v['qty'] if v['qty'] else 0, 'ltp': ltp, 'market_value': mv,
                         'unrealized_pnl': mv - v['value'] if mv is not None else None,
                         'quote_as_of': mq.as_of.isoformat() if mq else None})
    total_open = sum(h['book_cost'] for h in holdings)
    for h in holdings:
        h['weight'] = h['book_cost'] / total_open if total_open else 0
    holdings.sort(key=lambda x: x['book_cost'], reverse=True)
    quoted = bool(holdings) and all(h['market_value'] is not None for h in holdings)
    market_value = sum(h['market_value'] for h in holdings) if quoted else None
    unrealized = sum(h['unrealized_pnl'] for h in holdings) if quoted else None

    wins = sum(1 for x in round_trips if x['pnl'] > 0)
    daily = _daily_pnl(round_trips)
    risk = _risk(daily)
    brokerage = sum(s.displayed_buy_brokerage + s.displayed_sell_brokerage for s in secs)
    non_brokerage = sum(n.stt + n.cgst + n.sgst + n.ugst + n.igst + n.exchange_charges + n.sebi_fees + n.stamp_duty + n.ipft for n in notes)

    return {'trade_start': min((n.trade_date for n in notes), default=None),
            'trade_end': max((n.trade_date for n in notes), default=None),
            'contracts': len(notes), 'executions': len(execs), 'unique_securities': len({s.isin for s in secs}),
            'buy_qty': sum(e.quantity for e in execs if e.side == 'BUY'), 'sell_qty': sum(e.quantity for e in execs if e.side == 'SELL'),
            'gross_turnover': sum(e.amount for e in execs),
            'gross_buy_turnover': sum(e.amount for e in execs if e.side == 'BUY'),
            'gross_sell_turnover': sum(e.amount for e in execs if e.side == 'SELL'),
            'brokerage': brokerage, 'non_brokerage_charges': non_brokerage, 'total_charges': brokerage + non_brokerage,
            'realized_pnl': realized_after, 'gross_realized_pnl': gross_realized, 'charge_drag': gross_realized - realized_after,
            'open_book_cost': total_open, 'open_qty': sum(h['quantity'] for h in holdings),
            'portfolio_market_value': market_value, 'unrealized_pnl': unrealized,
            'win_rate': wins / len(round_trips) if round_trips else None, 'wins': wins,
            'losses': len(round_trips) - wins, 'top2_concentration': sum(h['weight'] for h in holdings[:2]),
            'top3_concentration': sum(h['weight'] for h in holdings[:3]), 'holdings': holdings,
            'realized_trades': round_trips, 'fifo_fragments': realized, 'daily_pnl': daily, 'risk': risk,
            'avg_holding_days': mean(x['holding_days'] for x in round_trips) if round_trips else None}


def intelligence(db: Session):
    o = overview(db)
    alerts = []
    if o['top2_concentration'] > .75:
        alerts.append({'severity': 'HIGH', 'title': 'Concentration risk', 'detail': f"Top 2 holdings represent {o['top2_concentration']*100:.1f}% of open book."})
    if o['top3_concentration'] > .90:
        alerts.append({'severity': 'HIGH', 'title': 'Top-3 concentration', 'detail': f"Top 3 holdings represent {o['top3_concentration']*100:.1f}% of open book."})
    missing = [h['security'] for h in o['holdings'] if h['ltp'] is None]
    if missing:
        alerts.append({'severity': 'INFO', 'title': 'Live quotes missing', 'detail': f"{len(missing)} open position(s) have no mapped live quote."})
    return {'alerts': alerts, 'metrics': {'realized_pnl': o['realized_pnl'], 'unrealized_pnl': o['unrealized_pnl'],
            'max_drawdown': o['risk']['max_drawdown'], 'volatility': o['risk']['volatility'],
            'sharpe_like': o['risk']['sharpe_like'], 'var_95': o['risk']['var_95'], 'cvar_95': o['risk']['cvar_95'],
            'avg_holding_days': o['avg_holding_days'], 'charge_drag': o['charge_drag']},
            'daily_pnl': o['daily_pnl'], 'holdings': o['holdings']}
