from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

_CAND = [Path(".env"), Path("../.env"), Path("/srv/inscricoes/.env")]
_env = next((str(p) for p in _CAND if p.exists()), ".env")

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_env, extra="ignore")
    database_url: str
    cookie_secure: bool = False
    app_base_url: str = "http://localhost"
    session_horas: int = 8
    smtp_host: str = "localhost"
    smtp_port: int = 25
    smtp_from: str = "nao-responda@exemplo.gov.br"
    smtp_user: str | None = None
    smtp_pass: str | None = None

settings = Settings()
