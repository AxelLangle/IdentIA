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


def upgrade() -> None:
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
    op.create_index(op.f("ix_careers_id"), "careers", ["id"], unique=False)
    op.create_index(op.f("ix_careers_organization_id"), "careers", ["organization_id"], unique=False)

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
    op.create_index(op.f("ix_subjects_career_id"), "subjects", ["career_id"], unique=False)
    op.create_index(op.f("ix_subjects_id"), "subjects", ["id"], unique=False)
    op.create_index(op.f("ix_subjects_organization_id"), "subjects", ["organization_id"], unique=False)

    with op.batch_alter_table("groups") as batch_op:
        batch_op.add_column(sa.Column("career_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("semester", sa.String(length=40), nullable=True))
        batch_op.create_index(op.f("ix_groups_career_id"), ["career_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_groups_career_id",
            "careers",
            ["career_id"],
            ["id"],
            ondelete="SET NULL",
        )

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
    op.create_index(op.f("ix_course_assignments_group_id"), "course_assignments", ["group_id"], unique=False)
    op.create_index(op.f("ix_course_assignments_id"), "course_assignments", ["id"], unique=False)
    op.create_index(op.f("ix_course_assignments_organization_id"), "course_assignments", ["organization_id"], unique=False)
    op.create_index(op.f("ix_course_assignments_subject_id"), "course_assignments", ["subject_id"], unique=False)
    op.create_index(op.f("ix_course_assignments_teacher_user_id"), "course_assignments", ["teacher_user_id"], unique=False)

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
    op.create_index(op.f("ix_class_schedules_course_assignment_id"), "class_schedules", ["course_assignment_id"], unique=False)
    op.create_index(op.f("ix_class_schedules_id"), "class_schedules", ["id"], unique=False)

    with op.batch_alter_table("attendance_sessions") as batch_op:
        batch_op.add_column(sa.Column("course_assignment_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("schedule_id", sa.Integer(), nullable=True))
        batch_op.create_index(
            op.f("ix_attendance_sessions_course_assignment_id"),
            ["course_assignment_id"],
            unique=False,
        )
        batch_op.create_index(
            op.f("ix_attendance_sessions_schedule_id"),
            ["schedule_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_sessions_course_assignment_id",
            "course_assignments",
            ["course_assignment_id"],
            ["id"],
            ondelete="SET NULL",
        )
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
