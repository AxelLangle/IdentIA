import { useEffect, useState, type FormEvent } from "react";
import { CalendarCheck, CalendarPlus, Download, Lock, Plus, Trash2 } from "lucide-react";
import { api } from "../lib/api";
import type {
  AttendanceEvent,
  AttendanceSession,
  AuthUser,
  CourseAssignment,
  Group,
  Organization,
  Person,
} from "../types/api";

interface SessionsPageProps {
  currentUser: AuthUser;
  organization: Organization;
  groups: Group[];
  sessions: AttendanceSession[];
  persons: Person[];
  events: AttendanceEvent[];
  onRefreshAll: () => Promise<void>;
}

export function SessionsPage({
  currentUser,
  organization,
  groups,
  sessions,
  persons,
  events,
  onRefreshAll,
}: SessionsPageProps) {
  const isTeacher = currentUser.role === "teacher";
  const isEducation = organization.mode === "education";
  const canManageGroups = currentUser.role === "superadmin" || currentUser.role === "org_admin";
  const canGenerateSessions =
    isEducation && ["superadmin", "org_admin", "teacher"].includes(currentUser.role);

  const [courses, setCourses] = useState<CourseAssignment[]>([]);
  // Crear grupo
  const [groupName, setGroupName] = useState("");
  const [groupCode, setGroupCode] = useState("");
  const [scheduleStart, setScheduleStart] = useState("08:00");
  const [scheduleEnd, setScheduleEnd] = useState("17:00");

  // Crear sesión
  const [sessionTitle, setSessionTitle] = useState("");
  const [sessionCourseId, setSessionCourseId] = useState<string>("");
  const [sessionGroupId, setSessionGroupId] = useState<string>("");
  const [expectedStart, setExpectedStart] = useState("");

  // Registro manual
  const [manualSessionId, setManualSessionId] = useState<string>("");
  const [manualPersonId, setManualPersonId] = useState<string>("");
  const [manualEventType, setManualEventType] = useState<"present" | "check_in" | "check_out">(
    organization.mode === "education" ? "present" : "check_in"
  );
  const [manualNotes, setManualNotes] = useState("");
  const [filterSessionId, setFilterSessionId] = useState<string>("");
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    setSessionCourseId("");
    setSessionGroupId("");
    setManualSessionId("");
    setManualPersonId("");
    if (!isEducation) {
      setCourses([]);
      return;
    }
    let cancelled = false;
    api
      .listCourses(organization.id)
      .then((list) => {
        if (!cancelled) setCourses(list);
      })
      .catch(() => {
        if (!cancelled) setCourses([]);
      });
    return () => {
      cancelled = true;
    };
  }, [isEducation, organization.id]);

  const openSessions = sessions.filter((s) => s.status === "open");
  const filteredEvents = filterSessionId
    ? events.filter((e) => e.session_id === Number(filterSessionId))
    : events;

  const selectedManualSession =
    openSessions.find((s) => String(s.id) === manualSessionId) ?? null;
  const manualPersonOptions =
    selectedManualSession && selectedManualSession.group_id !== null
      ? persons.filter((p) => p.group_ids.includes(selectedManualSession.group_id!))
      : persons;

  async function handleGenerateTodaySessions() {
    setErrorMsg(null);
    setStatusMsg(null);
    try {
      const now = new Date();
      const todayIso = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(
        now.getDate()
      ).padStart(2, "0")}`;
      const res = await api.generateAcademicSessions({
        organization_id: organization.id,
        target_date: todayIso,
      });
      setStatusMsg(
        `Sesiones del ${res.target_date}: ${res.created_count} nuevas, ${res.existing_count} existentes.`
      );
      await onRefreshAll();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "No se pudieron generar sesiones.");
    }
  }

  async function handleCreateGroup(e: FormEvent) {
    e.preventDefault();
    if (!groupName.trim() || !groupCode.trim()) return;
    await api.createGroup({
      organization_id: organization.id,
      name: groupName.trim(),
      code: groupCode.trim(),
      schedule_start: scheduleStart,
      schedule_end: scheduleEnd,
    });
    setGroupName("");
    setGroupCode("");
    await onRefreshAll();
  }

  async function handleDeleteGroup(groupId: number) {
    await api.deleteGroup(groupId);
    await onRefreshAll();
  }

  async function handleCreateSession(e: FormEvent) {
    e.preventDefault();
    if (!sessionTitle.trim()) return;
    setErrorMsg(null);
    try {
      await api.createSession({
        organization_id: organization.id,
        group_id: !sessionCourseId && sessionGroupId ? Number(sessionGroupId) : null,
        course_assignment_id: sessionCourseId ? Number(sessionCourseId) : null,
        title: sessionTitle.trim(),
        expected_start_time: expectedStart || null,
      });
      setSessionTitle("");
      setSessionCourseId("");
      setExpectedStart("");
      await onRefreshAll();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "No se pudo abrir la sesión.");
    }
  }

  async function handleCloseSession(sessionId: number) {
    await api.closeSession(sessionId);
    await onRefreshAll();
  }

  async function handleManualAttendance(e: FormEvent) {
    e.preventDefault();
    if (!manualSessionId || !manualPersonId) return;
    setErrorMsg(null);
    try {
      await api.createManualAttendance({
        session_id: Number(manualSessionId),
        person_id: Number(manualPersonId),
        event_type: manualEventType,
        status: "manual",
        notes: manualNotes.trim() || undefined,
      });
      setManualNotes("");
      setStatusMsg("Asistencia manual registrada.");
      await onRefreshAll();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "No se pudo registrar asistencia manual.");
    }
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">
            {isTeacher ? "Mis Sesiones e Historial" : "Grupos, Sesiones e Historial"}
          </h2>
          <p className="text-sm text-slate-400">
            {isTeacher
              ? "Sesiones y registros de tus asignaturas asignadas"
              : "Administra materias/departamentos, sesiones de asistencia y respaldo manual"}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {canGenerateSessions && (
            <button
              type="button"
              onClick={() => void handleGenerateTodaySessions()}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-emerald-600 hover:bg-emerald-500 text-white"
            >
              <CalendarCheck className="w-4 h-4" />
              Generar sesiones de hoy
            </button>
          )}
          <button
            type="button"
            onClick={() =>
              void api.downloadCsv(
                organization.id,
                filterSessionId ? Number(filterSessionId) : null
              )
            }
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-indigo-600 hover:bg-indigo-500 text-white"
          >
            <Download className="w-4 h-4" />
            Descargar CSV
          </button>
        </div>
      </div>

      {statusMsg && (
        <div className="rounded-xl bg-emerald-500/15 border border-emerald-500/40 px-4 py-2.5 text-xs text-emerald-200">
          {statusMsg}
        </div>
      )}
      {errorMsg && (
        <div className="rounded-xl bg-red-500/15 border border-red-500/40 px-4 py-2.5 text-xs text-red-200">
          {errorMsg}
        </div>
      )}

      {/* Grupos y Sesiones */}
      <div className={`grid grid-cols-1 ${isTeacher ? "" : "lg:grid-cols-2"} gap-6`}>
        {!isTeacher && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
          <h3 className="font-semibold text-base">
            {organization.mode === "education" ? "Grupos / Materias" : "Áreas / Departamentos"}
          </h3>

          {canManageGroups && (
            <form onSubmit={handleCreateGroup} className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
              <input
                type="text"
                required
                value={groupName}
                onChange={(e) => setGroupName(e.target.value)}
                placeholder="Nombre"
                className="col-span-2 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              />
              <input
                type="text"
                required
                value={groupCode}
                onChange={(e) => setGroupCode(e.target.value)}
                placeholder="Código"
                className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              />
              <button
                type="submit"
                className="inline-flex items-center justify-center gap-1 bg-indigo-600 hover:bg-indigo-500 rounded-lg px-3 py-2 text-sm font-semibold"
              >
                <Plus className="w-4 h-4" />
                Crear
              </button>
              <div className="col-span-2">
                <label className="block text-[11px] text-slate-400 mb-1">Inicio horario</label>
                <input
                  type="time"
                  value={scheduleStart}
                  onChange={(e) => setScheduleStart(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm"
                />
              </div>
              <div className="col-span-2">
                <label className="block text-[11px] text-slate-400 mb-1">Fin horario</label>
                <input
                  type="time"
                  value={scheduleEnd}
                  onChange={(e) => setScheduleEnd(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm"
                />
              </div>
            </form>
          )}

          <div className="space-y-2 max-h-56 overflow-y-auto">
            {groups.map((g) => (
              <div
                key={g.id}
                className="flex items-center justify-between px-3.5 py-2.5 rounded-xl bg-slate-800/50 border border-slate-800"
              >
                <div>
                  <p className="text-sm font-medium">
                    {g.name} <span className="text-xs text-slate-400">({g.code})</span>
                  </p>
                  <p className="text-xs text-slate-500">
                    {g.schedule_start} - {g.schedule_end} · {g.members_count} integrantes
                  </p>
                </div>
                {canManageGroups && (
                  <button
                    type="button"
                    onClick={() => void handleDeleteGroup(g.id)}
                    className="p-1.5 rounded-md text-slate-400 hover:text-red-400 hover:bg-red-500/10"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
        )}

        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
          <h3 className="font-semibold text-base">Sesiones de Asistencia</h3>

          <form onSubmit={handleCreateSession} className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
            {isEducation && (
              <select
                required={isTeacher}
                value={sessionCourseId}
                onChange={(e) => {
                  const val = e.target.value;
                  setSessionCourseId(val);
                  if (val && !sessionTitle.trim()) {
                    const matched = courses.find((c) => String(c.id) === val);
                    if (matched) {
                      setSessionTitle(`${matched.subject_name} — ${matched.group_name}`);
                    }
                  }
                }}
                className="sm:col-span-3 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              >
                <option value="">
                  {isTeacher
                    ? "Selecciona asignatura asignada..."
                    : "Opcional: vincular a asignatura de curso"}
                </option>
                {courses.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.subject_name} ({c.subject_code}) · {c.group_name}
                  </option>
                ))}
              </select>
            )}
            <input
              type="text"
              required
              value={sessionTitle}
              onChange={(e) => setSessionTitle(e.target.value)}
              placeholder="Título de la sesión"
              className="sm:col-span-2 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
            />
            <button
              type="submit"
              className="inline-flex items-center justify-center gap-1 bg-indigo-600 hover:bg-indigo-500 rounded-lg px-3 py-2 text-sm font-semibold"
            >
              <CalendarPlus className="w-4 h-4" />
              Abrir
            </button>
            {!isTeacher && (
              <select
                value={sessionGroupId}
                disabled={Boolean(sessionCourseId)}
                onChange={(e) => setSessionGroupId(e.target.value)}
                className="sm:col-span-2 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm disabled:opacity-50"
              >
                <option value="">Sin grupo específico</option>
                {groups.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.name}
                  </option>
                ))}
              </select>
            )}
            <input
              type="time"
              value={expectedStart}
              onChange={(e) => setExpectedStart(e.target.value)}
              className={`${isTeacher ? "sm:col-span-3" : ""} bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm`}
              title="Hora esperada de inicio"
            />
          </form>

          <div className="space-y-2 max-h-56 overflow-y-auto">
            {sessions.map((s) => (
              <div
                key={s.id}
                className="flex items-center justify-between px-3.5 py-2.5 rounded-xl bg-slate-800/50 border border-slate-800"
              >
                <div>
                  <p className="text-sm font-medium">{s.title}</p>
                  {s.subject_name && (
                    <p className="text-[11px] text-indigo-300 mt-0.5">
                      {s.subject_name}
                      {s.group_name ? ` · ${s.group_name}` : ""}
                      {s.teacher_name ? ` · ${s.teacher_name}` : ""}
                    </p>
                  )}
                  <p className="text-xs text-slate-500">
                    {s.session_date} · {s.events_count} eventos ·{" "}
                    <span className={s.status === "open" ? "text-emerald-400" : "text-slate-400"}>
                      {s.status === "open" ? "Abierta" : "Cerrada"}
                    </span>
                  </p>
                </div>
                {s.status === "open" && (
                  <button
                    type="button"
                    onClick={() => void handleCloseSession(s.id)}
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300"
                  >
                    <Lock className="w-3.5 h-3.5" />
                    Cerrar
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Registro manual */}
      <form
        onSubmit={handleManualAttendance}
        className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3"
      >
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-base">Registro Manual de Respaldo</h3>
          {statusMsg && <span className="text-xs text-emerald-300">{statusMsg}</span>}
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
          <select
            required
            value={manualSessionId}
            onChange={(e) => {
              setManualSessionId(e.target.value);
              setManualPersonId("");
            }}
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
          >
            <option value="">Selecciona sesión abierta...</option>
            {openSessions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title}
              </option>
            ))}
          </select>

          <select
            required
            value={manualPersonId}
            onChange={(e) => setManualPersonId(e.target.value)}
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
          >
            <option value="">Selecciona persona...</option>
            {manualPersonOptions.map((p) => (
              <option key={p.id} value={p.id}>
                {p.full_name} ({p.external_id})
              </option>
            ))}
          </select>

          <select
            value={manualEventType}
            onChange={(e) =>
              setManualEventType(e.target.value as "present" | "check_in" | "check_out")
            }
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
          >
            <option value="present">Asistencia</option>
            <option value="check_in">Entrada</option>
            <option value="check_out">Salida</option>
          </select>

          <input
            type="text"
            value={manualNotes}
            onChange={(e) => setManualNotes(e.target.value)}
            placeholder="Nota (ej. cámara sin luz)"
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
          />

          <button
            type="submit"
            className="bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg px-4 py-2 text-sm font-semibold"
          >
            Registrar Manual
          </button>
        </div>
      </form>

      {/* Historial de eventos */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="font-semibold text-base">Historial de Asistencias</h3>
          <select
            value={filterSessionId}
            onChange={(e) => setFilterSessionId(e.target.value)}
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm"
          >
            <option value="">Todas las sesiones</option>
            {sessions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title}
              </option>
            ))}
          </select>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="text-xs uppercase text-slate-400 border-b border-slate-800">
              <tr>
                <th className="py-2 pr-3">Fecha y Hora</th>
                <th className="py-2 px-3">Sesión</th>
                <th className="py-2 px-3">Persona</th>
                <th className="py-2 px-3">Tipo</th>
                <th className="py-2 px-3">Estado</th>
                <th className="py-2 px-3">Modo</th>
                <th className="py-2 pl-3 text-right">Confianza</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/70">
              {filteredEvents.map((ev) => (
                <tr key={ev.id} className="hover:bg-slate-800/30">
                  <td className="py-2.5 pr-3 text-xs text-slate-300">
                    {new Date(ev.timestamp).toLocaleString()}
                  </td>
                  <td className="py-2.5 px-3 text-xs text-slate-400">{ev.session_title}</td>
                  <td className="py-2.5 px-3 font-medium">
                    {ev.person_name}{" "}
                    <span className="text-xs text-slate-500">({ev.person_external_id})</span>
                  </td>
                  <td className="py-2.5 px-3 text-xs">{ev.event_type}</td>
                  <td className="py-2.5 px-3 text-xs">{ev.status}</td>
                  <td className="py-2.5 px-3 text-xs text-slate-400">{ev.capture_mode}</td>
                  <td className="py-2.5 pl-3 text-right text-xs">
                    {ev.confidence_score !== null
                      ? `${(ev.confidence_score * 100).toFixed(1)}%`
                      : "Manual"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
