import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.db.session import Base, engine
from app.api.routes import router
from app.core.config import settings
from app.services.auth import require_request_auth, auth_enabled
Base.metadata.create_all(bind=engine)
@asynccontextmanager
async def lifespan(app:FastAPI): yield
app=FastAPI(title='JM Trading Intelligence API',version='0.3.0',lifespan=lifespan)
origins=[x.strip() for x in settings.cors_origins.split(',') if x.strip()]
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_credentials=True,allow_methods=['*'],allow_headers=['*'])
@app.middleware('http')
async def auth_middleware(request:Request,call_next):
    path=request.url.path
    if auth_enabled() and path.startswith('/api/') and path not in {'/api/health','/api/auth/config','/api/auth/login'}:
        try: require_request_auth(request)
        except HTTPException as exc: return JSONResponse(status_code=exc.status_code,content={'detail':exc.detail})
    return await call_next(request)
@app.post('/api/auth/login')
async def login(payload:dict):
    from app.services.auth import check_credentials,issue_token
    name=str(payload.get('member_name','')).strip(); code=str(payload.get('access_code',''))
    if not check_credentials(name,code): raise HTTPException(status_code=401,detail='Invalid family access code')
    return {'token':issue_token(name),'member_name':name}
@app.get('/api/auth/config')
def auth_config(): return {'enabled':auth_enabled(),'app_name':settings.app_name,'session_hours':settings.auth_session_hours}
app.include_router(router,prefix='/api')
