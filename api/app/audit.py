"""Field-level history for every write.

Hooked into the database session itself, so no endpoint can forget to log.
Each change becomes one audit_log row: what changed, from what, to what,
who did it, when. Rows marked story=True show on the job's "story" tab;
everything shows on the "everything" tab.

Nothing is filtered at capture time. Deciding what is noise is a view
question and can change later; history never captured is gone for good.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from .models import AuditLog, Base

_SKIP_FIELDS = {"name_norm", "phone_norm", "email_norm", "created_at", "synced_at"}


def _plain(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _columns(obj: Base) -> list[str]:
    return [c.key for c in inspect(obj).mapper.column_attrs]


def _job_id(obj: Base) -> int | None:
    if obj.__tablename__ == "jobs":
        return getattr(obj, "id", None)
    return getattr(obj, "job_id", None)


def _row_id(obj: Base) -> str:
    # Read the primary key straight off the object: after the INSERT it is
    # populated, even though the identity key is only assigned later.
    mapper = inspect(obj).mapper
    values = [getattr(obj, mapper.get_property_by_column(col).key, None) for col in mapper.primary_key]
    return ",".join("" if v is None else str(v) for v in values)


# ------------------------------------------------------------ story lines
def _story(table: str, action: str, obj: Base, changes: dict) -> str | None:
    """A one-line human summary for changes worth reading on the job's story."""
    g = lambda f: getattr(obj, f, None)  # noqa: E731

    def changed(f: str) -> bool:
        return f in changes

    if table == "jobs":
        if action == "insert":
            return f"Job created: {g('name')}"
        lines = []
        if changed("name"):
            old, new = changes["name"]
            lines.append(f"Renamed from “{old}” to “{new}”")
        if changed("rep_id"):
            lines.append("Rep changed")
        if changed("status"):
            old, new = changes["status"]
            lines.append(f"Job {new.replace('_', ' ')}" + (f" (was {old.replace('_', ' ')})" if old else ""))
        if changed("class_code"):
            lines.append(f"Class set to {g('class_code')}")
        if changed("default_contact_id"):
            lines.append("Default contact changed")
        if changed("address") and g("address"):
            lines.append(f"Address set: {g('address')}")
        return "; ".join(lines) or None

    if table == "job_roles":
        role = (g("role") or "").replace("_", " ")
        if action == "insert":
            return f"{role.capitalize()} added to the job"
        if changed("active") and g("active") is False:
            return f"{role.capitalize()} removed from the job"
        return None

    if table == "areas":
        if action == "insert":
            return f"Area added: {g('name')}"
        if changed("status"):
            return f"{g('name')}: {g('status').replace('_', ' ')}"
        if changed("name"):
            old, new = changes["name"]
            return f"Area renamed from {old} to {new}"
        return None

    if table == "candidates" and action == "insert":
        return f"Tile added: {g('name') or ('item #' + str(g('netsuite_item_id')))}"

    if table == "candidate_tags":
        if action == "insert":
            return "Tile tagged to an area"
        if changed("status"):
            status = g("status")
            if status == "declined":
                return f"Tile declined — {g('reason')}"
            if status == "chosen":
                return "Tile chosen"
            return "Decision undone — back to considering"
        return None

    if table == "samples":
        if action == "insert":
            return f"Sample requested: {g('description')}"
        if changed("status"):
            return f"Sample {g('status')}: {g('description')}"
        return None

    if table == "events" and action == "insert":
        return g("summary")

    if table == "scheduled_visits":
        when = g("starts_at")
        when_txt = when.strftime("%b %-d, %-I:%M %p") if isinstance(when, datetime) else str(when)
        if action == "insert":
            return f"{'Site' if g('kind') == 'site' else 'Showroom'} visit scheduled for {when_txt}"
        if changed("status"):
            return f"Visit {g('status').replace('_', ' ')}"
        return None

    if table == "tasks":
        if action == "insert":
            return f"Next step: {g('title')} (due {g('due_date')})"
        if changed("status"):
            status = g("status")
            note = g("outcome_note")
            label = {
                "done": "Done",
                "blocked": "Blocked",
                "bad_answer": "Bad answer",
                "skipped": "Skipped",
                "open": "Reopened",
            }.get(status, status)
            return f"{label}: {g('title')}" + (f" — {note}" if note and status != "open" else "")
        if changed("assignee_id"):
            return f"Reassigned: {g('title')}"
        return None

    return None


# ------------------------------------------------------------- the hook
def _collect(session: Session) -> list[dict]:
    rows: list[dict] = []
    user_id = session.info.get("user_id")

    for obj in list(session.new):
        if isinstance(obj, AuditLog) or not isinstance(obj, Base):
            continue
        changes = {}
        unloaded = inspect(obj).unloaded
        for key in _columns(obj):
            # Skip fields the database filled in and that aren't loaded yet:
            # reading them here would fire a query in the middle of the flush.
            if key in _SKIP_FIELDS or key in unloaded:
                continue
            val = getattr(obj, key, None)
            if val is not None:
                changes[key] = [None, _plain(val)]
        rows.append(_row(obj, "insert", changes, user_id))

    for obj in list(session.dirty):
        if isinstance(obj, AuditLog) or not isinstance(obj, Base):
            continue
        if not session.is_modified(obj, include_collections=False):
            continue
        state = inspect(obj)
        changes = {}
        for key in _columns(obj):
            if key in _SKIP_FIELDS:
                continue
            hist = state.attrs[key].history
            if not hist.has_changes():
                continue
            old = hist.deleted[0] if hist.deleted else None
            new = hist.added[0] if hist.added else None
            if old == new:
                continue
            changes[key] = [_plain(old), _plain(new)]
        if changes:
            rows.append(_row(obj, "update", changes, user_id))

    for obj in list(session.deleted):
        if isinstance(obj, AuditLog) or not isinstance(obj, Base):
            continue
        unloaded = inspect(obj).unloaded
        changes = {k: [_plain(getattr(obj, k, None)), None] for k in _columns(obj) if k not in _SKIP_FIELDS and k not in unloaded}
        rows.append(_row(obj, "delete", changes, user_id))

    return rows


def _row(obj: Base, action: str, changes: dict, user_id: int | None) -> dict:
    table = obj.__tablename__
    summary = _story(table, action, obj, changes)
    return {
        "user_id": user_id,
        "job_id": _job_id(obj),
        "table_name": table,
        "row_id": _row_id(obj),
        "action": action,
        "changes": changes,
        "story": summary is not None,
        "summary": summary,
    }


@event.listens_for(Session, "after_flush")
def _after_flush(session: Session, _ctx) -> None:
    rows = _collect(session)
    if rows:
        session.connection().execute(AuditLog.__table__.insert(), rows)
