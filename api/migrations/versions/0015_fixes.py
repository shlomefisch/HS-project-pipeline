"""Fixes: an ordered line can drop to zero.

Revision ID: 0015
Revises: 0014
"""

from pathlib import Path

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = (Path(__file__).resolve().parents[1] / "sql" / "0015_fixes.sql").read_text()
    lines = [line.split("--", 1)[0] for line in sql.splitlines()]
    for statement in (s.strip() for s in "\n".join(lines).split(";")):
        if statement:
            op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    raise NotImplementedError("Forward-only: write a new migration instead.")
