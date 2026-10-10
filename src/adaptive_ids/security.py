"""Password hashing (scrypt, stdlib) and opaque session tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1
MIN_PASSWORD_LENGTH = 12


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, n, r, p, salt_b64, dk_b64 = encoded.split("$")
        if algo != "scrypt":
            return False
        expected = base64.b64decode(dk_b64)
        dk = hashlib.scrypt(
            password.encode("utf-8"), salt=base64.b64decode(salt_b64),
            n=int(n), r=int(r), p=int(p), dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk, expected)


# A fixed hash used to spend the same time on unknown usernames (no user enumeration by timing).
DUMMY_HASH = hash_password("dummy-password-for-timing")


def new_session_token() -> tuple[str, str]:
    """Return (token for the client, sha256 hash to store)."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
