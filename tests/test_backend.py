import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal
from app.services.pdf_parser import parse_pdf
from app.services.analytics import overview
from app.services.excel_parity import build_excel_parity

PDF=Path('/mnt/data/14031_439710019.pdf')
WORKBOOK=Path('/mnt/data/JM_Financial_Master_Trader_Dashboard.xlsx')

def test_pdf_parser_source_counts():
    parsed,errors=parse_pdf(PDF); assert not errors; assert len(parsed)==33
    assert sum(len(x['securities']) for x in parsed)==65; assert sum(len(x['executions']) for x in parsed)==92

def test_seeded_core_matches_source():
    if not WORKBOOK.exists(): return
    from subprocess import run
    run([sys.executable,'scripts/seed_from_workbook.py',str(WORKBOOK)],check=True)
    with SessionLocal() as db:
        o=overview(db); p=build_excel_parity(db)
        assert (o['contracts'],o['executions'],o['open_qty'])==(33,92,276)
        assert round(o['realized_pnl'],2)==16815.42; assert round(o['gross_realized_pnl'],2)==18283.91
        assert round(o['gross_turnover'],2)==1015224.87; assert round(o['open_book_cost'],2)==248440.32
        assert len(p['workbook_tabs'])==22; assert len(p['round_trips'])==12
        assert round(sum(x['pnl'] for x in p['round_trips']),2)==16815.42

def test_http_smoke():
    with TestClient(app) as c:
        assert c.get('/api/health').status_code==200
        r=c.get('/api/excel-parity'); assert r.status_code==200; assert len(r.json()['workbook_tabs'])==22
        assert c.get('/api/dashboard').status_code==200
