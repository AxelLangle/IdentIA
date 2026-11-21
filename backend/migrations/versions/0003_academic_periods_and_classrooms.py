"""Agrega tipos de periodo académico (institución/carrera) y aula fija en grupos.

Revision ID: 0003_academic_periods_and_classrooms
Revises: 0002_education_domain
Create Date: 2026-11-20 22:38:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_academic_periods_and_classrooms"
down_revision: Union[str, Sequence[str], None] = "0002_education_domain"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {col["name"] for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    org_cols = _column_names(inspector, "organizations")
    if "academic_period_type" not in org_cols:
        with op.batch_alter_table("organizations") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "academic_period_type",
                    sa.String(length=20),
                    nullable=False,
                    server_default="semestral",
                )
            )

    career_cols = _column_names(inspector, "careers")
    if "period_type" not in career_cols:
        with op.batch_alter_table("careers") as batch_op:
            batch_op.add_column(sa.Column("period_type", sa.String(length=20), nullable=True))

    group_cols = _column_names(inspector, "groups")
    if "default_classroom" not in group_cols:
        with op.batch_alter_table("groups") as batch_op:
            batch_op.add_column(
                sa.Column("default_classroom", sa.String(length=80), nullable=True)
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "default_classroom" in _column_names(inspector, "groups"):
        with op.batch_alter_table("groups") as batch_op:
            batch_op.drop_column("default_classroom")

    if "period_type" in _column_names(inspector, "careers"):
        with op.batch_alter_table("careers") as batch_op:
            batch_op.drop_column("period_type")

    if "academic_period_type" in _column_names(inspector, "organizations"):
        with op.batch_alter_table("organizations") as batch_op:
            batch_op.drop_column("academic_period_type")
