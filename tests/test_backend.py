import os,sys,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];DB=ROOT/'tests'/'test_auth.db'
if DB.exists():DB.unlink()
os.environ['DATABASE_URL']=f'sqlite:///{DB}';os.environ['APP_ENV']='test';os.environ['AUTH_SECRET']='unit-test-secret-change-me-abcdefghijklmnopqrstuvwxyz';os.environ['CORS_ORIGINS']='http://localhost:5173';sys.path.insert(0,str(ROOT/'backend'))
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal,Base,engine
from app.models.entities import User,Portfolio,ContractNote,Execution,SecurityLedger
from app.services.pdf_parser import parse_pdf
from app.services.analytics import overview
from app.services.excel_parity import build_excel_parity
PDF=Path('/mnt/data/14031_439710019.pdf');WORKBOOK=Path('/mnt/data/JM_Financial_Master_Trader_Dashboard.xlsx')
def setup_module():Base.metadata.drop_all(bind=engine);Base.metadata.create_all(bind=engine)
def token_for(c,email,password='DemoPass123!'):
 r=c.post('/api/auth/login',json={'email':email,'password':password});assert r.status_code==200,r.text;return r.json()['access_token']
def test_pdf_parser_source_counts():
 parsed,errors=parse_pdf(PDF);assert not errors and len(parsed)==33;assert sum(len(x['securities']) for x in parsed)==65;assert sum(len(x['executions']) for x in parsed)==92

def test_seeded_dashboard_and_parity():
 subprocess.check_call([sys.executable,str(ROOT/'scripts'/'seed_from_workbook.py'),str(WORKBOOK),'demo@example.com','DemoPass123!'],stdout=subprocess.DEVNULL)
 with SessionLocal() as db:
  u=db.query(User).filter_by(email='demo@example.com').one();p=db.query(Portfolio).filter_by(user_id=u.id).one();o=overview(db,u.id,p.id);x=build_excel_parity(db,u.id,p.id)
  assert (o['contracts'],o['executions'],o['open_qty'])==(33,92,276);assert round(o['realized_pnl'],2)==16815.42;assert round(o['gross_realized_pnl'],2)==18283.91;assert round(o['gross_turnover'],2)==1015224.87;assert round(o['open_book_cost'],2)==248440.32;assert len(x['workbook_tabs'])==22 and len(x['round_trips'])==12 and x['charge_allocation'];assert round(sum(r['pnl'] for r in x['round_trips']),2)==16815.42

def test_pdf_import_idempotency():
 with TestClient(app) as c:
  r=c.post('/api/auth/register',json={'name':'PDF','email':'pdf@example.com','password':'PdfPass123!'});assert r.status_code==200;h={'Authorization':f"Bearer {r.json()['access_token']}"};pid=r.json()['portfolio']['id']
  with PDF.open('rb') as f: assert c.post(f'/api/imports/upload?portfolio_id={pid}',headers=h,files={'files':('a.pdf',f,'application/pdf')}).status_code==200
  with PDF.open('rb') as f: assert c.post(f'/api/imports/upload?portfolio_id={pid}',headers=h,files={'files':('a.pdf',f,'application/pdf')}).status_code==200
  with SessionLocal() as db:
   u=db.query(User).filter_by(email='pdf@example.com').one();assert db.query(ContractNote).filter_by(user_id=u.id,portfolio_id=pid).count()==33;assert db.query(Execution).filter_by(user_id=u.id,portfolio_id=pid).count()==92;assert db.query(SecurityLedger).filter_by(user_id=u.id,portfolio_id=pid).count()==65

def test_auth_isolation_pagination_and_crud():
 with TestClient(app) as c:
  a=c.post('/api/auth/register',json={'name':'Alice','email':'alice@example.com','password':'AlicePass123!'}).json();h={'Authorization':f"Bearer {a['access_token']}"};assert c.cookies.get('jmti_refresh');assert c.post('/api/auth/refresh').status_code==200;assert c.patch('/api/auth/profile',headers=h,json={'name':'Alice Prime'}).status_code==200
  p=c.post('/api/portfolios',headers=h,json={'name':'Swing'}).json();assert c.get('/api/portfolios',headers=h).status_code==200
  reset=c.post('/api/auth/password-reset/request',json={'email':'alice@example.com'});assert reset.status_code==200;assert c.post('/api/auth/password-reset/confirm',json={'token':reset.json()['reset_token'],'new_password':'AlicePass456!'}).status_code==200
  demo=token_for(c,'demo@example.com');assert c.get('/api/dashboard',headers={'Authorization':f'Bearer {demo}'}).json()['contracts']==33;assert c.get(f"/api/dashboard?portfolio_id={p['id']}",headers=h).json()['contracts']==0
  assert c.get('/api/tables/contracts?page=1&page_size=5',headers={'Authorization':f'Bearer {demo}'}).json()['total']==33
  assert c.post('/api/instrument-mappings',headers={'Authorization':f'Bearer {demo}'},json={'isin':'INE000000000','security':'TEST','provider':'mock','instrument_key':'TEST'}).status_code==200
  assert c.get('/api/export/contracts',headers={'Authorization':f'Bearer {demo}'}).status_code==200

def test_protection_and_health():
 with TestClient(app) as c:
  assert c.get('/api/dashboard').status_code==401;assert c.get('/api/excel-parity').status_code==401;assert c.get('/api/health').status_code==200;assert c.get('/api/health/ready').status_code==200;assert c.get('/api/metrics').status_code==200
