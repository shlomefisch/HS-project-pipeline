"""Test setup: a real, throwaway Postgres database, migrated with the real migration.

Point TEST_DATABASE_URL at a server you can create databases on, e.g.
    postgresql://postgres:postgres@localhost:5432/postgres
"""

import os
import uuid
from datetime import date, timedelta

import pytest

BASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
DB_NAME = f"pipeline_test_{uuid.uuid4().hex[:8]}"


def _with_db(url: str, name: str) -> str:
    head, _, _ = url.rpartition("/")
    return f"{head}/{name}"


# Settings are read at import time, so the environment is set before the app is imported.
os.environ["DATABASE_URL"] = _with_db(BASE_URL, DB_NAME)
os.environ["DEV_LOGIN"] = "1"
os.environ["ADMIN_EMAILS"] = "boss@hstile.com"
os.environ["SECRET_KEY"] = "test-secret"
os.environ.setdefault("APP_TIMEZONE", "America/New_York")

from sqlalchemy import create_engine, text  # noqa: E402

PURE_ONLY = os.environ.get("PURE_ONLY") == "1"


@pytest.fixture(scope="session")
def database():
    if PURE_ONLY:
        pytest.skip("Database tests skipped (PURE_ONLY=1).")
    admin_url = BASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as c:
        c.execute(text(f'CREATE DATABASE "{DB_NAME}"'))

    from alembic import command
    from alembic.config import Config

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(here, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(here, "migrations"))
    command.upgrade(cfg, "head")

    yield

    from app.db import engine

    engine.dispose()
    with admin_engine.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)'))
    admin_engine.dispose()


TABLES = [
    "sync_runs", "audit_log", "tasks", "event_people", "events", "scheduled_visits", "samples", "candidate_tags",
    "candidates", "items", "areas", "job_roles", "jobs", "entities", "users",
]


@pytest.fixture()
def client(database):
    from fastapi.testclient import TestClient

    from app.db import engine
    from app.main import app

    with engine.begin() as c:
        c.execute(text("TRUNCATE " + ", ".join(TABLES) + " RESTART IDENTITY CASCADE"))
    with TestClient(app) as tc:
        yield tc


class Actor:
    """A signed-in person, for readable tests: jay.post(...), office.get(...)."""

    def __init__(self, client, user: dict, token: str):
        self.client, self.user, self.token = client, user, token
        self.id = user["id"]

    def _h(self):
        return {"Authorization": f"Bearer {self.token}"}

    def get(self, url, **kw):
        return self.client.get(url, headers=self._h(), **kw)

    def post(self, url, json=None, **kw):
        return self.client.post(url, json=json, headers=self._h(), **kw)

    def patch(self, url, json=None, **kw):
        return self.client.patch(url, json=json, headers=self._h(), **kw)

    def delete(self, url, **kw):
        return self.client.delete(url, headers=self._h(), **kw)


def sign_in(client, email: str, name: str = "") -> Actor:
    r = client.post("/api/auth/dev", json={"email": email, "name": name})
    assert r.status_code == 200, r.text
    body = r.json()
    return Actor(client, body["user"], body["token"])


@pytest.fixture()
def boss(client) -> Actor:
    return sign_in(client, "boss@hstile.com", "Boss")


def make_user(boss: Actor, email: str, name: str, role: str, showroom="Monsey", klass="Monsey Showroom") -> Actor:
    a = sign_in(boss.client, email, name)
    r = boss.patch(f"/api/users/{a.id}", json={"role": role, "home_showroom": showroom, "default_class": klass})
    assert r.status_code == 200, r.text
    a.user = r.json()
    return a


@pytest.fixture()
def jay(boss) -> Actor:
    return make_user(boss, "jay@hstile.com", "Jay S.", "rep")


@pytest.fixture()
def office(boss) -> Actor:
    return make_user(boss, "office@hstile.com", "Office", "back_office")


def tomorrow() -> str:
    return (date.today() + timedelta(days=1)).isoformat()


def step(assignee_id: int, title="Follow up", due: str | None = None) -> dict:
    return {"title": title, "assignee_id": assignee_id, "due_date": due or tomorrow()}


def new_entity(actor: Actor, name: str, phone: str | None = None, **kw) -> dict:
    r = actor.post("/api/entities", json={"name": name, "phone": phone, "confirm_new": True, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def new_job(actor: Actor, name="Kisch – Mountain", people=None, **kw) -> dict:
    if people is None:
        rifky = new_entity(actor, "Rifky Freund", "845-555-0101")
        people = [{"entity_id": rifky["id"], "role": "designer"}]
    body = {"name": name, "people": people, "next_step": step(actor.id), **kw}
    r = actor.post("/api/jobs", json=body)
    assert r.status_code == 201, r.text
    return r.json()
