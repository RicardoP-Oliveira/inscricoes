import asyncio
import logging
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

import asyncpg

from .config import settings
from .security import hash_senha, hash_token, novo_token

log = logging.getLogger("regras")


class ErroInscricao(Exception):
    pass


class EventoFechado(ErroInscricao):
    pass


class Lotado(ErroInscricao):
    pass


class DocumentoDuplicado(ErroInscricao):
    pass


class TokenInvalido(ErroInscricao):
    pass


class TokenExpirado(ErroInscricao):
    pass


class TransicaoInvalida(ErroInscricao):
    pass


async def garantir_admin(conn):
    total = await conn.fetchval("SELECT count(*) FROM usuario")
    if total:
        return
    await conn.execute(
        "INSERT INTO usuario (nome, username, email, senha_hash, perfil) "
        "VALUES ($1,$2,$3,$4,'ADMIN')",
        "Administrador", "admin", "admin@local", hash_senha("admin123"),
    )
    log.warning("Usuario criado: admin / admin123  (troque a senha)")


async def registrar_historico(conn, inscricao_id, anterior, novo, motivo):
    await conn.execute(
        "INSERT INTO inscricao_historico (inscricao_id, status_anterior, status_novo, motivo) "
        "VALUES ($1,$2,$3,$4)",
        inscricao_id, anterior, novo, motivo,
    )


async def enfileirar_email(conn, inscricao_id, destino, assunto, corpo):
    await conn.execute(
        "INSERT INTO email_outbox (inscricao_id, destinatario, assunto, corpo) "
        "VALUES ($1,$2,$3,$4)",
        inscricao_id, destino, assunto, corpo,
    )


async def preencher_vagas(conn, evento):
    promovidos = 0
    while True:
        ocupantes = await conn.fetchval(
            "SELECT count(*) FROM inscricao WHERE evento_id=$1 AND ocupa_vaga", evento["id"]
        )
        if ocupantes >= evento["vagas_titulares"]:
            return promovidos
        proximo = await conn.fetchrow(
            "SELECT id, nome, email FROM inscricao "
            "WHERE evento_id=$1 AND status='LISTA_ESPERA' "
            "ORDER BY ordem_espera LIMIT 1 FOR UPDATE",
            evento["id"],
        )
        if proximo is None:
            return promovidos
        token = novo_token()
        await conn.execute(
            "UPDATE inscricao SET status='CONVOCADO_LISTA_ESPERA', convocado_em=now(), "
            "origem_lista_espera=true, ordem_espera=NULL, token_hash=$2, "
            "token_expira_em=now() + make_interval(hours => $3), updated_at=now() "
            "WHERE id=$1",
            proximo["id"], hash_token(token), evento["prazo_confirmacao_horas"],
        )
        await registrar_historico(
            conn, proximo["id"], "LISTA_ESPERA", "CONVOCADO_LISTA_ESPERA", "vaga_liberada"
        )
        await enfileirar_email(
            conn, proximo["id"], proximo["email"],
            "Vaga liberada: " + evento["titulo"],
            "Uma vaga foi liberada e voce e o proximo da reserva.\n\n"
            "Confirme em ate {} horas:\n{}/#/confirmar/{}\n".format(
                evento["prazo_confirmacao_horas"], settings.app_base_url, token),
        )
        promovidos += 1


async def criar_inscricao(conn, evento_id, dados):
    documento = dados["documento"].strip().upper()
    email = dados["email"].strip().lower()
    nome = dados["nome"].strip()
    telefone = (dados.get("telefone") or "").strip() or None

    async with conn.transaction():
        evento = await conn.fetchrow("SELECT * FROM evento WHERE id=$1 FOR UPDATE", evento_id)
        if evento is None or evento["status"] != "ABERTO":
            raise EventoFechado()
        if evento["inscricoes_encerram_em"] and evento["inscricoes_encerram_em"] < datetime.now(timezone.utc):
            raise EventoFechado()

        duplicado = await conn.fetchval(
            "SELECT 1 FROM inscricao WHERE evento_id=$1 AND documento=$2 "
            "AND status NOT IN ('EXPIRADO','CANCELADO')",
            evento_id, documento,
        )
        if duplicado:
            raise DocumentoDuplicado()

        await preencher_vagas(conn, evento)

        ocupantes = await conn.fetchval(
            "SELECT count(*) FROM inscricao WHERE evento_id=$1 AND ocupa_vaga", evento_id
        )
        na_fila = await conn.fetchval(
            "SELECT count(*) FROM inscricao WHERE evento_id=$1 AND status='LISTA_ESPERA'", evento_id
        )
        vivas = await conn.fetchval(
            "SELECT count(*) FROM inscricao WHERE evento_id=$1 "
            "AND status NOT IN ('EXPIRADO','CANCELADO')",
            evento_id,
        )

        if vivas >= evento["vagas_titulares"] + evento["vagas_reserva"]:
            raise Lotado()

        if ocupantes < evento["vagas_titulares"]:
            status, tipo, ordem, token = "PENDENTE_CONFIRMACAO", "TITULAR", None, novo_token()
        elif na_fila < evento["vagas_reserva"]:
            status, tipo, token = "LISTA_ESPERA", "RESERVA", None
            ordem = await conn.fetchval(
                "SELECT COALESCE(MAX(ordem_espera),0)+1 FROM inscricao WHERE evento_id=$1",
                evento_id,
            )
        else:
            raise Lotado()

        try:
            inscricao_id = await conn.fetchval(
                "INSERT INTO inscricao (evento_id, nome, documento, email, telefone, status, "
                "tipo_vaga, ordem_espera, prazo_confirmacao_horas, token_hash, token_expira_em) "
                "VALUES ($1,$2,$3,$4,$5,$6::status_inscricao,$7::tipo_vaga,$8,$9,$10, "
                "CASE WHEN $10::text IS NULL THEN NULL "
                "ELSE now() + make_interval(hours => $9) END) RETURNING id",
                evento_id, nome, documento, email, telefone, status, tipo, ordem,
                evento["prazo_confirmacao_horas"], hash_token(token) if token else None,
            )
        except asyncpg.UniqueViolationError:
            raise DocumentoDuplicado()

        await registrar_historico(conn, inscricao_id, None, status, "inscricao_criada")

        if token:
            await enfileirar_email(
                conn, inscricao_id, email,
                "Confirme sua vaga: " + evento["titulo"],
                "Voce tem {} horas para confirmar:\n{}/#/confirmar/{}\n".format(
                    evento["prazo_confirmacao_horas"], settings.app_base_url, token),
            )
        else:
            await enfileirar_email(
                conn, inscricao_id, email,
                "Voce esta na reserva: " + evento["titulo"],
                "Sua posicao na lista de reserva e {}.\n"
                "Voce sera avisado se uma vaga for liberada.\n".format(ordem),
            )

    return {"id": inscricao_id, "status": status, "tipo_vaga": tipo, "ordem_espera": ordem}


async def confirmar(conn, token):
    async with conn.transaction():
        row = await conn.fetchrow(
            "SELECT * FROM inscricao WHERE token_hash=$1 FOR UPDATE", hash_token(token)
        )
        if row is None:
            raise TokenInvalido()
        if row["status"] in ("CONFIRMADO", "PRESENTE", "CERTIFICADO_LIBERADO"):
            return row
        if row["status"] not in ("PENDENTE_CONFIRMACAO", "CONVOCADO_LISTA_ESPERA"):
            raise TransicaoInvalida()
        if row["token_expira_em"] < datetime.now(timezone.utc):
            raise TokenExpirado()
        atualizado = await conn.fetchrow(
            "UPDATE inscricao SET status='CONFIRMADO', confirmado_em=now(), "
            "tipo_vaga='TITULAR', ordem_espera=NULL, updated_at=now() "
            "WHERE id=$1 RETURNING *",
            row["id"],
        )
        await registrar_historico(conn, row["id"], row["status"], "CONFIRMADO", "confirmacao_por_token")
        return atualizado


async def cancelar(conn, inscricao_id, motivo="cancelamento_manual"):
    async with conn.transaction():
        row = await conn.fetchrow("SELECT * FROM inscricao WHERE id=$1 FOR UPDATE", inscricao_id)
        if row is None or row["status"] in ("EXPIRADO", "CANCELADO"):
            raise TransicaoInvalida()
        await conn.execute(
            "UPDATE inscricao SET status='CANCELADO', cancelado_em=now(), "
            "ordem_espera=NULL, updated_at=now() WHERE id=$1",
            inscricao_id,
        )
        await registrar_historico(conn, inscricao_id, row["status"], "CANCELADO", motivo)
        evento = await conn.fetchrow("SELECT * FROM evento WHERE id=$1 FOR UPDATE", row["evento_id"])
        await preencher_vagas(conn, evento)


async def marcar_presente(conn, inscricao_id):
    async with conn.transaction():
        row = await conn.fetchrow("SELECT * FROM inscricao WHERE id=$1 FOR UPDATE", inscricao_id)
        if row is None or row["status"] not in ("CONFIRMADO", "PRESENTE"):
            raise TransicaoInvalida()
        if row["status"] == "PRESENTE":
            return
        await conn.execute(
            "UPDATE inscricao SET status='PRESENTE', presente_em=now(), updated_at=now() "
            "WHERE id=$1",
            inscricao_id,
        )
        await registrar_historico(conn, inscricao_id, row["status"], "PRESENTE", "checkin")


async def expirar_vencidos(conn):
    rows = await conn.fetch(
        "WITH alvo AS (SELECT id, status FROM inscricao "
        "WHERE status IN ('PENDENTE_CONFIRMACAO','CONVOCADO_LISTA_ESPERA') "
        "AND token_expira_em < now() FOR UPDATE SKIP LOCKED) "
        "UPDATE inscricao i SET status='EXPIRADO', updated_at=now() "
        "FROM alvo WHERE i.id = alvo.id RETURNING i.id, alvo.status AS anterior"
    )
    for r in rows:
        await registrar_historico(conn, r["id"], r["anterior"], "EXPIRADO", "prazo_vencido")
    return len(rows)


def _enviar_smtp(destino, assunto, corpo):
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = destino
    msg["Subject"] = assunto
    msg.set_content(corpo)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as s:
        s.send_message(msg)


async def despachar_emails(conn, limite=20):
    rows = await conn.fetch(
        "SELECT id, destinatario, assunto, corpo FROM email_outbox "
        "WHERE enviado_em IS NULL AND erro IS NULL ORDER BY id LIMIT $1",
        limite,
    )
    for r in rows:
        if not settings.smtp_host:
            log.info(
                "EMAIL nao enviado (SMTP_HOST vazio) para=%s assunto=%s\n%s",
                r["destinatario"], r["assunto"], r["corpo"],
            )
            await conn.execute("UPDATE email_outbox SET enviado_em=now() WHERE id=$1", r["id"])
            continue
        try:
            await asyncio.to_thread(_enviar_smtp, r["destinatario"], r["assunto"], r["corpo"])
            await conn.execute("UPDATE email_outbox SET enviado_em=now() WHERE id=$1", r["id"])
        except Exception as exc:
            log.exception("falha ao enviar email %s", r["id"])
            await conn.execute(
                "UPDATE email_outbox SET erro=$2 WHERE id=$1", r["id"], str(exc)[:500]
            )


async def ciclo_worker(conn):
    await expirar_vencidos(conn)
    eventos = await conn.fetch(
        "SELECT e.* FROM evento e WHERE e.status='ABERTO' "
        "AND EXISTS (SELECT 1 FROM inscricao i WHERE i.evento_id=e.id AND i.status='LISTA_ESPERA') "
        "AND (SELECT count(*) FROM inscricao x WHERE x.evento_id=e.id AND x.ocupa_vaga) "
        "    < e.vagas_titulares"
    )
    for ev in eventos:
        async with conn.transaction():
            travado = await conn.fetchrow("SELECT * FROM evento WHERE id=$1 FOR UPDATE", ev["id"])
            await preencher_vagas(conn, travado)
    await despachar_emails(conn)
