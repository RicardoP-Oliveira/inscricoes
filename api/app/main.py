from contextlib import asynccontextmanager
from fastapi import FastAPI
from .db import close_pool, init_pool
from .routes import admin, auth, publico

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    yield
    await close_pool()

app = FastAPI(title="Inscricoes", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(publico.router, prefix="/api")
app.include_router(auth.router, prefix="/api/auth")
app.include_router(admin.router, prefix="/api/admin")
