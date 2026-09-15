"""Passwords, sign-in tokens and join codes.

Three secrets, three treatments:

* Teacher passwords are hashed with Argon2 (slow on purpose).
* Sign-in tokens are long random strings; only their SHA-256 is stored, which
  is enough because they cannot be guessed.
* Join codes are short enough for a 14-year-old to type, so they are stored as
  an HMAC keyed by `SECRET_KEY`: a copy of the database alone does not reveal
  them, and they can still be looked up directly.
"""

import hashlib
import hmac
import re
import secrets

from pwdlib import PasswordHash

from app.config import get_settings

_passwords = PasswordHash.recommended()

# Verified against when the email is unknown, so a wrong email and a wrong
# password take the same time and cannot be told apart.
_DUMMY_HASH = _passwords.hash("not-a-real-password")

# No 0/O, 1/I/L: codes are read off paper and typed by hand.
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


def normalise_join_code(code: str) -> str:
    """Case, spaces and dashes are forgiven; the letters themselves are not."""
    return re.sub(r"[^A-Z0-9]", "", code.upper())


def join_code_digest(code: str) -> str:
    key = get_settings().secret_key.encode()
    return hmac.new(key, normalise_join_code(code).encode(), hashlib.sha256).hexdigest()


def normalise_email(email: str) -> str:
    return email.strip().lower()
