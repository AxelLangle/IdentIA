export type OrgMode = "enterprise" | "education";
export type PersonRole = "employee" | "student" | "teacher" | "admin";
export type PoseLabel = "frontal" | "left" | "right" | "up" | "down" | "smile";
export type ActionMode = "auto" | "check_in" | "check_out" | "present";
export type SessionStatus = "open" | "closed";

export interface Organization {
  id: number;
  name: string;
  mode: OrgMode;
  late_tolerance_minutes: number;
  cooldown_seconds: number;
  store_avatar_by_default: boolean;
  created_at: string;
}

export interface Group {
  id: number;
  organization_id: number;
  name: string;
  code: string;
  schedule_start: string;
  schedule_end: string;
  created_at: string;
  members_count: number;
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
  event_type: "check_in" | "check_out" | "present";
  status: "on_time" | "late" | "manual";
  confidence_score: number | null;
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
