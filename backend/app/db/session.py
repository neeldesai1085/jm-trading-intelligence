from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.core.config import settings

def _normalize(url: str) -> str:
    if url.startswith('postgres://'): return 'postgresql+psycopg://' + url[len('postgres://'):]
    if url.startswith('postgresql://'): return 'postgresql+psycopg://' + url[len('postgresql://'):]
    return url

database_url = _normalize(settings.database_url)
connect_args = {'check_same_thread': False} if database_url.startswith('sqlite') else {}
engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase): pass

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()
