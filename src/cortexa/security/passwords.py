import base64
import hashlib
import hmac
import secrets
from fastapi import HTTPException


def validate_password(password: str):
    if not 8 <= len(password) <= 128:
        raise HTTPException(422, "密码需为 8–128 位")


def hash_password(password: str) -> str:
    validate_password(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded or len(password) > 128:
        # Perform comparable work even for unknown users.
        hashlib.scrypt(b"invalid", salt=b"0" * 16, n=16384, r=8, p=1)
        return False
    try:
        scheme, salt, expected = encoded.split("$")
        if scheme != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=16384, r=8, p=1)
        return hmac.compare_digest(actual, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
