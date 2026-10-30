import asyncio, logging, smtplib
from email.message import EmailMessage
from ..config import settings

log = logging.getLogger("emailer")

def _enviar(para, assunto, corpo):
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = para
    msg["Subject"] = assunto
    msg.set_content(corpo)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as s:
        if settings.smtp_user:
            s.starttls()
            s.login(settings.smtp_user, settings.smtp_pass or "")
        s.send_message(msg)

async def despachar(conn, limite=20) -> int:
    enviados = 0
    async with conn.transaction():
        rows = await conn.fetch("""SELECT * FROM email_outbox
            WHERE enviado_em IS NULL AND erro IS NULL
            ORDER BY id LIMIT $1 FOR UPDATE SKIP LOCKED""", limite)
        for r in rows:
            try:
                await asyncio.to_thread(_enviar, r["destinatario"], r["assunto"], r["corpo"])
                await conn.execute("UPDATE email_outbox SET enviado_em=now() WHERE id=$1", r["id"])
                enviados += 1
            except Exception as e:
                log.exception("falha email %s", r["id"])
                await conn.execute("UPDATE email_outbox SET erro=$2 WHERE id=$1",
                                   r["id"], str(e)[:500])
    return enviados
