from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


OrgMode = Literal["enterprise", "education"]
AcademicPeriodType = Literal["bimestral", "trimestral", "cuatrimestral", "semestral", "ciclo"]
PersonRole = Literal["employee", "student", "teacher", "admin"]
UserRole = Literal["superadmin", "org_admin", "teacher", "operator"]
PoseLabel = Literal["frontal", "left", "right", "up", "down", "smile"]
SessionType = Literal["workday", "class"]
SessionStatus = Literal["open", "closed"]
ActionMode = Literal["auto", "check_in", "check_out", "present"]
EventType = Literal["check_in", "check_out", "present"]
EventStatus = Literal["on_time", "late", "manual"]
CaptureMode = Literal["kiosk_individual", "group_scan", "manual"]


# --- Organizaciones ---
class OrgAdminBootstrap(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=160)
    email: str = Field(..., min_length=4, max_length=160)
    password: str = Field(..., min_length=6, max_length=120)


class OrganizationCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    mode: OrgMode = "enterprise"
    academic_period_type: AcademicPeriodType = "semestral"
    late_tolerance_minutes: int = Field(default=15, ge=0, le=180)
    cooldown_seconds: int = Field(default=60, ge=5, le=3600)
    store_avatar_by_default: bool = True
    admin_user: OrgAdminBootstrap | None = None


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    mode: OrgMode | None = None
    academic_period_type: AcademicPeriodType | None = None
    late_tolerance_minutes: int | None = Field(default=None, ge=0, le=180)
    cooldown_seconds: int | None = Field(default=None, ge=5, le=3600)
    store_avatar_by_default: bool | None = None


class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    mode: str
    academic_period_type: str = "semestral"
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
    career_id: int | None = None
    semester: str | None = Field(default=None, max_length=40)
    default_classroom: str | None = Field(default=None, max_length=80)


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    code: str | None = Field(default=None, min_length=1, max_length=40)
    schedule_start: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    schedule_end: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    career_id: int | None = None
    semester: str | None = Field(default=None, max_length=40)
    default_classroom: str | None = Field(default=None, max_length=80)


class GroupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    career_id: int | None = None
    career_name: str | None = None
    name: str
    code: str
    semester: str | None = None
    default_classroom: str | None = None
    period_type: str = "semestral"
    schedule_start: str
    schedule_end: str
    created_at: datetime
    members_count: int = 0
    courses_count: int = 0


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


class BiometricsRevokeRequest(BaseModel):
    authorization_secret: str = Field(..., min_length=1, max_length=120)
    reason: str | None = Field(default=None, max_length=255)


class BiometricsRevokeResponse(BaseModel):
    person_id: int
    deleted_embeddings: int
    avatar_cleared: bool
    authorized_by_name: str | None = None
    authorization_method: str | None = None
    delegated_credential_label: str | None = None


class BatchBiometricsRevokeRequest(BaseModel):
    person_ids: list[int] = Field(..., min_length=1)
    authorization_secret: str = Field(..., min_length=1, max_length=120)
    reason: str | None = Field(default=None, max_length=255)


class BatchBiometricsRevokeResponse(BaseModel):
    revoked_persons_count: int
    deleted_embeddings: int
    authorized_by_name: str | None = None
    authorization_method: str
    delegated_credential_label: str | None = None


# --- Sesiones y Eventos de Asistencia ---
class SessionCreate(BaseModel):
    organization_id: int
    group_id: int | None = None
    course_assignment_id: int | None = None
    schedule_id: int | None = None
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
    course_assignment_id: int | None = None
    schedule_id: int | None = None
    subject_name: str | None = None
    subject_code: str | None = None
    career_name: str | None = None
    teacher_name: str | None = None
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


# --- Autenticación, Usuarios, Credenciales Delegadas y Auditoría ---
class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=160)
    password: str = Field(..., min_length=1, max_length=120)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role: str
    organization_id: int | None
    organization_name: str | None = None
    organization_mode: str | None = None
    is_active: bool
    created_by_user_id: int | None
    created_at: datetime


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


class UserCreate(BaseModel):
    email: str = Field(..., min_length=4, max_length=160)
    full_name: str = Field(..., min_length=2, max_length=160)
    password: str = Field(..., min_length=6, max_length=120)
    role: UserRole = "operator"
    organization_id: int | None = None


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    password: str | None = Field(default=None, min_length=6, max_length=120)
    role: UserRole | None = None
    is_active: bool | None = None


class DelegatedCredentialCreate(BaseModel):
    organization_id: int | None = None
    label: str = Field(..., min_length=2, max_length=120)
    assigned_to_user_id: int | None = None
    assigned_to_name: str | None = Field(default=None, max_length=160)
    custom_secret: str | None = Field(default=None, min_length=6, max_length=120)
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)
    allowed_operations: list[str] = Field(default_factory=lambda: ["revoke_biometrics"])


class DelegatedCredentialRead(BaseModel):
    id: int
    organization_id: int
    label: str
    secret_prefix: str
    created_by_user_id: int | None
    created_by_name: str | None = None
    assigned_to_user_id: int | None
    assigned_to_name: str
    allowed_operations: list[str]
    status: str
    expires_at: datetime | None
    created_at: datetime
    revoked_at: datetime | None


class DelegatedCredentialCreateResponse(BaseModel):
    credential: DelegatedCredentialRead
    plain_secret: str


class AuditLogRead(BaseModel):
    id: int
    organization_id: int | None
    action: str
    target_type: str
    target_id: int | None
    target_summary: str | None
    executed_by_user_id: int | None
    executed_by_name: str | None = None
    authorized_by_user_id: int | None
    authorized_by_name: str | None = None
    delegated_credential_id: int | None
    delegated_credential_prefix: str | None = None
    delegated_assigned_to_name: str | None = None
    details: str | None
    created_at: datetime


# --- Modelo Educativo Completo (Bloque C) ---
class CareerCreate(BaseModel):
    organization_id: int
    name: str = Field(..., min_length=2, max_length=140)
    code: str = Field(..., min_length=1, max_length=40)
    description: str | None = Field(default=None, max_length=255)
    period_type: AcademicPeriodType | None = None


class CareerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=140)
    code: str | None = Field(default=None, min_length=1, max_length=40)
    description: str | None = Field(default=None, max_length=255)
    period_type: AcademicPeriodType | None = None


class CareerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    name: str
    code: str
    description: str | None
    period_type: str | None = None
    effective_period_type: str = "semestral"
    created_at: datetime
    groups_count: int = 0
    subjects_count: int = 0


class SubjectCreate(BaseModel):
    organization_id: int
    career_id: int | None = None
    name: str = Field(..., min_length=2, max_length=140)
    code: str = Field(..., min_length=1, max_length=40)


class SubjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    career_id: int | None = None
    career_name: str | None = None
    name: str
    code: str
    created_at: datetime


class ClassScheduleCreate(BaseModel):
    day_of_week: int = Field(..., ge=0, le=6)
    start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    classroom: str | None = Field(default=None, max_length=80)


class ClassScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    course_assignment_id: int
    day_of_week: int
    start_time: str
    end_time: str
    classroom: str | None = None
    created_at: datetime


class CourseAssignmentCreate(BaseModel):
    organization_id: int
    group_id: int
    subject_id: int
    teacher_user_id: int | None = None
    term: str | None = Field(default=None, max_length=60)
    schedules: list[ClassScheduleCreate] = Field(default_factory=list)


class CourseAssignmentUpdate(BaseModel):
    teacher_user_id: int | None = None
    term: str | None = Field(default=None, max_length=60)
    is_active: bool | None = None


class CourseAssignmentRead(BaseModel):
    id: int
    organization_id: int
    group_id: int
    group_name: str
    group_code: str
    group_default_classroom: str | None = None
    semester: str | None = None
    period_type: str = "semestral"
    career_id: int | None = None
    career_name: str | None = None
    subject_id: int
    subject_name: str
    subject_code: str
    teacher_user_id: int | None = None
    teacher_name: str | None = None
    teacher_email: str | None = None
    term: str | None = None
    is_active: bool
    students_count: int = 0
    schedules: list[ClassScheduleRead] = Field(default_factory=list)
    created_at: datetime


class GenerateSessionsRequest(BaseModel):
    organization_id: int | None = None
    target_date: date | None = None
    course_assignment_id: int | None = None


class GenerateSessionsResponse(BaseModel):
    target_date: date
    created_count: int
    existing_count: int
    sessions: list[SessionRead] = Field(default_factory=list)


class StartCourseSessionRequest(BaseModel):
    schedule_id: int | None = None
    session_date: date | None = None


class TeacherAgendaSlot(BaseModel):
    schedule_id: int
    course_assignment_id: int
    subject_name: str
    subject_code: str
    group_id: int
    group_name: str
    group_code: str
    career_name: str | None = None
    day_of_week: int
    start_time: str
    end_time: str
    classroom: str | None = None
    slot_status: Literal["in_progress", "upcoming", "finished"]
    students_count: int = 0
    session: SessionRead | None = None


class TeacherAgendaResponse(BaseModel):
    target_date: date
    current_time: str
    current_slot: TeacherAgendaSlot | None = None
    today_slots: list[TeacherAgendaSlot] = Field(default_factory=list)
    courses: list[CourseAssignmentRead] = Field(default_factory=list)


class SubjectAttendanceStat(BaseModel):
    course_assignment_id: int
    subject_id: int
    subject_name: str
    subject_code: str
    group_id: int
    group_name: str
    group_code: str
    career_id: int | None = None
    career_name: str | None = None
    semester: str | None = None
    period_type: str = "semestral"
    teacher_name: str | None = None
    sessions_count: int
    enrolled_students: int
    expected_records: int
    present_count: int
    on_time_count: int
    late_count: int
    manual_count: int
    absent_count: int
    attendance_rate: float


class StudentGroupAttendanceStat(BaseModel):
    person_id: int
    external_id: str
    full_name: str
    expected_records: int
    present_count: int
    on_time_count: int
    late_count: int
    absent_count: int
    attendance_rate: float


class GroupAttendanceStat(BaseModel):
    group_id: int
    group_name: str
    group_code: str
    career_id: int | None = None
    career_name: str | None = None
    semester: str | None = None
    period_type: str = "semestral"
    subjects_count: int
    students_count: int
    total_sessions: int
    total_expected: int
    total_present: int
    total_on_time: int
    total_late: int
    total_absent: int
    overall_attendance_rate: float
    students_breakdown: list[StudentGroupAttendanceStat] = Field(default_factory=list)


class AcademicStatsSummary(BaseModel):
    total_careers: int
    total_groups: int
    total_subjects: int
    total_courses: int
    total_sessions: int
    overall_attendance_rate: float


class AcademicStatsResponse(BaseModel):
    organization_id: int
    date_from: date | None = None
    date_to: date | None = None
    summary: AcademicStatsSummary
    by_subject: list[SubjectAttendanceStat] = Field(default_factory=list)
    by_group: list[GroupAttendanceStat] = Field(default_factory=list)
