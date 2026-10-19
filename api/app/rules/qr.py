"""Reading the showroom QR tags.

Every stocking item carries a QR code holding a URL that ends with
"/<NetSuite internal id>". We keep only that number.
"""

from urllib.parse import parse_qs, urlsplit


def parse_item_code(code: str | None) -> int | None:
    if code is None:
        return None
    text = code.strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)

    parts = urlsplit(text)
    segments = [s for s in parts.path.split("/") if s]
    if segments and segments[-1].isdigit():
        return int(segments[-1])

    # Fallback: a URL carrying the id as ?id=12345
    query = parse_qs(parts.query)
    for key in ("id", "internalid", "item"):
        for val in query.get(key, []):
            if val.isdigit():
                return int(val)
    return None
