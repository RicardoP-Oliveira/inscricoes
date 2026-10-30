import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import db
from .config import settings
from .routes import admin, auth, publico
from .services import ciclo_worker, garantir_admin

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("app")

RAIZ = Path(__file__).resolve().parent.parent
WEB = RAIZ / "web"


async def laco_worker():
    while True:
        try:
            async with db.pool.acquire() as conn:
                await ciclo_worker(conn)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("falha no ciclo do worker")
        await asyncio.sleep(settings.worker_segundos)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.conectar()
    async with db.pool.acquire() as conn:
        await garantir_admin(conn)
    tarefa = asyncio.create_task(laco_worker())
    log.info("Aplicacao pronta em %s", settings.app_base_url)
    yield
    tarefa.cancel()
    await db.fechar()


app = FastAPI(title="Inscricoes em Eventos", lifespan=lifespan)

app.include_router(publico.router, prefix="/api")
app.include_router(auth.router, prefix="/api/auth")
app.include_router(admin.router, prefix="/api/admin")

app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")
