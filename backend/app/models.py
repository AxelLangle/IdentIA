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
    late_tolerance_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    store_avatar_by_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)

    groups: Mapped[list["Group"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    persons: Mapped[list["Person"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    sessions: Mapped[list["AttendanceSession"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    schedule_start: Mapped[str] = mapped_column(String(5), nullable=False, default="08:00")
    schedule_end: Mapped[str] = mapped_column(String(5), nullable=False, default="17:00")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)

    organization: Mapped["Organization"] = relationship(back_populates="groups")
    person_links: Mapped[list["PersonGroup"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )
    sessions: Mapped[list["AttendanceSession"]] = relationship(back_populates="group")


class Person(Base):
    __tablename__ = "persons"
    __table_args__ = (
        UniqueConstraint("organization_id", "external_id", name="uq_org_external_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
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
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    session_type: Mapped[str] = mapped_column(String(20), nullable=False, default="workday")
    expected_start_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="sessions")
    group: Mapped["Group | None"] = relationship(back_populates="sessions")
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
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="on_time")
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    capture_mode: Mapped[str] = mapped_column(String(30), nullable=False, default="kiosk_individual")
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utc_now_naive, index=True)
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)

    session: Mapped["AttendanceSession"] = relationship(back_populates="events")
    person: Mapped["Person"] = relationship(back_populates="attendance_events")
