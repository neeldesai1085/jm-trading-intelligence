from collections import defaultdict
from statistics import mean,median
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.entities import ContractNote,SecurityLedger,Execution
from app.services.analytics import fifo,overview

WORKBOOK_TABS=['Dashboard','Trader Review','Source of Truth','Dashboard Calc','Contract Notes','Security Ledger','Execution Ledger','Charges Detail','Charge Summary','Charge Allocation','FIFO / Realized P&L','Open Holdings','Realized P&L by Security','Security Summary','Monthly Performance','Cumulative P&L','Reconciliation','Performance Metrics','Source Audit','Data Dictionary','Report Notes','Master Calc']
DATA_DICTIONARY=[
 {'field':'Gross Buy / Sell Value','definition':'Sum of individual exchange execution Amount values for BUY/SELL records.'},
 {'field':'Buy/Sell Value After Brokerage','definition':'Contract-note security table total after brokerage.'},
 {'field':'Displayed Brokerage','definition':'Quantity multiplied by brokerage-per-share shown in the contract note; displayed rates are rounded.'},
 {'field':'Gross Realized P&L','definition':'Gross FIFO sale proceeds less gross FIFO acquisition cost using execution-level amounts.'},
 {'field':'Realized P&L After Brokerage','definition':'FIFO realized P&L using contract-note after-brokerage security totals.'},
 {'field':'Allocated Non-Brokerage Charges','definition':'Analytical allocation of contract-level levies to closed securities; not a tax computation.'},
 {'field':'Open Book Cost','definition':'Cost of shares remaining open after brokerage using FIFO lots.'},
 {'field':'Taxable Value of Supply','definition':'Source-reported taxable-value base; not an additional charge.'},
 {'field':'Net Amount','definition':'Source-reported final cash amount receivable/payable on each contract note.'},
]

def r(v):return round(v,2) if isinstance(v,(int,float)) else v
def month(d):return d.strftime('%Y-%m') if d else None

def build_excel_parity(db:Session,user_id:int):
 o=overview(db,user_id);notes=db.scalars(select(ContractNote).where(ContractNote.user_id==user_id).order_by(ContractNote.trade_date,ContractNote.id)).all();secs=db.scalars(select(SecurityLedger).where(SecurityLedger.user_id==user_id).order_by(SecurityLedger.trade_date,SecurityLedger.id)).all();execs=db.scalars(select(Execution).where(Execution.user_id==user_id).order_by(Execution.trade_date,Execution.trade_time,Execution.id)).all();realized,_=fifo(db,user_id)
 gross_by_note=defaultdict(lambda:{'buy':0,'sell':0,'bq':0,'sq':0})
 for e in execs:
  x=gross_by_note[e.contract_note];x['buy' if e.side=='BUY' else 'sell']+=e.amount;x['bq' if e.side=='BUY' else 'sq']+=e.quantity
 buy_rate={(s.security,s.trade_date):(-s.total_buy_value_after_brokerage)/s.buy_qty for s in secs if s.buy_qty};sell_rate={(s.security,s.trade_date):s.total_sell_value_after_brokerage/s.sell_qty for s in secs if s.sell_qty}
 trips=defaultdict(lambda:{'qty':0,'pnl':0,'gross_pnl':0,'cost':0})
 for x in realized:
  g=trips[(x['security'],x['buy_date'],x['sell_date'])];g['qty']+=x['qty'];g['gross_pnl']+=x['pnl'];br=buy_rate.get((x['security'],x['buy_date']));sr=sell_rate.get((x['security'],x['sell_date']));g['cost']+=x['qty']*br if br is not None else 0;g['pnl']+=x['qty']*(sr-br) if br is not None and sr is not None else x['pnl']
 round_trips=[{'security':k[0],'buy_date':k[1],'sell_date':k[2],'qty':v['qty'],'pnl':r(v['pnl']),'gross_pnl':r(v['gross_pnl']),'return':r(v['pnl']/v['cost']) if v['cost'] else 0,'holding_days':(k[2]-k[1]).days} for k,v in trips.items()];round_trips.sort(key=lambda x:(x['sell_date'],x['buy_date'],x['security']))
 wins=sum(x['pnl']>0 for x in round_trips);losses=sum(x['pnl']<0 for x in round_trips);gross_turnover=sum(e.amount for e in execs);gross_buy=sum(e.amount for e in execs if e.side=='BUY');gross_sell=sum(e.amount for e in execs if e.side=='SELL');brokerage=o['brokerage'];levies=o['non_brokerage_charges'];gross_realized=o['gross_realized_pnl'];realized_after=sum(x['pnl'] for x in round_trips)
 pf=sum(x['pnl'] for x in round_trips if x['pnl']>0)/abs(sum(x['pnl'] for x in round_trips if x['pnl']<0)) if losses else None;payoff=mean([x['pnl'] for x in round_trips if x['pnl']>0])/abs(mean([x['pnl'] for x in round_trips if x['pnl']<0])) if losses and wins else None
 metrics={'contract_notes':o['contracts'],'execution_records':o['executions'],'unique_securities':o['unique_securities'],'gross_turnover':r(gross_turnover),'gross_buy_turnover':r(gross_buy),'gross_sell_turnover':r(gross_sell),'gross_realized_pnl':r(gross_realized),'realized_pnl_after_brokerage':r(realized_after),'displayed_brokerage':r(brokerage),'non_brokerage_levies':r(levies),'total_actual_charges':r(brokerage+levies),'open_book_cost':r(o['open_book_cost']),'open_qty':o['open_qty'],'win_rate':wins/len(round_trips) if round_trips else None,'wins':wins,'losses':losses,'profit_factor':r(pf) if pf is not None else None,'payoff_ratio':r(payoff) if payoff is not None else None,'avg_holding_days':r(mean([x['holding_days'] for x in round_trips])) if round_trips else None,'median_round_trip_pnl':r(median([x['pnl'] for x in round_trips])) if round_trips else None,'top2_concentration':o['top2_concentration'],'top3_concentration':o['top3_concentration']}
 monthly=defaultdict(lambda:{'month':None,'buy_qty':0,'sell_qty':0,'gross_buy_value':0,'gross_sell_value':0,'buy_executions':0,'sell_executions':0,'gross_turnover':0,'net_market_flow':0,'net_amount':0,'non_brokerage_charges':0,'realized_pnl':0})
 for n in notes:
  m=monthly[month(n.trade_date)];m['month']=month(n.trade_date);m['net_amount']+=n.net_amount;m['non_brokerage_charges']+=sum(getattr(n,f) for f in ('stt','cgst','sgst','ugst','igst','exchange_charges','sebi_fees','stamp_duty','ipft'))
 for e in execs:
  m=monthly[month(e.trade_date)];m['month']=month(e.trade_date);m['gross_turnover']+=e.amount
  if e.side=='BUY':m['buy_qty']+=e.quantity;m['buy_executions']+=1;m['gross_buy_value']+=e.amount
  else:m['sell_qty']+=e.quantity;m['sell_executions']+=1;m['gross_sell_value']+=e.amount
 for x in round_trips:monthly[month(x['sell_date'])]['realized_pnl']+=x['pnl']
 monthly_rows=[]
 for m in monthly.values():m['net_market_flow']=m['gross_sell_value']-m['gross_buy_value'];monthly_rows.append({k:r(v) for k,v in m.items()})
 monthly_rows.sort(key=lambda x:x['month'] or '')
 sec=defaultdict(lambda:{'isin':'','security':'','buy_qty':0,'sell_qty':0,'gross_buy_value':0,'gross_sell_value':0,'buy_after_brokerage':0,'sell_after_brokerage':0,'brokerage':0})
 for s in secs:
  x=sec[s.isin];x['isin']=s.isin;x['security']=s.security;x['buy_qty']+=s.buy_qty;x['sell_qty']+=s.sell_qty;x['gross_buy_value']+=s.gross_buy;x['gross_sell_value']+=s.gross_sell;x['buy_after_brokerage']+=-s.total_buy_value_after_brokerage;x['sell_after_brokerage']+=s.total_sell_value_after_brokerage;x['brokerage']+=s.displayed_buy_brokerage+s.displayed_sell_brokerage
 sec_rows=[]
 for x in sec.values():
  x['net_qty']=x['buy_qty']-x['sell_qty'];x['turnover']=x['gross_buy_value']+x['gross_sell_value'];x['status']='CLOSED' if x['net_qty']==0 else 'OPEN';x['avg_book_cost']=x['buy_after_brokerage']/x['buy_qty'] if x['buy_qty'] else None;x['pnl_after_brokerage']=r(sum(t['pnl'] for t in round_trips if t['security']==x['security'])) if x['status']=='CLOSED' else None;sec_rows.append({k:r(v) for k,v in x.items()})
 realized_by=[]
 for x in sec_rows:
  if x['status']=='CLOSED':realized_by.append({'isin':x['isin'],'security':x['security'],'qty':x['sell_qty'],'realized_pnl':x['pnl_after_brokerage'],'return':r(x['pnl_after_brokerage']/x['buy_after_brokerage']) if x['buy_after_brokerage'] else None})
 charge_fields=[('Brokerage (displayed)',brokerage),('STT',sum(n.stt for n in notes)),('CGST',sum(n.cgst for n in notes)),('SGST',sum(n.sgst for n in notes)),('UGST',sum(n.ugst for n in notes)),('IGST',sum(n.igst for n in notes)),('Exchange Transaction Charges',sum(n.exchange_charges for n in notes)),('SEBI Turnover Fees',sum(n.sebi_fees for n in notes)),('Stamp Duty',sum(n.stamp_duty for n in notes)),('IPFT Charges',sum(n.ipft for n in notes))];charges=[{'charge_type':k,'amount':r(v),'pct_turnover':r(v/gross_turnover) if gross_turnover else 0} for k,v in charge_fields]
 cumulative=[];run=peak=0
 for x in o['daily_pnl']:
  run+=x['pnl'];peak=max(peak,run);cumulative.append({'date':x['date'],'daily_pnl':r(x['pnl']),'cumulative_pnl':r(run),'drawdown':r(run-peak)})
 contract_rows=[]
 for n in notes:
  g=gross_by_note[n.contract_note];contract_rows.append({'contract_note':n.contract_note,'trade_date':n.trade_date.isoformat(),'settlement_no':n.settlement_no,'settlement_date':n.settlement_date.isoformat() if n.settlement_date else None,'buy_qty':g['bq'] or n.buy_qty,'sell_qty':g['sq'] or n.sell_qty,'gross_buy_value':r(g['buy'] or n.gross_buy_value),'gross_sell_value':r(g['sell'] or n.gross_sell_value),'gross_turnover':r((g['buy']+g['sell']) or n.gross_buy_value+n.gross_sell_value),'displayed_brokerage':r(n.displayed_brokerage),'buy_value_after_brokerage':r(n.buy_value_after_brokerage),'sell_value_after_brokerage':r(n.sell_value_after_brokerage),'market_flow_after_brokerage':r(n.market_flow_after_brokerage),'payin_obligation':r(n.payin_obligation),'taxable_value':r(n.taxable_value),'stt':r(n.stt),'cgst':r(n.cgst),'sgst':r(n.sgst),'ugst':r(n.ugst),'igst':r(n.igst),'exchange_charges':r(n.exchange_charges),'sebi_fees':r(n.sebi_fees),'stamp_duty':r(n.stamp_duty),'ipft':r(n.ipft),'net_amount':r(n.net_amount)})
 execution_rows=[{'trade_date':e.trade_date.isoformat(),'contract_note':e.contract_note,'order_no':e.order_no,'order_time':e.order_time,'trade_no':e.trade_no,'trade_time':e.trade_time,'security':e.security,'exchange':e.exchange,'side':e.side,'quantity':e.quantity,'market_rate':r(e.market_rate),'amount':r(e.amount)} for e in execs]
 reconciliation=[{'item':'Gross buy value from exchange executions','amount':r(gross_buy)},{'item':'Gross sell value from exchange executions','amount':r(gross_sell)},{'item':'Gross market cash flow','amount':r(gross_sell-gross_buy)},{'item':'Contract-note buy value after brokerage','amount':r(sum(-s.total_buy_value_after_brokerage for s in secs))},{'item':'Contract-note sell value after brokerage','amount':r(sum(s.total_sell_value_after_brokerage for s in secs))},{'item':'Total actual charges','amount':r(o['total_charges'])},{'item':'Source net amount','amount':r(sum(n.net_amount for n in notes))},{'item':'Realized P&L after brokerage','amount':r(realized_after)}]
 dashboard={'title':'JM FINANCIAL — MASTER TRADER PERFORMANCE DASHBOARD','source_scope':f"{o['contracts']} contract notes • {o['executions']} executions • {o['unique_securities']} securities",'metrics':metrics,'top_open':o['holdings'][:6],'round_trips':round_trips,'monthly':monthly_rows,'alerts':[]}
 if o['top3_concentration']>.90:dashboard['alerts'].append('Top 3 open positions exceed 90% of open book cost.')
 trader_review={'executive_conclusion':f"Closed-trade performance is {'strong' if realized_after>0 else 'negative'}: ₹{realized_after:,.2f} realized P&L after brokerage across {len(round_trips)} FIFO round trips, {wins} winners and {losses} losers.",'priority_flags':[{'priority':1,'area':'Capital concentration','finding':f"Top 3 open positions represent {o['top3_concentration']*100:.1f}% of open book cost."},{'priority':2,'area':'Cost efficiency','finding':f"All-in charges are {(o['total_charges']/gross_turnover*10000 if gross_turnover else 0):.1f} bps of gross turnover."},{'priority':3,'area':'Trade quality','finding':f"{wins}/{len(round_trips)} FIFO round trips were profitable."}]}
 source={'workbook_source':'JM Financial contract-note source','contract_notes':o['contracts'],'executions':o['executions'],'unique_securities':o['unique_securities'],'gross_turnover':r(gross_turnover),'realized_pnl_after_brokerage':r(realized_after),'total_actual_charges':r(o['total_charges']),'open_book_cost':r(o['open_book_cost'])}
 return {'workbook_tabs':WORKBOOK_TABS,'dashboard':dashboard,'trader_review':trader_review,'source_of_truth':source,'dashboard_calc':monthly_rows,'metrics':metrics,'monthly':monthly_rows,'securities':sec_rows,'realized_by_security':realized_by,'holdings':o['holdings'],'cumulative_pnl':cumulative,'charges':charges,'charge_allocation':[],'round_trips':round_trips,'contract_notes':contract_rows,'executions':execution_rows,'reconciliation':reconciliation,'performance_metrics':[{'metric':k,'value':v} for k,v in metrics.items()],'source_audit':contract_rows,'data_dictionary':DATA_DICTIONARY,'report_notes':[{'topic':'P&L method','note':'FIFO matching with contract-note after-brokerage rates.'},{'topic':'Charges','note':'Source-reported levies are preserved separately.'}],'master_calc':cumulative}
