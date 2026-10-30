from datetime import datetime, timezone
import asyncpg
from ..config import settings
from ..security import hash_token, novo_token

class InscricaoError(Exception): ...
class EventoFechado(InscricaoError): ...
class Lotado(InscricaoError): ...
class DocumentoDuplicado(InscricaoError): ...
class TokenInvalido(InscricaoError): ...
class TokenExpirado(InscricaoError): ...
class TransicaoInvalida(InscricaoError): ...

async def _hist(conn, iid, antes, novo, motivo):
    await conn.execute("""INSERT INTO inscricao_historico
        (inscricao_id,status_anterior,status_novo,motivo) VALUES ($1,$2,$3,$4)""",
        iid, antes, novo, motivo)

async def _email(conn, iid, para, assunto, corpo):
    await conn.execute("""INSERT INTO email_outbox
        (inscricao_id,destinatario,assunto,corpo) VALUES ($1,$2,$3,$4)""",
        iid, para, assunto, corpo)

async def preencher_vagas(conn, ev) -> int:
    promovidos = 0
    while True:
        ocup = await conn.fetchval(
            "SELECT count(*) FROM inscricao WHERE evento_id=$1 AND ocupa_vaga", ev["id"])
        if ocup >= ev["vagas_titulares"]:
            return promovidos
        prox = await conn.fetchrow("""SELECT id,nome,email FROM inscricao
            WHERE evento_id=$1 AND status='LISTA_ESPERA'
            ORDER BY ordem_espera LIMIT 1 FOR UPDATE""", ev["id"])
        if prox is None:
            return promovidos
        tk = novo_token()
        await conn.execute("""UPDATE inscricao SET status='CONVOCADO_LISTA_ESPERA',
            convocado_em=now(), origem_lista_espera=true, ordem_espera=NULL,
            token_hash=$2, token_expira_em=now()+make_interval(hours=>$3), updated_at=now()
            WHERE id=$1""", prox["id"], hash_token(tk), ev["prazo_confirmacao_horas"])
        await _email(conn, prox["id"], prox["email"], f"Vaga liberada: {ev['titulo']}",
            f"Voce foi convocado da reserva. Confirme em ate {ev['prazo_confirmacao_horas']}h: "
            f"{settings.app_base_url}/confirmar/{tk}")
        await _hist(conn, prox["id"], "LISTA_ESPERA", "CONVOCADO_LISTA_ESPERA", "vaga_titular_liberada")
        promovidos += 1

async def criar_inscricao(conn, evento_id: int, dados: dict):
    doc = dados["documento"].strip().upper()
    email = dados["email"].strip().lower()
    async with conn.transaction():
        ev = await conn.fetchrow("SELECT * FROM evento WHERE id=$1 FOR UPDATE", evento_id)
        if ev is None or ev["status"] != "ABERTO":
            raise EventoFechado()
        if ev["inscricoes_encerram_em"] and ev["inscricoes_encerram_em"] < datetime.now(timezone.utc):
            raise EventoFechado()
        dup = await conn.fetchval("""SELECT id FROM inscricao WHERE evento_id=$1
            AND documento=$2 AND status NOT IN ('EXPIRADO','CANCELADO')""", evento_id, doc)
        if dup:
            raise DocumentoDuplicado()
        await preencher_vagas(conn, ev)
        ocup = await conn.fetchval("SELECT count(*) FROM inscricao WHERE evento_id=$1 AND ocupa_vaga", evento_id)
        fila = await conn.fetchval("SELECT count(*) FROM inscricao WHERE evento_id=$1 AND status='LISTA_ESPERA'", evento_id)
        vivas = await conn.fetchval("""SELECT count(*) FROM inscricao WHERE evento_id=$1
            AND status NOT IN ('EXPIRADO','CANCELADO')""", evento_id)
        if vivas >= ev["vagas_titulares"] + ev["vagas_reserva"]:
            raise Lotado()
        if ocup < ev["vagas_titulares"]:
            status, tipo, ordem, tk = "PENDENTE_CONFIRMACAO", "TITULAR", None, novo_token()
        elif fila < ev["vagas_reserva"]:
            status, tipo, tk = "LISTA_ESPERA", "RESERVA", None
            ordem = await conn.fetchval(
                "SELECT COALESCE(MAX(ordem_espera),0)+1 FROM inscricao WHERE evento_id=$1", evento_id)
        else:
            raise Lotado()
        try:
            iid = await conn.fetchval("""INSERT INTO inscricao
                (evento_id,nome,documento,email,telefone,status,tipo_vaga,ordem_espera,
                 prazo_confirmacao_horas,token_hash,token_expira_em)
                VALUES ($1,$2,$3,$4,$5,$6::status_inscricao,$7::tipo_vaga,$8,$9,$10,
                 CASE WHEN $10::text IS NULL THEN NULL
                      ELSE now()+make_interval(hours=>$9) END) RETURNING id""",
                evento_id, dados["nome"].strip(), doc, email, dados.get("telefone") or None,
                status, tipo, ordem, ev["prazo_confirmacao_horas"],
                hash_token(tk) if tk else None)
        except asyncpg.UniqueViolationError:
            raise DocumentoDuplicado()
        await _hist(conn, iid, None, status, "inscricao_criada")
        if tk:
            await _email(conn, iid, email, f"Confirme sua vaga: {ev['titulo']}",
                f"Voce tem {ev['prazo_confirmacao_horas']}h para confirmar: "
                f"{settings.app_base_url}/confirmar/{tk}")
        else:
            await _email(conn, iid, email, f"Voce esta na reserva: {ev['titulo']}",
                f"Sua posicao na reserva e {ordem}.")
        return status, iid

async def confirmar(conn, token: str) -> dict:
    async with conn.transaction():
        row = await conn.fetchrow("SELECT * FROM inscricao WHERE token_hash=$1 FOR UPDATE",
                                  hash_token(token))
        if row is None:
            raise TokenInvalido()
        if row["status"] in ("CONFIRMADO","PRESENTE","CERTIFICADO_LIBERADO"):
            return dict(row)
        if row["status"] not in ("PENDENTE_CONFIRMACAO","CONVOCADO_LISTA_ESPERA"):
            raise TransicaoInvalida()
        if row["token_expira_em"] < datetime.now(timezone.utc):
            raise TokenExpirado()
        novo = await conn.fetchrow("""UPDATE inscricao SET status='CONFIRMADO',
            confirmado_em=now(), tipo_vaga='TITULAR', ordem_espera=NULL, updated_at=now()
            WHERE id=$1 RETURNING *""", row["id"])
        await _hist(conn, row["id"], row["status"], "CONFIRMADO", "confirmacao_por_token")
        return dict(novo)

async def cancelar(conn, iid: int, motivo="cancelamento_manual"):
    async with conn.transaction():
        row = await conn.fetchrow("SELECT * FROM inscricao WHERE id=$1 FOR UPDATE", iid)
        if row is None or row["status"] in ("EXPIRADO","CANCELADO"):
            raise TransicaoInvalida()
        await conn.execute("""UPDATE inscricao SET status='CANCELADO', cancelado_em=now(),
            ordem_espera=NULL, updated_at=now() WHERE id=$1""", iid)
        await _hist(conn, iid, row["status"], "CANCELADO", motivo)
        ev = await conn.fetchrow("SELECT * FROM evento WHERE id=$1 FOR UPDATE", row["evento_id"])
        await preencher_vagas(conn, ev)

async def marcar_presente(conn, iid: int):
    async with conn.transaction():
        row = await conn.fetchrow("SELECT * FROM inscricao WHERE id=$1 FOR UPDATE", iid)
        if row is None or row["status"] not in ("CONFIRMADO","PRESENTE"):
            raise TransicaoInvalida()
        if row["status"] == "PRESENTE":
            return
        await conn.execute("""UPDATE inscricao SET status='PRESENTE',
            presente_em=now(), updated_at=now() WHERE id=$1""", iid)
        await _hist(conn, iid, row["status"], "PRESENTE", "checkin")
