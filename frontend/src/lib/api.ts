import type {
  AcademicStatsResponse,
  ActionMode,
  AttendanceEvent,
  AttendanceSession,
  AuditLogEntry,
  AuthUser,
  BatchBiometricsRevokeResponse,
  Career,
  ClassSchedule,
  CourseAssignment,
  DelegatedCredential,
  DelegatedCredentialCreated,
  EnrollFrameResponse,
  GenerateSessionsResponse,
  Group,
  HealthResponse,
  LoginResponse,
  Organization,
  OrgMode,
  Person,
  PersonRole,
  PoseLabel,
  RecognizeFrameResponse,
  Subject,
  TeacherAgendaResponse,
  UserRole,
} from "../types/api";

const TOKEN_STORAGE_KEY = "identia_token";
let onUnauthorizedCallback: (() => void) | null = null;

export function getStoredToken(): string | null {
  return window.localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setStoredToken(token: string | null): void {
  if (token) {
    window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
  } else {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  }
}

export function setOnUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorizedCallback = handler;
}

async function fetchWithAuth(url: string, init: RequestInit = {}): Promise<Response> {
  const token = getStoredToken();
  const headers = new Headers(init.headers);
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(url, { ...init, headers });
  if (response.status === 401 && !url.endsWith("/api/auth/login")) {
    setStoredToken(null);
    onUnauthorizedCallback?.();
  }
  return response;
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetchWithAuth(url, init);
  if (!response.ok) {
    let detail = `Error HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) detail = payload.detail;
    } catch {
      // Ignora error si la respuesta no es JSON
    }
    throw new Error(detail);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const api = {
  getHealth: () => requestJson<HealthResponse>("/api/health"),

  login: async (email: string, password: string): Promise<LoginResponse> => {
    const res = await requestJson<LoginResponse>("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    setStoredToken(res.access_token);
    return res;
  },
  getMe: () => requestJson<AuthUser>("/api/auth/me"),

  listUsers: (organizationId?: number | null) => {
    const params = new URLSearchParams();
    if (organizationId !== undefined && organizationId !== null) {
      params.set("organization_id", String(organizationId));
    }
    const qs = params.toString();
    return requestJson<AuthUser[]>(`/api/users${qs ? `?${qs}` : ""}`);
  },
  createUser: (data: {
    email: string;
    full_name: string;
    password: string;
    role: UserRole;
    organization_id?: number | null;
  }) =>
    requestJson<AuthUser>("/api/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  updateUser: (
    userId: number,
    data: Partial<{ full_name: string; password: string; role: UserRole; is_active: boolean }>
  ) =>
    requestJson<AuthUser>(`/api/users/${userId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),

  listDelegatedCredentials: (organizationId?: number | null) => {
    const params = new URLSearchParams();
    if (organizationId !== undefined && organizationId !== null) {
      params.set("organization_id", String(organizationId));
    }
    const qs = params.toString();
    return requestJson<DelegatedCredential[]>(
      `/api/security/delegated-credentials${qs ? `?${qs}` : ""}`
    );
  },
  createDelegatedCredential: (data: {
    organization_id?: number | null;
    label: string;
    assigned_to_user_id?: number | null;
    assigned_to_name?: string | null;
    custom_secret?: string | null;
    expires_in_days?: number | null;
  }) =>
    requestJson<DelegatedCredentialCreated>("/api/security/delegated-credentials", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  revokeDelegatedCredential: (credId: number) =>
    requestJson<DelegatedCredential>(`/api/security/delegated-credentials/${credId}/revoke`, {
      method: "POST",
    }),
  listAuditLogs: (organizationId?: number | null, limit = 100) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (organizationId !== undefined && organizationId !== null) {
      params.set("organization_id", String(organizationId));
    }
    return requestJson<AuditLogEntry[]>(`/api/security/audit-logs?${params.toString()}`);
  },

  listOrganizations: () => requestJson<Organization[]>("/api/organizations"),
  createOrganization: (data: {
    name: string;
    mode: OrgMode;
    late_tolerance_minutes?: number;
    cooldown_seconds?: number;
    store_avatar_by_default?: boolean;
    admin_user?: {
      full_name: string;
      email: string;
      password: string;
    } | null;
  }) =>
    requestJson<Organization>("/api/organizations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  updateOrganization: (
    orgId: number,
    data: Partial<
      Pick<
        Organization,
        "name" | "mode" | "late_tolerance_minutes" | "cooldown_seconds" | "store_avatar_by_default"
      >
    >
  ) =>
    requestJson<Organization>(`/api/organizations/${orgId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),

  listGroups: (organizationId: number) =>
    requestJson<Group[]>(`/api/groups?organization_id=${organizationId}`),
  createGroup: (data: {
    organization_id: number;
    name: string;
    code: string;
    schedule_start: string;
    schedule_end: string;
    career_id?: number | null;
    semester?: string | null;
  }) =>
    requestJson<Group>("/api/groups", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  updateGroup: (
    groupId: number,
    data: Partial<{
      name: string;
      code: string;
      schedule_start: string;
      schedule_end: string;
      career_id: number | null;
      semester: string | null;
    }>
  ) =>
    requestJson<Group>(`/api/groups/${groupId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  deleteGroup: (groupId: number) =>
    requestJson<void>(`/api/groups/${groupId}`, { method: "DELETE" }),

  listPersons: (organizationId: number, search?: string, groupId?: number | null) => {
    const params = new URLSearchParams({ organization_id: String(organizationId) });
    if (search && search.trim()) params.set("search", search.trim());
    if (groupId !== undefined && groupId !== null) params.set("group_id", String(groupId));
    return requestJson<Person[]>(`/api/persons?${params.toString()}`);
  },
  createPerson: (data: {
    organization_id: number;
    external_id: string;
    full_name: string;
    email?: string | null;
    role: PersonRole;
    biometric_consent: boolean;
    group_ids: number[];
  }) =>
    requestJson<Person>("/api/persons", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  updatePerson: (
    personId: number,
    data: Partial<{
      full_name: string;
      email: string | null;
      role: PersonRole;
      biometric_consent: boolean;
      is_active: boolean;
      group_ids: number[];
    }>
  ) =>
    requestJson<Person>(`/api/persons/${personId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  deletePerson: (personId: number) =>
    requestJson<void>(`/api/persons/${personId}`, { method: "DELETE" }),

  enrollFrame: (
    personId: number,
    imageBlob: Blob,
    poseLabel: PoseLabel,
    storeAvatar?: boolean,
    dryRun = false
  ) => {
    const form = new FormData();
    form.append("image", imageBlob, "frame.jpg");
    form.append("pose_label", poseLabel);
    if (storeAvatar !== undefined) {
      form.append("store_avatar", String(storeAvatar));
    }
    if (dryRun) {
      form.append("dry_run", "true");
    }
    return requestJson<EnrollFrameResponse>(`/api/persons/${personId}/enroll-frame`, {
      method: "POST",
      body: form,
    });
  },
  revokeBiometricsBatch: (data: {
    person_ids: number[];
    authorization_secret: string;
    reason?: string;
  }) =>
    requestJson<BatchBiometricsRevokeResponse>("/api/persons/biometrics/revoke", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),

  listSessions: (organizationId: number, status?: "open" | "closed") => {
    const params = new URLSearchParams({ organization_id: String(organizationId) });
    if (status) params.set("status", status);
    return requestJson<AttendanceSession[]>(`/api/sessions?${params.toString()}`);
  },
  createSession: (data: {
    organization_id: number;
    group_id?: number | null;
    course_assignment_id?: number | null;
    schedule_id?: number | null;
    title: string;
    expected_start_time?: string | null;
  }) =>
    requestJson<AttendanceSession>("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  closeSession: (sessionId: number) =>
    requestJson<AttendanceSession>(`/api/sessions/${sessionId}/close`, { method: "POST" }),

  recognizeFrame: (params: {
    imageBlob: Blob;
    organizationId: number;
    sessionId?: number | null;
    groupId?: number | null;
    actionMode?: ActionMode;
  }) => {
    const form = new FormData();
    form.append("image", params.imageBlob, "frame.jpg");
    form.append("organization_id", String(params.organizationId));
    if (params.sessionId !== undefined && params.sessionId !== null) {
      form.append("session_id", String(params.sessionId));
    }
    if (params.groupId !== undefined && params.groupId !== null) {
      form.append("group_id", String(params.groupId));
    }
    form.append("action_mode", params.actionMode ?? "auto");
    return requestJson<RecognizeFrameResponse>("/api/attendance/recognize-frame", {
      method: "POST",
      body: form,
    });
  },

  listEvents: (organizationId: number, sessionId?: number | null, limit = 100) => {
    const params = new URLSearchParams({
      organization_id: String(organizationId),
      limit: String(limit),
    });
    if (sessionId !== undefined && sessionId !== null) {
      params.set("session_id", String(sessionId));
    }
    return requestJson<AttendanceEvent[]>(`/api/attendance/events?${params.toString()}`);
  },

  createManualAttendance: (data: {
    session_id: number;
    person_id: number;
    event_type: "check_in" | "check_out" | "present";
    status?: "on_time" | "late" | "manual";
    notes?: string;
  }) =>
    requestJson<AttendanceEvent>("/api/attendance/manual", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),

  downloadCsv: async (organizationId: number, sessionId?: number | null): Promise<void> => {
    const params = new URLSearchParams({ organization_id: String(organizationId) });
    if (sessionId !== undefined && sessionId !== null) {
      params.set("session_id", String(sessionId));
    }
    const response = await fetchWithAuth(`/api/attendance/export.csv?${params.toString()}`);
    if (!response.ok) {
      throw new Error(`No se pudo descargar el reporte (HTTP ${response.status}).`);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "asistencia_identia.csv";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  },

  // --- Modelo Educativo Completo (Bloque C) ---
  listCareers: (organizationId: number) =>
    requestJson<Career[]>(`/api/academic/careers?organization_id=${organizationId}`),
  createCareer: (data: {
    organization_id: number;
    name: string;
    code: string;
    description?: string | null;
  }) =>
    requestJson<Career>("/api/academic/careers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  updateCareer: (
    careerId: number,
    data: Partial<{ name: string; code: string; description: string | null }>
  ) =>
    requestJson<Career>(`/api/academic/careers/${careerId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  deleteCareer: (careerId: number) =>
    requestJson<void>(`/api/academic/careers/${careerId}`, { method: "DELETE" }),

  listSubjects: (organizationId: number, careerId?: number | null) => {
    const params = new URLSearchParams({ organization_id: String(organizationId) });
    if (careerId !== undefined && careerId !== null) params.set("career_id", String(careerId));
    return requestJson<Subject[]>(`/api/academic/subjects?${params.toString()}`);
  },
  createSubject: (data: {
    organization_id: number;
    career_id?: number | null;
    name: string;
    code: string;
  }) =>
    requestJson<Subject>("/api/academic/subjects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  deleteSubject: (subjectId: number) =>
    requestJson<void>(`/api/academic/subjects/${subjectId}`, { method: "DELETE" }),

  listCourses: (
    organizationId: number,
    groupId?: number | null,
    teacherUserId?: number | null
  ) => {
    const params = new URLSearchParams({ organization_id: String(organizationId) });
    if (groupId !== undefined && groupId !== null) params.set("group_id", String(groupId));
    if (teacherUserId !== undefined && teacherUserId !== null) {
      params.set("teacher_user_id", String(teacherUserId));
    }
    return requestJson<CourseAssignment[]>(`/api/academic/courses?${params.toString()}`);
  },
  createCourse: (data: {
    organization_id: number;
    group_id: number;
    subject_id: number;
    teacher_user_id?: number | null;
    term?: string | null;
    schedules: {
      day_of_week: number;
      start_time: string;
      end_time: string;
      classroom?: string | null;
    }[];
  }) =>
    requestJson<CourseAssignment>("/api/academic/courses", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  updateCourse: (
    courseId: number,
    data: Partial<{ teacher_user_id: number | null; term: string | null; is_active: boolean }>
  ) =>
    requestJson<CourseAssignment>(`/api/academic/courses/${courseId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  deleteCourse: (courseId: number) =>
    requestJson<void>(`/api/academic/courses/${courseId}`, { method: "DELETE" }),

  addCourseSchedule: (
    courseId: number,
    data: {
      day_of_week: number;
      start_time: string;
      end_time: string;
      classroom?: string | null;
    }
  ) =>
    requestJson<ClassSchedule>(`/api/academic/courses/${courseId}/schedules`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  deleteSchedule: (scheduleId: number) =>
    requestJson<void>(`/api/academic/schedules/${scheduleId}`, { method: "DELETE" }),

  getStudentCourses: (personId: number) =>
    requestJson<CourseAssignment[]>(`/api/academic/students/${personId}/courses`),

  generateAcademicSessions: (data: {
    organization_id: number;
    target_date?: string | null;
    course_assignment_id?: number | null;
  }) =>
    requestJson<GenerateSessionsResponse>("/api/academic/sessions/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),

  startCourseSession: (
    courseId: number,
    data?: { schedule_id?: number | null; session_date?: string | null }
  ) =>
    requestJson<AttendanceSession>(`/api/academic/courses/${courseId}/start-session`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data ?? {}),
    }),

  getTeacherAgenda: (params: {
    organization_id: number;
    target_date?: string | null;
    current_time?: string | null;
    teacher_user_id?: number | null;
  }) => {
    const qs = new URLSearchParams({ organization_id: String(params.organization_id) });
    if (params.target_date) qs.set("target_date", params.target_date);
    if (params.current_time) qs.set("current_time", params.current_time);
    if (params.teacher_user_id !== undefined && params.teacher_user_id !== null) {
      qs.set("teacher_user_id", String(params.teacher_user_id));
    }
    return requestJson<TeacherAgendaResponse>(`/api/academic/teacher/agenda?${qs.toString()}`);
  },

  getAcademicStats: (params: {
    organization_id: number;
    date_from?: string | null;
    date_to?: string | null;
    career_id?: number | null;
    group_id?: number | null;
  }) => {
    const qs = new URLSearchParams({ organization_id: String(params.organization_id) });
    if (params.date_from) qs.set("date_from", params.date_from);
    if (params.date_to) qs.set("date_to", params.date_to);
    if (params.career_id !== undefined && params.career_id !== null) {
      qs.set("career_id", String(params.career_id));
    }
    if (params.group_id !== undefined && params.group_id !== null) {
      qs.set("group_id", String(params.group_id));
    }
    return requestJson<AcademicStatsResponse>(`/api/academic/stats?${qs.toString()}`);
  },
};
