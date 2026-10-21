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


# Answers worth replaying. A 401/403/429 says nothing about the work itself — after the
# person signs in again, the same save must be allowed to go through.
KEEP = lambda code: 200 <= code < 300 or code in (404, 409, 422)  # noqa: E731
WORKING = 0  # placeholder while the first request is still running


class IdempotencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        key = request.headers.get("Idempotency-Key")
        if request.method not in ("POST", "PUT", "PATCH") or not key or not KEY_OK.match(key):
            return await call_next(request)
        # Keys are random 128-bit values made on the phone, so nobody can guess another's.
        scoped = key
        # Claim the key before doing the work, so a resend that arrives mid-way doesn't do it twice.
        with engine.begin() as c:
            claimed = c.execute(
                text("INSERT INTO idempotency_keys (key, method, path, status_code, body) "
                     "VALUES (:k, :m, :p, :s, NULL) ON CONFLICT (key) DO NOTHING RETURNING key"),
                {"k": scoped, "m": request.method, "p": request.url.path[:300], "s": WORKING},
            ).first()
            hit = None if claimed else c.execute(text("SELECT status_code, body FROM idempotency_keys WHERE key = :k"), {"k": scoped}).first()
        if hit:
            if hit.status_code == WORKING:
                # The first send is still being worked on. A 503 makes the phone keep it and try again shortly.
                return Response(content='{"detail":"Still saving the first try — trying again shortly."}', status_code=503,
                                media_type="application/json", headers={"Retry-After": "3"})
            return Response(content=hit.body or "", status_code=hit.status_code, media_type="application/json",
                            headers={"Idempotent-Replay": "true"})

        try:
            response = await call_next(request)
            body = b""
            async for chunk in response.body_iterator:
                body += chunk
        except Exception:
            with engine.begin() as c:
                c.execute(text("DELETE FROM idempotency_keys WHERE key = :k AND status_code = :w"), {"k": scoped, "w": WORKING})
            raise
        with engine.begin() as c:
            if KEEP(response.status_code):
                c.execute(text("UPDATE idempotency_keys SET status_code = :s, body = :b WHERE key = :k"),
                          {"k": scoped, "s": response.status_code, "b": body.decode("utf-8", "replace")})
            else:
                c.execute(text("DELETE FROM idempotency_keys WHERE key = :k AND status_code = :w"), {"k": scoped, "w": WORKING})
        headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
        return Response(content=body, status_code=response.status_code, headers=headers, media_type=response.media_type)


def prune() -> int:
    with engine.begin() as c:
        # Old answers go; so does a claim stuck from a crash (older than an hour, never filled in).
        return c.execute(text(
            f"DELETE FROM idempotency_keys WHERE created_at < now() - interval '{KEEP_DAYS} days' "
            f"OR (status_code = {WORKING} AND created_at < now() - interval '1 hour')"
        )).rowcount
