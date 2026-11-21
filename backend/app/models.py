from datetime import date, datetime, timezone
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utc_now_naive() -> datetime:
    """Devuelve la fecha/hora UTC actual sin tzinfo para compatibilidad limpia con SQLite."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="enterprise")
    academic_period_type: Mapped[str] = mapped_column(String(20), nullable=False, default="semestral")
    late_tolerance_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    store_avatar_by_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)

    groups: Mapped[list["Group"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    careers: Mapped[list["Career"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    subjects: Mapped[list["Subject"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    course_assignments: Mapped[list["CourseAssignment"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    work_shifts: Mapped[list["WorkShift"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    users: Mapped[list["User"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    persons: Mapped[list["Person"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    sessions: Mapped[list["AttendanceSession"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    delegated_credentials: Mapped[list["DelegatedCredential"]] = relationship(
        cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(
        cascade="all, delete-orphan"
    )


class Career(Base):
    __tablename__ = "careers"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_career_org_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    period_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)

    organization: Mapped["Organization"] = relationship(back_populates="careers")
    groups: Mapped[list["Group"]] = relationship(back_populates="career")
    subjects: Mapped[list["Subject"]] = relationship(back_populates="career")


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    career_id: Mapped[int | None] = mapped_column(
        ForeignKey("careers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    default_work_shift_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_shifts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    semester: Mapped[str | None] = mapped_column(String(40), nullable=True)
    default_classroom: Mapped[str | None] = mapped_column(String(80), nullable=True)
    schedule_start: Mapped[str] = mapped_column(String(5), nullable=False, default="08:00")
    schedule_end: Mapped[str] = mapped_column(String(5), nullable=False, default="17:00")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)

    organization: Mapped["Organization"] = relationship(back_populates="groups")
    career: Mapped["Career | None"] = relationship(back_populates="groups")
    default_work_shift: Mapped["WorkShift | None"] = relationship(
        foreign_keys=[default_work_shift_id]
    )
    person_links: Mapped[list["PersonGroup"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )
    course_assignments: Mapped[list["CourseAssignment"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )
    sessions: Mapped[list["AttendanceSession"]] = relationship(back_populates="group")


class Subject(Base):
    __tablename__ = "subjects"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_subject_org_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    career_id: Mapped[int | None] = mapped_column(
        ForeignKey("careers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)

    organization: Mapped["Organization"] = relationship(back_populates="subjects")
    career: Mapped["Career | None"] = relationship(back_populates="subjects")
    course_assignments: Mapped[list["CourseAssignment"]] = relationship(
        back_populates="subject", cascade="all, delete-orphan"
    )


class CourseAssignment(Base):
    __tablename__ = "course_assignments"
    __table_args__ = (
        UniqueConstraint("group_id", "subject_id", name="uq_course_group_subject"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    teacher_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    term: Mapped[str | None] = mapped_column(String(60), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)

    organization: Mapped["Organization"] = relationship(back_populates="course_assignments")
    group: Mapped["Group"] = relationship(back_populates="course_assignments")
    subject: Mapped["Subject"] = relationship(back_populates="course_assignments")
    teacher: Mapped["User | None"] = relationship(foreign_keys=[teacher_user_id])
    schedules: Mapped[list["ClassSchedule"]] = relationship(
        back_populates="course_assignment", cascade="all, delete-orphan"
    )


class ClassSchedule(Base):
    __tablename__ = "class_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    course_assignment_id: Mapped[int] = mapped_column(
        ForeignKey("course_assignments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=Lunes .. 6=Domingo
    start_time: Mapped[str] = mapped_column(String(5), nullable=False)
    end_time: Mapped[str] = mapped_column(String(5), nullable=False)
    classroom: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)

    course_assignment: Mapped["CourseAssignment"] = relationship(back_populates="schedules")


class WorkShift(Base):
    __tablename__ = "work_shifts"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_work_shift_org_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    start_time: Mapped[str] = mapped_column(String(5), nullable=False)
    end_time: Mapped[str] = mapped_column(String(5), nullable=False)
    crosses_midnight: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    days_of_week: Mapped[str] = mapped_column(String(30), nullable=False, default="0,1,2,3,4")
    late_tolerance_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    early_exit_tolerance_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)

    organization: Mapped["Organization"] = relationship(back_populates="work_shifts")


class Person(Base):
    __tablename__ = "persons"
    __table_args__ = (
        UniqueConstraint("organization_id", "external_id", name="uq_org_external_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    work_shift_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_shifts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    external_id: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str | None] = mapped_column(String(160), nullable=True)
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="employee")
    avatar_base64: Mapped[str | None] = mapped_column(Text, nullable=True)
    biometric_consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    biometric_consent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)

    organization: Mapped["Organization"] = relationship(back_populates="persons")
    work_shift: Mapped["WorkShift | None"] = relationship(foreign_keys=[work_shift_id])
    group_links: Mapped[list["PersonGroup"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    embeddings: Mapped[list["FaceEmbedding"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    attendance_events: Mapped[list["AttendanceEvent"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )


class PersonGroup(Base):
    __tablename__ = "person_groups"

    person_id: Mapped[int] = mapped_column(
        ForeignKey("persons.id", ondelete="CASCADE"), primary_key=True
    )
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )

    person: Mapped["Person"] = relationship(back_populates="group_links")
    group: Mapped["Group"] = relationship(back_populates="person_links")


class FaceEmbedding(Base):
    __tablename__ = "face_embeddings"
    __table_args__ = (
        UniqueConstraint("person_id", "pose_label", name="uq_person_pose"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    person_id: Mapped[int] = mapped_column(
        ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pose_label: Mapped[str] = mapped_column(String(30), nullable=False)
    vector_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    model_name: Mapped[str] = mapped_column(String(40), nullable=False)
    model_version: Mapped[str] = mapped_column(String(60), nullable=False)
    quality_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    mouth_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    pitch_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)

    person: Mapped["Person"] = relationship(back_populates="embeddings")


class AttendanceSession(Base):
    __tablename__ = "attendance_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey("groups.id", ondelete="SET NULL"), nullable=True, index=True
    )
    course_assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("course_assignments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    schedule_id: Mapped[int | None] = mapped_column(
        ForeignKey("class_schedules.id", ondelete="SET NULL"), nullable=True, index=True
    )
    work_shift_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_shifts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    session_type: Mapped[str] = mapped_column(String(20), nullable=False, default="workday")
    expected_start_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="sessions")
    group: Mapped["Group | None"] = relationship(back_populates="sessions")
    course_assignment: Mapped["CourseAssignment | None"] = relationship()
    schedule: Mapped["ClassSchedule | None"] = relationship()
    work_shift: Mapped["WorkShift | None"] = relationship(foreign_keys=[work_shift_id])
    events: Mapped[list["AttendanceEvent"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class AttendanceEvent(Base):
    __tablename__ = "attendance_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("attendance_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    person_id: Mapped[int] = mapped_column(
        ForeignKey("persons.id", ondelete="CASCADE"), nullable=False, index=True
    )
    work_shift_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_shifts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="on_time")
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    worked_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    late_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    early_exit_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    capture_mode: Mapped[str] = mapped_column(String(30), nullable=False, default="kiosk_individual")
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive, index=True)
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)

    session: Mapped["AttendanceSession"] = relationship(back_populates="events")
    person: Mapped["Person"] = relationship(back_populates="attendance_events")
    work_shift: Mapped["WorkShift | None"] = relationship(foreign_keys=[work_shift_id])


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(160), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="operator")
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)

    organization: Mapped["Organization | None"] = relationship(back_populates="users")


class DelegatedCredential(Base):
    __tablename__ = "delegated_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    secret_prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    assigned_to_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    assigned_to_name: Mapped[str] = mapped_column(String(160), nullable=False)
    allowed_operations: Mapped[str] = mapped_column(
        String(255), nullable=False, default="revoke_biometrics"
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_summary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    executed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    authorized_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    delegated_credential_id: Mapped[int | None] = mapped_column(
        ForeignKey("delegated_credentials.id", ondelete="SET NULL"), nullable=True
    )
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now_naive, index=True
    )
