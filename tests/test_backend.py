import os, sys, subprocess
from pathlib import Path
from datetime import date, timedelta

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'tests' / 'test_auth.db'
if DB.exists(): DB.unlink()
os.environ['DATABASE_URL'] = f'sqlite:///{DB}'
os.environ['APP_ENV'] = 'test'
os.environ['AUTH_SECRET'] = 'unit-test-secret-change-me-abcdefghijklmnopqrstuvwxyz'
os.environ['CORS_ORIGINS'] = 'http://localhost:5173'
os.environ['AUTH_COOKIE_SECURE'] = 'false'
sys.path.insert(0, str(ROOT / 'backend'))

from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal, Base, engine
from app.models.entities import User, ContractNote, SecurityLedger, Execution, Portfolio
from app.services.auth import hash_password
from app.services.pdf_parser import parse_pdf
from app.services.analytics import overview
from app.services.excel_parity import build_excel_parity

PDF = Path('/mnt/data/14031_439710019.pdf')
WORKBOOK = Path('/mnt/data/JM_Financial_Master_Trader_Dashboard.xlsx')
SOURCE_AVAILABLE = PDF.exists() and WORKBOOK.exists()


def setup_module():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def token_for(client, email, password='DemoPass123!'):
    response = client.post('/api/auth/login', json={'email': email, 'password': password})
    assert response.status_code == 200, response.text
    return response.json()['access_token']


def seed_demo():
    with SessionLocal() as db:
        if db.query(User).filter_by(email='demo@example.com').first(): return
        user = User(email='demo@example.com', name='Demo User', password_hash=hash_password('DemoPass123!'), is_active=True)
        db.add(user); db.flush()
        portfolio = Portfolio(user_id=user.id, name='Main Portfolio', is_default=True)
        db.add(portfolio); db.flush()
        start = date(2026, 1, 5); trade_no = 1000
        for n in range(33):
            td = start + timedelta(days=n)
            note = ContractNote(user_id=user.id, portfolio_id=portfolio.id, contract_note=str(200000+n), trade_date=td, settlement_date=td+timedelta(days=1), source_file='synthetic-ci')
            db.add(note); db.flush()
            rows = 2 if n < 32 else 1
            for j in range(rows):
                isin = f'INECI{n:06d}{j:02d}'; security = f'TEST SECURITY {n:02d}-{j}'
                qty = 2; gross = 100.0 + n + j; after = -(gross + 0.25)
                db.add(SecurityLedger(user_id=user.id, portfolio_id=portfolio.id, contract_note=note.contract_note, trade_date=td, isin=isin, security=security, buy_qty=qty, buy_wap=gross/qty, buy_brokerage_share=.125, buy_wap_after_brokerage=(gross+.25)/qty, total_buy_value_after_brokerage=after, gross_buy=gross, displayed_buy_brokerage=.25, net_qty=qty, net_obligation_before_levies=after))
                db.add(Execution(user_id=user.id, portfolio_id=portfolio.id, contract_note=note.contract_note, trade_date=td, order_no=str(700000+n), order_time='09:15:00', trade_no=str(trade_no), trade_time='09:15:01', security=security, exchange='NSE', side='BUY', quantity=qty, market_rate=gross/qty, amount=gross)); trade_no += 1
                note.buy_qty += qty; note.gross_buy_value += gross; note.buy_value_after_brokerage += after
        db.commit()


def ensure_demo_data():
    if SOURCE_AVAILABLE:
        subprocess.check_call([sys.executable, str(ROOT/'scripts'/'seed_from_workbook.py'), str(WORKBOOK), 'demo@example.com', 'DemoPass123!'], stdout=subprocess.DEVNULL)
    else: seed_demo()


def test_pdf_parser_source_counts():
    if not SOURCE_AVAILABLE:
        import pytest; pytest.skip('JM source PDF is not part of CI environment')
    parsed, errors = parse_pdf(PDF)
    assert not errors and len(parsed) == 33
    assert sum(len(x['securities']) for x in parsed) == 65
    assert sum(len(x['executions']) for x in parsed) == 92


def test_seeded_dashboard_and_excel_parity():
    ensure_demo_data()
    with SessionLocal() as db:
        user = db.query(User).filter_by(email='demo@example.com').one(); portfolio = db.query(Portfolio).filter_by(user_id=user.id).one()
        result = overview(db, user.id, portfolio.id); parity = build_excel_parity(db, user.id, portfolio.id)
        assert result['contracts'] == 33 and result['executions'] >= 33
        assert len(parity['workbook_tabs']) == 22


def test_pdf_import_and_idempotency():
    if not SOURCE_AVAILABLE:
        import pytest; pytest.skip('Private source PDF is not part of CI')
    with TestClient(app) as client:
        reg = client.post('/api/auth/register', json={'name':'PDF Importer','email':'pdf@example.com','password':'PdfPass123!'})
        assert reg.status_code == 200; headers = {'Authorization': f"Bearer {reg.json()['access_token']}"}; pid = reg.json()['portfolio']['id']
        with PDF.open('rb') as f:
            response = client.post(f'/api/imports/upload?portfolio_id={pid}', headers=headers, files={'files':('contract-notes.pdf', f, 'application/pdf')})
        assert response.status_code == 200, response.text
        with PDF.open('rb') as f:
            response2 = client.post(f'/api/imports/upload?portfolio_id={pid}', headers=headers, files={'files':('contract-notes.pdf', f, 'application/pdf')})
        assert response2.status_code == 200, response2.text
        with SessionLocal() as db:
            user = db.query(User).filter_by(email='pdf@example.com').one()
            assert db.query(ContractNote).filter_by(user_id=user.id, portfolio_id=pid).count() == 33
            assert db.query(Execution).filter_by(user_id=user.id, portfolio_id=pid).count() == 92
            assert db.query(SecurityLedger).filter_by(user_id=user.id, portfolio_id=pid).count() == 65


def test_auth_isolation_and_password_change():
    ensure_demo_data()
    with TestClient(app) as client:
        reg = client.post('/api/auth/register', json={'name':'Alice','email':'alice@example.com','password':'AlicePass123!'})
        assert reg.status_code == 200; access = reg.json()['access_token']; assert client.cookies.get('jmti_refresh')
        assert client.get('/api/auth/me', headers={'Authorization': f'Bearer {access}'}).json()['email'] == 'alice@example.com'
        assert client.post('/api/auth/refresh').status_code == 200
        assert client.patch('/api/auth/profile', headers={'Authorization': f'Bearer {access}'}, json={'name':'Alice Prime'}).status_code == 200
        assert client.post('/api/auth/change-password', headers={'Authorization': f'Bearer {access}'}, json={'current_password':'AlicePass123!','new_password':'AlicePass456!'}).status_code == 200
        assert client.post('/api/auth/login', json={'email':'alice@example.com','password':'AlicePass123!'}).status_code == 401
        assert client.post('/api/auth/login', json={'email':'alice@example.com','password':'AlicePass456!'}).status_code == 200
        demo = token_for(client, 'demo@example.com')
        assert client.get('/api/dashboard', headers={'Authorization': f'Bearer {access}'}).json()['contracts'] == 0
        assert client.get('/api/dashboard', headers={'Authorization': f'Bearer {demo}'}).json()['contracts'] == 33


def test_api_surface_and_exports():
    ensure_demo_data()
    with TestClient(app) as client:
        headers = {'Authorization': f"Bearer {token_for(client, 'demo@example.com')}"}
        for path in ['/dashboard','/intelligence','/analytics/advanced','/risk','/performance/daily','/holdings','/realized','/missing-dates','/instrument-mappings','/quotes/latest','/excel-parity','/imports']:
            response = client.get('/api'+path, headers=headers); assert response.status_code == 200, (path, response.text)
        response = client.post('/api/instrument-mappings', headers=headers, json={'isin':'INE000000000','security':'TEST','provider':'yahoo','instrument_key':'TEST.NS'}); assert response.status_code == 200
        assert client.get('/api/export/contracts', headers=headers).status_code == 200
        assert client.get('/api/tables/contracts?page=1&page_size=5', headers=headers).status_code == 200
        assert client.get('/api/tables/executions?page=1&page_size=10', headers=headers).status_code == 200


def test_health_unauthorized_and_no_removed_endpoints():
    with TestClient(app) as client:
        assert client.get('/api/health').status_code == 200
        assert client.get('/api/health/ready').status_code == 200
        assert client.get('/api/metrics').status_code == 200
        assert client.get('/api/dashboard').status_code == 401
        assert client.post('/api/auth/password-reset/request', json={'email':'demo@example.com'}).status_code == 404
        assert client.post('/api/auth/verification/request').status_code == 401
