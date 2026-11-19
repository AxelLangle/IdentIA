from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


OrgMode = Literal["enterprise", "education"]
PersonRole = Literal["employee", "student", "teacher", "admin"]
PoseLabel = Literal["frontal", "left", "right", "up", "down", "smile"]
SessionType = Literal["workday", "class"]
SessionStatus = Literal["open", "closed"]
ActionMode = Literal["auto", "check_in", "check_out", "present"]
EventType = Literal["check_in", "check_out", "present"]
EventStatus = Literal["on_time", "late", "manual"]
CaptureMode = Literal["kiosk_individual", "group_scan", "manual"]


# --- Organizaciones ---
class OrganizationCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    mode: OrgMode = "enterprise"
    late_tolerance_minutes: int = Field(default=15, ge=0, le=180)
    cooldown_seconds: int = Field(default=60, ge=5, le=3600)
    store_avatar_by_default: bool = True


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    mode: OrgMode | None = None
    late_tolerance_minutes: int | None = Field(default=None, ge=0, le=180)
    cooldown_seconds: int | None = Field(default=None, ge=5, le=3600)
    store_avatar_by_default: bool | None = None


class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    mode: str
    late_tolerance_minutes: int
    cooldown_seconds: int
    store_avatar_by_default: bool
    created_at: datetime


# --- Grupos ---
class GroupCreate(BaseModel):
    organization_id: int
    name: str = Field(..., min_length=2, max_length=120)
    code: str = Field(..., min_length=1, max_length=40)
    schedule_start: str = Field(default="08:00", pattern=r"^\d{2}:\d{2}$")
    schedule_end: str = Field(default="17:00", pattern=r"^\d{2}:\d{2}$")


class GroupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    name: str
    code: str
    schedule_start: str
    schedule_end: str
    created_at: datetime
    members_count: int = 0


# --- Personas y Enrolamiento ---
class PersonCreate(BaseModel):
    organization_id: int
    external_id: str = Field(..., min_length=1, max_length=60)
    full_name: str = Field(..., min_length=2, max_length=160)
    email: str | None = Field(default=None, max_length=160)
    role: PersonRole = "employee"
    biometric_consent: bool = False
    group_ids: list[int] = Field(default_factory=list)


class PersonUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    email: str | None = Field(default=None, max_length=160)
    role: PersonRole | None = None
    biometric_consent: bool | None = None
    is_active: bool | None = None
    group_ids: list[int] | None = None


class PersonRead(BaseModel):
    id: int
    organization_id: int
    external_id: str
    full_name: str
    email: str | None
    role: str
    avatar_base64: str | None
    biometric_consent: bool
    biometric_consent_at: datetime | None
    is_active: bool
    created_at: datetime
    group_ids: list[int] = Field(default_factory=list)
    embeddings_count: int = 0
    poses_completed: list[str] = Field(default_factory=list)
    needs_reenroll: bool = False


class FaceBoxSchema(BaseModel):
    x: int
    y: int
    w: int
    h: int
    confidence: float
    image_width: int
    image_height: int
    nx: float
    ny: float
    nw: float
    nh: float


class QualityReportSchema(BaseModel):
    ok: bool
    reason: str | None = None
    blur_score: float
    brightness: float
    face_width: int
    face_height: int
    pose_hint: str
    shadow_asymmetry: float = 0.0
    backlight_detected: bool = False
    yaw_ratio: float = 0.0
    pitch_ratio: float = 0.55
    mouth_ratio: float = 0.72
    pose_matches: bool = True
    pose_feedback: str | None = None


class EnrollFrameResponse(BaseModel):
    accepted: bool
    pose_valid: bool = False
    pose_label: str
    message: str
    embeddings_count: int
    poses_completed: list[str]
    is_complete: bool = False
    required_poses_count: int = 6
    face_box: FaceBoxSchema | None = None
    quality: QualityReportSchema | None = None
    avatar_saved: bool = False


class BiometricsRevokeResponse(BaseModel):
    person_id: int
    deleted_embeddings: int
    avatar_cleared: bool


# --- Sesiones y Eventos de Asistencia ---
class SessionCreate(BaseModel):
    organization_id: int
    group_id: int | None = None
    title: str = Field(..., min_length=2, max_length=160)
    session_date: date | None = None
    session_type: SessionType | None = None
    expected_start_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    group_id: int | None
    group_name: str | None = None
    title: str
    session_date: date
    session_type: str
    expected_start_time: str | None
    status: str
    created_at: datetime
    closed_at: datetime | None
    events_count: int = 0


class AttendanceEventRead(BaseModel):
    id: int
    session_id: int
    session_title: str | None = None
    person_id: int
    person_name: str
    person_external_id: str
    person_avatar_base64: str | None = None
    event_type: str
    status: str
    confidence_score: float | None
    capture_mode: str
    timestamp: datetime
    notes: str | None = None


class ManualAttendanceRequest(BaseModel):
    session_id: int
    person_id: int
    event_type: EventType = "present"
    status: EventStatus = "manual"
    notes: str | None = Field(default=None, max_length=255)


class PersonSummaryBrief(BaseModel):
    id: int
    external_id: str
    full_name: str
    role: str
    avatar_base64: str | None = None


class RecognizeFrameResponse(BaseModel):
    faces_detected: int
    match_status: Literal["matched", "unknown", "ambiguous", "no_face", "low_quality"]
    face_box: FaceBoxSchema | None = None
    quality: QualityReportSchema | None = None
    person: PersonSummaryBrief | None = None
    confidence: float = 0.0
    second_best_score: float | None = None
    attendance_action: Literal["recorded", "cooldown", "already_present", "invalid_sequence"] | None = None
    event: AttendanceEventRead | None = None
    worked_minutes: int | None = None
    session_id: int | None = None
    message: str
    latency_ms: float


# --- Salud del Sistema ---
class HealthResponse(BaseModel):
    status: str
    models_loaded: bool
    model_name: str
    model_version: str
    organizations_count: int
    persons_count: int
    embeddings_count: int
