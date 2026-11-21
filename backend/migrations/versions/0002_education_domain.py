"""Agrega dominio educativo completo: carreras, asignaturas, cursos, horarios y sesiones académicas.

Revision ID: 0002_education_domain
Revises: 0001_initial_rbac_and_biometrics
Create Date: 2026-11-19 20:45:00

Incluye comprobaciones idempotentes para recuperarse limpiamente si las tablas
fueron creadas previamente mediante `BaseDeclarativa.metadata.create_all`.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Identificadores de revisión Alembic (invariantes)
revision: str = "0002_education_domain"
down_revision: Union[str, Sequence[str], None] = "0001_initial_rbac_and_biometrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _nombres_indices(inspector: sa.Inspector, nombre_tabla: str) -> set[str]:
    """Devuelve el conjunto de nombres de índices existentes en la tabla indicada."""
    return {
        indice["name"]
        for indice in inspector.get_indexes(nombre_tabla)
        if indice.get("name") is not None
    }


def _nombres_columnas(inspector: sa.Inspector, nombre_tabla: str) -> set[str]:
    """Devuelve el conjunto de columnas físicas existentes en la tabla indicada."""
    return {columna["name"] for columna in inspector.get_columns(nombre_tabla)}


def _tiene_llave_foranea(
    inspector: sa.Inspector,
    nombre_tabla: str,
    nombre_fk: str,
    nombre_columna: str,
) -> bool:
    """Verifica si ya existe la restricción de llave foránea por nombre o columna restringida."""
    for fk in inspector.get_foreign_keys(nombre_tabla):
        if fk.get("name") == nombre_fk or fk.get("constrained_columns") == [nombre_columna]:
            return True
    return False


def _asegurar_indice(
    inspector: sa.Inspector,
    nombre_indice: str,
    nombre_tabla: str,
    columnas: list[str],
) -> None:
    """Crea el índice si no está presente en el esquema inspeccionado."""
    if nombre_indice not in _nombres_indices(inspector, nombre_tabla):
        op.create_index(nombre_indice, nombre_tabla, columnas, unique=False)


def upgrade() -> None:
    """Agrega tablas y columnas del modelo educativo verificando estado previo."""
    conexion = op.get_bind()
    inspector = sa.inspect(conexion)
    tablas_existentes = set(inspector.get_table_names())

    # Catálogo de carreras académicas
    if "careers" not in tablas_existentes:
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
        inspector = sa.inspect(conexion)
    _asegurar_indice(inspector, op.f("ix_careers_id"), "careers", ["id"])
    _asegurar_indice(
        inspector, op.f("ix_careers_organization_id"), "careers", ["organization_id"]
    )

    # Catálogo de asignaturas o materias
    if "subjects" not in tablas_existentes:
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
        inspector = sa.inspect(conexion)
    _asegurar_indice(inspector, op.f("ix_subjects_career_id"), "subjects", ["career_id"])
    _asegurar_indice(inspector, op.f("ix_subjects_id"), "subjects", ["id"])
    _asegurar_indice(
        inspector, op.f("ix_subjects_organization_id"), "subjects", ["organization_id"]
    )

    # Vinculación opcional de grupos con su carrera y semestre
    columnas_grupo = _nombres_columnas(inspector, "groups")
    indices_grupo = _nombres_indices(inspector, "groups")
    grupo_tiene_fk = _tiene_llave_foranea(inspector, "groups", "fk_groups_career_id", "career_id")
    if (
        "career_id" not in columnas_grupo
        or "semester" not in columnas_grupo
        or op.f("ix_groups_career_id") not in indices_grupo
        or not grupo_tiene_fk
    ):
        with op.batch_alter_table("groups") as lote:
            if "career_id" not in columnas_grupo:
                lote.add_column(sa.Column("career_id", sa.Integer(), nullable=True))
            if "semester" not in columnas_grupo:
                lote.add_column(sa.Column("semester", sa.String(length=40), nullable=True))
            if op.f("ix_groups_career_id") not in indices_grupo:
                lote.create_index(op.f("ix_groups_career_id"), ["career_id"], unique=False)
            if not grupo_tiene_fk:
                lote.create_foreign_key(
                    "fk_groups_career_id",
                    "careers",
                    ["career_id"],
                    ["id"],
                    ondelete="SET NULL",
                )

    inspector = sa.inspect(conexion)
    # Asignaciones de curso (Grupo + Materia + Profesor)
    if "course_assignments" not in tablas_existentes:
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
        inspector = sa.inspect(conexion)
    _asegurar_indice(
        inspector, op.f("ix_course_assignments_group_id"), "course_assignments", ["group_id"]
    )
    _asegurar_indice(inspector, op.f("ix_course_assignments_id"), "course_assignments", ["id"])
    _asegurar_indice(
        inspector,
        op.f("ix_course_assignments_organization_id"),
        "course_assignments",
        ["organization_id"],
    )
    _asegurar_indice(
        inspector, op.f("ix_course_assignments_subject_id"), "course_assignments", ["subject_id"]
    )
    _asegurar_indice(
        inspector,
        op.f("ix_course_assignments_teacher_user_id"),
        "course_assignments",
        ["teacher_user_id"],
    )

    # Bloques semanales de horario para cada asignatura
    if "class_schedules" not in tablas_existentes:
        op.create_table(
            "class_schedules",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("course_assignment_id", sa.Integer(), nullable=False),
            sa.Column("day_of_week", sa.Integer(), nullable=False),
            sa.Column("start_time", sa.String(length=5), nullable=False),
            sa.Column("end_time", sa.String(length=5), nullable=False),
            sa.Column("classroom", sa.String(length=80), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["course_assignment_id"], ["course_assignments.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        inspector = sa.inspect(conexion)
    _asegurar_indice(
        inspector,
        op.f("ix_class_schedules_course_assignment_id"),
        "class_schedules",
        ["course_assignment_id"],
    )
    _asegurar_indice(inspector, op.f("ix_class_schedules_id"), "class_schedules", ["id"])

    # Vinculación de sesiones de asistencia con asignaturas y bloques de clase
    columnas_sesion = _nombres_columnas(inspector, "attendance_sessions")
    indices_sesion = _nombres_indices(inspector, "attendance_sessions")
    sesion_tiene_fk_curso = _tiene_llave_foranea(
        inspector,
        "attendance_sessions",
        "fk_sessions_course_assignment_id",
        "course_assignment_id",
    )
    sesion_tiene_fk_horario = _tiene_llave_foranea(
        inspector, "attendance_sessions", "fk_sessions_schedule_id", "schedule_id"
    )
    if (
        "course_assignment_id" not in columnas_sesion
        or "schedule_id" not in columnas_sesion
        or op.f("ix_attendance_sessions_course_assignment_id") not in indices_sesion
        or op.f("ix_attendance_sessions_schedule_id") not in indices_sesion
        or not sesion_tiene_fk_curso
        or not sesion_tiene_fk_horario
    ):
        with op.batch_alter_table("attendance_sessions") as lote:
            if "course_assignment_id" not in columnas_sesion:
                lote.add_column(sa.Column("course_assignment_id", sa.Integer(), nullable=True))
            if "schedule_id" not in columnas_sesion:
                lote.add_column(sa.Column("schedule_id", sa.Integer(), nullable=True))
            if op.f("ix_attendance_sessions_course_assignment_id") not in indices_sesion:
                lote.create_index(
                    op.f("ix_attendance_sessions_course_assignment_id"),
                    ["course_assignment_id"],
                    unique=False,
                )
            if op.f("ix_attendance_sessions_schedule_id") not in indices_sesion:
                lote.create_index(
                    op.f("ix_attendance_sessions_schedule_id"),
                    ["schedule_id"],
                    unique=False,
                )
            if not sesion_tiene_fk_curso:
                lote.create_foreign_key(
                    "fk_sessions_course_assignment_id",
                    "course_assignments",
                    ["course_assignment_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
            if not sesion_tiene_fk_horario:
                lote.create_foreign_key(
                    "fk_sessions_schedule_id",
                    "class_schedules",
                    ["schedule_id"],
                    ["id"],
                    ondelete="SET NULL",
                )


def downgrade() -> None:
    """Revierte las tablas y columnas académicas introducidas en esta migración."""
    with op.batch_alter_table("attendance_sessions") as lote:
        lote.drop_constraint("fk_sessions_schedule_id", type_="foreignkey")
        lote.drop_constraint("fk_sessions_course_assignment_id", type_="foreignkey")
        lote.drop_index(op.f("ix_attendance_sessions_schedule_id"))
        lote.drop_index(op.f("ix_attendance_sessions_course_assignment_id"))
        lote.drop_column("schedule_id")
        lote.drop_column("course_assignment_id")

    op.drop_index(op.f("ix_class_schedules_id"), table_name="class_schedules")
    op.drop_index(op.f("ix_class_schedules_course_assignment_id"), table_name="class_schedules")
    op.drop_table("class_schedules")

    op.drop_index(op.f("ix_course_assignments_teacher_user_id"), table_name="course_assignments")
    op.drop_index(op.f("ix_course_assignments_subject_id"), table_name="course_assignments")
    op.drop_index(op.f("ix_course_assignments_organization_id"), table_name="course_assignments")
    op.drop_index(op.f("ix_course_assignments_id"), table_name="course_assignments")
    op.drop_index(op.f("ix_course_assignments_group_id"), table_name="course_assignments")
    op.drop_table("course_assignments")

    with op.batch_alter_table("groups") as lote:
        lote.drop_constraint("fk_groups_career_id", type_="foreignkey")
        lote.drop_index(op.f("ix_groups_career_id"))
        lote.drop_column("semester")
        lote.drop_column("career_id")

    op.drop_index(op.f("ix_subjects_organization_id"), table_name="subjects")
    op.drop_index(op.f("ix_subjects_id"), table_name="subjects")
    op.drop_index(op.f("ix_subjects_career_id"), table_name="subjects")
    op.drop_table("subjects")

    op.drop_index(op.f("ix_careers_organization_id"), table_name="careers")
    op.drop_index(op.f("ix_careers_id"), table_name="careers")
    op.drop_table("careers")
