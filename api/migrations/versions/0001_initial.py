"""First slice: people, jobs, selection, timeline, tasks, audit.

The schema lives as plain SQL in migrations/sql/0001_initial.sql, so it can
be read, reviewed and run on its own.

Revision ID: 0001
Revises:
"""

from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = (Path(__file__).resolve().parents[1] / "sql" / "0001_initial.sql").read_text()
    for statement in split_sql(sql):
        # Straight to the driver, one statement at a time: no bind-parameter
        # parsing of the SQL text, no multi-statement surprises.
        op.get_bind().exec_driver_sql(statement)


def split_sql(sql: str) -> list[str]:
    """Drops -- comments and splits on semicolons. The schema files contain no
    functions or quoted semicolons, so this simple split is safe for them."""
    lines = [line.split("--", 1)[0] for line in sql.splitlines()]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def downgrade() -> None:
    raise NotImplementedError("Forward-only: write a new migration instead.")
