"""Password hashing with scrypt from the standard library. Stored as
scrypt$n$r$p$salt$hash (base64), so the cost can be raised later without
breaking existing passwords."""

import base64
import hashlib
import hmac
import secrets

N, R, P = 2**14, 8, 1
MIN_LENGTH = 8


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=N, r=R, p=P, dklen=32)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"scrypt${N}${R}${P}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def problem_with(password: str | None) -> str | None:
    """A plain-words reason a new password won't do, or None."""
    if not password or len(password) < MIN_LENGTH:
        return f"A password needs at least {MIN_LENGTH} characters."
    if password.strip() != password:
        return "A password can't start or end with a space."
    return None
