import type { ReactNode } from "react";
import {
  Activity,
  Building2,
  CalendarClock,
  GraduationCap,
  LayoutDashboard,
  ScanFace,
  Users,
} from "lucide-react";
import type { HealthResponse, Organization } from "../types/api";

export type NavTab = "dashboard" | "kiosk" | "enrollment" | "sessions";

interface LayoutProps {
  activeTab: NavTab;
  onChangeTab: (tab: NavTab) => void;
  organizations: Organization[];
  selectedOrg: Organization | null;
  onSelectOrg: (orgId: number) => void;
  health: HealthResponse | null;
  children: ReactNode;
}

const NAV_ITEMS: { id: NavTab; label: string; icon: typeof LayoutDashboard }[] = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "kiosk", label: "Kiosco en vivo", icon: ScanFace },
  { id: "enrollment", label: "Personas y Registro", icon: Users },
  { id: "sessions", label: "Grupos y Sesiones", icon: CalendarClock },
];

export function Layout({
  activeTab,
  onChangeTab,
  organizations,
  selectedOrg,
  onSelectOrg,
  health,
  children,
}: LayoutProps) {
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
            {NAV_ITEMS.map((item) => {
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

        <div className="hidden md:block p-4 border-t border-slate-800 text-xs text-slate-400 space-y-2">
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
        <header className="h-16 border-b border-slate-800 bg-slate-900/60 backdrop-blur px-4 sm:px-6 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 min-w-0">
            <label htmlFor="org-selector" className="text-xs uppercase tracking-wider text-slate-400 hidden sm:inline">
              Organización
            </label>
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

          <div className="text-xs text-slate-400 hidden sm:flex items-center gap-2">
            <span>Modelo:</span>
            <code className="px-2 py-0.5 rounded bg-slate-800 text-slate-200">
              {health?.model_version ?? "sface_2021dec"}
            </code>
          </div>
        </header>

        <main className="flex-1 p-4 sm:p-6 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}
