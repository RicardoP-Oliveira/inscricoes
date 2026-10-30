import hashlib, secrets
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_ph = PasswordHasher()

def hash_senha(s: str) -> str:
    return _ph.hash(s)

def senha_confere(h: str, s: str) -> bool:
    try:
        return _ph.verify(h, s)
    except (VerifyMismatchError, InvalidHashError):
        return False

def novo_token() -> str:
    return secrets.token_urlsafe(32)

def hash_token(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()
