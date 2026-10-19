"""How names, phones and emails are compared when looking for duplicates.

The same rules are used for our own people list and, later, for matching
NetSuite customers at the handoff. "Pinches  Kisch " and "pinches kisch"
are the same man; (845) 555-1234 and 845.555.1234 are the same phone.
"""

import re
import unicodedata

_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")
_DIGITS = re.compile(r"\D")


def norm_name(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value).lower()
    text = text.replace("_", " ")
    text = _NON_WORD.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def norm_phone(value: str | None) -> str | None:
    """Digits only, US country code dropped. Too short to be a phone -> None."""
    if not value:
        return None
    digits = _DIGITS.sub("", value)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) < 7:
        return None
    return digits


def norm_email(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip().lower()
    if "@" not in text or text.startswith("@") or text.endswith("@"):
        return None
    return text
