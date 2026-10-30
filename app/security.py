import hashlib
import hmac
import secrets

_N = 2 ** 14


def hash_senha(senha: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(senha.encode(), salt=salt, n=_N, r=8, p=1, dklen=32)
    return "scrypt$" + salt.hex() + "$" + dk.hex()


def senha_confere(guardado: str, senha: str) -> bool:
    try:
        partes = guardado.split("$")
        if len(partes) != 3 or partes[0] != "scrypt":
            return False
        dk = hashlib.scrypt(
            senha.encode(), salt=bytes.fromhex(partes[1]), n=_N, r=8, p=1, dklen=32
        )
        return hmac.compare_digest(dk.hex(), partes[2])
    except Exception:
        return False


def novo_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
