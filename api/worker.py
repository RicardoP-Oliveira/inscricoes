import asyncio, logging
import asyncpg
from app.config import settings
from app.db import _setup
from app.services.emailer import despachar
from app.services.inscricao import _hist, preencher_vagas

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("worker")

async def tick(conn):
    exp = await conn.fetch("""WITH alvo AS (
        SELECT id,status FROM inscricao
        WHERE status IN ('PENDENTE_CONFIRMACAO','CONVOCADO_LISTA_ESPERA')
          AND token_expira_em < now() FOR UPDATE SKIP LOCKED)
        UPDATE inscricao i SET status='EXPIRADO', updated_at=now()
        FROM alvo a WHERE i.id=a.id RETURNING i.id, a.status AS anterior""")
    for e in exp:
        await _hist(conn, e["id"], e["anterior"], "EXPIRADO", "prazo_vencido")
    if exp:
        log.info("expirados: %s", len(exp))
    evs = await conn.fetch("""SELECT e.id FROM evento e WHERE e.status='ABERTO'
        AND EXISTS (SELECT 1 FROM inscricao i WHERE i.evento_id=e.id AND i.status='LISTA_ESPERA')
        AND (SELECT count(*) FROM inscricao i WHERE i.evento_id=e.id AND i.ocupa_vaga) < e.vagas_titulares""")
    for ev in evs:
        async with conn.transaction():
            full = await conn.fetchrow("SELECT * FROM evento WHERE id=$1 FOR UPDATE", ev["id"])
            await preencher_vagas(conn, full)
    await despachar(conn)

async def main():
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=3, init=_setup)
    async with pool.acquire() as conn:
        while True:
            try:
                await tick(conn)
            except Exception:
                log.exception("falha no tick")
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
