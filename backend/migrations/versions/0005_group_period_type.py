"""Agrega tipo de periodo propio opcional en grupos académicos.

Revision ID: 0005_group_period_type
Revises: 0004_enterprise_work_shifts
Create Date: 2026-11-21 10:35:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005_group_period_type"
down_revision: Union[str, Sequence[str], None] = "0004_enterprise_work_shifts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {col["name"] for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "period_type" not in _column_names(inspector, "groups"):
        with op.batch_alter_table("groups") as batch_op:
            batch_op.add_column(sa.Column("period_type", sa.String(length=20), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "period_type" in _column_names(inspector, "groups"):
        with op.batch_alter_table("groups") as batch_op:
            batch_op.drop_column("period_type")
