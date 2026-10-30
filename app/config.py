import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")


class Settings:
    database_url = os.environ.get("DATABASE_URL", "")
    cookie_secure = os.environ.get("COOKIE_SECURE", "false").lower() == "true"
    app_base_url = os.environ.get("APP_BASE_URL", "http://127.0.0.1:8000")
    session_horas = int(os.environ.get("SESSION_HORAS", "8"))
    smtp_host = os.environ.get("SMTP_HOST", "").strip()
    smtp_port = int(os.environ.get("SMTP_PORT", "25"))
    smtp_from = os.environ.get("SMTP_FROM", "nao-responda@local")
    worker_segundos = int(os.environ.get("WORKER_SEGUNDOS", "20"))


settings = Settings()
