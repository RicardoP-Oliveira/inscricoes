import asyncpg

from .config import settings

pool = None


async def _ajustar_conexao(conn):
    await conn.set_type_codec("numeric", encoder=str, decoder=float, schema="pg_catalog")


async def conectar():
    global pool
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL ausente em ~/inscricoes/.env")
    pool = await asyncpg.create_pool(
        settings.database_url, min_size=1, max_size=8, init=_ajustar_conexao
    )
    return pool


async def fechar():
    if pool is not None:
        await pool.close()


async def get_conn():
    async with pool.acquire() as conn:
        yield conn
