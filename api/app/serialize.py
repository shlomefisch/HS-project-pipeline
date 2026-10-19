"""Turning rows into JSON-ready dicts."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import inspect

from .models import Base


def _val(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


def row(obj: Base | None, *, skip: tuple[str, ...] = ()) -> dict | None:
    if obj is None:
        return None
    return {c.key: _val(getattr(obj, c.key)) for c in inspect(obj).mapper.column_attrs if c.key not in skip}


ENTITY_SKIP = ("name_norm", "phone_norm", "email_norm")


def user_out(u) -> dict | None:
    if u is None:
        return None
    return {
        "id": u.id,
        "email": u.email,
        "name": u.name,
        "role": u.role,
        "is_admin": u.is_admin,
        "home_showroom": u.home_showroom,
        "default_class": u.default_class,
        "active": u.active,
        "has_password": bool(u.password_hash),
        "must_change_password": bool(u.must_change_password),
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


def entity_out(e) -> dict | None:
    return row(e, skip=ENTITY_SKIP)
