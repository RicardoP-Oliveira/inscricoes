import hmac
from fastapi import Depends, HTTPException, Request
from .db import get_conn
from .security import hash_token

async def usuario_atual(request: Request, conn=Depends(get_conn)):
    token = request.cookies.get("sid")
    if not token:
        raise HTTPException(401, "Nao autenticado.")
    row = await conn.fetchrow(
        """SELECT u.id,u.nome,u.username,u.perfil,s.id AS sessao_id,s.csrf_token
             FROM sessao s JOIN usuario u ON u.id=s.usuario_id
            WHERE s.token_hash=$1 AND s.revogada_em IS NULL
              AND s.expira_em>now() AND u.ativo""", hash_token(token))
    if row is None:
        raise HTTPException(401, "Sessao expirada.")
    return dict(row)

async def verificar_csrf(request: Request, user=Depends(usuario_atual)):
    if request.method in ("GET","HEAD","OPTIONS"):
        return user
    h = request.headers.get("X-CSRF-Token")
    if not h or not hmac.compare_digest(h, user["csrf_token"]):
        raise HTTPException(403, "CSRF invalido.")
    return user

def requer_perfil(*perfis):
    async def dep(user=Depends(verificar_csrf)):
        if user["perfil"] not in perfis:
            raise HTTPException(403, "Sem permissao.")
        return user
    return dep

def requer_acesso_evento(*papeis):
    async def dep(evento_id: int, user=Depends(verificar_csrf), conn=Depends(get_conn)):
        if user["perfil"] == "ADMIN":
            return {**user, "papel_evento": "ADMIN"}
        papel = await conn.fetchval(
            "SELECT papel FROM evento_usuario WHERE evento_id=$1 AND usuario_id=$2",
            evento_id, user["id"])
        if papel is None or papel not in papeis:
            raise HTTPException(403, "Sem acesso a este evento.")
        return {**user, "papel_evento": papel}
    return dep
