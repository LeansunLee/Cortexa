"""Fernet symmetric encryption for sensitive credentials."""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet


_DEFAULT_KEY_SEED = "agentdevstu-default-dev-key"


def _get_key() -> bytes:
    """Get encryption key from env or derive from seed."""
    env_key = os.getenv("DATA_ENCRYPT_KEY", "")
    if env_key:
        return env_key.encode() if len(env_key) == 44 else base64.urlsafe_b64encode(
            hashlib.sha256(env_key.encode()).digest()
        )
    derived = hashlib.sha256(_DEFAULT_KEY_SEED.encode()).digest()
    return base64.urlsafe_b64encode(derived)


_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_get_key())
    return _fernet


def encrypt_value(plaintext: str) -> str:
    """Encrypt a plaintext string, return base64 ciphertext."""
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_value(ciphertext: str) -> str:
    """Decrypt a base64 ciphertext string, return plaintext."""
    return _get_fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")


def encrypt_dict(data: dict) -> str:
    """Encrypt a dict as JSON string."""
    import json
    return encrypt_value(json.dumps(data, ensure_ascii=False))


def decrypt_dict(ciphertext: str) -> dict:
    """Decrypt to dict."""
    import json
    return json.loads(decrypt_value(ciphertext))


# --- Safe display helpers ---

def mask_value(value: str, show_chars: int = 4) -> str:
    """Mask a sensitive value, showing only last N chars."""
    if len(value) <= show_chars:
        return "***"
    return "*" * (len(value) - show_chars) + value[-show_chars:]


def safe_credential_response(credential) -> dict:
    """Build a safe credential dict for API response (never expose secrets)."""
    return {
        "id": str(credential.id),
        "workspace_id": str(credential.workspace_id),
        "name": credential.name,
        "type": credential.type,
        "created_at": credential.created_at.isoformat() if credential.created_at else None,
        "updated_at": credential.updated_at.isoformat() if credential.updated_at else None,
    }
