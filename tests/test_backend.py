import os,sys,subprocess
from pathlib import Path
from datetime import date,timedelta
ROOT=Path(__file__).resolve().parents[1];DB=ROOT/'tests'/'test_auth.db'
if DB.exists():DB.unlink()
os.environ['DATABASE_URL']=f'sqlite:///{DB}';os.environ['APP_ENV']='test';os.environ['AUTH_SECRET']='unit-test-secret-change-me-abcdefghijklmnopqrstuvwxyz';os.environ['CORS_ORIGINS']='http://localhost:5173';os.environ['AUTH_COOKIE_SECURE']='false';sys.path.insert(0,str(ROOT/'backend'))
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal,Base,engine
from app.models.entities import User,ContractNote,SecurityLedger,Execution,Portfolio
from app.services.auth import hash_password
from app.services.pdf_parser import parse_pdf
from app.services.analytics import overview
from app.services.excel_parity import build_excel_parity
PDF=Path('/mnt/data/14031_439710019.pdf');WORKBOOK=Path('/mnt/data/JM_Financial_Master_Trader_Dashboard.xlsx');SOURCE_AVAILABLE=PDF.exists() and WORKBOOK.exists()
def setup_module():Base.metadata.drop_all(bind=engine);Base.metadata.create_all(bind=engine)
def token_for(client,email,password='DemoPass123!'):
 r=client.post('/api/auth/login',json={'email':email,'password':password});assert r.status_code==200,r.text;return r.json()['access_token']
def seed_synthetic_demo():
 with SessionLocal() as db:
  if db.query(User).filter_by(email='demo@example.com').first():return
  user=User(email='demo@example.com',name='Demo User',password_hash=hash_password('DemoPass123!'),is_active=True);db.add(user);db.flush();portfolio=Portfolio(user_id=user.id,name='Main Portfolio',is_default=True);db.add(portfolio);db.flush();start=date(2026,1,5);trade_no=1000;contract_no=200000;securities=[(f'TEST SECURITY {i+1:02d}',f'INETEST{i+1:09d}') for i in range(65)];sec_cursor=0
  for n in range(33):
   td=start+timedelta(days=n);note=ContractNote(user_id=user.id,portfolio_id=portfolio.id,contract_note=str(contract_no+n),trade_date=td,settlement_date=td+timedelta(days=1),settlement_no=str(9000+n),source_file='synthetic-ci');db.add(note);db.flush();rows_for_note=2 if n<32 else 1
   for _ in range(rows_for_note):
    sec,isin=securities[sec_cursor];sec_cursor+=1;qty_buy=2;buy_gross=100.0+sec_cursor;after=-(buy_gross+0.25);db.add(SecurityLedger(user_id=user.id,portfolio_id=portfolio.id,contract_note=note.contract_note,trade_date=td,isin=isin,security=sec,buy_qty=qty_buy,buy_wap=buy_gross/qty_buy,buy_brokerage_share=0.125,buy_wap_after_brokerage=(buy_gross+0.25)/qty_buy,total_buy_value_after_brokerage=after,gross_buy=buy_gross,displayed_buy_brokerage=0.25,net_qty=qty_buy,net_obligation_before_levies=after));db.add(Execution(user_id=user.id,portfolio_id=portfolio.id,contract_note=note.contract_note,trade_date=td,order_no=str(700000+n),order_time='09:15:00',trade_no=str(trade_no),trade_time='09:15:01',security=sec,exchange='NSE',side='BUY',quantity=qty_buy,market_rate=buy_gross/qty_buy,amount=buy_gross));trade_no+=1;note.buy_qty+=qty_buy;note.gross_buy_value+=buy_gross;note.buy_value_after_brokerage+=after
  db.flush();execution_rows=db.query(Execution).filter_by(user_id=user.id,portfolio_id=portfolio.id).order_by(Execution.id).all()
  for e in execution_rows[:27]:
   sell_amount=e.amount+5.0;db.add(Execution(user_id=user.id,portfolio_id=portfolio.id,contract_note=e.contract_note,trade_date=e.trade_date,order_no=e.order_no+'S',order_time='10:00:00',trade_no=str(trade_no),trade_time='10:00:01',security=e.security,exchange='NSE',side='SELL',quantity=e.quantity,market_rate=sell_amount/e.quantity,amount=sell_amount));trade_no+=1
  db.commit()
def ensure_demo_data():
 if SOURCE_AVAILABLE:subprocess.check_call([sys.executable,str(ROOT/'scripts'/'seed_from_workbook.py'),str(WORKBOOK),'demo@example.com','DemoPass123!'],stdout=subprocess.DEVNULL)
 else:seed_synthetic_demo()
def test_pdf_parser_source_counts():
 if not SOURCE_AVAILABLE:import pytest;pytest.skip('JM source PDF is not part of repository/CI environment')
 parsed,errors=parse_pdf(PDF);assert not errors;assert len(parsed)==33;assert sum(len(x['securities']) for x in parsed)==65;assert sum(len(x['executions']) for x in parsed)==92
def test_seeded_dashboard_and_excel_parity():
 ensure_demo_data();
 with SessionLocal() as db:
  user=db.query(User).filter_by(email='demo@example.com').one();portfolio=db.query(Portfolio).filter_by(user_id=user.id).one();o=overview(db,user.id,portfolio.id);p=build_excel_parity(db,user.id,portfolio.id);assert o['contracts']==33 and o['executions']==92;assert len(p['workbook_tabs'])==22
  if SOURCE_AVAILABLE:assert o['open_qty']==276 and round(o['realized_pnl'],2)==16815.42 and round(o['gross_turnover'],2)==1015224.87 and round(o['open_book_cost'],2)==248440.32

def test_real_pdf_import_end_to_end_and_idempotency():
 if not SOURCE_AVAILABLE:import pytest;pytest.skip('Private source PDF is not part of CI')
 with TestClient(app) as client:
  reg=client.post('/api/auth/register',json={'name':'PDF Importer','email':'pdf@example.com','password':'PdfPass123!'});assert reg.status_code==200;h={'Authorization':f"Bearer {reg.json()['access_token']}"};pid=reg.json()['portfolio']['id']
  with PDF.open('rb') as f:r=client.post(f'/api/imports/upload?portfolio_id={pid}',headers=h,files={'files':('contract-notes.pdf',f,'application/pdf')});assert r.status_code==200,r.text
  with SessionLocal() as db:
   u=db.query(User).filter_by(email='pdf@example.com').one();assert db.query(ContractNote).filter_by(user_id=u.id,portfolio_id=pid).count()==33;assert db.query(Execution).filter_by(user_id=u.id,portfolio_id=pid).count()==92;assert db.query(SecurityLedger).filter_by(user_id=u.id,portfolio_id=pid).count()==65

def test_auth_cookie_rotation_profile_reset_isolation_and_portfolios():
 ensure_demo_data();
 with TestClient(app) as client:
  reg=client.post('/api/auth/register',json={'name':'Alice','email':'alice@example.com','password':'AlicePass123!'});assert reg.status_code==200;access=reg.json()['access_token'];assert client.cookies.get('jmti_refresh');ref=client.post('/api/auth/refresh');assert ref.status_code==200;assert client.cookies.get('jmti_refresh');new_access=ref.json()['access_token'];assert client.patch('/api/auth/profile',headers={'Authorization':f'Bearer {new_access}'},json={'name':'Alice Prime'}).status_code==200;np=client.post('/api/portfolios',headers={'Authorization':f'Bearer {new_access}'},json={'name':'Swing'});assert np.status_code==200;reset=client.post('/api/auth/password-reset/request',json={'email':'alice@example.com'});assert reset.status_code==200;assert client.post('/api/auth/password-reset/confirm',json={'token':reset.json().get('reset_token',''),'new_password':'AlicePass456!'}).status_code==200;assert client.post('/api/auth/login',json={'email':'alice@example.com','password':'AlicePass123!'}).status_code==401;demo=token_for(client,'demo@example.com');assert client.get('/api/dashboard',headers={'Authorization':f'Bearer {demo}'}).status_code==200;assert client.get('/api/dashboard',headers={'Authorization':f'Bearer {new_access}'}).json()['contracts']==0

def test_pagination_crud_protected_exports_and_background_import():
 ensure_demo_data();
 with TestClient(app) as client:
  token=token_for(client,'demo@example.com');h={'Authorization':f'Bearer {token}'}
  for path in ['/dashboard','/intelligence','/analytics/advanced','/risk','/performance/daily','/holdings','/realized','/missing-dates','/instrument-mappings','/quotes/latest','/excel-parity','/imports']:
   r=client.get('/api'+path,headers=h);assert r.status_code==200,(path,r.text)
  r=client.get('/api/tables/contracts?page=1&page_size=5',headers=h);assert r.status_code==200
  r=client.post('/api/instrument-mappings',headers=h,json={'isin':'INE000000000','security':'TEST','provider':'mock','instrument_key':'TEST'});assert r.status_code==200
  assert client.get('/api/export/contracts',headers=h).status_code==200

def test_unauthorized_and_health():
 with TestClient(app) as client:assert client.get('/api/dashboard').status_code==401;assert client.get('/api/excel-parity').status_code==401;assert client.get('/api/health').status_code==200;assert client.get('/api/health/ready').status_code==200;assert client.get('/api/metrics').status_code==200
