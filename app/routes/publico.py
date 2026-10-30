from fastapi import APIRouter, Depends, HTTPException

from ..db import get_conn
from ..schemas import InscricaoIn
from ..security import hash_token
from ..services import (
    DocumentoDuplicado,
    EventoFechado,
    Lotado,
    TokenExpirado,
    TokenInvalido,
    TransicaoInvalida,
    confirmar,
    criar_inscricao,
)

router = APIRouter(tags=["publico"])


@router.get("/eventos/publicos")
async def listar(conn=Depends(get_conn)):
    rows = await conn.fetch(
        "SELECT e.id, e.titulo, e.descricao, e.data_evento, e.local, "
        "e.vagas_titulares, e.vagas_reserva, o.ocupantes, o.livres, o.pct_ocupacao "
        "FROM evento e JOIN vw_evento_ocupacao o ON o.evento_id = e.id "
        "WHERE e.status='ABERTO' ORDER BY e.data_evento"
    )
    return [dict(r) for r in rows]


@router.get("/eventos/publicos/{evento_id}")
async def detalhe(evento_id: int, conn=Depends(get_conn)):
    row = await conn.fetchrow(
        "SELECT e.id, e.titulo, e.descricao, e.data_evento, e.local, "
        "e.vagas_titulares, e.vagas_reserva, e.prazo_confirmacao_horas, "
        "e.inscricoes_encerram_em, o.ocupantes, o.livres, o.pct_ocupacao "
        "FROM evento e JOIN vw_evento_ocupacao o ON o.evento_id = e.id "
        "WHERE e.id=$1 AND e.status='ABERTO'",
        evento_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Evento nao encontrado.")
    return dict(row)


@router.post("/eventos/publicos/{evento_id}/inscricoes", status_code=201)
async def inscrever(evento_id: int, dados: InscricaoIn, conn=Depends(get_conn)):
    if dados.website:
        return {"status": "titular", "mensagem": "Inscricao registrada. Confira seu e-mail."}
    try:
        r = await criar_inscricao(conn, evento_id, dados.model_dump())
    except EventoFechado:
        raise HTTPException(status_code=409, detail="As inscricoes nao estao abertas.")
    except Lotado:
        raise HTTPException(status_code=409, detail="Todas as vagas e reservas foram preenchidas.")
    except DocumentoDuplicado:
        raise HTTPException(status_code=409, detail="Este documento ja possui inscricao ativa.")

    if r["status"] == "TITULAR":
        return {"status": "titular", "id": r["id"],
                "mensagem": "Inscricao registrada. Confira o e-mail para confirmar."}
    return {"status": "reserva", "id": r["id"], "ordem": r["ordem_espera"],
            "mensagem": "Voce esta na reserva (posicao {}). Sera avisado se liberar vaga.".format(
                r["ordem_espera"])}


@router.get("/confirmar/{token}")
async def ver_token(token: str, conn=Depends(get_conn)):
    row = await conn.fetchrow(
        "SELECT i.nome, i.status, i.token_expira_em, e.titulo, e.data_evento, e.local "
        "FROM inscricao i JOIN evento e ON e.id = i.evento_id WHERE i.token_hash=$1",
        hash_token(token),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Link invalido ou expirado.")
    return dict(row)


@router.post("/confirmar/{token}")
async def efetivar(token: str, conn=Depends(get_conn)):
    try:
        row = await confirmar(conn, token)
    except TokenInvalido:
        raise HTTPException(status_code=404, detail="Link invalido.")
    except TokenExpirado:
        raise HTTPException(status_code=410, detail="Prazo de confirmacao vencido.")
    except TransicaoInvalida:
        raise HTTPException(status_code=409, detail="Esta inscricao nao pode ser confirmada.")
    evento = await conn.fetchrow(
        "SELECT titulo, data_evento, local FROM evento WHERE id=$1", row["evento_id"]
    )
    return {"nome": row["nome"], "status": row["status"],
            "evento": evento["titulo"], "data_evento": evento["data_evento"],
            "local": evento["local"]}
