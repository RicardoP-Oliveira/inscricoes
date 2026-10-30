import asyncio
import asyncpg
from app.config import settings
from app.security import hash_senha

async def main():
    conn = await asyncpg.connect(settings.database_url)
    await conn.execute("""INSERT INTO usuario (nome,username,email,senha_hash,perfil)
        VALUES ('Administrador','admin','admin@exemplo.gov.br',$1,'ADMIN')
        ON CONFLICT (username) DO NOTHING""", hash_senha("admin123"))
    await conn.close()
    print("seed ok: admin / admin123")

asyncio.run(main())
