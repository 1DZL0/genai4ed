"""Passwords (Argon2), sign-in tokens (stored as a SHA-256 digest) and join codes (stored as an
HMAC keyed by `SECRET_KEY`, because they are short enough to brute-force from a database copy)."""

import hashlib
import hmac
import re
import secrets

from pwdlib import PasswordHash

from app.config import get_settings

_passwords = PasswordHash.recommended()

# Verified against when the email is unknown, so a wrong email takes as long as a wrong password.
_DUMMY_HASH = _passwords.hash("not-a-real-password")

# No 0/O or 1/I/L: codes are read off paper and typed by hand.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 8

MIN_PASSWORD_LENGTH = 10


def hash_password(password: str) -> str:
    return _passwords.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if password_hash is None:
        _passwords.verify(password, _DUMMY_HASH)
        return False
    return _passwords.verify(password, password_hash)


def new_password() -> str:
    return secrets.token_urlsafe(12)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_join_code() -> str:
    raw = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))
    return f"{raw[:4]}-{raw[4:]}"


def join_code_digest(code: str) -> str:
    # Case, spaces and dashes are forgiven; the letters themselves are not.
    code = re.sub(r"[^A-Z0-9]", "", code.upper())
    return hmac.new(get_settings().secret_key.encode(), code.encode(), hashlib.sha256).hexdigest()


def normalise_email(email: str) -> str:
    return email.strip().lower()
