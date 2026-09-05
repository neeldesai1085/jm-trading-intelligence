from contextlib import asynccontextmanager
from time import perf_counter
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router
from app.core.config import settings
from app.core.metrics import record
from app.db.session import Base, engine

if settings.app_env.lower()!='production': Base.metadata.create_all(bind=engine)
if settings.app_env.lower()=='production' and (not settings.auth_secret or len(settings.auth_secret)<32 or settings.auth_secret=='change-this-secret'): raise RuntimeError('AUTH_SECRET must be set to a random value of at least 32 characters in production')
if settings.app_env.lower()=='production' and not settings.auth_cookie_secure: raise RuntimeError('AUTH_COOKIE_SECURE must be true in production')

@asynccontextmanager
async def lifespan(app:FastAPI): yield

app=FastAPI(title='JM Trading Intelligence API',version='0.3.0',lifespan=lifespan)
origins=[x.strip() for x in settings.cors_origins.split(',') if x.strip()]
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_credentials=True,allow_methods=['*'],allow_headers=['*'])

@app.middleware('http')
async def request_metrics(request:Request,call_next):
    started=perf_counter(); response=None
    try: response=await call_next(request); return response
    finally:
        if response is not None: record(request.url.path,request.method,response.status_code,perf_counter()-started)

app.include_router(router,prefix='/api')
