import type { ReactNode } from "react";
import {
  Activity,
  BookOpen,
  Building2,
  CalendarClock,
  GraduationCap,
  LayoutDashboard,
  LogOut,
  ScanFace,
  ShieldCheck,
  Users,
} from "lucide-react";
import type { AuthUser, HealthResponse, Organization, UserRole } from "../types/api";

export type NavTab =
  | "dashboard"
  | "kiosk"
  | "enrollment"
  | "sessions"
  | "academic"
  | "teacher_portal"
  | "security";

interface LayoutProps {
  activeTab: NavTab;
  onChangeTab: (tab: NavTab) => void;
  currentUser: AuthUser;
  onLogout: () => void;
  organizations: Organization[];
  selectedOrg: Organization | null;
  onSelectOrg: (orgId: number) => void;
  health: HealthResponse | null;
  children: ReactNode;
}

const ROLE_LABELS: Record<UserRole, string> = {
  superadmin: "Superadmin",
  org_admin: "Admin Org",
  teacher: "Profesor",
  operator: "Operador",
};

export function Layout({
  activeTab,
  onChangeTab,
  currentUser,
  onLogout,
  organizations,
  selectedOrg,
  onSelectOrg,
  health,
  children,
}: LayoutProps) {
  const canViewSecurity = currentUser.role === "superadmin" || currentUser.role === "org_admin";
  const isEducation = selectedOrg?.mode === "education";
  const isTeacher = currentUser.role === "teacher";

  const navItems: { id: NavTab; label: string; icon: typeof LayoutDashboard; visible: boolean }[] = [
    {
      id: "teacher_portal",
      label: "Mi Agenda Docente",
      icon: BookOpen,
      visible: isEducation && isTeacher,
    },
    { id: "dashboard", label: "Dashboard", icon: LayoutDashboard, visible: !isTeacher },
    { id: "kiosk", label: "Kiosco en vivo", icon: ScanFace, visible: true },
    { id: "enrollment", label: "Personas y Registro", icon: Users, visible: !isTeacher },
    {
      id: "academic",
      label: "Estructura Académica",
      icon: GraduationCap,
      visible: isEducation && canViewSecurity,
    },
    {
      id: "sessions",
      label: isTeacher ? "Mis Sesiones" : "Grupos y Sesiones",
      icon: CalendarClock,
      visible: true,
    },
    { id: "security", label: "Seguridad y Usuarios", icon: ShieldCheck, visible: canViewSecurity },
  ];

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col md:flex-row">
      {/* Barra lateral */}
      <aside className="w-full md:w-64 bg-slate-900 border-b md:border-b-0 md:border-r border-slate-800 flex flex-col justify-between shrink-0">
        <div>
          <div className="px-5 py-5 border-b border-slate-800 flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-indigo-600/20 border border-indigo-500/40 flex items-center justify-center text-indigo-400">
              <ScanFace className="w-5 h-5" />
            </div>
            <div>
              <h1 className="font-bold tracking-tight text-lg leading-none">IdentIA</h1>
              <p className="text-xs text-slate-400 mt-1">Asistencia Biométrica</p>
            </div>
          </div>

          <nav className="p-3 flex md:flex-col gap-1 overflow-x-auto">
            {navItems
              .filter((item) => item.visible)
              .map((item) => {
                const Icon = item.icon;
                const isActive = activeTab === item.id;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => onChangeTab(item.id)}
                    className={`flex items-center gap-3 px-3.5 py-2.5 rounded-lg text-sm font-medium transition-colors whitespace-nowrap ${
                      isActive
                        ? "bg-indigo-600 text-white shadow-sm"
                        : "text-slate-300 hover:bg-slate-800/80 hover:text-white"
                    }`}
                  >
                    <Icon className="w-4 h-4 shrink-0" />
                    <span>{item.label}</span>
                  </button>
                );
              })}
          </nav>
        </div>

        <div className="hidden md:block p-4 border-t border-slate-800 text-xs text-slate-400 space-y-2.5">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1.5">
              <Activity className="w-3.5 h-3.5 text-emerald-400" />
              Motor IA
            </span>
            <span
              className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${
                health?.models_loaded
                  ? "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
                  : "bg-amber-500/15 text-amber-300 border border-amber-500/30"
              }`}
            >
              {health?.models_loaded ? "YuNet + SFace" : "Cargando"}
            </span>
          </div>
          <p className="text-[11px] text-slate-500">
            Privacidad activa: embeddings L2 en memoria, sin fotos crudas en disco.
          </p>
        </div>
      </aside>

      {/* Contenido principal */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="min-h-16 py-2 border-b border-slate-800 bg-slate-900/60 backdrop-blur px-4 sm:px-6 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <span className="text-xs uppercase tracking-wider text-slate-400 hidden sm:inline">
              Organización
            </span>

            {currentUser.role === "superadmin" ? (
              <select
                id="org-selector"
                value={selectedOrg?.id ?? ""}
                onChange={(e) => onSelectOrg(Number(e.target.value))}
                className="bg-slate-800 border border-slate-700 text-slate-100 text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-500 max-w-xs truncate"
              >
                {organizations.map((org) => (
                  <option key={org.id} value={org.id}>
                    {org.name}
                  </option>
                ))}
              </select>
            ) : (
              <span className="text-sm font-semibold text-slate-100 truncate max-w-xs">
                {selectedOrg?.name ?? "Sin organización"}
              </span>
            )}

            {selectedOrg && (
              <span
                className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${
                  selectedOrg.mode === "enterprise"
                    ? "bg-indigo-500/15 text-indigo-300 border-indigo-500/30"
                    : "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
                }`}
              >
                {selectedOrg.mode === "enterprise" ? (
                  <>
                    <Building2 className="w-3.5 h-3.5" />
                    Empresa (Check-in/out)
                  </>
                ) : (
                  <>
                    <GraduationCap className="w-3.5 h-3.5" />
                    Escuela (Pase de lista)
                  </>
                )}
              </span>
            )}
          </div>

          <div className="flex items-center gap-3">
            <div className="text-right hidden sm:block">
              <p className="text-xs font-semibold text-slate-200 leading-tight">
                {currentUser.full_name}
              </p>
              <p className="text-[11px] text-indigo-300">
                {ROLE_LABELS[currentUser.role]} · {currentUser.email}
              </p>
            </div>
            <button
              type="button"
              onClick={onLogout}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200"
              title="Cerrar sesión"
            >
              <LogOut className="w-3.5 h-3.5" />
              Salir
            </button>
          </div>
        </header>

        <main className="flex-1 p-4 sm:p-6 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}
