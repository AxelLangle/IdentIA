import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  ArrowUpDown,
  BarChart3,
  Briefcase,
  CalendarCheck,
  Clock,
  Moon,
  Pencil,
  Plus,
  ScanFace,
  Sun,
  Trash2,
  Users,
  X,
} from "lucide-react";
import { api } from "../lib/api";
import type {
  AuthUser,
  EnterpriseStatsResponse,
  Group,
  Organization,
  Person,
  WorkShift,
} from "../types/api";

interface EnterpriseShiftsPageProps {
  currentUser: AuthUser;
  organization: Organization;
  groups: Group[];
  persons: Person[];
  onRefreshOrg: () => Promise<void>;
  onOpenSessionInKiosk: (sessionId: number) => void;
}

type EnterpriseSubTab = "shifts" | "assignments" | "stats";
type EmployeeSortField = "name" | "shift" | "attendance" | "absences" | "worked";

const WEEKDAYS = [
  { value: 0, short: "Lun", mini: "L", label: "Lunes" },
  { value: 1, short: "Mar", mini: "M", label: "Martes" },
  { value: 2, short: "Mié", mini: "X", label: "Miércoles" },
  { value: 3, short: "Jue", mini: "J", label: "Jueves" },
  { value: 4, short: "Vie", mini: "V", label: "Viernes" },
  { value: 5, short: "Sáb", mini: "S", label: "Sábado" },
  { value: 6, short: "Dom", mini: "D", label: "Domingo" },
];

function formatDuration(totalMinutes: number): string {
  const mins = Math.max(0, Math.round(totalMinutes));
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  if (h === 0) return `${m}m`;
  return `${h}h ${String(m).padStart(2, "0")}m`;
}

function computeShiftPreview(startTime: string, endTime: string): {
  valid: boolean;
  crossesMidnight: boolean;
  durationMinutes: number;
} {
  if (!/^\d{2}:\d{2}$/.test(startTime) || !/^\d{2}:\d{2}$/.test(endTime)) {
    return { valid: false, crossesMidnight: false, durationMinutes: 0 };
  }
  const [sh, sm] = startTime.split(":").map(Number);
  const [eh, em] = endTime.split(":").map(Number);
  const startMin = sh * 60 + sm;
  const endMin = eh * 60 + em;
  if (startMin === endMin) {
    return { valid: false, crossesMidnight: false, durationMinutes: 0 };
  }
  const crossesMidnight = endMin < startMin;
  const durationMinutes = crossesMidnight ? 1440 - startMin + endMin : endMin - startMin;
  return { valid: true, crossesMidnight, durationMinutes };
}

function getIsoOffsetDate(daysDelta: number): string {
  const dt = new Date();
  dt.setDate(dt.getDate() + daysDelta);
  const y = dt.getFullYear();
  const m = String(dt.getMonth() + 1).padStart(2, "0");
  const d = String(dt.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function EnterpriseShiftsPage({
  currentUser,
  organization,
  groups,
  persons,
  onRefreshOrg,
  onOpenSessionInKiosk,
}: EnterpriseShiftsPageProps) {
  const canManage = currentUser.role === "superadmin" || currentUser.role === "org_admin";

  const [subTab, setSubTab] = useState<EnterpriseSubTab>("shifts");
  const [shifts, setShifts] = useState<WorkShift[]>([]);
  const [stats, setStats] = useState<EnterpriseStatsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [statsLoading, setStatsLoading] = useState(false);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Formulario alta / edición de turno
  const [editingShiftId, setEditingShiftId] = useState<number | null>(null);
  const [shiftName, setShiftName] = useState("");
  const [shiftCode, setShiftCode] = useState("");
  const [startTime, setStartTime] = useState("09:00");
  const [endTime, setEndTime] = useState("18:00");
  const [daysOfWeek, setDaysOfWeek] = useState<number[]>([0, 1, 2, 3, 4]);
  const [lateTolerance, setLateTolerance] = useState<string>("");
  const [earlyExitTolerance, setEarlyExitTolerance] = useState<number>(10);
  const [shiftActive, setShiftActive] = useState(true);
  const [savingShift, setSavingShift] = useState(false);

  // Asignación de empleados y departamentos
  const [empSearch, setEmpSearch] = useState("");
  const [empGroupFilter, setEmpGroupFilter] = useState<string>("");
  const [empShiftFilter, setEmpShiftFilter] = useState<string>("");
  const [selectedPersonIds, setSelectedPersonIds] = useState<number[]>([]);
  const [bulkShiftId, setBulkShiftId] = useState<string>("");

  // Filtros y ordenamiento de estadísticas
  const [dateFrom, setDateFrom] = useState<string>(() => getIsoOffsetDate(-6));
  const [dateTo, setDateTo] = useState<string>(() => getIsoOffsetDate(0));
  const [statsShiftId, setStatsShiftId] = useState<string>("");
  const [statsGroupId, setStatsGroupId] = useState<string>("");
  const [empSortField, setEmpSortField] = useState<EmployeeSortField>("attendance");
  const [empSortDir, setEmpSortDir] = useState<"asc" | "desc">("desc");

  const loadShifts = useCallback(async () => {
    setLoading(true);
    try {
      const list = await api.listWorkShifts(organization.id);
      setShifts(list);
      setErrorMsg(null);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Error cargando turnos laborales.");
    } finally {
      setLoading(false);
    }
  }, [organization.id]);

  const loadStats = useCallback(async () => {
    setStatsLoading(true);
    try {
      const data = await api.getEnterpriseStats({
        organization_id: organization.id,
        date_from: dateFrom || null,
        date_to: dateTo || null,
        work_shift_id: statsShiftId ? Number(statsShiftId) : null,
        group_id: statsGroupId ? Number(statsGroupId) : null,
      });
      setStats(data);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "No se pudieron cargar las estadísticas.");
    } finally {
      setStatsLoading(false);
    }
  }, [dateFrom, dateTo, organization.id, statsGroupId, statsShiftId]);

  useEffect(() => {
    resetShiftForm();
    setSelectedPersonIds([]);
    setStats(null);
    void loadShifts();
  }, [loadShifts, organization.id]);

  useEffect(() => {
    if (subTab === "stats") {
      void loadStats();
    }
  }, [loadStats, subTab]);

  useEffect(() => {
    if (!bulkShiftId && shifts.length > 0) {
      const firstActive = shifts.find((s) => s.is_active) ?? shifts[0];
      setBulkShiftId(String(firstActive.id));
    }
  }, [bulkShiftId, shifts]);

  function resetShiftForm() {
    setEditingShiftId(null);
    setShiftName("");
    setShiftCode("");
    setStartTime("09:00");
    setEndTime("18:00");
    setDaysOfWeek([0, 1, 2, 3, 4]);
    setLateTolerance("");
    setEarlyExitTolerance(10);
    setShiftActive(true);
  }

  function startEditShift(sh: WorkShift) {
    setEditingShiftId(sh.id);
    setShiftName(sh.name);
    setShiftCode(sh.code);
    setStartTime(sh.start_time);
    setEndTime(sh.end_time);
    setDaysOfWeek([...sh.days_of_week]);
    setLateTolerance(sh.late_tolerance_minutes !== null ? String(sh.late_tolerance_minutes) : "");
    setEarlyExitTolerance(sh.early_exit_tolerance_minutes);
    setShiftActive(sh.is_active);
    setStatusMsg(null);
    setErrorMsg(null);
  }

  function toggleDay(dayValue: number) {
    setDaysOfWeek((prev) =>
      prev.includes(dayValue)
        ? prev.filter((d) => d !== dayValue)
        : [...prev, dayValue].sort((a, b) => a - b)
    );
  }

  const preview = computeShiftPreview(startTime, endTime);

  async function handleSaveShift(e: FormEvent) {
    e.preventDefault();
    if (!shiftName.trim() || !shiftCode.trim()) return;
    if (!preview.valid) {
      setErrorMsg("La hora de entrada y salida no pueden ser iguales.");
      return;
    }
    if (daysOfWeek.length === 0) {
      setErrorMsg("Selecciona al menos un día laboral para el turno.");
      return;
    }

    setErrorMsg(null);
    setStatusMsg(null);
    setSavingShift(true);
    try {
      const parsedLateTol = lateTolerance.trim() === "" ? null : Number(lateTolerance);
      if (editingShiftId !== null) {
        await api.updateWorkShift(editingShiftId, {
          name: shiftName.trim(),
          code: shiftCode.trim().toUpperCase(),
          start_time: startTime,
          end_time: endTime,
          days_of_week: daysOfWeek,
          late_tolerance_minutes: parsedLateTol,
          early_exit_tolerance_minutes: Number(earlyExitTolerance),
          is_active: shiftActive,
        });
        setStatusMsg(`Turno "${shiftName.trim()}" actualizado correctamente.`);
      } else {
        await api.createWorkShift({
          organization_id: organization.id,
          name: shiftName.trim(),
          code: shiftCode.trim().toUpperCase(),
          start_time: startTime,
          end_time: endTime,
          days_of_week: daysOfWeek,
          late_tolerance_minutes: parsedLateTol,
          early_exit_tolerance_minutes: Number(earlyExitTolerance),
          is_active: shiftActive,
        });
        setStatusMsg(`Turno "${shiftName.trim()}" creado correctamente.`);
      }
      resetShiftForm();
      await Promise.all([loadShifts(), onRefreshOrg()]);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "No se pudo guardar el turno.");
    } finally {
      setSavingShift(false);
    }
  }

  async function handleToggleShiftActive(sh: WorkShift) {
    setErrorMsg(null);
    try {
      await api.updateWorkShift(sh.id, { is_active: !sh.is_active });
      await Promise.all([loadShifts(), onRefreshOrg()]);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "No se pudo cambiar el estado del turno.");
    }
  }

  async function handleDeleteShift(sh: WorkShift) {
    if (
      !window.confirm(
        `¿Eliminar el turno "${sh.name} (${sh.code})"? Los empleados y áreas vinculados quedarán sin este turno asignado.`
      )
    ) {
      return;
    }
    setErrorMsg(null);
    try {
      await api.deleteWorkShift(sh.id);
      if (editingShiftId === sh.id) resetShiftForm();
      setStatusMsg(`Turno "${sh.name}" eliminado.`);
      await Promise.all([loadShifts(), onRefreshOrg()]);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "No se pudo eliminar el turno.");
    }
  }

  async function handleStartShiftInKiosk(shiftId: number) {
    setErrorMsg(null);
    try {
      const session = await api.startWorkShiftSession(shiftId, {
        session_date: getIsoOffsetDate(0),
      });
      await onRefreshOrg();
      onOpenSessionInKiosk(session.id);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "No se pudo abrir la jornada del turno.");
    }
  }

  async function handleGenerateTodaySessions() {
    setErrorMsg(null);
    setStatusMsg(null);
    try {
      const res = await api.generateEnterpriseSessions({
        organization_id: organization.id,
        target_date: getIsoOffsetDate(0),
      });
      setStatusMsg(
        `Jornadas del ${res.target_date}: ${res.created_count} nuevas, ${res.existing_count} existentes.`
      );
      await onRefreshOrg();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "No se pudieron generar las jornadas.");
    }
  }

  async function handleGroupDefaultShiftChange(groupId: number, shiftIdStr: string) {
    setErrorMsg(null);
    try {
      await api.updateGroup(groupId, {
        default_work_shift_id: shiftIdStr ? Number(shiftIdStr) : null,
      });
      await Promise.all([loadShifts(), onRefreshOrg()]);
      setStatusMsg("Turno por defecto del departamento actualizado.");
    } catch (err) {
      setErrorMsg(
        err instanceof Error ? err.message : "No se pudo actualizar el turno del departamento."
      );
    }
  }

  async function handlePersonDirectShiftChange(personId: number, shiftIdStr: string) {
    setErrorMsg(null);
    try {
      await api.updatePerson(personId, {
        work_shift_id: shiftIdStr ? Number(shiftIdStr) : null,
      });
      await Promise.all([loadShifts(), onRefreshOrg()]);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "No se pudo asignar el turno al empleado.");
    }
  }

  async function handleBulkAssign(clearShift: boolean) {
    if (selectedPersonIds.length === 0) return;
    const targetShiftId = clearShift
      ? shifts[0]?.id
      : bulkShiftId
        ? Number(bulkShiftId)
        : shifts[0]?.id;
    if (!targetShiftId) {
      setErrorMsg("Crea primero al menos un turno en el catálogo.");
      return;
    }

    setErrorMsg(null);
    try {
      const res = await api.assignWorkShiftPersons(targetShiftId, {
        person_ids: selectedPersonIds,
        clear_shift: clearShift,
      });
      setSelectedPersonIds([]);
      setStatusMsg(
        clearShift
          ? `Se removió el turno directo en ${res.updated_count} empleado(s) (ahora heredan su departamento).`
          : `Se asignó "${res.work_shift_name}" a ${res.updated_count} empleado(s).`
      );
      await Promise.all([loadShifts(), onRefreshOrg()]);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Error en asignación masiva.");
    }
  }

  const groupNameMap = new Map(groups.map((g) => [g.id, g.name]));
  const filteredPersons = persons.filter((p) => {
    if (empGroupFilter && !p.group_ids.includes(Number(empGroupFilter))) {
      return false;
    }
    if (empShiftFilter === "__none__" && p.effective_work_shift_id !== null) {
      return false;
    }
    if (
      empShiftFilter &&
      empShiftFilter !== "__none__" &&
      String(p.effective_work_shift_id ?? "") !== empShiftFilter
    ) {
      return false;
    }
    const q = empSearch.trim().toLowerCase();
    if (!q) return true;
    return p.full_name.toLowerCase().includes(q) || p.external_id.toLowerCase().includes(q);
  });

  function togglePersonSelection(personId: number) {
    setSelectedPersonIds((prev) =>
      prev.includes(personId) ? prev.filter((id) => id !== personId) : [...prev, personId]
    );
  }

  function toggleSelectAllVisible() {
    const visibleIds = filteredPersons.map((p) => p.id);
    const allSelected =
      visibleIds.length > 0 && visibleIds.every((id) => selectedPersonIds.includes(id));
    if (allSelected) {
      setSelectedPersonIds((prev) => prev.filter((id) => !visibleIds.includes(id)));
    } else {
      setSelectedPersonIds((prev) => Array.from(new Set([...prev, ...visibleIds])));
    }
  }

  const sortedEmployeeStats = stats
    ? [...stats.by_employee].sort((a, b) => {
        const dir = empSortDir === "asc" ? 1 : -1;
        switch (empSortField) {
          case "name":
            return a.full_name.localeCompare(b.full_name, "es") * dir;
          case "shift":
            return (
              (a.shift_name ?? "zzz").localeCompare(b.shift_name ?? "zzz", "es") * dir
            );
          case "absences":
            return (a.absent_days - b.absent_days) * dir;
          case "worked":
            return (a.total_worked_minutes - b.total_worked_minutes) * dir;
          case "attendance":
          default:
            return (a.attendance_rate - b.attendance_rate) * dir;
        }
      })
    : [];

  function handleSortEmployees(field: EmployeeSortField) {
    if (empSortField === field) {
      setEmpSortDir((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setEmpSortField(field);
      setEmpSortDir(field === "name" || field === "shift" ? "asc" : "desc");
    }
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight flex items-center gap-2.5">
            <Briefcase className="w-6 h-6 text-indigo-400" />
            Turnos y Jornadas Empresariales
          </h2>
          <p className="text-sm text-slate-400 mt-0.5">
            Configura turnos diurnos o nocturnos, asígnalos a áreas y empleados y audita puntualidad y horas trabajadas.
          </p>
        </div>

        <button
          type="button"
          onClick={() => void handleGenerateTodaySessions()}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-emerald-600 hover:bg-emerald-500 text-white"
        >
          <CalendarCheck className="w-4 h-4" />
          Generar jornadas de hoy
        </button>
      </div>

      {/* Sub-pestañas */}
      <div className="flex flex-wrap gap-2 border-b border-slate-800 pb-3">
        {[
          { id: "shifts" as const, label: "Catálogo de Turnos", icon: Clock },
          { id: "assignments" as const, label: "Asignación a Personal y Áreas", icon: Users },
          { id: "stats" as const, label: "Estadísticas de Jornada", icon: BarChart3 },
        ].map((tab) => {
          const Icon = tab.icon;
          const active = subTab === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => setSubTab(tab.id)}
              className={`inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                active
                  ? "bg-indigo-600 text-white"
                  : "bg-slate-900 border border-slate-800 text-slate-300 hover:bg-slate-800"
              }`}
            >
              <Icon className="w-4 h-4" />
              {tab.label}
            </button>
          );
        })}
      </div>

      {statusMsg && (
        <div className="rounded-xl bg-emerald-500/15 border border-emerald-500/40 px-4 py-2.5 text-xs text-emerald-200 flex items-center justify-between gap-2">
          <span>{statusMsg}</span>
          <button type="button" onClick={() => setStatusMsg(null)} className="text-emerald-300 hover:underline">
            Cerrar
          </button>
        </div>
      )}
      {errorMsg && (
        <div className="rounded-xl bg-red-500/15 border border-red-500/40 px-4 py-2.5 text-xs text-red-200 flex items-center justify-between gap-2">
          <span>{errorMsg}</span>
          <button type="button" onClick={() => setErrorMsg(null)} className="text-red-300 hover:underline">
            Cerrar
          </button>
        </div>
      )}

      {/* Sub-pestaña 1: Catálogo de Turnos */}
      {subTab === "shifts" && (
        <div className="space-y-6">
          {canManage && (
            <form
              onSubmit={handleSaveShift}
              className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="font-semibold text-base">
                  {editingShiftId !== null ? "Editar Turno Laboral" : "Nuevo Turno Laboral"}
                </h3>
                {editingShiftId !== null && (
                  <button
                    type="button"
                    onClick={resetShiftForm}
                    className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-white"
                  >
                    <X className="w-3.5 h-3.5" />
                    Cancelar edición
                  </button>
                )}
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Nombre del turno</label>
                  <input
                    type="text"
                    required
                    value={shiftName}
                    onChange={(e) => setShiftName(e.target.value)}
                    placeholder="Ej. Matutino Planta / Nocturno"
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Código único</label>
                  <input
                    type="text"
                    required
                    value={shiftCode}
                    onChange={(e) => setShiftCode(e.target.value.toUpperCase())}
                    placeholder="Ej. MAT-01"
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm uppercase"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Hora de entrada</label>
                  <input
                    type="time"
                    required
                    value={startTime}
                    onChange={(e) => setStartTime(e.target.value)}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Hora de salida</label>
                  <input
                    type="time"
                    required
                    value={endTime}
                    onChange={(e) => setEndTime(e.target.value)}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                  />
                </div>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-3 bg-slate-950/60 border border-slate-800 rounded-xl px-3.5 py-2.5 text-xs">
                {!preview.valid ? (
                  <span className="text-red-300">
                    La hora de entrada y salida deben ser distintas.
                  </span>
                ) : preview.crossesMidnight ? (
                  <span className="inline-flex items-center gap-2 text-indigo-300 font-medium">
                    <Moon className="w-4 h-4 text-indigo-400" />
                    Turno nocturno (cruza medianoche: la salida se evalúa al día siguiente) · Duración:{" "}
                    <strong>{formatDuration(preview.durationMinutes)}</strong>
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-2 text-emerald-300 font-medium">
                    <Sun className="w-4 h-4 text-emerald-400" />
                    Turno diurno/mixto (mismo día) · Duración:{" "}
                    <strong>{formatDuration(preview.durationMinutes)}</strong>
                  </span>
                )}
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-end">
                <div className="lg:col-span-1">
                  <div className="flex items-center justify-between mb-1.5">
                    <label className="text-xs text-slate-400">Días laborales</label>
                    <div className="flex gap-1.5 text-[11px]">
                      <button
                        type="button"
                        onClick={() => setDaysOfWeek([0, 1, 2, 3, 4])}
                        className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300"
                      >
                        L-V
                      </button>
                      <button
                        type="button"
                        onClick={() => setDaysOfWeek([0, 1, 2, 3, 4, 5])}
                        className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300"
                      >
                        L-S
                      </button>
                      <button
                        type="button"
                        onClick={() => setDaysOfWeek([0, 1, 2, 3, 4, 5, 6])}
                        className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300"
                      >
                        Todos
                      </button>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {WEEKDAYS.map((d) => {
                      const active = daysOfWeek.includes(d.value);
                      return (
                        <button
                          key={d.value}
                          type="button"
                          onClick={() => toggleDay(d.value)}
                          title={d.label}
                          className={`px-2.5 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${
                            active
                              ? "bg-indigo-600 border-indigo-500 text-white"
                              : "bg-slate-800 border-slate-700 text-slate-400 hover:text-white"
                          }`}
                        >
                          {d.short}
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div>
                  <label className="block text-xs text-slate-400 mb-1">
                    Tolerancia retardo (min, vacío = usar org: {organization.late_tolerance_minutes}m)
                  </label>
                  <input
                    type="number"
                    min={0}
                    max={180}
                    value={lateTolerance}
                    onChange={(e) => setLateTolerance(e.target.value)}
                    placeholder={`Heredar (${organization.late_tolerance_minutes} min)`}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                  />
                </div>

                <div className="flex items-end gap-3">
                  <div className="flex-1">
                    <label className="block text-xs text-slate-400 mb-1">
                      Tolerancia salida anticipada (min)
                    </label>
                    <input
                      type="number"
                      min={0}
                      max={180}
                      required
                      value={earlyExitTolerance}
                      onChange={(e) => setEarlyExitTolerance(Number(e.target.value))}
                      className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                    />
                  </div>
                  <button
                    type="submit"
                    disabled={savingShift || !preview.valid}
                    className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-semibold bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white whitespace-nowrap"
                  >
                    <Plus className="w-4 h-4" />
                    {editingShiftId !== null ? "Guardar cambios" : "Crear turno"}
                  </button>
                </div>
              </div>

              {editingShiftId !== null && (
                <label className="inline-flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={shiftActive}
                    onChange={(e) => setShiftActive(e.target.checked)}
                    className="rounded border-slate-600 bg-slate-800 text-indigo-600"
                  />
                  Turno activo para generación de jornadas
                </label>
              )}
            </form>
          )}

          {loading ? (
            <p className="text-sm text-slate-400 py-8 text-center">Cargando turnos...</p>
          ) : shifts.length === 0 ? (
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-8 text-center text-sm text-slate-400">
              No hay turnos configurados en esta empresa. Crea el primero arriba (por ejemplo{" "}
              <span className="text-slate-200">Matutino 08:00–16:00</span> o{" "}
              <span className="text-slate-200">Nocturno 22:00–06:00</span>).
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {shifts.map((sh) => (
                <div
                  key={sh.id}
                  className={`bg-slate-900 border rounded-2xl p-5 space-y-3 ${
                    sh.is_active ? "border-slate-800" : "border-slate-800/60 opacity-75"
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h4 className="font-semibold text-base">{sh.name}</h4>
                        <span className="px-2 py-0.5 rounded-full text-[11px] font-mono bg-slate-800 text-slate-300 border border-slate-700">
                          {sh.code}
                        </span>
                        {sh.crosses_midnight ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] bg-indigo-500/15 text-indigo-300 border border-indigo-500/30">
                            <Moon className="w-3 h-3" />
                            Cruza medianoche
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
                            <Sun className="w-3 h-3" />
                            Diurno
                          </span>
                        )}
                        {!sh.is_active && (
                          <span className="px-2 py-0.5 rounded-full text-[11px] bg-amber-500/15 text-amber-300 border border-amber-500/30">
                            Inactivo
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-slate-200 font-mono mt-1.5">
                        {sh.start_time} → {sh.end_time}{" "}
                        <span className="text-xs text-slate-400 font-sans">
                          ({formatDuration(sh.expected_duration_minutes)})
                        </span>
                      </p>
                    </div>

                    {canManage && (
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => startEditShift(sh)}
                          className="p-1.5 rounded-lg text-slate-400 hover:text-indigo-300 hover:bg-indigo-500/10"
                          title="Editar turno"
                        >
                          <Pencil className="w-4 h-4" />
                        </button>
                        <button
                          type="button"
                          onClick={() => void handleDeleteShift(sh)}
                          className="p-1.5 rounded-lg text-slate-400 hover:text-red-400 hover:bg-red-500/10"
                          title="Eliminar turno"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    )}
                  </div>

                  <div className="flex flex-wrap gap-1">
                    {WEEKDAYS.map((d) => {
                      const activeDay = sh.days_of_week.includes(d.value);
                      return (
                        <span
                          key={d.value}
                          className={`px-2 py-0.5 rounded text-[11px] font-medium ${
                            activeDay
                              ? "bg-indigo-600/20 text-indigo-300 border border-indigo-500/30"
                              : "bg-slate-800/60 text-slate-600"
                          }`}
                        >
                          {d.mini}
                        </span>
                      );
                    })}
                  </div>

                  <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-slate-800 text-xs text-slate-400">
                    <div className="space-y-0.5">
                      <p>
                        Retardo:{" "}
                        <strong className="text-slate-200">
                          {sh.effective_late_tolerance_minutes} min
                        </strong>
                        {sh.late_tolerance_minutes === null ? " (org)" : ""} · Salida ant.:{" "}
                        <strong className="text-slate-200">
                          {sh.early_exit_tolerance_minutes} min
                        </strong>
                      </p>
                      <p>
                        <strong className="text-slate-200">{sh.assigned_employees_count}</strong>{" "}
                        empleados directos ·{" "}
                        <strong className="text-slate-200">{sh.default_groups_count}</strong>{" "}
                        áreas por defecto
                      </p>
                    </div>

                    <div className="flex items-center gap-2">
                      {canManage && (
                        <button
                          type="button"
                          onClick={() => void handleToggleShiftActive(sh)}
                          className="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 text-xs"
                        >
                          {sh.is_active ? "Pausar" : "Activar"}
                        </button>
                      )}
                      {sh.is_active && (
                        <button
                          type="button"
                          onClick={() => void handleStartShiftInKiosk(sh.id)}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold"
                        >
                          <ScanFace className="w-3.5 h-3.5" />
                          Abrir en Kiosco
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Sub-pestaña 2: Asignación a Personal y Departamentos */}
      {subTab === "assignments" && (
        <div className="space-y-6">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3">
            <div>
              <h3 className="font-semibold text-base">Turno por Defecto por Área / Departamento</h3>
              <p className="text-xs text-slate-400">
                Todo empleado sin turno individual asignado hereda automáticamente el turno del primer departamento al que pertenezca.
              </p>
            </div>
            {groups.length === 0 ? (
              <p className="text-xs text-slate-500">No hay departamentos registrados.</p>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {groups.map((g) => (
                  <div
                    key={g.id}
                    className="rounded-xl bg-slate-800/60 border border-slate-800 p-3.5 space-y-2"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-sm font-medium truncate">
                        {g.name} <span className="text-xs text-slate-400">({g.code})</span>
                      </p>
                      <span className="text-[11px] text-slate-400 shrink-0">
                        {g.members_count} pers.
                      </span>
                    </div>
                    <select
                      disabled={!canManage}
                      value={g.default_work_shift_id ? String(g.default_work_shift_id) : ""}
                      onChange={(e) => void handleGroupDefaultShiftChange(g.id, e.target.value)}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs disabled:opacity-60"
                    >
                      <option value="">Sin turno por defecto</option>
                      {shifts.map((sh) => (
                        <option key={sh.id} value={sh.id}>
                          {sh.name} ({sh.start_time}-{sh.end_time})
                        </option>
                      ))}
                    </select>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="font-semibold text-base">Asignación de Turno por Empleado</h3>
                <p className="text-xs text-slate-400">
                  Asigna individualmente o marca varios empleados para asignar/limpiar en lote.
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <input
                  type="text"
                  value={empSearch}
                  onChange={(e) => setEmpSearch(e.target.value)}
                  placeholder="Buscar empleado o ID..."
                  className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-xs"
                />
                <select
                  value={empGroupFilter}
                  onChange={(e) => setEmpGroupFilter(e.target.value)}
                  className="bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs"
                >
                  <option value="">Todos los departamentos</option>
                  {groups.map((g) => (
                    <option key={g.id} value={g.id}>
                      {g.name}
                    </option>
                  ))}
                </select>
                <select
                  value={empShiftFilter}
                  onChange={(e) => setEmpShiftFilter(e.target.value)}
                  className="bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs"
                >
                  <option value="">Todos los turnos</option>
                  <option value="__none__">Sin turno asignado</option>
                  {shifts.map((sh) => (
                    <option key={sh.id} value={sh.id}>
                      {sh.name} ({sh.code})
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {canManage && selectedPersonIds.length > 0 && shifts.length > 0 && (
              <div className="rounded-xl bg-indigo-500/10 border border-indigo-500/40 px-4 py-3 flex flex-wrap items-center justify-between gap-3">
                <span className="text-xs font-medium text-indigo-200">
                  {selectedPersonIds.length} empleado(s) seleccionado(s)
                </span>
                <div className="flex flex-wrap items-center gap-2">
                  <select
                    value={bulkShiftId}
                    onChange={(e) => setBulkShiftId(e.target.value)}
                    className="bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs"
                  >
                    {shifts.map((sh) => (
                      <option key={sh.id} value={sh.id}>
                        {sh.name} ({sh.start_time}-{sh.end_time})
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={() => void handleBulkAssign(false)}
                    className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold"
                  >
                    Asignar turno
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleBulkAssign(true)}
                    className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 text-xs"
                  >
                    Quitar turno directo (heredar)
                  </button>
                </div>
              </div>
            )}

            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead className="text-xs uppercase text-slate-400 border-b border-slate-800">
                  <tr>
                    {canManage && (
                      <th className="py-2 pr-2 w-8">
                        <input
                          type="checkbox"
                          checked={
                            filteredPersons.length > 0 &&
                            filteredPersons.every((p) => selectedPersonIds.includes(p.id))
                          }
                          onChange={toggleSelectAllVisible}
                          className="rounded border-slate-600 bg-slate-800 text-indigo-600"
                          title="Seleccionar visibles"
                        />
                      </th>
                    )}
                    <th className="py-2 pr-3">Empleado</th>
                    <th className="py-2 px-3">Departamentos</th>
                    <th className="py-2 px-3">Turno Efectivo</th>
                    <th className="py-2 pl-3">Turno Directo</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/70">
                  {filteredPersons.length === 0 ? (
                    <tr>
                      <td colSpan={canManage ? 5 : 4} className="py-6 text-center text-xs text-slate-500">
                        No hay empleados que coincidan con el filtro.
                      </td>
                    </tr>
                  ) : (
                    filteredPersons.map((p) => (
                      <tr key={p.id} className="hover:bg-slate-800/30">
                        {canManage && (
                          <td className="py-2.5 pr-2">
                            <input
                              type="checkbox"
                              checked={selectedPersonIds.includes(p.id)}
                              onChange={() => togglePersonSelection(p.id)}
                              className="rounded border-slate-600 bg-slate-800 text-indigo-600"
                            />
                          </td>
                        )}
                        <td className="py-2.5 pr-3">
                          <p className="font-medium leading-tight">{p.full_name}</p>
                          <p className="text-xs text-slate-500">{p.external_id}</p>
                        </td>
                        <td className="py-2.5 px-3 text-xs text-slate-300">
                          {p.group_ids.length > 0
                            ? p.group_ids
                                .map((gid) => groupNameMap.get(gid) ?? `#${gid}`)
                                .join(", ")
                            : "—"}
                        </td>
                        <td className="py-2.5 px-3 text-xs">
                          {p.effective_work_shift_name ? (
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className="font-medium text-slate-100">
                                {p.effective_work_shift_name}
                              </span>
                              <span
                                className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${
                                  p.shift_source === "direct"
                                    ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/30"
                                    : "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
                                }`}
                              >
                                {p.shift_source === "direct" ? "Directo" : "Heredado de área"}
                              </span>
                            </div>
                          ) : (
                            <span className="px-2 py-0.5 rounded-full text-[10px] bg-slate-800 text-slate-400">
                              Sin turno
                            </span>
                          )}
                        </td>
                        <td className="py-2.5 pl-3">
                          <select
                            disabled={!canManage}
                            value={p.work_shift_id ? String(p.work_shift_id) : ""}
                            onChange={(e) =>
                              void handlePersonDirectShiftChange(p.id, e.target.value)
                            }
                            className="bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs disabled:opacity-60"
                          >
                            <option value="">(Heredar de departamento / Sin turno)</option>
                            {shifts.map((sh) => (
                              <option key={sh.id} value={sh.id}>
                                {sh.name} ({sh.start_time}-{sh.end_time})
                              </option>
                            ))}
                          </select>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Sub-pestaña 3: Estadísticas de Jornada */}
      {subTab === "stats" && (
        <div className="space-y-6">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 flex flex-wrap items-end justify-between gap-3">
            <div className="flex flex-wrap items-center gap-1.5">
              <button
                type="button"
                onClick={() => {
                  const today = getIsoOffsetDate(0);
                  setDateFrom(today);
                  setDateTo(today);
                }}
                className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs"
              >
                Hoy
              </button>
              <button
                type="button"
                onClick={() => {
                  setDateFrom(getIsoOffsetDate(-6));
                  setDateTo(getIsoOffsetDate(0));
                }}
                className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs"
              >
                Últimos 7 días
              </button>
              <button
                type="button"
                onClick={() => {
                  setDateFrom(getIsoOffsetDate(-29));
                  setDateTo(getIsoOffsetDate(0));
                }}
                className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs"
              >
                Últimos 30 días
              </button>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 w-full lg:w-auto">
              <div>
                <label className="block text-[11px] text-slate-400 mb-1">Desde</label>
                <input
                  type="date"
                  value={dateFrom}
                  onChange={(e) => setDateFrom(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs"
                />
              </div>
              <div>
                <label className="block text-[11px] text-slate-400 mb-1">Hasta</label>
                <input
                  type="date"
                  value={dateTo}
                  onChange={(e) => setDateTo(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs"
                />
              </div>
              <div>
                <label className="block text-[11px] text-slate-400 mb-1">Turno</label>
                <select
                  value={statsShiftId}
                  onChange={(e) => setStatsShiftId(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs"
                >
                  <option value="">Todos los turnos</option>
                  {shifts.map((sh) => (
                    <option key={sh.id} value={sh.id}>
                      {sh.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-[11px] text-slate-400 mb-1">Departamento</label>
                <select
                  value={statsGroupId}
                  onChange={(e) => setStatsGroupId(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs"
                >
                  <option value="">Todos</option>
                  {groups.map((g) => (
                    <option key={g.id} value={g.id}>
                      {g.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          {statsLoading || !stats ? (
            <p className="text-sm text-slate-400 py-8 text-center">Calculando métricas...</p>
          ) : (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4">
                  <p className="text-xs text-slate-400 uppercase">Turnos Activos</p>
                  <p className="text-2xl font-bold mt-1">
                    {stats.summary.active_shifts}{" "}
                    <span className="text-sm font-normal text-slate-400">
                      / {stats.summary.total_shifts}
                    </span>
                  </p>
                </div>
                <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4">
                  <p className="text-xs text-slate-400 uppercase">Empleados con Turno</p>
                  <p className="text-2xl font-bold mt-1">
                    {stats.summary.assigned_employees}{" "}
                    <span className="text-sm font-normal text-slate-400">
                      / {stats.summary.total_employees}
                    </span>
                  </p>
                </div>
                <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4">
                  <p className="text-xs text-slate-400 uppercase">Asistencia del Periodo</p>
                  <p className="text-2xl font-bold mt-1 text-emerald-300">
                    {stats.summary.attendance_rate.toFixed(1)}%
                  </p>
                  <p className="text-[11px] text-slate-500 mt-0.5">
                    {stats.summary.present_days} / {stats.summary.scheduled_employee_days} jornadas
                  </p>
                </div>
                <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4">
                  <p className="text-xs text-slate-400 uppercase">Puntualidad</p>
                  <p className="text-2xl font-bold mt-1 text-indigo-300">
                    {stats.summary.punctuality_rate.toFixed(1)}%
                  </p>
                  <p className="text-[11px] text-slate-500 mt-0.5">
                    Total trabajado: {formatDuration(stats.summary.total_worked_minutes)}
                  </p>
                </div>
              </div>

              <div className="flex flex-wrap gap-2 text-xs">
                <span className="px-3 py-1 rounded-full bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
                  A tiempo: <strong>{stats.summary.on_time_days}</strong>
                </span>
                <span className="px-3 py-1 rounded-full bg-amber-500/15 text-amber-300 border border-amber-500/30">
                  Retardos: <strong>{stats.summary.late_days}</strong>
                </span>
                <span className="px-3 py-1 rounded-full bg-orange-500/15 text-orange-300 border border-orange-500/30">
                  Salidas anticipadas: <strong>{stats.summary.early_exit_days}</strong>
                </span>
                <span className="px-3 py-1 rounded-full bg-red-500/15 text-red-300 border border-red-500/30">
                  Faltas: <strong>{stats.summary.absent_days}</strong>
                </span>
                <span className="px-3 py-1 rounded-full bg-slate-800 text-slate-300 border border-slate-700">
                  Sin salida registrada: <strong>{stats.summary.missing_checkout_days}</strong>
                </span>
              </div>

              {/* Resumen por Turno */}
              <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3">
                <h3 className="font-semibold text-base">Resumen por Turno</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm text-left">
                    <thead className="text-xs uppercase text-slate-400 border-b border-slate-800">
                      <tr>
                        <th className="py-2 pr-3">Turno</th>
                        <th className="py-2 px-2">Horario</th>
                        <th className="py-2 px-2 text-right">Empl.</th>
                        <th className="py-2 px-2 text-right">Prog.</th>
                        <th className="py-2 px-2 text-right">Asist.</th>
                        <th className="py-2 px-2 text-right">Retardos</th>
                        <th className="py-2 px-2 text-right">Sal. Ant.</th>
                        <th className="py-2 px-2 text-right">Faltas</th>
                        <th className="py-2 px-2 text-right">Prom.</th>
                        <th className="py-2 pl-2 text-right">Asist. / Punt.</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/70">
                      {stats.by_shift.map((row) => (
                        <tr key={row.work_shift_id ?? "unassigned"} className="hover:bg-slate-800/30">
                          <td className="py-2.5 pr-3 font-medium">
                            {row.shift_name}
                            {row.shift_code && (
                              <span className="ml-1.5 text-xs text-slate-400">
                                ({row.shift_code})
                              </span>
                            )}
                          </td>
                          <td className="py-2.5 px-2 text-xs text-slate-300">
                            {row.start_time && row.end_time
                              ? `${row.start_time}-${row.end_time}${row.crosses_midnight ? " 🌙" : ""}`
                              : "—"}
                          </td>
                          <td className="py-2.5 px-2 text-right text-xs">{row.employees_count}</td>
                          <td className="py-2.5 px-2 text-right text-xs">{row.scheduled_days}</td>
                          <td className="py-2.5 px-2 text-right text-xs">{row.present_days}</td>
                          <td className="py-2.5 px-2 text-right text-xs text-amber-300">
                            {row.late_days}
                          </td>
                          <td className="py-2.5 px-2 text-right text-xs text-orange-300">
                            {row.early_exit_days}
                          </td>
                          <td className="py-2.5 px-2 text-right text-xs text-red-300">
                            {row.absent_days}
                          </td>
                          <td className="py-2.5 px-2 text-right text-xs text-slate-300">
                            {row.avg_worked_minutes > 0 ? formatDuration(row.avg_worked_minutes) : "—"}
                          </td>
                          <td className="py-2.5 pl-2 text-right text-xs font-semibold">
                            <span className="text-emerald-300">{row.attendance_rate}%</span>
                            <span className="text-slate-500"> / </span>
                            <span className="text-indigo-300">{row.punctuality_rate}%</span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Detalle por Empleado */}
              <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="font-semibold text-base">Detalle por Empleado</h3>
                  <div className="flex flex-wrap items-center gap-1.5 text-xs">
                    <span className="text-slate-400 mr-1">Ordenar por:</span>
                    {(
                      [
                        { id: "attendance", label: "% Asistencia" },
                        { id: "name", label: "Nombre" },
                        { id: "shift", label: "Turno" },
                        { id: "absences", label: "Faltas" },
                        { id: "worked", label: "Horas trabajadas" },
                      ] as const
                    ).map((opt) => (
                      <button
                        key={opt.id}
                        type="button"
                        onClick={() => handleSortEmployees(opt.id)}
                        className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border ${
                          empSortField === opt.id
                            ? "bg-indigo-600/20 border-indigo-500/40 text-indigo-300"
                            : "bg-slate-800 border-slate-700 text-slate-300"
                        }`}
                      >
                        {opt.label}
                        {empSortField === opt.id && <ArrowUpDown className="w-3 h-3" />}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-sm text-left">
                    <thead className="text-xs uppercase text-slate-400 border-b border-slate-800">
                      <tr>
                        <th className="py-2 pr-3">Empleado</th>
                        <th className="py-2 px-2">Turno</th>
                        <th className="py-2 px-2 text-right">Prog.</th>
                        <th className="py-2 px-2 text-right">Asist.</th>
                        <th className="py-2 px-2 text-right">Retardos</th>
                        <th className="py-2 px-2 text-right">Sal. Ant.</th>
                        <th className="py-2 px-2 text-right">Faltas</th>
                        <th className="py-2 px-2 text-right">Trabajado</th>
                        <th className="py-2 pl-2 text-right">Asist.</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/70">
                      {sortedEmployeeStats.map((emp) => (
                        <tr key={emp.person_id} className="hover:bg-slate-800/30">
                          <td className="py-2.5 pr-3">
                            <p className="font-medium leading-tight">{emp.full_name}</p>
                            <p className="text-[11px] text-slate-500">
                              {emp.external_id}
                              {emp.group_names.length > 0 ? ` · ${emp.group_names.join(", ")}` : ""}
                            </p>
                          </td>
                          <td className="py-2.5 px-2 text-xs">
                            {emp.shift_name ? (
                              <span>
                                {emp.shift_name}{" "}
                                <span className="text-[10px] text-slate-400">
                                  ({emp.shift_source === "direct" ? "directo" : "área"})
                                </span>
                              </span>
                            ) : (
                              <span className="text-slate-500">Sin turno</span>
                            )}
                          </td>
                          <td className="py-2.5 px-2 text-right text-xs">{emp.scheduled_days}</td>
                          <td className="py-2.5 px-2 text-right text-xs">{emp.present_days}</td>
                          <td className="py-2.5 px-2 text-right text-xs text-amber-300">
                            {emp.late_days}
                            {emp.total_late_minutes > 0 ? ` (${emp.total_late_minutes}m)` : ""}
                          </td>
                          <td className="py-2.5 px-2 text-right text-xs text-orange-300">
                            {emp.early_exit_days}
                            {emp.total_early_exit_minutes > 0
                              ? ` (${emp.total_early_exit_minutes}m)`
                              : ""}
                          </td>
                          <td className="py-2.5 px-2 text-right text-xs text-red-300">
                            {emp.absent_days}
                          </td>
                          <td className="py-2.5 px-2 text-right text-xs text-slate-200">
                            {formatDuration(emp.total_worked_minutes)}
                          </td>
                          <td className="py-2.5 pl-2 text-right text-xs font-semibold text-emerald-300">
                            {emp.attendance_rate}%
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
