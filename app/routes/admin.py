from fastapi import APIRouter, Depends, HTTPException

from ..db import get_conn
from ..deps import requer_acesso_evento, requer_perfil, usuario_atual
from ..schemas import EventoIn, UsuarioIn
from ..security import hash_senha
from ..services import TransicaoInvalida, cancelar, marcar_presente, preencher_vagas

router = APIRouter(tags=["admin"])

BASE = (
    "SELECT e.id, e.titulo, e.status, e.data_evento, e.local, e.prazo_confirmacao_horas, "
    "e.vagas_titulares, e.vagas_reserva, e.inscricoes_encerram_em, "
    "o.ocupantes, o.livres, o.pct_ocupacao, "
    "f.inscritos, f.confirmados, f.presentes, f.na_fila, f.convocados, f.perdidos "
    "FROM evento e "
    "JOIN vw_evento_ocupacao o ON o.evento_id = e.id "
    "JOIN vw_evento_funil f ON f.evento_id = e.id"
)


@router.get("/eventos")
async def listar_eventos(user=Depends(usuario_atual), conn=Depends(get_conn)):
    if user["perfil"] == "ADMIN":
        rows = await conn.fetch(BASE + " ORDER BY e.data_evento DESC")
    else:
        rows = await conn.fetch(
            BASE + " JOIN evento_usuario eu ON eu.evento_id = e.id AND eu.usuario_id=$1 "
            "ORDER BY e.data_evento DESC",
            user["id"],
        )
    return [dict(r) for r in rows]


@router.post("/eventos", status_code=201)
async def criar_evento(dados: EventoIn, user=Depends(requer_perfil("ADMIN", "ORGANIZADOR")),
                       conn=Depends(get_conn)):
    evento_id = await conn.fetchval(
        "INSERT INTO evento (titulo, descricao, data_evento, local, vagas_titulares, "
        "vagas_reserva, prazo_confirmacao_horas, status, inscricoes_encerram_em, criado_por_id) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,'RASCUNHO',$8,$9) RETURNING id",
        dados.titulo, dados.descricao, dados.data_evento, dados.local,
        dados.vagas_titulares, dados.vagas_reserva, dados.prazo_confirmacao_horas,
        dados.inscricoes_encerram_em, user["id"],
    )
    if user["perfil"] != "ADMIN":
        await conn.execute(
            "INSERT INTO evento_usuario (evento_id, usuario_id, papel) VALUES ($1,$2,'ORGANIZADOR')",
            evento_id, user["id"],
        )
    return {"id": evento_id}


@router.post("/eventos/{evento_id}/status/{novo}")
async def mudar_status(evento_id: int, novo: str,
                       user=Depends(requer_acesso_evento("ORGANIZADOR", "APOIO")),
                       conn=Depends(get_conn)):
    if novo not in ("RASCUNHO", "ABERTO", "ENCERRADO", "FINALIZADO"):
        raise HTTPException(status_code=400, detail="Status invalido.")
    await conn.execute(
        "UPDATE evento SET status=$2::status_evento, updated_at=now() WHERE id=$1",
        evento_id, novo,
    )
    return {"ok": True, "status": novo}


@router.get("/eventos/{evento_id}/metricas")
async def metricas(evento_id: int,
                   user=Depends(requer_acesso_evento("ORGANIZADOR", "APOIO")),
                   conn=Depends(get_conn)):
    funil = await conn.fetchrow("SELECT * FROM vw_evento_funil WHERE evento_id=$1", evento_id)
    ocupacao = await conn.fetchrow("SELECT * FROM vw_evento_ocupacao WHERE evento_id=$1", evento_id)
    serie = await conn.fetch(
        "SELECT * FROM vw_evento_inscricoes_dia WHERE evento_id=$1 ORDER BY dia", evento_id
    )
    if ocupacao is None:
        raise HTTPException(status_code=404, detail="Evento nao encontrado.")
    return {"funil": dict(funil or {}), "ocupacao": dict(ocupacao),
            "serie": [dict(r) for r in serie]}


@router.get("/eventos/{evento_id}/inscricoes")
async def listar_inscricoes(evento_id: int,
                            user=Depends(requer_acesso_evento("ORGANIZADOR", "APOIO")),
                            conn=Depends(get_conn)):
    rows = await conn.fetch(
        "SELECT id, nome, documento, email, telefone, status::text, tipo_vaga::text, "
        "ordem_espera, confirmado_em, presente_em, created_at "
        "FROM inscricao WHERE evento_id=$1 ORDER BY created_at DESC",
        evento_id,
    )
    return [dict(r) for r in rows]


@router.get("/eventos/{evento_id}/emails")
async def listar_emails(evento_id: int,
                        user=Depends(requer_acesso_evento("ORGANIZADOR", "APOIO")),
                        conn=Depends(get_conn)):
    rows = await conn.fetch(
        "SELECT o.id, o.destinatario, o.assunto, o.corpo, o.enviado_em, o.erro, o.created_at "
        "FROM email_outbox o JOIN inscricao i ON i.id = o.inscricao_id "
        "WHERE i.evento_id=$1 ORDER BY o.id DESC LIMIT 50",
        evento_id,
    )
    return [dict(r) for r in rows]


@router.post("/eventos/{evento_id}/inscricoes/{inscricao_id}/presenca")
async def presenca(evento_id: int, inscricao_id: int,
                   user=Depends(requer_acesso_evento("ORGANIZADOR", "APOIO")),
                   conn=Depends(get_conn)):
    try:
        await marcar_presente(conn, inscricao_id)
    except TransicaoInvalida:
        raise HTTPException(status_code=409, detail="Inscricao nao esta confirmada.")
    return {"ok": True}


@router.post("/eventos/{evento_id}/inscricoes/{inscricao_id}/cancelar")
async def cancelar_inscricao(evento_id: int, inscricao_id: int,
                             user=Depends(requer_acesso_evento("ORGANIZADOR", "APOIO")),
                             conn=Depends(get_conn)):
    try:
        await cancelar(conn, inscricao_id)
    except TransicaoInvalida:
        raise HTTPException(status_code=409, detail="Inscricao nao pode ser cancelada.")
    return {"ok": True}


@router.post("/eventos/{evento_id}/convocar")
async def convocar(evento_id: int,
                   user=Depends(requer_acesso_evento("ORGANIZADOR", "APOIO")),
                   conn=Depends(get_conn)):
    async with conn.transaction():
        evento = await conn.fetchrow("SELECT * FROM evento WHERE id=$1 FOR UPDATE", evento_id)
        if evento is None:
            raise HTTPException(status_code=404, detail="Evento nao encontrado.")
        total = await preencher_vagas(conn, evento)
    return {"convocados": total}


@router.get("/usuarios")
async def listar_usuarios(user=Depends(requer_perfil("ADMIN")), conn=Depends(get_conn)):
    rows = await conn.fetch(
        "SELECT id, nome, username, email, perfil::text, ativo FROM usuario ORDER BY nome"
    )
    return [dict(r) for r in rows]


@router.post("/usuarios", status_code=201)
async def criar_usuario(dados: UsuarioIn, user=Depends(requer_perfil("ADMIN")),
                        conn=Depends(get_conn)):
    if await conn.fetchval("SELECT 1 FROM usuario WHERE username=$1", dados.username):
        raise HTTPException(status_code=409, detail="Usuario ja existe.")
    novo_id = await conn.fetchval(
        "INSERT INTO usuario (nome, username, email, senha_hash, perfil) "
        "VALUES ($1,$2,$3,$4,$5::perfil_usuario) RETURNING id",
        dados.nome, dados.username, dados.email, hash_senha(dados.senha), dados.perfil,
    )
    return {"id": novo_id}


@router.post("/usuarios/{usuario_id}/desativar")
async def desativar_usuario(usuario_id: int, user=Depends(requer_perfil("ADMIN")),
                            conn=Depends(get_conn)):
    await conn.execute("UPDATE usuario SET ativo=false WHERE id=$1", usuario_id)
    await conn.execute(
        "UPDATE sessao SET revogada_em=now() WHERE usuario_id=$1 AND revogada_em IS NULL",
        usuario_id,
    )
    return {"ok": True}
