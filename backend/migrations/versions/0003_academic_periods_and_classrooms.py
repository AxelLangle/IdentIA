"""Agrega tipos de periodo académico (institución/carrera) y aula fija en grupos.

Revision ID: 0003_academic_periods_and_classrooms
Revises: 0002_education_domain
Create Date: 2026-11-20 22:38:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores de revisión Alembic (invariantes)
revision: str = "0003_academic_periods_and_classrooms"
down_revision: Union[str, Sequence[str], None] = "0002_education_domain"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _nombres_columnas(inspector: sa.Inspector, nombre_tabla: str) -> set[str]:
    """Obtiene el conjunto de columnas actuales de una tabla."""
    return {columna["name"] for columna in inspector.get_columns(nombre_tabla)}


def upgrade() -> None:
    """Agrega tipo de periodo general/por carrera y aula fija por defecto en grupos."""
    conexion = op.get_bind()
    inspector = sa.inspect(conexion)

    columnas_org = _nombres_columnas(inspector, "organizations")
    if "academic_period_type" not in columnas_org:
        with op.batch_alter_table("organizations") as lote:
            lote.add_column(
                sa.Column(
                    "academic_period_type",
                    sa.String(length=20),
                    nullable=False,
                    server_default="semestral",
                )
            )

    columnas_carrera = _nombres_columnas(inspector, "careers")
    if "period_type" not in columnas_carrera:
        with op.batch_alter_table("careers") as lote:
            lote.add_column(sa.Column("period_type", sa.String(length=20), nullable=True))

    columnas_grupo = _nombres_columnas(inspector, "groups")
    if "default_classroom" not in columnas_grupo:
        with op.batch_alter_table("groups") as lote:
            lote.add_column(
                sa.Column("default_classroom", sa.String(length=80), nullable=True)
            )


def downgrade() -> None:
    """Elimina las columnas de periodo académico y aula fija por defecto."""
    conexion = op.get_bind()
    inspector = sa.inspect(conexion)

    if "default_classroom" in _nombres_columnas(inspector, "groups"):
        with op.batch_alter_table("groups") as lote:
            lote.drop_column("default_classroom")

    if "period_type" in _nombres_columnas(inspector, "careers"):
        with op.batch_alter_table("careers") as lote:
            lote.drop_column("period_type")

    if "academic_period_type" in _nombres_columnas(inspector, "organizations"):
        with op.batch_alter_table("organizations") as lote:
            lote.drop_column("academic_period_type")
