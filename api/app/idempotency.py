"""Requests carrying an Idempotency-Key are done once. A repeat with the same key
gets the first answer back instead of doing the work again. The phone's offline
queue sends one with every save it holds."""

import re

from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .db import engine

KEY_OK = re.compile(r"^[A-Za-z0-9_-]{16,80}$")
KEEP_DAYS = 14


class IdempotencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        key = request.headers.get("Idempotency-Key")
        if request.method not in ("POST", "PUT", "PATCH") or not key or not KEY_OK.match(key):
            return await call_next(request)
        # Keys are random 128-bit values made on the phone, so nobody can guess another's.
        scoped = key
        with engine.connect() as c:
            hit = c.execute(text("SELECT status_code, body FROM idempotency_keys WHERE key = :k"), {"k": scoped}).first()
        if hit:
            return Response(content=hit.body or "", status_code=hit.status_code, media_type="application/json",
                            headers={"Idempotent-Replay": "true"})

        response = await call_next(request)
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        # Keep every answer the work actually decided (2xx and 4xx). A 5xx may be worth trying again.
        if response.status_code < 500:
            with engine.begin() as c:
                c.execute(
                    text("INSERT INTO idempotency_keys (key, method, path, status_code, body) "
                         "VALUES (:k, :m, :p, :s, :b) ON CONFLICT (key) DO NOTHING"),
                    {"k": scoped, "m": request.method, "p": request.url.path[:300], "s": response.status_code,
                     "b": body.decode("utf-8", "replace")},
                )
        headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
        return Response(content=body, status_code=response.status_code, headers=headers, media_type=response.media_type)


def prune() -> int:
    with engine.begin() as c:
        return c.execute(text(f"DELETE FROM idempotency_keys WHERE created_at < now() - interval '{KEEP_DAYS} days'")).rowcount
