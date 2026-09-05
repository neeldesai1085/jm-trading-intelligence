import re,subprocess
from datetime import datetime
from pathlib import Path
def num(x):
 s=str(x or '').replace(',','').replace('₹','').strip()
 if s in ('','-'):return 0.0
 try:return float(s)
 except ValueError:return 0.0
def dt(s):return datetime.strptime(s,'%d/%m/%Y').date()
def extract_text(path:Path):
 try:
  p=subprocess.run(['pdftotext','-layout',str(path),'-'],capture_output=True,text=True,encoding='utf-8',errors='ignore')
  if p.returncode==0 and p.stdout.strip():return p.stdout
 except Exception:pass
 import pdfplumber
 with pdfplumber.open(path) as pdf:return '\n'.join(page.extract_text(x_tolerance=1.5,y_tolerance=3) or '' for page in pdf.pages)
def blocks(text):
 starts=[m.start() for m in re.finditer(r'CONTRACT NOTE CUM BILL',text)];return [text[a:(starts[i+1] if i+1<len(starts) else len(text))] for i,a in enumerate(starts)]
SEC_RE=re.compile(r'^(IN[A-Z0-9]{10})\s+(.+?)\s+(\d[\d,]*)\s+([\d,.]+)\s+([\d,.]+)\s+([\d,.]+)\s+(-?[\d,.]+)\s+(\d[\d,]*)\s+([\d,.]+)\s+([\d,.]+)\s+([\d,.]+)\s+(-?[\d,.]+)\s+(-?\d[\d,]*)\s+(-?[\d,.]+)\s*$')
EXEC_RE=re.compile(r'^(\d+)\s+(\d{2}:\d{2}:\d{2})\s+(\d+)\s+(\d{2}:\d{2}:\d{2})\s+(.+?)\s+(NSE|BSE|MSEI|MCX|NCDEX)\s+(BUY|SELL)\s+(\d[\d,]*)\s+([\d,.]+)\s+([\d,.]+)\s*$')
CHARGE_PATTERNS={'taxable_value':r'Taxable Value of Supply3\s+[-\d,.]+\s+([-\d,.]+)','stt':r'Securities Transaction Tax \(Rs\.\)\s+[-\d,.]+\s+([-\d,.]+)','cgst':r'CGST4.*?\s+[-\d,.]+\s+([-\d,.]+)','sgst':r'SGST4.*?\s+[-\d,.]+\s+([-\d,.]+)','ugst':r'UGST4.*?\s+[-\d,.]+\s+([-\d,.]+)','igst':r'IGST4.*?\s+[-\d,.]+\s+([-\d,.]+)','exchange_charges':r'Exchange Transaction Charges \(Rs\.\)\s+[-\d,.]+\s+([-\d,.]+)','sebi_fees':r'SEBI turnover Fees \(Rs\.\)\s+[-\d,.]+\s+([-\d,.]+)','stamp_duty':r'Stamp Duty \(Rs\.\)\s+[-\d,.]+\s+([-\d,.]+)','ipft':r'IPFT Charges\s+[-\d,.]+\s+([-\d,.]+)','net_amount':r'Net amount receivable by Client.*?\s+([-\d,.]+)'}
def parse_block(block):
 m=re.search(r'CONTRACT NOTE NO\.\s*:\s*([0-9]+)',block);d=re.search(r'Trade Date\s*:\s*(\d{2}/\d{2}/\d{4})',block)
 if not(m and d):raise ValueError('Could not identify contract note number/date')
 note,trade_date=m.group(1),dt(d.group(1));sm=re.search(r'SETTLEMENT DATE\s+(\d{2}/\d{2}/\d{4})',block);settlement_date=dt(sm.group(1)) if sm else None;secs=[];execs=[]
 for line in block.splitlines():
  mm=SEC_RE.match(line.strip())
  if mm:
   g=mm.groups();secs.append(dict(trade_date=trade_date,contract_note=note,settlement_date=settlement_date,isin=g[0],security=g[1].strip(),buy_qty=int(num(g[2])),buy_wap=num(g[3]),buy_brokerage_share=num(g[4]),buy_wap_after_brokerage=num(g[5]),total_buy_value_after_brokerage=num(g[6]),sell_qty=int(num(g[7])),sell_wap=num(g[8]),sell_brokerage_share=num(g[9]),sell_wap_after_brokerage=num(g[10]),total_sell_value_after_brokerage=num(g[11]),net_qty=int(num(g[12])),net_obligation_before_levies=num(g[13])))
 ann=re.search(r'Annexure / Transactions',block)
 if ann:
  for line in block[ann.start():].splitlines():
   mm=EXEC_RE.match(line.strip())
   if mm:
    g=mm.groups();execs.append(dict(trade_date=trade_date,contract_note=note,order_no=g[0],order_time=g[1],trade_no=g[2],trade_time=g[3],security=g[4].strip(),exchange=g[5],side=g[6],quantity=int(num(g[7])),market_rate=num(g[8]),amount=num(g[9])))
 charges={k:(num(m.group(1)) if (m:=re.search(p,block,re.I|re.S)) else 0.0) for k,p in CHARGE_PATTERNS.items()};return {'contract_note':note,'trade_date':trade_date,'settlement_date':settlement_date,'securities':secs,'executions':execs,'charges':charges}
def parse_pdf(path:Path):
 text=extract_text(path);raw=blocks(text);parsed=[];errors=[];i=0
 while i<len(raw):
  try:parse_block(raw[i])
  except Exception:i+=1;continue
  combined=raw[i];j=i+1
  while j<len(raw):
   if re.search(r'CONTRACT NOTE NO\.\s*:\s*[0-9]+',raw[j]) and re.search(r'Trade Date\s*:',raw[j]):break
   combined+='\n'+raw[j];j+=1
  try:parsed.append(parse_block(combined))
  except Exception as e:errors.append(f'contract block {i+1}: {e}')
  i=j
 return parsed,errors
