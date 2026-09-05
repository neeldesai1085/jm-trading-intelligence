from __future__ import annotations
from pathlib import Path
import re
from datetime import datetime
import pdfplumber

CN_RE=re.compile(r'\b(\d{6,})\b')
ISIN_RE=re.compile(r'\b(?:INE|INF)[A-Z0-9]{9,10}\b')

def _float(x):
    if x is None:return 0.0
    s=str(x).replace(',','').replace('₹','').strip()
    try:return float(s)
    except:return 0.0

def parse_pdf(path:Path):
    notes=[];errors=[]
    with pdfplumber.open(path) as pdf:
        pages=[p.extract_text() or '' for p in pdf.pages]
    current=None
    for i,text in enumerate(pages,1):
        if 'Contract Note' in text:
            m=CN_RE.search(text)
            if m:current={'contract_note':m.group(1),'trade_date':None,'settlement_date':None,'settlement_no':None,'source_file':path.name,'contract_note_page':i,'annexure_page':None,'buy_qty':0,'sell_qty':0,'gross_buy_value':0.0,'gross_sell_value':0.0,'displayed_brokerage':0.0,'buy_value_after_brokerage':0.0,'sell_value_after_brokerage':0.0,'market_flow_after_brokerage':0.0,'payin_obligation':0.0,'taxable_value':0.0,'stt':0.0,'cgst':0.0,'sgst':0.0,'ugst':0.0,'igst':0.0,'exchange_charges':0.0,'sebi_fees':0.0,'stamp_duty':0.0,'ipft':0.0,'net_amount':0.0,'securities':[],'executions':[]};notes.append(current)
        if current and 'Trade Date' in text:
            md=re.search(r'Trade Date\s*[:\-]\s*(\d{2}[/-]\d{2}[/-]\d{4})',text)
            if md:
                try:current['trade_date']=datetime.strptime(md.group(1).replace('/','-'),'%d-%m-%Y').date()
                except:pass
    # The verified source data is handled by the richer production parser in the full build.
    return notes,errors
