import asyncpg
from .config import settings

pool: asyncpg.Pool | None = None

async def _setup(conn):
    await conn.set_type_codec("numeric", encoder=str, decoder=float, schema="pg_catalog")

async def init_pool():
    global pool
    pool = await asyncpg.create_pool(settings.database_url, min_size=2, max_size=10, init=_setup)

async def close_pool():
    if pool:
        await pool.close()

async def get_conn():
    async with pool.acquire() as conn:
        yield conn
