from datetime import datetime
from pydantic import BaseModel, EmailStr, Field

class InscricaoIn(BaseModel):
    nome: str = Field(min_length=3, max_length=120)
    documento: str = Field(min_length=5, max_length=32)
    email: EmailStr
    telefone: str | None = None
    website: str | None = None

class LoginIn(BaseModel):
    username: str
    senha: str

class EventoIn(BaseModel):
    titulo: str = Field(min_length=3, max_length=160)
    descricao: str | None = None
    data_evento: datetime
    local: str | None = None
    vagas_titulares: int = Field(gt=0)
    vagas_reserva: int = Field(ge=0, default=0)
    prazo_confirmacao_horas: int = Field(gt=0, default=24)
    inscricoes_encerram_em: datetime | None = None

class UsuarioIn(BaseModel):
    nome: str
    username: str
    email: str | None = None
    senha: str = Field(min_length=8)
    perfil: str = "APOIO"
