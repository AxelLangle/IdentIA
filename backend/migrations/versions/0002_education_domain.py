"""Agrega dominio educativo completo: carreras, asignaturas, cursos, horarios y sesiones académicas.

Revision ID: 0002_education_domain
Revises: 0001_initial_rbac_and_biometrics
Create Date: 2026-11-19 20:45:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_education_domain"
down_revision: Union[str, Sequence[str], None] = "0001_initial_rbac_and_biometrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {
        idx["name"]
        for idx in inspector.get_indexes(table_name)
        if idx.get("name") is not None
    }


def _column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {col["name"] for col in inspector.get_columns(table_name)}


def _has_fk(inspector: sa.Inspector, table_name: str, fk_name: str, col_name: str) -> bool:
    for fk in inspector.get_foreign_keys(table_name):
        if fk.get("name") == fk_name or fk.get("constrained_columns") == [col_name]:
            return True
    return False


def _ensure_index(inspector: sa.Inspector, index_name: str, table_name: str, columns: list[str]) -> None:
    if index_name not in _index_names(inspector, table_name):
        op.create_index(index_name, table_name, columns, unique=False)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "careers" not in existing_tables:
        op.create_table(
            "careers",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("organization_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=140), nullable=False),
            sa.Column("code", sa.String(length=40), nullable=False),
            sa.Column("description", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("organization_id", "code", name="uq_career_org_code"),
        )
        inspector = sa.inspect(bind)
    _ensure_index(inspector, op.f("ix_careers_id"), "careers", ["id"])
    _ensure_index(inspector, op.f("ix_careers_organization_id"), "careers", ["organization_id"])

    if "subjects" not in existing_tables:
        op.create_table(
            "subjects",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("organization_id", sa.Integer(), nullable=False),
            sa.Column("career_id", sa.Integer(), nullable=True),
            sa.Column("name", sa.String(length=140), nullable=False),
            sa.Column("code", sa.String(length=40), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["career_id"], ["careers.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("organization_id", "code", name="uq_subject_org_code"),
        )
        inspector = sa.inspect(bind)
    _ensure_index(inspector, op.f("ix_subjects_career_id"), "subjects", ["career_id"])
    _ensure_index(inspector, op.f("ix_subjects_id"), "subjects", ["id"])
    _ensure_index(inspector, op.f("ix_subjects_organization_id"), "subjects", ["organization_id"])

    group_cols = _column_names(inspector, "groups")
    group_idxs = _index_names(inspector, "groups")
    group_has_fk = _has_fk(inspector, "groups", "fk_groups_career_id", "career_id")
    if (
        "career_id" not in group_cols
        or "semester" not in group_cols
        or op.f("ix_groups_career_id") not in group_idxs
        or not group_has_fk
    ):
        with op.batch_alter_table("groups") as batch_op:
            if "career_id" not in group_cols:
                batch_op.add_column(sa.Column("career_id", sa.Integer(), nullable=True))
            if "semester" not in group_cols:
                batch_op.add_column(sa.Column("semester", sa.String(length=40), nullable=True))
            if op.f("ix_groups_career_id") not in group_idxs:
                batch_op.create_index(op.f("ix_groups_career_id"), ["career_id"], unique=False)
            if not group_has_fk:
                batch_op.create_foreign_key(
                    "fk_groups_career_id",
                    "careers",
                    ["career_id"],
                    ["id"],
                    ondelete="SET NULL",
                )

    inspector = sa.inspect(bind)
    if "course_assignments" not in existing_tables:
        op.create_table(
            "course_assignments",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("organization_id", sa.Integer(), nullable=False),
            sa.Column("group_id", sa.Integer(), nullable=False),
            sa.Column("subject_id", sa.Integer(), nullable=False),
            sa.Column("teacher_user_id", sa.Integer(), nullable=True),
            sa.Column("term", sa.String(length=60), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["teacher_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("group_id", "subject_id", name="uq_course_group_subject"),
        )
        inspector = sa.inspect(bind)
    _ensure_index(inspector, op.f("ix_course_assignments_group_id"), "course_assignments", ["group_id"])
    _ensure_index(inspector, op.f("ix_course_assignments_id"), "course_assignments", ["id"])
    _ensure_index(inspector, op.f("ix_course_assignments_organization_id"), "course_assignments", ["organization_id"])
    _ensure_index(inspector, op.f("ix_course_assignments_subject_id"), "course_assignments", ["subject_id"])
    _ensure_index(inspector, op.f("ix_course_assignments_teacher_user_id"), "course_assignments", ["teacher_user_id"])

    if "class_schedules" not in existing_tables:
        op.create_table(
            "class_schedules",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("course_assignment_id", sa.Integer(), nullable=False),
            sa.Column("day_of_week", sa.Integer(), nullable=False),
            sa.Column("start_time", sa.String(length=5), nullable=False),
            sa.Column("end_time", sa.String(length=5), nullable=False),
            sa.Column("classroom", sa.String(length=80), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["course_assignment_id"], ["course_assignments.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        inspector = sa.inspect(bind)
    _ensure_index(inspector, op.f("ix_class_schedules_course_assignment_id"), "class_schedules", ["course_assignment_id"])
    _ensure_index(inspector, op.f("ix_class_schedules_id"), "class_schedules", ["id"])

    sess_cols = _column_names(inspector, "attendance_sessions")
    sess_idxs = _index_names(inspector, "attendance_sessions")
    sess_has_course_fk = _has_fk(
        inspector, "attendance_sessions", "fk_sessions_course_assignment_id", "course_assignment_id"
    )
    sess_has_sched_fk = _has_fk(
        inspector, "attendance_sessions", "fk_sessions_schedule_id", "schedule_id"
    )
    if (
        "course_assignment_id" not in sess_cols
        or "schedule_id" not in sess_cols
        or op.f("ix_attendance_sessions_course_assignment_id") not in sess_idxs
        or op.f("ix_attendance_sessions_schedule_id") not in sess_idxs
        or not sess_has_course_fk
        or not sess_has_sched_fk
    ):
        with op.batch_alter_table("attendance_sessions") as batch_op:
            if "course_assignment_id" not in sess_cols:
                batch_op.add_column(sa.Column("course_assignment_id", sa.Integer(), nullable=True))
            if "schedule_id" not in sess_cols:
                batch_op.add_column(sa.Column("schedule_id", sa.Integer(), nullable=True))
            if op.f("ix_attendance_sessions_course_assignment_id") not in sess_idxs:
                batch_op.create_index(
                    op.f("ix_attendance_sessions_course_assignment_id"),
                    ["course_assignment_id"],
                    unique=False,
                )
            if op.f("ix_attendance_sessions_schedule_id") not in sess_idxs:
                batch_op.create_index(
                    op.f("ix_attendance_sessions_schedule_id"),
                    ["schedule_id"],
                    unique=False,
                )
            if not sess_has_course_fk:
                batch_op.create_foreign_key(
                    "fk_sessions_course_assignment_id",
                    "course_assignments",
                    ["course_assignment_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
            if not sess_has_sched_fk:
                batch_op.create_foreign_key(
                    "fk_sessions_schedule_id",
                    "class_schedules",
                    ["schedule_id"],
                    ["id"],
                    ondelete="SET NULL",
                )


def downgrade() -> None:
    with op.batch_alter_table("attendance_sessions") as batch_op:
        batch_op.drop_constraint("fk_sessions_schedule_id", type_="foreignkey")
        batch_op.drop_constraint("fk_sessions_course_assignment_id", type_="foreignkey")
        batch_op.drop_index(op.f("ix_attendance_sessions_schedule_id"))
        batch_op.drop_index(op.f("ix_attendance_sessions_course_assignment_id"))
        batch_op.drop_column("schedule_id")
        batch_op.drop_column("course_assignment_id")

    op.drop_index(op.f("ix_class_schedules_id"), table_name="class_schedules")
    op.drop_index(op.f("ix_class_schedules_course_assignment_id"), table_name="class_schedules")
    op.drop_table("class_schedules")

    op.drop_index(op.f("ix_course_assignments_teacher_user_id"), table_name="course_assignments")
    op.drop_index(op.f("ix_course_assignments_subject_id"), table_name="course_assignments")
    op.drop_index(op.f("ix_course_assignments_organization_id"), table_name="course_assignments")
    op.drop_index(op.f("ix_course_assignments_id"), table_name="course_assignments")
    op.drop_index(op.f("ix_course_assignments_group_id"), table_name="course_assignments")
    op.drop_table("course_assignments")

    with op.batch_alter_table("groups") as batch_op:
        batch_op.drop_constraint("fk_groups_career_id", type_="foreignkey")
        batch_op.drop_index(op.f("ix_groups_career_id"))
        batch_op.drop_column("semester")
        batch_op.drop_column("career_id")

    op.drop_index(op.f("ix_subjects_organization_id"), table_name="subjects")
    op.drop_index(op.f("ix_subjects_id"), table_name="subjects")
    op.drop_index(op.f("ix_subjects_career_id"), table_name="subjects")
    op.drop_table("subjects")

    op.drop_index(op.f("ix_careers_organization_id"), table_name="careers")
    op.drop_index(op.f("ix_careers_id"), table_name="careers")
    op.drop_table("careers")
