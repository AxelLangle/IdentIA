import type {
  ActionMode,
  AttendanceEvent,
  AttendanceSession,
  EnrollFrameResponse,
  Group,
  HealthResponse,
  Organization,
  OrgMode,
  Person,
  PersonRole,
  PoseLabel,
  RecognizeFrameResponse,
} from "../types/api";

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
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

  listOrganizations: () => requestJson<Organization[]>("/api/organizations"),
  createOrganization: (data: {
    name: string;
    mode: OrgMode;
    late_tolerance_minutes?: number;
    cooldown_seconds?: number;
    store_avatar_by_default?: boolean;
  }) =>
    requestJson<Organization>("/api/organizations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  updateOrganization: (
    orgId: number,
    data: Partial<Pick<Organization, "name" | "mode" | "late_tolerance_minutes" | "cooldown_seconds" | "store_avatar_by_default">>
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
  }) =>
    requestJson<Group>("/api/groups", {
      method: "POST",
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
  revokeBiometrics: (personId: number) =>
    requestJson<{ person_id: number; deleted_embeddings: number; avatar_cleared: boolean }>(
      `/api/persons/${personId}/biometrics`,
      { method: "DELETE" }
    ),

  listSessions: (organizationId: number, status?: "open" | "closed") => {
    const params = new URLSearchParams({ organization_id: String(organizationId) });
    if (status) params.set("status", status);
    return requestJson<AttendanceSession[]>(`/api/sessions?${params.toString()}`);
  },
  createSession: (data: {
    organization_id: number;
    group_id?: number | null;
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

  exportCsvUrl: (organizationId: number, sessionId?: number | null) => {
    const params = new URLSearchParams({ organization_id: String(organizationId) });
    if (sessionId !== undefined && sessionId !== null) {
      params.set("session_id", String(sessionId));
    }
    return `/api/attendance/export.csv?${params.toString()}`;
  },
};
