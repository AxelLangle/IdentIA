import { useCallback, useEffect, useState } from "react";
import { Layout, type NavTab } from "./components/Layout";
import { api } from "./lib/api";
import { DashboardPage } from "./pages/DashboardPage";
import { EnrollmentPage } from "./pages/EnrollmentPage";
import { KioskPage } from "./pages/KioskPage";
import { SessionsPage } from "./pages/SessionsPage";
import type {
  AttendanceEvent,
  AttendanceSession,
  Group,
  HealthResponse,
  Organization,
  Person,
} from "./types/api";

export function App() {
  const [activeTab, setActiveTab] = useState<NavTab>("dashboard");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [selectedOrgId, setSelectedOrgId] = useState<number | null>(null);

  const [groups, setGroups] = useState<Group[]>([]);
  const [persons, setPersons] = useState<Person[]>([]);
  const [sessions, setSessions] = useState<AttendanceSession[]>([]);
  const [events, setEvents] = useState<AttendanceEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const loadOrgData = useCallback(async (orgId: number) => {
    const [grps, pers, sess, evs, hlt] = await Promise.all([
      api.listGroups(orgId),
      api.listPersons(orgId),
      api.listSessions(orgId),
      api.listEvents(orgId),
      api.getHealth(),
    ]);
    setGroups(grps);
    setPersons(pers);
    setSessions(sess);
    setEvents(evs);
    setHealth(hlt);
  }, []);

  const bootstrap = useCallback(
    async (preferredOrgId?: number) => {
      try {
        setLoadError(null);
        const [hlt, orgs] = await Promise.all([api.getHealth(), api.listOrganizations()]);
        setHealth(hlt);
        setOrganizations(orgs);
        const targetId = preferredOrgId ?? selectedOrgId ?? orgs[0]?.id ?? null;
        setSelectedOrgId(targetId);
        if (targetId !== null) {
          await loadOrgData(targetId);
        }
      } catch (err) {
        setLoadError(
          err instanceof Error
            ? `No se pudo conectar al backend de IdentIA: ${err.message}`
            : "Error al iniciar la aplicación."
        );
      } finally {
        setLoading(false);
      }
    },
    [loadOrgData, selectedOrgId]
  );

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  const handleSelectOrg = async (orgId: number) => {
    setSelectedOrgId(orgId);
    await loadOrgData(orgId);
  };

  const refreshCurrentOrg = useCallback(async () => {
    if (selectedOrgId === null) return;
    const orgs = await api.listOrganizations();
    setOrganizations(orgs);
    await loadOrgData(selectedOrgId);
  }, [loadOrgData, selectedOrgId]);

  const selectedOrg = organizations.find((o) => o.id === selectedOrgId) ?? null;

  return (
    <Layout
      activeTab={activeTab}
      onChangeTab={setActiveTab}
      organizations={organizations}
      selectedOrg={selectedOrg}
      onSelectOrg={(id) => void handleSelectOrg(id)}
      health={health}
    >
      {loading ? (
        <div className="flex items-center justify-center h-64 text-sm text-slate-400">
          Cargando IdentIA...
        </div>
      ) : loadError ? (
        <div className="max-w-xl mx-auto mt-10 rounded-2xl bg-red-500/10 border border-red-500/40 p-6 text-sm text-red-200 space-y-3">
          <p className="font-semibold">Error de conexión</p>
          <p>{loadError}</p>
          <button
            type="button"
            onClick={() => void bootstrap()}
            className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-500 text-white text-xs font-semibold"
          >
            Reintentar
          </button>
        </div>
      ) : !selectedOrg ? (
        <div className="text-center text-slate-400 py-16 text-sm">
          No hay organizaciones disponibles.
        </div>
      ) : (
        <>
          {activeTab === "dashboard" && (
            <DashboardPage
              organization={selectedOrg}
              health={health}
              persons={persons}
              events={events}
              onRefreshAll={refreshCurrentOrg}
              onOrganizationCreated={async (id) => {
                await bootstrap(id);
              }}
              onNavigateTab={setActiveTab}
            />
          )}
          {activeTab === "kiosk" && (
            <KioskPage
              organization={selectedOrg}
              groups={groups}
              sessions={sessions}
              events={events}
              onRefreshEvents={async () => {
                const evs = await api.listEvents(selectedOrg.id);
                setEvents(evs);
              }}
            />
          )}
          {activeTab === "enrollment" && (
            <EnrollmentPage
              organization={selectedOrg}
              groups={groups}
              persons={persons}
              onRefreshPersons={async () => {
                const [pers, hlt] = await Promise.all([
                  api.listPersons(selectedOrg.id),
                  api.getHealth(),
                ]);
                setPersons(pers);
                setHealth(hlt);
              }}
            />
          )}
          {activeTab === "sessions" && (
            <SessionsPage
              organization={selectedOrg}
              groups={groups}
              sessions={sessions}
              persons={persons}
              events={events}
              onRefreshAll={refreshCurrentOrg}
            />
          )}
        </>
      )}
    </Layout>
  );
}

export default App;
