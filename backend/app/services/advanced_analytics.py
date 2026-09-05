from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from statistics import mean, pstdev

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import Execution, MarketQuote, SecurityLedger
from app.services.analytics import fifo_lots


def _pct(value: float) -> float:
    return round(value * 100, 2)


def _benchmark(db: Session, user_id: int, portfolio_id: int | None, holdings: list[dict]) -> dict:
    rows = db.scalars(
        select(MarketQuote)
        .where(MarketQuote.user_id == user_id)
        .order_by(MarketQuote.as_of)
    ).all()
    grouped = defaultdict(list)
    for row in rows:
        if row.ltp is not None:
            grouped[row.isin].append(row)

    benchmark_rows = grouped.get(settings.benchmark_isin, [])
    result = {
        'name': 'NIFTY 50',
        'symbol': settings.benchmark_yahoo_symbol,
        'points': 0,
        'beta': None,
        'alpha_like': None,
        'message': 'Collect portfolio and NIFTY 50 quote snapshots to calculate beta/alpha-like estimates.',
    }
    if len(benchmark_rows) < 3 or not holdings:
        return result

    timestamps = sorted({row.as_of for row in rows if row.isin != settings.benchmark_isin})
    portfolio_values = []
    benchmark_values = []
    for timestamp in timestamps:
        portfolio_value = 0.0
        complete = True
        for holding in holdings:
            history = [r for r in grouped.get(holding['isin'], []) if r.as_of <= timestamp]
            if not history:
                complete = False
                break
            portfolio_value += history[-1].ltp * holding['quantity']
        benchmark_history = [r for r in benchmark_rows if r.as_of <= timestamp]
        if complete and benchmark_history:
            portfolio_values.append(portfolio_value)
            benchmark_values.append(benchmark_history[-1].ltp)

    portfolio_returns = [b / a - 1 for a, b in zip(portfolio_values, portfolio_values[1:]) if a]
    benchmark_returns = [b / a - 1 for a, b in zip(benchmark_values, benchmark_values[1:]) if a]
    paired = list(zip(portfolio_returns, benchmark_returns))
    result['points'] = len(paired)
    if len(paired) < 3:
        return result

    portfolio_mean = mean(x for x, _ in paired)
    benchmark_mean = mean(y for _, y in paired)
    covariance = mean((x - portfolio_mean) * (y - benchmark_mean) for x, y in paired)
    benchmark_variance = mean((y - benchmark_mean) ** 2 for _, y in paired)
    beta = covariance / benchmark_variance if benchmark_variance else None
    result['beta'] = beta
    result['alpha_like'] = portfolio_mean - beta * benchmark_mean if beta is not None else None
    result['message'] = 'Approximate beta/alpha-like estimates use synchronized portfolio and NIFTY 50 quote snapshots.'
    return result


def advanced(db: Session, user_id: int, portfolio_id: int | None = None):
    query = select(Execution).where(Execution.user_id == user_id)
    if portfolio_id is not None:
        query = query.where(Execution.portfolio_id == portfolio_id)
    executions = db.scalars(query.order_by(Execution.trade_date, Execution.trade_time, Execution.id)).all()
    closed, open_lots = fifo_lots(db, user_id, portfolio_id)
    pnls = [row['pnl'] for row in closed]
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    expectancy = mean(pnls) if pnls else 0
    profit_factor = sum(wins) / abs(sum(losses)) if losses else None

    daily = defaultdict(float)
    for row in closed:
        daily[str(row['sell_date'])] += row['pnl']
    curve = peak = 0.0
    drawdowns = []
    for value in [daily[key] for key in sorted(daily)]:
        curve += value
        peak = max(peak, curve)
        drawdowns.append(curve - peak)
    returns = list(daily.values())
    volatility = pstdev(returns) if len(returns) > 1 else 0
    sharpe = mean(returns) / volatility if volatility else None
    holding_days = [
        (row['sell_date'] - row['buy_date']).days
        for row in closed
        if isinstance(row['sell_date'], date) and isinstance(row['buy_date'], date)
    ]

    quote_rows = db.scalars(
        select(MarketQuote).where(MarketQuote.user_id == user_id).order_by(MarketQuote.as_of.desc())
    ).all()
    latest = {}
    for row in quote_rows:
        latest.setdefault(row.isin, row)

    ledger_query = select(SecurityLedger).where(SecurityLedger.user_id == user_id)
    if portfolio_id is not None:
        ledger_query = ledger_query.where(SecurityLedger.portfolio_id == portfolio_id)
    ledger_rows = db.scalars(ledger_query.order_by(SecurityLedger.trade_date, SecurityLedger.id)).all()
    security_to_isin = {}
    for row in ledger_rows:
        security_to_isin.setdefault(row.security, row.isin)

    holdings_map = defaultdict(lambda: {'quantity': 0, 'book_cost': 0.0})
    for lot in open_lots:
        holdings_map[lot['security']]['quantity'] += lot['qty']
        holdings_map[lot['security']]['book_cost'] += lot['qty'] * lot['unit_cost']
    holdings = []
    for security, value in sorted(holdings_map.items()):
        isin = security_to_isin.get(security)
        quote = latest.get(isin)
        market_value = quote.ltp * value['quantity'] if quote and quote.ltp is not None else None
        holdings.append({'security': security, 'isin': isin, **value, 'market_value': market_value, 'quote_as_of': quote.as_of if quote else None})

    return {
        'trades': len(closed),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': _pct(len(wins) / len(pnls)) if pnls else 0,
        'expectancy': expectancy,
        'profit_factor': profit_factor,
        'max_drawdown': min(drawdowns) if drawdowns else 0,
        'volatility': volatility,
        'sharpe_like': sharpe,
        'avg_holding_days': mean(holding_days) if holding_days else None,
        'max_holding_days': max(holding_days) if holding_days else None,
        'closed': closed,
        'open_lots': open_lots,
        'holdings': holdings,
        'benchmark': _benchmark(db, user_id, portfolio_id, holdings),
        'generated_at': datetime.now(timezone.utc).isoformat(),
    }
