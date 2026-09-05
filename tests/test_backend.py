import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'tests' / 'ci_test.db'
if DB.exists():
    DB.unlink()
os.environ['DATABASE_URL'] = f'sqlite:///{DB}'
os.environ['APP_ENV'] = 'test'
os.environ['AUTH_SECRET'] = 'unit-test-secret-change-me-abcdefghijklmnopqrstuvwxyz'
os.environ['AUTH_COOKIE_SECURE'] = 'false'
sys.path.insert(0, str(ROOT / 'backend'))

from fastapi.testclient import TestClient
from app.main import app
from app.db.session import Base, engine


def setup_module():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_health_and_protected_routes():
    with TestClient(app) as client:
        assert client.get('/api/health').status_code == 200
        assert client.get('/api/dashboard').status_code == 401
        assert client.get('/api/excel-parity').status_code == 401


def test_auth_and_refresh():
    with TestClient(app) as client:
        r = client.post('/api/auth/register', json={'name': 'CI User', 'email': 'ci@example.com', 'password': 'CiPass123!'})
        assert r.status_code == 200, r.text
        token = r.json()['access_token']
        refresh_token = r.json()['refresh_token']
        assert refresh_token
        assert client.get('/api/auth/me', headers={'Authorization': f'Bearer {token}'}).status_code == 200
        refreshed = client.post('/api/auth/refresh', json={'refresh_token': refresh_token})
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()['access_token']
        assert refreshed.json()['refresh_token'] != refresh_token


def test_source_regression_when_private_file_is_available():
    pdf = Path('/mnt/data/14031_439710019.pdf')
    if not pdf.exists():
        import pytest
        pytest.skip('Private JM source PDF is intentionally not committed to CI')
    from app.services.pdf_parser import parse_pdf
    parsed, errors = parse_pdf(pdf)
    assert not errors
    assert len(parsed) == 33
    assert sum(len(x['securities']) for x in parsed) == 65
    assert sum(len(x['executions']) for x in parsed) == 92


def test_excel_parity_smoke():
    with TestClient(app) as client:
        r = client.post('/api/auth/register', json={'name': 'Parity', 'email': 'parity@example.com', 'password': 'Parity123!'})
        assert r.status_code == 200
        h = {'Authorization': f"Bearer {r.json()['access_token']}"}
        r = client.get('/api/excel-parity', headers=h)
        assert r.status_code == 200, r.text
        assert len(r.json()['workbook_tabs']) == 22
