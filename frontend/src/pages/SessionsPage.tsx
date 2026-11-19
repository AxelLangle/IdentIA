import { useState, type FormEvent } from "react";
import { CalendarPlus, Download, Lock, Plus, Trash2 } from "lucide-react";
import { api } from "../lib/api";
import type {
  AttendanceEvent,
  AttendanceSession,
  Group,
  Organization,
  Person,
} from "../types/api";

interface SessionsPageProps {
  organization: Organization;
  groups: Group[];
  sessions: AttendanceSession[];
  persons: Person[];
  events: AttendanceEvent[];
  onRefreshAll: () => Promise<void>;
}

export function SessionsPage({
  organization,
  groups,
  sessions,
  persons,
  events,
  onRefreshAll,
}: SessionsPageProps) {
  // Crear grupo
  const [groupName, setGroupName] = useState("");
  const [groupCode, setGroupCode] = useState("");
  const [scheduleStart, setScheduleStart] = useState("08:00");
  const [scheduleEnd, setScheduleEnd] = useState("17:00");

  // Crear sesión
  const [sessionTitle, setSessionTitle] = useState("");
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

  const openSessions = sessions.filter((s) => s.status === "open");
  const filteredEvents = filterSessionId
    ? events.filter((e) => e.session_id === Number(filterSessionId))
    : events;

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
    await api.createSession({
      organization_id: organization.id,
      group_id: sessionGroupId ? Number(sessionGroupId) : null,
      title: sessionTitle.trim(),
      expected_start_time: expectedStart || null,
    });
    setSessionTitle("");
    setExpectedStart("");
    await onRefreshAll();
  }

  async function handleCloseSession(sessionId: number) {
    await api.closeSession(sessionId);
    await onRefreshAll();
  }

  async function handleManualAttendance(e: FormEvent) {
    e.preventDefault();
    if (!manualSessionId || !manualPersonId) return;
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
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Grupos, Sesiones e Historial</h2>
          <p className="text-sm text-slate-400">
            Administra materias/departamentos, sesiones de asistencia y respaldo manual
          </p>
        </div>

        <a
          href={api.exportCsvUrl(
            organization.id,
            filterSessionId ? Number(filterSessionId) : null
          )}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-indigo-600 hover:bg-indigo-500 text-white"
        >
          <Download className="w-4 h-4" />
          Descargar CSV
        </a>
      </div>

      {/* Grupos y Sesiones */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
          <h3 className="font-semibold text-base">
            {organization.mode === "education" ? "Grupos / Materias" : "Áreas / Departamentos"}
          </h3>

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
                <button
                  type="button"
                  onClick={() => void handleDeleteGroup(g.id)}
                  className="p-1.5 rounded-md text-slate-400 hover:text-red-400 hover:bg-red-500/10"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
          <h3 className="font-semibold text-base">Sesiones de Asistencia</h3>

          <form onSubmit={handleCreateSession} className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
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
            <select
              value={sessionGroupId}
              onChange={(e) => setSessionGroupId(e.target.value)}
              className="sm:col-span-2 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
            >
              <option value="">Sin grupo específico</option>
              {groups.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
            <input
              type="time"
              value={expectedStart}
              onChange={(e) => setExpectedStart(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
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
            onChange={(e) => setManualSessionId(e.target.value)}
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
            {persons.map((p) => (
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
