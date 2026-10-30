from fastapi import APIRouter, Depends, HTTPException
from ..db import get_conn
from ..schemas import InscricaoIn
from ..security import hash_token
from ..services import inscricao as svc

router = APIRouter(tags=["publico"])

@router.get("/eventos/publicos")
async def listar(conn=Depends(get_conn)):
    rows = await conn.fetch("""SELECT e.id,e.titulo,e.descricao,e.data_evento,e.local,
        e.vagas_titulares,e.vagas_reserva,o.ocupantes,o.livres
        FROM evento e JOIN vw_evento_ocupacao o ON o.evento_id=e.id
        WHERE e.status='ABERTO' ORDER BY e.data_evento""")
    return [dict(r) for r in rows]

@router.get("/eventos/publicos/{evento_id}")
async def detalhe(evento_id: int, conn=Depends(get_conn)):
    row = await conn.fetchrow("""SELECT e.id,e.titulo,e.descricao,e.data_evento,e.local,
        e.vagas_titulares,e.vagas_reserva,o.ocupantes,o.livres,e.inscricoes_encerram_em
        FROM evento e JOIN vw_evento_ocupacao o ON o.evento_id=e.id
        WHERE e.id=$1 AND e.status='ABERTO'""", evento_id)
    if row is None:
        raise HTTPException(404, "Evento nao encontrado.")
    return dict(row)

@router.post("/eventos/publicos/{evento_id}/inscricoes", status_code=201)
async def inscrever(evento_id: int, dados: InscricaoIn, conn=Depends(get_conn)):
    if dados.website:
        return {"status": "titular", "mensagem": "Inscricao registrada."}
    try:
        status, iid = await svc.criar_inscricao(conn, evento_id, dados.model_dump())
    except svc.EventoFechado:
        raise HTTPException(409, "Inscricoes nao estao abertas.")
    except svc.Lotado:
        raise HTTPException(409, "Todas as vagas ja foram preenchidas.")
    except svc.DocumentoDuplicado:
        raise HTTPException(409, "Este documento ja tem inscricao ativa.")
    if status == "TITULAR":
        return {"status": "titular", "id": iid,
                "mensagem": "Inscricao registrada. Confira seu e-mail para confirmar."}
    return {"status": "reserva", "id": iid,
            "mensagem": "Voce esta na reserva. Sera avisado se uma vaga for liberada."}

@router.get("/confirmar/{token}")
async def ver_token(token: str, conn=Depends(get_conn)):
    row = await conn.fetchrow("""SELECT i.nome,i.status,i.token_expira_em,e.titulo,
        e.data_evento,e.local FROM inscricao i JOIN evento e ON e.id=i.evento_id
        WHERE i.token_hash=$1""", hash_token(token))
    if row is None:
        raise HTTPException(404, "Link invalido.")
    return dict(row)

@router.post("/confirmar/{token}")
async def efetivar(token: str, conn=Depends(get_conn)):
    try:
        row = await svc.confirmar(conn, token)
    except svc.TokenInvalido:
        raise HTTPException(404, "Link invalido.")
    except svc.TokenExpirado:
        raise HTTPException(410, "Prazo de confirmacao vencido.")
    except svc.TransicaoInvalida:
        raise HTTPException(409, "Inscricao nao pode ser confirmada.")
    ev = await conn.fetchrow("SELECT titulo,data_evento,local FROM evento WHERE id=$1", row["evento_id"])
    return {"nome": row["nome"], "status": row["status"], "evento": ev["titulo"],
            "data_evento": ev["data_evento"], "local": ev["local"]}
