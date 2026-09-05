import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.db.session import Base, engine
from app.api.routes import router
from app.core.config import settings

Base.metadata.create_all(bind=engine)

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(title='JM Trading Intelligence API', version='0.2.0', lifespan=lifespan)
origins = [x.strip() for x in settings.cors_origins.split(',') if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
app.include_router(router, prefix='/api')
