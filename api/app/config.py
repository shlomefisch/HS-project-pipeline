"""Settings, read once from the environment."""

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _list(name: str) -> list[str]:
    raw = os.environ.get(name, "")
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "postgresql+psycopg://postgres@localhost:5432/pipeline")
    # Railway hands out postgres:// or postgresql:// — point SQLAlchemy at psycopg 3.
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=_database_url)
    secret_key: str = field(default_factory=lambda: os.environ.get("SECRET_KEY", "dev-only-change-me"))
    google_client_id: str = field(default_factory=lambda: os.environ.get("GOOGLE_CLIENT_ID", ""))
    allowed_domain: str = field(default_factory=lambda: os.environ.get("ALLOWED_DOMAIN", "hstile.com").lower())
    admin_emails: list[str] = field(default_factory=lambda: _list("ADMIN_EMAILS"))
    # Lets you sign in by typing an email, with no Google. Never turn on in production.
    dev_login: bool = field(default_factory=lambda: _bool("DEV_LOGIN"))
    timezone: str = field(default_factory=lambda: os.environ.get("APP_TIMEZONE", "America/New_York"))
    token_days: int = field(default_factory=lambda: int(os.environ.get("TOKEN_DAYS", "30")))
    web_dist: str = field(default_factory=lambda: os.environ.get("WEB_DIST", ""))


settings = Settings()
