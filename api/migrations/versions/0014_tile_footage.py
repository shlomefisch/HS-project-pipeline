"""The number on the tile is the footage: write the area number onto chosen tiles that had none.

Revision ID: 0014
Revises: 0013
"""

from pathlib import Path

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = (Path(__file__).resolve().parents[1] / "sql" / "0014_tile_footage.sql").read_text()
    lines = [line.split("--", 1)[0] for line in sql.splitlines()]
    for statement in (s.strip() for s in "\n".join(lines).split(";")):
        if statement:
            op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    raise NotImplementedError("Forward-only: write a new migration instead.")
