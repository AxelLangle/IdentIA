"""Esquema inicial con soporte multi-tenant RBAC, credenciales delegadas, auditoría y biometría.

Revision ID: 0001_initial_rbac_and_biometrics
Revises:
Create Date: 2026-11-19 14:20:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_initial_rbac_and_biometrics"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("late_tolerance_minutes", sa.Integer(), nullable=False),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False),
        sa.Column("store_avatar_by_default", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_organizations_id"), "organizations", ["id"], unique=False)

    op.create_table(
        "groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("schedule_start", sa.String(length=5), nullable=False),
        sa.Column("schedule_end", sa.String(length=5), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_groups_id"), "groups", ["id"], unique=False)
    op.create_index(op.f("ix_groups_organization_id"), "groups", ["organization_id"], unique=False)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=160), nullable=False),
        sa.Column("full_name", sa.String(length=160), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_id"), "users", ["id"], unique=False)
    op.create_index(op.f("ix_users_organization_id"), "users", ["organization_id"], unique=False)

    op.create_table(
        "persons",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(length=60), nullable=False),
        sa.Column("full_name", sa.String(length=160), nullable=False),
        sa.Column("email", sa.String(length=160), nullable=True),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.Column("avatar_base64", sa.Text(), nullable=True),
        sa.Column("biometric_consent", sa.Boolean(), nullable=False),
        sa.Column("biometric_consent_at", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "external_id", name="uq_org_external_id"),
    )
    op.create_index(op.f("ix_persons_external_id"), "persons", ["external_id"], unique=False)
    op.create_index(op.f("ix_persons_id"), "persons", ["id"], unique=False)
    op.create_index(op.f("ix_persons_organization_id"), "persons", ["organization_id"], unique=False)

    op.create_table(
        "person_groups",
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("person_id", "group_id"),
    )

    op.create_table(
        "face_embeddings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("pose_label", sa.String(length=30), nullable=False),
        sa.Column("vector_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("model_name", sa.String(length=40), nullable=False),
        sa.Column("model_version", sa.String(length=60), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("mouth_ratio", sa.Float(), nullable=True),
        sa.Column("pitch_ratio", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("person_id", "pose_label", name="uq_person_pose"),
    )
    op.create_index(op.f("ix_face_embeddings_id"), "face_embeddings", ["id"], unique=False)
    op.create_index(op.f("ix_face_embeddings_person_id"), "face_embeddings", ["person_id"], unique=False)

    op.create_table(
        "attendance_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("session_type", sa.String(length=20), nullable=False),
        sa.Column("expected_start_time", sa.String(length=5), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_attendance_sessions_group_id"), "attendance_sessions", ["group_id"], unique=False)
    op.create_index(op.f("ix_attendance_sessions_id"), "attendance_sessions", ["id"], unique=False)
    op.create_index(op.f("ix_attendance_sessions_organization_id"), "attendance_sessions", ["organization_id"], unique=False)

    op.create_table(
        "attendance_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("capture_mode", sa.String(length=30), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("notes", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["attendance_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_attendance_events_id"), "attendance_events", ["id"], unique=False)
    op.create_index(op.f("ix_attendance_events_person_id"), "attendance_events", ["person_id"], unique=False)
    op.create_index(op.f("ix_attendance_events_session_id"), "attendance_events", ["session_id"], unique=False)
    op.create_index(op.f("ix_attendance_events_timestamp"), "attendance_events", ["timestamp"], unique=False)

    op.create_table(
        "delegated_credentials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("secret_prefix", sa.String(length=20), nullable=False),
        sa.Column("secret_hash", sa.String(length=255), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("assigned_to_user_id", sa.Integer(), nullable=True),
        sa.Column("assigned_to_name", sa.String(length=160), nullable=False),
        sa.Column("allowed_operations", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["assigned_to_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_delegated_credentials_id"), "delegated_credentials", ["id"], unique=False)
    op.create_index(op.f("ix_delegated_credentials_organization_id"), "delegated_credentials", ["organization_id"], unique=False)

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("target_summary", sa.String(length=255), nullable=True),
        sa.Column("executed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("authorized_by_user_id", sa.Integer(), nullable=True),
        sa.Column("delegated_credential_id", sa.Integer(), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["authorized_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["delegated_credential_id"], ["delegated_credentials.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["executed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_logs_created_at"), "audit_logs", ["created_at"], unique=False)
    op.create_index(op.f("ix_audit_logs_id"), "audit_logs", ["id"], unique=False)
    op.create_index(op.f("ix_audit_logs_organization_id"), "audit_logs", ["organization_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_logs_organization_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_created_at"), table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index(op.f("ix_delegated_credentials_organization_id"), table_name="delegated_credentials")
    op.drop_index(op.f("ix_delegated_credentials_id"), table_name="delegated_credentials")
    op.drop_table("delegated_credentials")

    op.drop_index(op.f("ix_attendance_events_timestamp"), table_name="attendance_events")
    op.drop_index(op.f("ix_attendance_events_session_id"), table_name="attendance_events")
    op.drop_index(op.f("ix_attendance_events_person_id"), table_name="attendance_events")
    op.drop_index(op.f("ix_attendance_events_id"), table_name="attendance_events")
    op.drop_table("attendance_events")

    op.drop_index(op.f("ix_attendance_sessions_organization_id"), table_name="attendance_sessions")
    op.drop_index(op.f("ix_attendance_sessions_id"), table_name="attendance_sessions")
    op.drop_index(op.f("ix_attendance_sessions_group_id"), table_name="attendance_sessions")
    op.drop_table("attendance_sessions")

    op.drop_index(op.f("ix_face_embeddings_person_id"), table_name="face_embeddings")
    op.drop_index(op.f("ix_face_embeddings_id"), table_name="face_embeddings")
    op.drop_table("face_embeddings")

    op.drop_table("person_groups")

    op.drop_index(op.f("ix_persons_organization_id"), table_name="persons")
    op.drop_index(op.f("ix_persons_id"), table_name="persons")
    op.drop_index(op.f("ix_persons_external_id"), table_name="persons")
    op.drop_table("persons")

    op.drop_index(op.f("ix_users_organization_id"), table_name="users")
    op.drop_index(op.f("ix_users_id"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")

    op.drop_index(op.f("ix_groups_organization_id"), table_name="groups")
    op.drop_index(op.f("ix_groups_id"), table_name="groups")
    op.drop_table("groups")

    op.drop_index(op.f("ix_organizations_id"), table_name="organizations")
    op.drop_table("organizations")
