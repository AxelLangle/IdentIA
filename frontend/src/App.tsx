import { useCallback, useEffect, useState } from "react";
import { Layout, type NavTab } from "./components/Layout";
import {
  api,
  getStoredToken,
  setOnUnauthorizedHandler,
  setStoredToken,
} from "./lib/api";
import { DashboardPage } from "./pages/DashboardPage";
import { EnrollmentPage } from "./pages/EnrollmentPage";
import { KioskPage } from "./pages/KioskPage";
import { LoginPage } from "./pages/LoginPage";
import { SecurityPage } from "./pages/SecurityPage";
import { SessionsPage } from "./pages/SessionsPage";
import type {
  AttendanceEvent,
  AttendanceSession,
  AuthUser,
  Group,
  HealthResponse,
  LoginResponse,
  Organization,
  Person,
} from "./types/api";

export function App() {
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null);
  const [checkingAuth, setCheckingAuth] = useState(true);

  const [activeTab, setActiveTab] = useState<NavTab>("dashboard");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [selectedOrgId, setSelectedOrgId] = useState<number | null>(null);

  const [groups, setGroups] = useState<Group[]>([]);
  const [persons, setPersons] = useState<Person[]>([]);
  const [sessions, setSessions] = useState<AttendanceSession[]>([]);
  const [events, setEvents] = useState<AttendanceEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const handleLogout = useCallback(() => {
    setStoredToken(null);
    setCurrentUser(null);
    setOrganizations([]);
    setSelectedOrgId(null);
    setGroups([]);
    setPersons([]);
    setSessions([]);
    setEvents([]);
    setActiveTab("dashboard");
  }, []);

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

  const bootstrapWorkspace = useCallback(
    async (preferredOrgId?: number) => {
      setLoading(true);
      try {
        setLoadError(null);
        const [hlt, orgs] = await Promise.all([api.getHealth(), api.listOrganizations()]);
        setHealth(hlt);
        setOrganizations(orgs);
        const targetId = preferredOrgId ?? orgs[0]?.id ?? null;
        setSelectedOrgId(targetId);
        if (targetId !== null) {
          await loadOrgData(targetId);
        }
      } catch (err) {
        setLoadError(
          err instanceof Error
            ? `No se pudo cargar la información de IdentIA: ${err.message}`
            : "Error al iniciar el espacio de trabajo."
        );
      } finally {
        setLoading(false);
      }
    },
    [loadOrgData]
  );

  useEffect(() => {
    setOnUnauthorizedHandler(() => {
      handleLogout();
    });
    return () => setOnUnauthorizedHandler(null);
  }, [handleLogout]);

  useEffect(() => {
    async function restoreSession() {
      const token = getStoredToken();
      if (!token) {
        setCheckingAuth(false);
        return;
      }
      try {
        const user = await api.getMe();
        setCurrentUser(user);
        await bootstrapWorkspace(user.organization_id ?? undefined);
      } catch {
        setStoredToken(null);
        setCurrentUser(null);
      } finally {
        setCheckingAuth(false);
      }
    }
    void restoreSession();
  }, [bootstrapWorkspace]);

  const handleLoginSuccess = async (loginData: LoginResponse) => {
    setCurrentUser(loginData.user);
    setActiveTab("dashboard");
    await bootstrapWorkspace(loginData.user.organization_id ?? undefined);
  };

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

  if (checkingAuth) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-400 flex items-center justify-center text-sm">
        Verificando sesión...
      </div>
    );
  }

  if (!currentUser) {
    return <LoginPage onSuccess={(res) => void handleLoginSuccess(res)} />;
  }

  const selectedOrg = organizations.find((o) => o.id === selectedOrgId) ?? null;

  return (
    <Layout
      activeTab={activeTab}
      onChangeTab={setActiveTab}
      currentUser={currentUser}
      onLogout={handleLogout}
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
            onClick={() => void bootstrapWorkspace(selectedOrgId ?? undefined)}
            className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-500 text-white text-xs font-semibold"
          >
            Reintentar
          </button>
        </div>
      ) : !selectedOrg ? (
        <div className="text-center text-slate-400 py-16 text-sm">
          No hay organizaciones asignadas a tu usuario.
        </div>
      ) : (
        <>
          {activeTab === "dashboard" && (
            <DashboardPage
              currentUser={currentUser}
              organization={selectedOrg}
              health={health}
              persons={persons}
              events={events}
              onRefreshAll={refreshCurrentOrg}
              onOrganizationCreated={async (id) => {
                await bootstrapWorkspace(id);
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
              currentUser={currentUser}
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
              currentUser={currentUser}
              organization={selectedOrg}
              groups={groups}
              sessions={sessions}
              persons={persons}
              events={events}
              onRefreshAll={refreshCurrentOrg}
            />
          )}
          {activeTab === "security" &&
            (currentUser.role === "superadmin" || currentUser.role === "org_admin") && (
              <SecurityPage currentUser={currentUser} organization={selectedOrg} />
            )}
        </>
      )}
    </Layout>
  );
}

export default App;
