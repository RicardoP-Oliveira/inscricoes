import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..config import settings
from ..db import get_conn
from ..deps import usuario_atual
from ..schemas import LoginIn
from ..security import hash_token, novo_token, senha_confere

router = APIRouter(tags=["auth"])


@router.post("/login")
async def login(dados: LoginIn, request: Request, response: Response, conn=Depends(get_conn)):
    ip = request.client.host if request.client else None
    falhas = await conn.fetchval(
        "SELECT count(*) FROM tentativa_login "
        "WHERE ip=$1::inet AND NOT sucesso AND created_at > now() - interval '15 minutes'",
        ip,
    )
    if falhas and falhas >= 10:
        raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde 15 minutos.")

    usuario = await conn.fetchrow(
        "SELECT * FROM usuario WHERE username=$1 AND ativo", dados.username
    )
    ok = bool(usuario) and senha_confere(usuario["senha_hash"], dados.senha)
    await conn.execute(
        "INSERT INTO tentativa_login (username, ip, sucesso) VALUES ($1,$2::inet,$3)",
        dados.username, ip, ok,
    )
    if not ok:
        raise HTTPException(status_code=401, detail="Usuario ou senha invalidos.")

    token = novo_token()
    csrf = secrets.token_urlsafe(24)
    await conn.execute(
        "INSERT INTO sessao (usuario_id, token_hash, csrf_token, ip, user_agent, expira_em) "
        "VALUES ($1,$2,$3,$4::inet,$5, now() + make_interval(hours => $6))",
        usuario["id"], hash_token(token), csrf, ip,
        request.headers.get("user-agent"), settings.session_horas,
    )
    idade = settings.session_horas * 3600
    response.set_cookie("sid", token, httponly=True, secure=settings.cookie_secure,
                        samesite="lax", max_age=idade, path="/")
    response.set_cookie("csrf", csrf, httponly=False, secure=settings.cookie_secure,
                        samesite="lax", max_age=idade, path="/")
    return {"id": usuario["id"], "nome": usuario["nome"], "perfil": usuario["perfil"]}


@router.post("/logout")
async def logout(response: Response, user=Depends(usuario_atual), conn=Depends(get_conn)):
    await conn.execute("UPDATE sessao SET revogada_em=now() WHERE id=$1", user["sessao_id"])
    response.delete_cookie("sid", path="/")
    response.delete_cookie("csrf", path="/")
    return {"ok": True}


@router.get("/me")
async def me(user=Depends(usuario_atual), conn=Depends(get_conn)):
    if user["perfil"] == "ADMIN":
        rows = await conn.fetch("SELECT id, titulo FROM evento ORDER BY data_evento DESC")
    else:
        rows = await conn.fetch(
            "SELECT e.id, e.titulo FROM evento e "
            "JOIN evento_usuario eu ON eu.evento_id = e.id "
            "WHERE eu.usuario_id=$1 ORDER BY e.data_evento DESC",
            user["id"],
        )
    return {"id": user["id"], "nome": user["nome"], "perfil": user["perfil"],
            "eventos": [dict(r) for r in rows]}
