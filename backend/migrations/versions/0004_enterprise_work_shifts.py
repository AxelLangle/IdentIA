"""Agrega turnos laborales empresariales (WorkShift) y métricas de puntualidad/salida.

Revision ID: 0004_enterprise_work_shifts
Revises: 0003_academic_periods_and_classrooms
Create Date: 2026-11-21 00:20:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores de revisión Alembic (invariantes)
revision: str = "0004_enterprise_work_shifts"
down_revision: Union[str, Sequence[str], None] = "0003_academic_periods_and_classrooms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _nombres_columnas(inspector: sa.Inspector, nombre_tabla: str) -> set[str]:
    """Lista las columnas físicas actuales de `nombre_tabla`."""
    return {columna["name"] for columna in inspector.get_columns(nombre_tabla)}


def _nombres_indices(inspector: sa.Inspector, nombre_tabla: str) -> set[str]:
    """Lista los nombres de índices actuales de `nombre_tabla`."""
    return {indice["name"] for indice in inspector.get_indexes(nombre_tabla)}


def _tiene_llave_foranea(
    inspector: sa.Inspector,
    nombre_tabla: str,
    nombre_fk: str,
    nombre_columna: str,
) -> bool:
    """Comprueba la existencia previa de una llave foránea sobre `nombre_columna`."""
    for fk in inspector.get_foreign_keys(nombre_tabla):
        if fk.get("name") == nombre_fk or nombre_columna in (
            fk.get("constrained_columns") or []
        ):
            return True
    return False


def _asegurar_indice(
    inspector: sa.Inspector,
    nombre_indice: str,
    nombre_tabla: str,
    columnas: list[str],
) -> None:
    """Crea un índice no único si aún no existe."""
    if nombre_indice not in _nombres_indices(inspector, nombre_tabla):
        op.create_index(nombre_indice, nombre_tabla, columnas, unique=False)


def _agregar_columna_fk_turno(
    inspector: sa.Inspector,
    *,
    nombre_tabla: str,
    nombre_columna: str,
    nombre_indice: str,
    nombre_fk: str,
) -> None:
    """Agrega una columna nullable referenciando `work_shifts.id` junto con su índice y FK."""
    columnas = _nombres_columnas(inspector, nombre_tabla)
    indices = _nombres_indices(inspector, nombre_tabla)
    tiene_fk = _tiene_llave_foranea(inspector, nombre_tabla, nombre_fk, nombre_columna)
    if nombre_columna not in columnas or nombre_indice not in indices or not tiene_fk:
        with op.batch_alter_table(nombre_tabla) as lote:
            if nombre_columna not in columnas:
                lote.add_column(sa.Column(nombre_columna, sa.Integer(), nullable=True))
            if nombre_indice not in indices:
                lote.create_index(nombre_indice, [nombre_columna], unique=False)
            if not tiene_fk:
                lote.create_foreign_key(
                    nombre_fk,
                    "work_shifts",
                    [nombre_columna],
                    ["id"],
                    ondelete="SET NULL",
                )


def upgrade() -> None:
    """Crea la tabla `work_shifts` y extiende grupos, personas, sesiones y eventos."""
    conexion = op.get_bind()
    inspector = sa.inspect(conexion)
    tablas_existentes = set(inspector.get_table_names())

    if "work_shifts" not in tablas_existentes:
        op.create_table(
            "work_shifts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("organization_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("code", sa.String(length=40), nullable=False),
            sa.Column("start_time", sa.String(length=5), nullable=False),
            sa.Column("end_time", sa.String(length=5), nullable=False),
            sa.Column("crosses_midnight", sa.Boolean(), nullable=False),
            sa.Column("days_of_week", sa.String(length=30), nullable=False),
            sa.Column("late_tolerance_minutes", sa.Integer(), nullable=True),
            sa.Column("early_exit_tolerance_minutes", sa.Integer(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("organization_id", "code", name="uq_work_shift_org_code"),
        )
        inspector = sa.inspect(conexion)

    _asegurar_indice(inspector, op.f("ix_work_shifts_id"), "work_shifts", ["id"])
    _asegurar_indice(
        inspector, op.f("ix_work_shifts_organization_id"), "work_shifts", ["organization_id"]
    )

    _agregar_columna_fk_turno(
        inspector,
        nombre_tabla="groups",
        nombre_columna="default_work_shift_id",
        nombre_indice=op.f("ix_groups_default_work_shift_id"),
        nombre_fk="fk_groups_default_work_shift_id",
    )
    _agregar_columna_fk_turno(
        inspector,
        nombre_tabla="persons",
        nombre_columna="work_shift_id",
        nombre_indice=op.f("ix_persons_work_shift_id"),
        nombre_fk="fk_persons_work_shift_id",
    )
    _agregar_columna_fk_turno(
        inspector,
        nombre_tabla="attendance_sessions",
        nombre_columna="work_shift_id",
        nombre_indice=op.f("ix_attendance_sessions_work_shift_id"),
        nombre_fk="fk_attendance_sessions_work_shift_id",
    )

    inspector = sa.inspect(conexion)
    columnas_ev = _nombres_columnas(inspector, "attendance_events")
    indices_ev = _nombres_indices(inspector, "attendance_events")
    ev_tiene_fk = _tiene_llave_foranea(
        inspector, "attendance_events", "fk_attendance_events_work_shift_id", "work_shift_id"
    )
    nombre_indice_ev = op.f("ix_attendance_events_work_shift_id")
    if (
        "work_shift_id" not in columnas_ev
        or "worked_minutes" not in columnas_ev
        or "late_minutes" not in columnas_ev
        or "early_exit_minutes" not in columnas_ev
        or nombre_indice_ev not in indices_ev
        or not ev_tiene_fk
    ):
        with op.batch_alter_table("attendance_events") as lote:
            if "work_shift_id" not in columnas_ev:
                lote.add_column(sa.Column("work_shift_id", sa.Integer(), nullable=True))
            if "worked_minutes" not in columnas_ev:
                lote.add_column(sa.Column("worked_minutes", sa.Integer(), nullable=True))
            if "late_minutes" not in columnas_ev:
                lote.add_column(sa.Column("late_minutes", sa.Integer(), nullable=True))
            if "early_exit_minutes" not in columnas_ev:
                lote.add_column(sa.Column("early_exit_minutes", sa.Integer(), nullable=True))
            if nombre_indice_ev not in indices_ev:
                lote.create_index(nombre_indice_ev, ["work_shift_id"], unique=False)
            if not ev_tiene_fk:
                lote.create_foreign_key(
                    "fk_attendance_events_work_shift_id",
                    "work_shifts",
                    ["work_shift_id"],
                    ["id"],
                    ondelete="SET NULL",
                )


def downgrade() -> None:
    """Elimina las columnas, índices y la tabla `work_shifts` agregadas en esta revisión."""
    conexion = op.get_bind()
    inspector = sa.inspect(conexion)

    columnas_ev = _nombres_columnas(inspector, "attendance_events")
    indices_ev = _nombres_indices(inspector, "attendance_events")
    if (
        "work_shift_id" in columnas_ev
        or "worked_minutes" in columnas_ev
        or "late_minutes" in columnas_ev
        or "early_exit_minutes" in columnas_ev
    ):
        with op.batch_alter_table("attendance_events") as lote:
            if _tiene_llave_foranea(
                inspector,
                "attendance_events",
                "fk_attendance_events_work_shift_id",
                "work_shift_id",
            ):
                lote.drop_constraint("fk_attendance_events_work_shift_id", type_="foreignkey")
            if op.f("ix_attendance_events_work_shift_id") in indices_ev:
                lote.drop_index(op.f("ix_attendance_events_work_shift_id"))
            for nombre_col in (
                "early_exit_minutes",
                "late_minutes",
                "worked_minutes",
                "work_shift_id",
            ):
                if nombre_col in columnas_ev:
                    lote.drop_column(nombre_col)

    for nombre_tabla, nombre_col, nombre_idx, nombre_fk in (
        (
            "attendance_sessions",
            "work_shift_id",
            op.f("ix_attendance_sessions_work_shift_id"),
            "fk_attendance_sessions_work_shift_id",
        ),
        (
            "persons",
            "work_shift_id",
            op.f("ix_persons_work_shift_id"),
            "fk_persons_work_shift_id",
        ),
        (
            "groups",
            "default_work_shift_id",
            op.f("ix_groups_default_work_shift_id"),
            "fk_groups_default_work_shift_id",
        ),
    ):
        columnas = _nombres_columnas(inspector, nombre_tabla)
        indices = _nombres_indices(inspector, nombre_tabla)
        if nombre_col in columnas or nombre_idx in indices:
            with op.batch_alter_table(nombre_tabla) as lote:
                if _tiene_llave_foranea(inspector, nombre_tabla, nombre_fk, nombre_col):
                    lote.drop_constraint(nombre_fk, type_="foreignkey")
                if nombre_idx in indices:
                    lote.drop_index(nombre_idx)
                if nombre_col in columnas:
                    lote.drop_column(nombre_col)

    inspector = sa.inspect(conexion)
    if "work_shifts" in inspector.get_table_names():
        indices_ws = _nombres_indices(inspector, "work_shifts")
        if op.f("ix_work_shifts_organization_id") in indices_ws:
            op.drop_index(op.f("ix_work_shifts_organization_id"), table_name="work_shifts")
        if op.f("ix_work_shifts_id") in indices_ws:
            op.drop_index(op.f("ix_work_shifts_id"), table_name="work_shifts")
        op.drop_table("work_shifts")
