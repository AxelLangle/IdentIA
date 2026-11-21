export type OrgMode = "enterprise" | "education";
export type AcademicPeriodType =
  | "bimestral"
  | "trimestral"
  | "cuatrimestral"
  | "semestral"
  | "ciclo";
export type PersonRole = "employee" | "student" | "teacher" | "admin";
export type UserRole = "superadmin" | "org_admin" | "teacher" | "operator";
export type PoseLabel = "frontal" | "left" | "right" | "up" | "down" | "smile";
export type ActionMode = "auto" | "check_in" | "check_out" | "present";
export type SessionStatus = "open" | "closed";
export type ShiftSource = "direct" | "group" | "none";

export interface Organization {
  id: number;
  name: string;
  mode: OrgMode;
  academic_period_type: AcademicPeriodType;
  late_tolerance_minutes: number;
  cooldown_seconds: number;
  store_avatar_by_default: boolean;
  created_at: string;
}

export interface Group {
  id: number;
  organization_id: number;
  career_id: number | null;
  career_name: string | null;
  name: string;
  code: string;
  semester: string | null;
  default_classroom: string | null;
  default_work_shift_id: number | null;
  default_work_shift_name: string | null;
  default_work_shift_code: string | null;
  period_type: string;
  custom_period_type: AcademicPeriodType | null;
  schedule_start: string;
  schedule_end: string;
  created_at: string;
  members_count: number;
  courses_count: number;
}

export interface Person {
  id: number;
  organization_id: number;
  external_id: string;
  full_name: string;
  email: string | null;
  role: PersonRole;
  avatar_base64: string | null;
  biometric_consent: boolean;
  biometric_consent_at: string | null;
  is_active: boolean;
  created_at: string;
  group_ids: number[];
  work_shift_id: number | null;
  work_shift_name: string | null;
  effective_work_shift_id: number | null;
  effective_work_shift_name: string | null;
  effective_work_shift_code: string | null;
  shift_source: ShiftSource;
  embeddings_count: number;
  poses_completed: PoseLabel[];
  needs_reenroll: boolean;
}

export interface FaceBox {
  x: number;
  y: number;
  w: number;
  h: number;
  confidence: number;
  image_width: number;
  image_height: number;
  nx: number;
  ny: number;
  nw: number;
  nh: number;
}

export interface QualityReport {
  ok: boolean;
  reason: string | null;
  blur_score: number;
  brightness: number;
  face_width: number;
  face_height: number;
  pose_hint: string;
  shadow_asymmetry: number;
  backlight_detected: boolean;
  yaw_ratio: number;
  pitch_ratio: number;
  mouth_ratio: number;
  pose_matches: boolean;
  pose_feedback: string | null;
}

export interface EnrollFrameResponse {
  accepted: boolean;
  pose_valid: boolean;
  pose_label: PoseLabel;
  message: string;
  embeddings_count: number;
  poses_completed: PoseLabel[];
  is_complete: boolean;
  required_poses_count: number;
  face_box: FaceBox | null;
  quality: QualityReport | null;
  avatar_saved: boolean;
}

export interface AttendanceSession {
  id: number;
  organization_id: number;
  group_id: number | null;
  group_name: string | null;
  course_assignment_id: number | null;
  schedule_id: number | null;
  work_shift_id: number | null;
  work_shift_name: string | null;
  work_shift_code: string | null;
  work_shift_crosses_midnight: boolean;
  subject_name: string | null;
  subject_code: string | null;
  career_name: string | null;
  teacher_name: string | null;
  title: string;
  session_date: string;
  session_type: "workday" | "class";
  expected_start_time: string | null;
  status: SessionStatus;
  created_at: string;
  closed_at: string | null;
  events_count: number;
}

export interface AttendanceEvent {
  id: number;
  session_id: number;
  session_title: string | null;
  person_id: number;
  person_name: string;
  person_external_id: string;
  person_avatar_base64: string | null;
  work_shift_id: number | null;
  work_shift_name: string | null;
  event_type: "check_in" | "check_out" | "present";
  status: "on_time" | "late" | "early_exit" | "manual";
  confidence_score: number | null;
  worked_minutes: number | null;
  late_minutes: number | null;
  early_exit_minutes: number | null;
  capture_mode: "kiosk_individual" | "group_scan" | "manual";
  timestamp: string;
  notes: string | null;
}

export interface PersonSummaryBrief {
  id: number;
  external_id: string;
  full_name: string;
  role: string;
  avatar_base64: string | null;
}

export interface RecognizeFrameResponse {
  faces_detected: number;
  match_status: "matched" | "unknown" | "ambiguous" | "no_face" | "low_quality";
  face_box: FaceBox | null;
  quality: QualityReport | null;
  person: PersonSummaryBrief | null;
  confidence: number;
  second_best_score: number | null;
  attendance_action: "recorded" | "cooldown" | "already_present" | "invalid_sequence" | null;
  event: AttendanceEvent | null;
  worked_minutes: number | null;
  shift_name: string | null;
  late_minutes: number | null;
  early_exit_minutes: number | null;
  session_id: number | null;
  message: string;
  latency_ms: number;
}

export interface HealthResponse {
  status: string;
  models_loaded: boolean;
  model_name: string;
  model_version: string;
  organizations_count: number;
  persons_count: number;
  embeddings_count: number;
}

export interface AuthUser {
  id: number;
  email: string;
  full_name: string;
  role: UserRole;
  organization_id: number | null;
  organization_name: string | null;
  organization_mode: OrgMode | null;
  is_active: boolean;
  created_by_user_id: number | null;
  created_at: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: AuthUser;
}

export interface DelegatedCredential {
  id: number;
  organization_id: number;
  label: string;
  secret_prefix: string;
  created_by_user_id: number | null;
  created_by_name: string | null;
  assigned_to_user_id: number | null;
  assigned_to_name: string;
  allowed_operations: string[];
  status: "active" | "revoked" | "expired";
  expires_at: string | null;
  created_at: string;
  revoked_at: string | null;
}

export interface DelegatedCredentialCreated {
  credential: DelegatedCredential;
  plain_secret: string;
}

export interface AuditLogEntry {
  id: number;
  organization_id: number | null;
  action: string;
  target_type: string;
  target_id: number | null;
  target_summary: string | null;
  executed_by_user_id: number | null;
  executed_by_name: string | null;
  authorized_by_user_id: number | null;
  authorized_by_name: string | null;
  delegated_credential_id: number | null;
  delegated_credential_prefix: string | null;
  delegated_assigned_to_name: string | null;
  details: string | null;
  created_at: string;
}

export interface BatchBiometricsRevokeResponse {
  revoked_persons_count: number;
  deleted_embeddings: number;
  authorized_by_name: string | null;
  authorization_method: string;
  delegated_credential_label: string | null;
}

export interface Career {
  id: number;
  organization_id: number;
  name: string;
  code: string;
  description: string | null;
  period_type: AcademicPeriodType | null;
  effective_period_type: AcademicPeriodType;
  created_at: string;
  groups_count: number;
  subjects_count: number;
}

export interface Subject {
  id: number;
  organization_id: number;
  career_id: number | null;
  career_name: string | null;
  name: string;
  code: string;
  created_at: string;
}

export interface ClassSchedule {
  id: number;
  course_assignment_id: number;
  day_of_week: number;
  start_time: string;
  end_time: string;
  classroom: string | null;
  created_at: string;
}

export interface CourseAssignment {
  id: number;
  organization_id: number;
  group_id: number;
  group_name: string;
  group_code: string;
  group_default_classroom: string | null;
  semester: string | null;
  period_type: string;
  career_id: number | null;
  career_name: string | null;
  subject_id: number;
  subject_name: string;
  subject_code: string;
  teacher_user_id: number | null;
  teacher_name: string | null;
  teacher_email: string | null;
  term: string | null;
  is_active: boolean;
  students_count: number;
  schedules: ClassSchedule[];
  created_at: string;
}

export interface GenerateSessionsResponse {
  target_date: string;
  created_count: number;
  existing_count: number;
  sessions: AttendanceSession[];
}

export interface TeacherAgendaSlot {
  schedule_id: number;
  course_assignment_id: number;
  subject_name: string;
  subject_code: string;
  group_id: number;
  group_name: string;
  group_code: string;
  career_name: string | null;
  day_of_week: number;
  start_time: string;
  end_time: string;
  classroom: string | null;
  slot_status: "in_progress" | "upcoming" | "finished";
  students_count: number;
  session: AttendanceSession | null;
}

export interface TeacherAgendaResponse {
  target_date: string;
  current_time: string;
  current_slot: TeacherAgendaSlot | null;
  today_slots: TeacherAgendaSlot[];
  courses: CourseAssignment[];
}

export interface SubjectAttendanceStat {
  course_assignment_id: number;
  subject_id: number;
  subject_name: string;
  subject_code: string;
  group_id: number;
  group_name: string;
  group_code: string;
  career_id: number | null;
  career_name: string | null;
  semester: string | null;
  period_type: string;
  teacher_name: string | null;
  sessions_count: number;
  enrolled_students: number;
  expected_records: number;
  present_count: number;
  on_time_count: number;
  late_count: number;
  manual_count: number;
  absent_count: number;
  attendance_rate: number;
}

export interface StudentGroupAttendanceStat {
  person_id: number;
  external_id: string;
  full_name: string;
  expected_records: number;
  present_count: number;
  on_time_count: number;
  late_count: number;
  absent_count: number;
  attendance_rate: number;
}

export interface GroupAttendanceStat {
  group_id: number;
  group_name: string;
  group_code: string;
  career_id: number | null;
  career_name: string | null;
  semester: string | null;
  period_type: string;
  subjects_count: number;
  students_count: number;
  total_sessions: number;
  total_expected: number;
  total_present: number;
  total_on_time: number;
  total_late: number;
  total_absent: number;
  overall_attendance_rate: number;
  students_breakdown: StudentGroupAttendanceStat[];
}

export interface AcademicStatsSummary {
  total_careers: number;
  total_groups: number;
  total_subjects: number;
  total_courses: number;
  total_sessions: number;
  overall_attendance_rate: number;
}

export interface AcademicStatsResponse {
  organization_id: number;
  date_from: string | null;
  date_to: string | null;
  summary: AcademicStatsSummary;
  by_subject: SubjectAttendanceStat[];
  by_group: GroupAttendanceStat[];
}

// --- Turnos Empresariales y Reglas de Jornada (Bloque D) ---
export interface WorkShift {
  id: number;
  organization_id: number;
  name: string;
  code: string;
  start_time: string;
  end_time: string;
  crosses_midnight: boolean;
  expected_duration_minutes: number;
  days_of_week: number[];
  late_tolerance_minutes: number | null;
  effective_late_tolerance_minutes: number;
  early_exit_tolerance_minutes: number;
  is_active: boolean;
  assigned_employees_count: number;
  default_groups_count: number;
  created_at: string;
}

export interface ShiftBulkAssignResponse {
  work_shift_id: number | null;
  work_shift_name: string | null;
  updated_count: number;
}

export interface ShiftAttendanceStat {
  work_shift_id: number | null;
  shift_name: string;
  shift_code: string | null;
  start_time: string | null;
  end_time: string | null;
  crosses_midnight: boolean;
  days_of_week: number[];
  employees_count: number;
  scheduled_days: number;
  present_days: number;
  on_time_days: number;
  late_days: number;
  early_exit_days: number;
  absent_days: number;
  missing_checkout_days: number;
  total_worked_minutes: number;
  avg_worked_minutes: number;
  attendance_rate: number;
  punctuality_rate: number;
}

export interface EmployeeAttendanceStat {
  person_id: number;
  external_id: string;
  full_name: string;
  group_names: string[];
  work_shift_id: number | null;
  shift_name: string | null;
  shift_code: string | null;
  shift_source: ShiftSource;
  scheduled_days: number;
  present_days: number;
  on_time_days: number;
  late_days: number;
  early_exit_days: number;
  absent_days: number;
  missing_checkout_days: number;
  total_late_minutes: number;
  total_early_exit_minutes: number;
  total_worked_minutes: number;
  attendance_rate: number;
  punctuality_rate: number;
}

export interface EnterpriseStatsSummary {
  total_shifts: number;
  active_shifts: number;
  total_employees: number;
  assigned_employees: number;
  unassigned_employees: number;
  scheduled_employee_days: number;
  present_days: number;
  on_time_days: number;
  late_days: number;
  early_exit_days: number;
  absent_days: number;
  missing_checkout_days: number;
  total_worked_minutes: number;
  attendance_rate: number;
  punctuality_rate: number;
}

export interface EnterpriseStatsResponse {
  organization_id: number;
  date_from: string;
  date_to: string;
  summary: EnterpriseStatsSummary;
  by_shift: ShiftAttendanceStat[];
  by_employee: EmployeeAttendanceStat[];
}
