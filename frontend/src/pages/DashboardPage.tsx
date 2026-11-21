import { useEffect, useState, type FormEvent } from "react";
import {
  Activity,
  Briefcase,
  CheckCircle2,
  Download,
  Plus,
  ScanFace,
  ShieldCheck,
  Users,
} from "lucide-react";
import { PasswordInput } from "../components/PasswordInput";
import { ACADEMIC_PERIOD_OPTIONS } from "../lib/academicPeriods";
import { api } from "../lib/api";
import type { NavTab } from "../components/Layout";
import type {
  AcademicPeriodType,
  AttendanceEvent,
  AuthUser,
  HealthResponse,
  Organization,
  OrgMode,
  Person,
} from "../types/api";

interface DashboardPageProps {
  currentUser: AuthUser;
  organization: Organization;
  health: HealthResponse | null;
  persons: Person[];
  events: AttendanceEvent[];
  onRefreshAll: () => Promise<void>;
  onOrganizationCreated: (orgId: number) => Promise<void>;
  onNavigateTab: (tab: NavTab) => void;
}

export function DashboardPage({
  currentUser,
  organization,
  health,
  persons,
  events,
  onRefreshAll,
  onOrganizationCreated,
  onNavigateTab,
}: DashboardPageProps) {
  const [mode, setMode] = useState<OrgMode>(organization.mode);
  const [academicPeriodType, setAcademicPeriodType] = useState<AcademicPeriodType>(
    organization.academic_period_type
  );
  const [periodAuthSecret, setPeriodAuthSecret] = useState("");
  const [tolerance, setTolerance] = useState<number>(organization.late_tolerance_minutes);
  const [cooldown, setCooldown] = useState<number>(organization.cooldown_seconds);
  const [storeAvatar, setStoreAvatar] = useState<boolean>(organization.store_avatar_by_default);
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);

  const [showNewOrg, setShowNewOrg] = useState(false);
  const [newOrgName, setNewOrgName] = useState("");
  const [newOrgMode, setNewOrgMode] = useState<OrgMode>("education");
  const [newOrgPeriodType, setNewOrgPeriodType] = useState<AcademicPeriodType>("semestral");
  const [createInitialAdmin, setCreateInitialAdmin] = useState(true);
  const [adminFullName, setAdminFullName] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const [orgFormError, setOrgFormError] = useState<string | null>(null);
  const [creatingOrg, setCreatingOrg] = useState(false);

  const isSuperadmin = currentUser.role === "superadmin";
  const canEditOrg = isSuperadmin || currentUser.role === "org_admin";

  useEffect(() => {
    setMode(organization.mode);
    setAcademicPeriodType(organization.academic_period_type ?? "semestral");
    setPeriodAuthSecret("");
    setTolerance(organization.late_tolerance_minutes);
    setCooldown(organization.cooldown_seconds);
    setStoreAvatar(organization.store_avatar_by_default);
    setFeedback(null);
  }, [organization]);

  const activePersons = persons.filter((p) => p.is_active);
  const enrolledPersons = activePersons.filter((p) => p.embeddings_count > 0);
  const coveragePct =
    activePersons.length > 0
      ? Math.round((enrolledPersons.length / activePersons.length) * 100)
      : 0;

  async function handleSaveConfig(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setFeedback(null);
    const periodChanged =
      mode === "education" &&
      academicPeriodType !== (organization.academic_period_type ?? "semestral");
    try {
      await api.updateOrganization(organization.id, {
        mode,
        academic_period_type: academicPeriodType,
        late_tolerance_minutes: Number(tolerance),
        cooldown_seconds: Number(cooldown),
        store_avatar_by_default: storeAvatar,
        ...(periodChanged ? { authorization_secret: periodAuthSecret } : {}),
      });
      setPeriodAuthSecret("");
      await onRefreshAll();
      setFeedback("Configuración actualizada correctamente.");
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "Error al guardar.");
    } finally {
      setSaving(false);
    }
  }

  async function handleCreateOrg(e: FormEvent) {
    e.preventDefault();
    if (!newOrgName.trim()) return;
    setOrgFormError(null);
    setCreatingOrg(true);
    try {
      const created = await api.createOrganization({
        name: newOrgName.trim(),
        mode: newOrgMode,
        academic_period_type: newOrgMode === "education" ? newOrgPeriodType : "semestral",
        admin_user: createInitialAdmin
          ? {
              full_name: adminFullName.trim(),
              email: adminEmail.trim(),
              password: adminPassword,
            }
          : null,
      });
      setNewOrgName("");
      setAdminFullName("");
      setAdminEmail("");
      setAdminPassword("");
      setShowNewOrg(false);
      await onOrganizationCreated(created.id);
    } catch (err) {
      setOrgFormError(err instanceof Error ? err.message : "No se pudo crear la organización.");
    } finally {
      setCreatingOrg(false);
    }
  }

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Panel General</h2>
          <p className="text-sm text-slate-400 mt-0.5">
            Resumen operativo y configuración biométrica de {organization.name}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {isSuperadmin && (
            <button
              type="button"
              onClick={() => setShowNewOrg((v) => !v)}
              className="inline-flex items-center gap-2 px-3.5 py-2 rounded-lg text-sm font-medium bg-slate-800 hover:bg-slate-700 border border-slate-700 transition-colors"
            >
              <Plus className="w-4 h-4" />
              Nueva Organización
            </button>
          )}
          {organization.mode === "enterprise" &&
            (canEditOrg || currentUser.role === "supervisor") && (
              <button
                type="button"
                onClick={() => onNavigateTab("enterprise_shifts")}
                className="inline-flex items-center gap-2 px-3.5 py-2 rounded-lg text-sm font-medium bg-slate-800 hover:bg-slate-700 border border-slate-700 transition-colors"
              >
                <Briefcase className="w-4 h-4 text-indigo-400" />
                Turnos y Jornadas
              </button>
            )}
          <button
            type="button"
            onClick={() => void api.downloadCsv(organization.id)}
            className="inline-flex items-center gap-2 px-3.5 py-2 rounded-lg text-sm font-medium bg-slate-800 hover:bg-slate-700 border border-slate-700 transition-colors"
          >
            <Download className="w-4 h-4" />
            Exportar CSV
          </button>
          <button
            type="button"
            onClick={() => onNavigateTab("kiosk")}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-indigo-600 hover:bg-indigo-500 text-white transition-colors"
          >
            <ScanFace className="w-4 h-4" />
            Abrir Kiosco
          </button>
        </div>
      </div>

      {isSuperadmin && showNewOrg && (
        <form
          onSubmit={handleCreateOrg}
          className="bg-slate-900 border border-indigo-500/40 rounded-2xl p-5 space-y-4"
        >
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="sm:col-span-2">
              <label className="block text-xs text-slate-400 mb-1">
                Nombre de la institución o empresa
              </label>
              <input
                type="text"
                required
                value={newOrgName}
                onChange={(e) => setNewOrgName(e.target.value)}
                placeholder="Ej. Ingeniería en Software — UPT"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1">Modo operativo</label>
              <select
                value={newOrgMode}
                onChange={(e) => setNewOrgMode(e.target.value as OrgMode)}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              >
                <option value="education">Escuela (Pase de lista)</option>
                <option value="enterprise">Empresa (Check-in / Check-out)</option>
              </select>
            </div>
          </div>

          {newOrgMode === "education" && (
            <div className="sm:max-w-xs">
              <label className="block text-xs text-slate-400 mb-1">
                Periodo académico general
              </label>
              <select
                value={newOrgPeriodType}
                onChange={(e) => setNewOrgPeriodType(e.target.value as AcademicPeriodType)}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              >
                {ACADEMIC_PERIOD_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
          )}

          <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
            <input
              type="checkbox"
              checked={createInitialAdmin}
              onChange={(e) => setCreateInitialAdmin(e.target.checked)}
              className="rounded border-slate-600 bg-slate-800 text-indigo-600"
            />
            Crear administrador exclusivo para esta organización
          </label>

          {createInitialAdmin && (
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-1">
              <input
                type="text"
                required
                value={adminFullName}
                onChange={(e) => setAdminFullName(e.target.value)}
                placeholder="Nombre del administrador"
                className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              />
              <input
                type="email"
                required
                value={adminEmail}
                onChange={(e) => setAdminEmail(e.target.value)}
                placeholder="admin@nuevaorg.com"
                className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              />
              <PasswordInput
                required
                minLength={6}
                value={adminPassword}
                onChange={(e) => setAdminPassword(e.target.value)}
                placeholder="Contraseña (mín. 6)"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              />
            </div>
          )}

          {orgFormError && (
            <p className="text-xs text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">
              {orgFormError}
            </p>
          )}

          <div className="flex justify-end">
            <button
              type="submit"
              disabled={creatingOrg}
              className="px-4 py-2 rounded-lg text-sm font-semibold bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50"
            >
              {creatingOrg ? "Creando..." : "Crear Organización"}
            </button>
          </div>
        </form>
      )}

      {/* KPIs */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5">
          <div className="flex items-center justify-between text-slate-400 text-xs font-medium uppercase">
            <span>Personas Activas</span>
            <Users className="w-4 h-4 text-indigo-400" />
          </div>
          <p className="text-3xl font-bold mt-2">{activePersons.length}</p>
          <p className="text-xs text-slate-500 mt-1">Padrón en esta organización</p>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5">
          <div className="flex items-center justify-between text-slate-400 text-xs font-medium uppercase">
            <span>Biometría Lista</span>
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
          </div>
          <p className="text-3xl font-bold mt-2">
            {enrolledPersons.length}{" "}
            <span className="text-sm font-normal text-slate-400">({coveragePct}%)</span>
          </p>
          <p className="text-xs text-slate-500 mt-1">Perfiles con embeddings ONNX</p>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5">
          <div className="flex items-center justify-between text-slate-400 text-xs font-medium uppercase">
            <span>Eventos Recientes</span>
            <CheckCircle2 className="w-4 h-4 text-sky-400" />
          </div>
          <p className="text-3xl font-bold mt-2">{events.length}</p>
          <p className="text-xs text-slate-500 mt-1">Últimos 100 registros</p>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5">
          <div className="flex items-center justify-between text-slate-400 text-xs font-medium uppercase">
            <span>Motor ONNX</span>
            <Activity className="w-4 h-4 text-emerald-400" />
          </div>
          <p className="text-lg font-bold mt-2 text-emerald-300">
            {health?.models_loaded ? "YuNet + SFace Listo" : "Sin inicializar"}
          </p>
          <p className="text-xs text-slate-500 mt-1">
            {health?.embeddings_count ?? 0} vectores totales
          </p>
        </div>
      </div>

      {/* Configuración + Últimos eventos */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <form
          onSubmit={handleSaveConfig}
          className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4"
        >
          <div>
            <h3 className="font-semibold text-base">Reglas de Organización</h3>
            <p className="text-xs text-slate-400 mt-0.5">
              Adapta el mismo motor entre empresa y escuela.
            </p>
          </div>

          <div>
            <label className="block text-xs text-slate-400 mb-1">Modo operativo</label>
            <select
              value={mode}
              disabled={!canEditOrg}
              onChange={(e) => setMode(e.target.value as OrgMode)}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm disabled:opacity-60"
            >
              <option value="enterprise">Empresa (Entrada y Salida)</option>
              <option value="education">Escuela (Pase de lista único)</option>
            </select>
          </div>

          {mode === "education" && (
            <div className="space-y-2.5">
              <div>
                <label className="block text-xs text-slate-400 mb-1">
                  Periodo académico general
                </label>
                <select
                  value={academicPeriodType}
                  disabled={!canEditOrg}
                  onChange={(e) => setAcademicPeriodType(e.target.value as AcademicPeriodType)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm disabled:opacity-60"
                >
                  {ACADEMIC_PERIOD_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>
              {canEditOrg &&
                academicPeriodType !== (organization.academic_period_type ?? "semestral") && (
                  <div className="rounded-xl bg-amber-500/10 border border-amber-500/30 p-3 space-y-1.5">
                    <label className="block text-[11px] font-medium text-amber-200">
                      Contraseña de administrador requerida para cambiar el tipo de periodo
                    </label>
                    <PasswordInput
                      required
                      value={periodAuthSecret}
                      onChange={(e) => setPeriodAuthSecret(e.target.value)}
                      placeholder="Contraseña de administrador"
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs"
                    />
                  </div>
                )}
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-slate-400 mb-1">Tolerancia (min)</label>
              <input
                type="number"
                min={0}
                max={180}
                disabled={!canEditOrg}
                value={tolerance}
                onChange={(e) => setTolerance(Number(e.target.value))}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm disabled:opacity-60"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1">Cooldown (seg)</label>
              <input
                type="number"
                min={5}
                max={3600}
                disabled={!canEditOrg}
                value={cooldown}
                onChange={(e) => setCooldown(Number(e.target.value))}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm disabled:opacity-60"
              />
            </div>
          </div>

          <label className="flex items-start gap-2.5 text-xs text-slate-300 cursor-pointer">
            <input
              type="checkbox"
              disabled={!canEditOrg}
              checked={storeAvatar}
              onChange={(e) => setStoreAvatar(e.target.checked)}
              className="mt-0.5 rounded border-slate-600 bg-slate-800 text-indigo-600"
            />
            <span>
              Guardar miniatura visual (200×200) en toma frontal. Las capturas crudas nunca se
              almacenan en disco.
            </span>
          </label>

          {feedback && (
            <p className="text-xs text-emerald-300 bg-emerald-500/10 border border-emerald-500/30 rounded-lg px-3 py-2">
              {feedback}
            </p>
          )}

          {canEditOrg && (
            <button
              type="submit"
              disabled={saving}
              className="w-full py-2 rounded-lg text-sm font-semibold bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 transition-colors"
            >
              {saving ? "Guardando..." : "Guardar configuración"}
            </button>
          )}
        </form>

        <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-2xl p-5 flex flex-col">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="font-semibold text-base">Últimos Movimientos</h3>
              <p className="text-xs text-slate-400">Registros recientes por reconocimiento o manual</p>
            </div>
            <button
              type="button"
              onClick={() => onNavigateTab("sessions")}
              className="text-xs text-indigo-400 hover:text-indigo-300 font-medium"
            >
              Ver historial completo →
            </button>
          </div>

          {events.length === 0 ? (
            <div className="flex-1 flex flex-col items-center justify-center py-12 text-center text-slate-500 text-sm">
              <p>Aún no hay asistencias registradas.</p>
              <button
                type="button"
                onClick={() => onNavigateTab("enrollment")}
                className="mt-3 text-indigo-400 hover:underline text-xs"
              >
                Comienza registrando personas en el padrón
              </button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead className="text-xs uppercase text-slate-400 border-b border-slate-800">
                  <tr>
                    <th className="py-2 pr-3">Persona</th>
                    <th className="py-2 px-3">Movimiento</th>
                    <th className="py-2 px-3">Estado</th>
                    <th className="py-2 px-3">Confianza</th>
                    <th className="py-2 pl-3 text-right">Hora</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/70">
                  {events.slice(0, 8).map((ev) => (
                    <tr key={ev.id} className="hover:bg-slate-800/30">
                      <td className="py-2.5 pr-3">
                        <div className="flex items-center gap-2.5">
                          {ev.person_avatar_base64 ? (
                            <img
                              src={ev.person_avatar_base64}
                              alt={ev.person_name}
                              className="w-7 h-7 rounded-full object-cover border border-slate-700"
                            />
                          ) : (
                            <div className="w-7 h-7 rounded-full bg-slate-800 flex items-center justify-center text-xs font-semibold text-slate-300">
                              {ev.person_name.slice(0, 1).toUpperCase()}
                            </div>
                          )}
                          <div>
                            <p className="font-medium leading-tight">{ev.person_name}</p>
                            <p className="text-[11px] text-slate-500">{ev.person_external_id}</p>
                          </div>
                        </div>
                      </td>
                      <td className="py-2.5 px-3 text-xs">
                        {ev.event_type === "check_in"
                          ? "Entrada"
                          : ev.event_type === "check_out"
                            ? "Salida"
                            : "Asistencia"}
                        {ev.work_shift_name && (
                          <span className="block text-[11px] text-slate-400">
                            {ev.work_shift_name}
                          </span>
                        )}
                      </td>
                      <td className="py-2.5 px-3">
                        <span
                          className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${
                            ev.status === "on_time"
                              ? "bg-emerald-500/15 text-emerald-300"
                              : ev.status === "late"
                                ? "bg-amber-500/15 text-amber-300"
                                : ev.status === "early_exit"
                                  ? "bg-orange-500/15 text-orange-300"
                                  : "bg-sky-500/15 text-sky-300"
                          }`}
                        >
                          {ev.status === "on_time"
                            ? "A tiempo"
                            : ev.status === "late"
                              ? "Retardo"
                              : ev.status === "early_exit"
                                ? "Salida anticipada"
                                : "Manual"}
                        </span>
                      </td>
                      <td className="py-2.5 px-3 text-xs text-slate-300">
                        {ev.confidence_score !== null
                          ? `${(ev.confidence_score * 100).toFixed(1)}%`
                          : "—"}
                      </td>
                      <td className="py-2.5 pl-3 text-right text-xs text-slate-400">
                        {new Date(ev.timestamp).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
