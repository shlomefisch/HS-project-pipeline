"""Estimates assembled on the job, priced from NetSuite Base Price.

Revision ID: 0007
Revises: 0006
"""

from pathlib import Path

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = (Path(__file__).resolve().parents[1] / "sql" / "0007_estimates.sql").read_text()
    lines = [line.split("--", 1)[0] for line in sql.splitlines()]
    for statement in (s.strip() for s in "\n".join(lines).split(";")):
        if statement:
            op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    raise NotImplementedError("Forward-only: write a new migration instead.")
