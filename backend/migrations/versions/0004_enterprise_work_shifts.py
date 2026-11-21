"""Agrega turnos laborales empresariales (WorkShift) y métricas de puntualidad/salida.

Revision ID: 0004_enterprise_work_shifts
Revises: 0003_academic_periods_and_classrooms
Create Date: 2026-11-21 00:20:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_enterprise_work_shifts"
down_revision: Union[str, Sequence[str], None] = "0003_academic_periods_and_classrooms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {col["name"] for col in inspector.get_columns(table_name)}


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {idx["name"] for idx in inspector.get_indexes(table_name)}


def _has_fk(inspector: sa.Inspector, table_name: str, fk_name: str, col_name: str) -> bool:
    for fk in inspector.get_foreign_keys(table_name):
        if fk.get("name") == fk_name or col_name in (fk.get("constrained_columns") or []):
            return True
    return False


def _ensure_index(
    inspector: sa.Inspector,
    index_name: str,
    table_name: str,
    columns: list[str],
) -> None:
    if index_name not in _index_names(inspector, table_name):
        op.create_index(index_name, table_name, columns, unique=False)


def _add_work_shift_fk_column(
    inspector: sa.Inspector,
    *,
    table_name: str,
    column_name: str,
    index_name: str,
    fk_name: str,
) -> None:
    cols = _column_names(inspector, table_name)
    idxs = _index_names(inspector, table_name)
    has_fk = _has_fk(inspector, table_name, fk_name, column_name)
    if column_name not in cols or index_name not in idxs or not has_fk:
        with op.batch_alter_table(table_name) as batch_op:
            if column_name not in cols:
                batch_op.add_column(sa.Column(column_name, sa.Integer(), nullable=True))
            if index_name not in idxs:
                batch_op.create_index(index_name, [column_name], unique=False)
            if not has_fk:
                batch_op.create_foreign_key(
                    fk_name,
                    "work_shifts",
                    [column_name],
                    ["id"],
                    ondelete="SET NULL",
                )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "work_shifts" not in existing_tables:
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
        inspector = sa.inspect(bind)

    _ensure_index(inspector, op.f("ix_work_shifts_id"), "work_shifts", ["id"])
    _ensure_index(inspector, op.f("ix_work_shifts_organization_id"), "work_shifts", ["organization_id"])

    _add_work_shift_fk_column(
        inspector,
        table_name="groups",
        column_name="default_work_shift_id",
        index_name=op.f("ix_groups_default_work_shift_id"),
        fk_name="fk_groups_default_work_shift_id",
    )
    _add_work_shift_fk_column(
        inspector,
        table_name="persons",
        column_name="work_shift_id",
        index_name=op.f("ix_persons_work_shift_id"),
        fk_name="fk_persons_work_shift_id",
    )
    _add_work_shift_fk_column(
        inspector,
        table_name="attendance_sessions",
        column_name="work_shift_id",
        index_name=op.f("ix_attendance_sessions_work_shift_id"),
        fk_name="fk_attendance_sessions_work_shift_id",
    )

    inspector = sa.inspect(bind)
    ev_cols = _column_names(inspector, "attendance_events")
    ev_idxs = _index_names(inspector, "attendance_events")
    ev_has_fk = _has_fk(
        inspector, "attendance_events", "fk_attendance_events_work_shift_id", "work_shift_id"
    )
    ev_idx_name = op.f("ix_attendance_events_work_shift_id")
    if (
        "work_shift_id" not in ev_cols
        or "worked_minutes" not in ev_cols
        or "late_minutes" not in ev_cols
        or "early_exit_minutes" not in ev_cols
        or ev_idx_name not in ev_idxs
        or not ev_has_fk
    ):
        with op.batch_alter_table("attendance_events") as batch_op:
            if "work_shift_id" not in ev_cols:
                batch_op.add_column(sa.Column("work_shift_id", sa.Integer(), nullable=True))
            if "worked_minutes" not in ev_cols:
                batch_op.add_column(sa.Column("worked_minutes", sa.Integer(), nullable=True))
            if "late_minutes" not in ev_cols:
                batch_op.add_column(sa.Column("late_minutes", sa.Integer(), nullable=True))
            if "early_exit_minutes" not in ev_cols:
                batch_op.add_column(sa.Column("early_exit_minutes", sa.Integer(), nullable=True))
            if ev_idx_name not in ev_idxs:
                batch_op.create_index(ev_idx_name, ["work_shift_id"], unique=False)
            if not ev_has_fk:
                batch_op.create_foreign_key(
                    "fk_attendance_events_work_shift_id",
                    "work_shifts",
                    ["work_shift_id"],
                    ["id"],
                    ondelete="SET NULL",
                )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    ev_cols = _column_names(inspector, "attendance_events")
    ev_idxs = _index_names(inspector, "attendance_events")
    if (
        "work_shift_id" in ev_cols
        or "worked_minutes" in ev_cols
        or "late_minutes" in ev_cols
        or "early_exit_minutes" in ev_cols
    ):
        with op.batch_alter_table("attendance_events") as batch_op:
            if _has_fk(inspector, "attendance_events", "fk_attendance_events_work_shift_id", "work_shift_id"):
                batch_op.drop_constraint("fk_attendance_events_work_shift_id", type_="foreignkey")
            if op.f("ix_attendance_events_work_shift_id") in ev_idxs:
                batch_op.drop_index(op.f("ix_attendance_events_work_shift_id"))
            for col in ("early_exit_minutes", "late_minutes", "worked_minutes", "work_shift_id"):
                if col in ev_cols:
                    batch_op.drop_column(col)

    for table_name, col_name, idx_name, fk_name in (
        ("attendance_sessions", "work_shift_id", op.f("ix_attendance_sessions_work_shift_id"), "fk_attendance_sessions_work_shift_id"),
        ("persons", "work_shift_id", op.f("ix_persons_work_shift_id"), "fk_persons_work_shift_id"),
        ("groups", "default_work_shift_id", op.f("ix_groups_default_work_shift_id"), "fk_groups_default_work_shift_id"),
    ):
        cols = _column_names(inspector, table_name)
        idxs = _index_names(inspector, table_name)
        if col_name in cols or idx_name in idxs:
            with op.batch_alter_table(table_name) as batch_op:
                if _has_fk(inspector, table_name, fk_name, col_name):
                    batch_op.drop_constraint(fk_name, type_="foreignkey")
                if idx_name in idxs:
                    batch_op.drop_index(idx_name)
                if col_name in cols:
                    batch_op.drop_column(col_name)

    inspector = sa.inspect(bind)
    if "work_shifts" in inspector.get_table_names():
        ws_idxs = _index_names(inspector, "work_shifts")
        if op.f("ix_work_shifts_organization_id") in ws_idxs:
            op.drop_index(op.f("ix_work_shifts_organization_id"), table_name="work_shifts")
        if op.f("ix_work_shifts_id") in ws_idxs:
            op.drop_index(op.f("ix_work_shifts_id"), table_name="work_shifts")
        op.drop_table("work_shifts")
