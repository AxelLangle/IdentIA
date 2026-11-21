"""Agrega tipo de periodo propio opcional en grupos académicos.

Revision ID: 0005_group_period_type
Revises: 0004_enterprise_work_shifts
Create Date: 2026-11-21 10:35:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores de revisión Alembic (invariantes)
revision: str = "0005_group_period_type"
down_revision: Union[str, Sequence[str], None] = "0004_enterprise_work_shifts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _nombres_columnas(inspector: sa.Inspector, nombre_tabla: str) -> set[str]:
    """Devuelve el conjunto de columnas actuales de `nombre_tabla`."""
    return {columna["name"] for columna in inspector.get_columns(nombre_tabla)}


def upgrade() -> None:
    """Agrega la columna opcional `period_type` a la tabla `groups`."""
    conexion = op.get_bind()
    inspector = sa.inspect(conexion)
    if "period_type" not in _nombres_columnas(inspector, "groups"):
        with op.batch_alter_table("groups") as lote:
            lote.add_column(sa.Column("period_type", sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Elimina la columna `period_type` de la tabla `groups`."""
    conexion = op.get_bind()
    inspector = sa.inspect(conexion)
    if "period_type" in _nombres_columnas(inspector, "groups"):
        with op.batch_alter_table("groups") as lote:
            lote.drop_column("period_type")
