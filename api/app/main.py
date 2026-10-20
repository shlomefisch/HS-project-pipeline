"""One service: the API under /api, and the installable web app at /.

Serving both from one place means one URL to whitelist on filtered
phones, one deploy, and no cross-origin setup.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from starlette.requests import Request

from . import audit  # noqa: F401  — registers the audit hook on every session
from . import scheduler
from .config import settings
from .db import engine
from .routers import auth, dashboard, entities, jobs, meta, plans, selection, sync, tasks, timeline, users



@asynccontextmanager
async def lifespan(_: FastAPI):
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="Project Pipeline", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)

for r in (meta, auth, users, entities, jobs, selection, plans, timeline, tasks, dashboard, sync):
    app.include_router(r.router, prefix="/api")


@app.get("/api/health", tags=["meta"])
def health():
    with engine.connect() as conn:
        conn.execute(text("select 1"))
    return {"ok": True}


# ------------------------------------------------------------ web app
def _dist() -> Path | None:
    candidates = [settings.web_dist] if settings.web_dist else []
    candidates.append(str(Path(__file__).resolve().parents[2] / "web" / "dist"))
    for c in candidates:
        p = Path(c)
        if (p / "index.html").is_file():
            return p
    return None


@app.exception_handler(404)
async def spa_fallback(request: Request, exc: HTTPException):
    """Unknown non-API paths get the app shell, so deep links work."""
    path = request.url.path
    dist = _dist()
    if path == "/api" or path.startswith("/api/") or dist is None or request.method != "GET":
        detail = getattr(exc, "detail", "Not found.")
        return JSONResponse({"detail": detail}, status_code=404)
    return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/{path:path}", include_in_schema=False)
def static_files(path: str):
    if path == "api" or path.startswith("api/"):
        raise HTTPException(404, "No such API endpoint.")
    dist = _dist()
    if dist is None:
        raise HTTPException(404, "Web app not built.")
    target = (dist / path).resolve()
    if path and target.is_file() and dist.resolve() in target.parents:
        # Only fingerprinted bundles under assets/ are cached hard. index.html and
        # sw.js must always be re-checked, or updates never reach the phones.
        hashed = path.startswith("assets/")
        headers = {"Cache-Control": "public, max-age=31536000, immutable"} if hashed else {"Cache-Control": "no-cache"}
        return FileResponse(target, headers=headers)
    return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})
