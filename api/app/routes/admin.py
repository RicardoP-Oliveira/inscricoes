from fastapi import APIRouter, Depends, HTTPException
from ..db import get_conn
from ..deps import requer_acesso_evento, requer_perfil, verificar_csrf
from ..schemas import EventoIn, UsuarioIn
from ..security import hash_senha
from ..services import inscricao as svc

router = APIRouter(dependencies=[Depends(verificar_csrf)])

BASE = """SELECT e.id,e.titulo,e.status,e.data_evento,e.vagas_titulares,e.vagas_reserva,
o.ocupantes,o.livres,o.pct_ocupacao,f.inscritos,f.confirmados,f.na_fila,f.convocados
FROM evento e JOIN vw_evento_ocupacao o ON o.evento_id=e.id
JOIN vw_evento_funil f ON f.evento_id=e.id"""

@router.get("/eventos")
async def listar(user=Depends(verificar_csrf), conn=Depends(get_conn)):
    if user["perfil"] == "ADMIN":
        rows = await conn.fetch(BASE + " ORDER BY e.data_evento DESC")
    else:
        rows = await conn.fetch(BASE + """ JOIN evento_usuario eu ON eu.evento_id=e.id
            AND eu.usuario_id=$1 ORDER BY e.data_evento DESC""", user["id"])
    return [dict(r) for r in rows]

@router.post("/eventos", status_code=201)
async def criar(dados: EventoIn, user=Depends(requer_perfil("ADMIN","ORGANIZADOR")),
                conn=Depends(get_conn)):
    eid = await conn.fetchval("""INSERT INTO evento
        (titulo,descricao,data_evento,local,vagas_titulares,vagas_reserva,
         prazo_confirmacao_horas,status,inscricoes_encerram_em,criado_por_id)
        VALUES ($1,$2,$3,$4,$5,$6,$7,'RASCUNHO',$8,$9) RETURNING id""",
        dados.titulo, dados.descricao, dados.data_evento, dados.local,
        dados.vagas_titulares, dados.vagas_reserva, dados.prazo_confirmacao_horas,
        dados.inscricoes_encerram_em, user["id"])
    if user["perfil"] != "ADMIN":
        await conn.execute("""INSERT INTO evento_usuario (evento_id,usuario_id,papel)
            VALUES ($1,$2,'ORGANIZADOR')""", eid, user["id"])
    return {"id": eid}

@router.post("/eventos/{evento_id}/status/{novo}")
async def mudar_status(evento_id: int, novo: str,
                       user=Depends(requer_acesso_evento("ORGANIZADOR")), conn=Depends(get_conn)):
    if novo not in ("RASCUNHO","ABERTO","ENCERRADO","FINALIZADO"):
        raise HTTPException(400, "Status invalido.")
    await conn.execute("UPDATE evento SET status=$2::status_evento, updated_at=now() WHERE id=$1",
                       evento_id, novo)
    return {"ok": True}

@router.get("/eventos/{evento_id}/metricas")
async def metricas(evento_id: int,
                   user=Depends(requer_acesso_evento("ORGANIZADOR","APOIO")),
                   conn=Depends(get_conn)):
    funil = await conn.fetchrow("SELECT * FROM vw_evento_funil WHERE evento_id=$1", evento_id)
    serie = await conn.fetch("SELECT * FROM vw_evento_inscricoes_dia WHERE evento_id=$1 ORDER BY dia", evento_id)
    ocup = await conn.fetchrow("SELECT * FROM vw_evento_ocupacao WHERE evento_id=$1", evento_id)
    return {"funil": dict(funil or {}), "serie": [dict(r) for r in serie],
            "ocupacao": dict(ocup or {})}

@router.get("/eventos/{evento_id}/inscricoes")
async def inscricoes(evento_id: int,
                     user=Depends(requer_acesso_evento("ORGANIZADOR","APOIO")),
                     conn=Depends(get_conn)):
    rows = await conn.fetch("SELECT * FROM inscricao WHERE evento_id=$1 ORDER BY created_at DESC",
                            evento_id)
    return [dict(r) for r in rows]

@router.post("/eventos/{evento_id}/inscricoes/{iid}/presenca")
async def presenca(evento_id: int, iid: int,
                   user=Depends(requer_acesso_evento("ORGANIZADOR","APOIO")),
                   conn=Depends(get_conn)):
    try:
        await svc.marcar_presente(conn, iid)
    except svc.TransicaoInvalida:
        raise HTTPException(409, "Inscricao nao esta confirmada.")
    return {"ok": True}

@router.post("/eventos/{evento_id}/inscricoes/{iid}/cancelar")
async def cancelar(evento_id: int, iid: int,
                   user=Depends(requer_acesso_evento("ORGANIZADOR")), conn=Depends(get_conn)):
    try:
        await svc.cancelar(conn, iid)
    except svc.TransicaoInvalida:
        raise HTTPException(409, "Inscricao nao pode ser cancelada.")
    return {"ok": True}

@router.post("/eventos/{evento_id}/convocar")
async def convocar(evento_id: int,
                   user=Depends(requer_acesso_evento("ORGANIZADOR")), conn=Depends(get_conn)):
    async with conn.transaction():
        ev = await conn.fetchrow("SELECT * FROM evento WHERE id=$1 FOR UPDATE", evento_id)
        if ev is None:
            raise HTTPException(404, "Evento nao encontrado.")
        n = await svc.preencher_vagas(conn, ev)
    return {"convocados": n}

@router.get("/usuarios")
async def usuarios(user=Depends(requer_perfil("ADMIN")), conn=Depends(get_conn)):
    rows = await conn.fetch("SELECT id,nome,username,email,perfil,ativo FROM usuario ORDER BY nome")
    return [dict(r) for r in rows]

@router.post("/usuarios", status_code=201)
async def criar_usuario(dados: UsuarioIn, user=Depends(requer_perfil("ADMIN")),
                        conn=Depends(get_conn)):
    if await conn.fetchval("SELECT 1 FROM usuario WHERE username=$1", dados.username):
        raise HTTPException(409, "Usuario ja existe.")
    uid = await conn.fetchval("""INSERT INTO usuario (nome,username,email,senha_hash,perfil)
        VALUES ($1,$2,$3,$4,$5::perfil_usuario) RETURNING id""",
        dados.nome, dados.username, dados.email, hash_senha(dados.senha), dados.perfil)
    return {"id": uid}

@router.post("/usuarios/{uid}/desativar")
async def desativar(uid: int, user=Depends(requer_perfil("ADMIN")), conn=Depends(get_conn)):
    await conn.execute("UPDATE usuario SET ativo=false WHERE id=$1", uid)
    await conn.execute("""UPDATE sessao SET revogada_em=now()
        WHERE usuario_id=$1 AND revogada_em IS NULL""", uid)
    return {"ok": True}
