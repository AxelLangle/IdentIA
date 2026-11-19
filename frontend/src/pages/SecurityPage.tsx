import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  Check,
  Copy,
  FileSpreadsheet,
  KeyRound,
  Plus,
  ShieldAlert,
  UserPlus,
  Users,
} from "lucide-react";
import { api } from "../lib/api";
import type {
  AuditLogEntry,
  AuthUser,
  DelegatedCredential,
  Organization,
  UserRole,
} from "../types/api";

interface SecurityPageProps {
  currentUser: AuthUser;
  organization: Organization;
}

type SecuritySubTab = "users" | "credentials" | "audit";

export function SecurityPage({ currentUser, organization }: SecurityPageProps) {
  const [subTab, setSubTab] = useState<SecuritySubTab>("users");
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [credentials, setCredentials] = useState<DelegatedCredential[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Alta de usuario
  const [newFullName, setNewFullName] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState<UserRole>("operator");
  const [creatingUser, setCreatingUser] = useState(false);

  // Alta de credencial delegada
  const [credLabel, setCredLabel] = useState("");
  const [assignedUserId, setAssignedUserId] = useState<string>("");
  const [assignedCustomName, setAssignedCustomName] = useState("");
  const [customSecret, setCustomSecret] = useState("");
  const [expiresDays, setExpiresDays] = useState<string>("30");
  const [creatingCred, setCreatingCred] = useState(false);
  const [revealedSecret, setRevealedSecret] = useState<{
    secret: string;
    assignedTo: string;
  } | null>(null);
  const [copiedSecret, setCopiedSecret] = useState(false);

  const loadSecurityData = useCallback(async () => {
    setLoading(true);
    setErrorMsg(null);
    try {
      const [usr, creds, logs] = await Promise.all([
        api.listUsers(organization.id),
        api.listDelegatedCredentials(organization.id),
        api.listAuditLogs(organization.id),
      ]);
      setUsers(usr);
      setCredentials(creds);
      setAuditLogs(logs);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "No se pudieron cargar los datos de seguridad.");
    } finally {
      setLoading(false);
    }
  }, [organization.id]);

  useEffect(() => {
    setRevealedSecret(null);
    void loadSecurityData();
  }, [loadSecurityData]);

  async function handleCreateUser(e: FormEvent) {
    e.preventDefault();
    setCreatingUser(true);
    setErrorMsg(null);
    try {
      await api.createUser({
        full_name: newFullName.trim(),
        email: newEmail.trim(),
        password: newPassword,
        role: newRole,
        organization_id: newRole === "superadmin" ? null : organization.id,
      });
      setNewFullName("");
      setNewEmail("");
      setNewPassword("");
      await loadSecurityData();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "No se pudo crear el usuario.");
    } finally {
      setCreatingUser(false);
    }
  }

  async function handleToggleUserActive(user: AuthUser) {
    setErrorMsg(null);
    try {
      await api.updateUser(user.id, { is_active: !user.is_active });
      await loadSecurityData();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "No se pudo actualizar el usuario.");
    }
  }

  async function handleCreateCredential(e: FormEvent) {
    e.preventDefault();
    setCreatingCred(true);
    setErrorMsg(null);
    setCopiedSecret(false);
    try {
      const res = await api.createDelegatedCredential({
        organization_id: organization.id,
        label: credLabel.trim(),
        assigned_to_user_id: assignedUserId ? Number(assignedUserId) : null,
        assigned_to_name: !assignedUserId ? assignedCustomName.trim() : null,
        custom_secret: customSecret.trim() || null,
        expires_in_days: expiresDays ? Number(expiresDays) : null,
      });
      setCredLabel("");
      setAssignedCustomName("");
      setCustomSecret("");
      setRevealedSecret({
        secret: res.plain_secret,
        assignedTo: res.credential.assigned_to_name,
      });
      await loadSecurityData();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "No se pudo crear la contraseña delegada.");
    } finally {
      setCreatingCred(false);
    }
  }

  async function handleRevokeCredential(credId: number) {
    if (!window.confirm("¿Revocar esta contraseña delegada? Dejará de funcionar de inmediato.")) {
      return;
    }
    setErrorMsg(null);
    try {
      await api.revokeDelegatedCredential(credId);
      await loadSecurityData();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "No se pudo revocar la credencial.");
    }
  }

  async function handleCopySecret(secret: string) {
    await navigator.clipboard.writeText(secret);
    setCopiedSecret(true);
  }

  const orgSubordinates = users.filter((u) => u.is_active && u.organization_id === organization.id);

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Seguridad, Usuarios y Auditoría</h2>
          <p className="text-sm text-slate-400">
            Control de acceso aislado para {organization.name} y contraseñas delegadas trazables
          </p>
        </div>

        <div className="flex items-center gap-1.5 bg-slate-900 border border-slate-800 rounded-xl p-1">
          <button
            type="button"
            onClick={() => setSubTab("users")}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium ${
              subTab === "users" ? "bg-indigo-600 text-white" : "text-slate-300 hover:bg-slate-800"
            }`}
          >
            <Users className="w-3.5 h-3.5" />
            Usuarios ({users.length})
          </button>
          <button
            type="button"
            onClick={() => setSubTab("credentials")}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium ${
              subTab === "credentials"
                ? "bg-indigo-600 text-white"
                : "text-slate-300 hover:bg-slate-800"
            }`}
          >
            <KeyRound className="w-3.5 h-3.5" />
            Contraseñas Delegadas ({credentials.length})
          </button>
          <button
            type="button"
            onClick={() => setSubTab("audit")}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium ${
              subTab === "audit" ? "bg-indigo-600 text-white" : "text-slate-300 hover:bg-slate-800"
            }`}
          >
            <FileSpreadsheet className="w-3.5 h-3.5" />
            Auditoría ({auditLogs.length})
          </button>
        </div>
      </div>

      {errorMsg && (
        <div className="rounded-xl bg-red-500/15 border border-red-500/40 px-4 py-3 text-sm text-red-200">
          {errorMsg}
        </div>
      )}

      {loading ? (
        <div className="py-16 text-center text-sm text-slate-400">Cargando panel de seguridad...</div>
      ) : subTab === "users" ? (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          <form
            onSubmit={handleCreateUser}
            className="lg:col-span-4 bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4 h-fit"
          >
            <h3 className="font-semibold text-base flex items-center gap-2">
              <UserPlus className="w-4 h-4 text-indigo-400" />
              Nuevo Usuario
            </h3>

            <div>
              <label className="block text-xs text-slate-400 mb-1">Nombre completo</label>
              <input
                type="text"
                required
                value={newFullName}
                onChange={(e) => setNewFullName(e.target.value)}
                placeholder="Nombre y apellidos"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              />
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1">Correo electrónico</label>
              <input
                type="email"
                required
                value={newEmail}
                onChange={(e) => setNewEmail(e.target.value)}
                placeholder="usuario@organizacion.com"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              />
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1">Contraseña</label>
              <input
                type="password"
                required
                minLength={6}
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="Mínimo 6 caracteres"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              />
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1">Rol</label>
              <select
                value={newRole}
                onChange={(e) => setNewRole(e.target.value as UserRole)}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              >
                <option value="org_admin">Admin de Organización</option>
                <option value="operator">Operador / Kiosco</option>
                <option value="teacher">Profesor</option>
                {currentUser.role === "superadmin" && (
                  <option value="superadmin">Superadmin Global</option>
                )}
              </select>
            </div>

            <button
              type="submit"
              disabled={creatingUser}
              className="w-full inline-flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-semibold bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50"
            >
              <Plus className="w-4 h-4" />
              {creatingUser ? "Creando..." : "Crear usuario"}
            </button>
          </form>

          <div className="lg:col-span-8 bg-slate-900 border border-slate-800 rounded-2xl p-5 overflow-x-auto">
            <h3 className="font-semibold text-base mb-4">Cuentas en esta organización</h3>
            <table className="w-full text-sm text-left">
              <thead className="text-xs uppercase text-slate-400 border-b border-slate-800">
                <tr>
                  <th className="py-2 pr-3">Usuario</th>
                  <th className="py-2 px-3">Rol</th>
                  <th className="py-2 px-3">Estado</th>
                  <th className="py-2 pl-3 text-right">Acción</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/70">
                {users.map((u) => (
                  <tr key={u.id} className="hover:bg-slate-800/30">
                    <td className="py-3 pr-3">
                      <p className="font-medium">{u.full_name}</p>
                      <p className="text-xs text-slate-400">{u.email}</p>
                    </td>
                    <td className="py-3 px-3 text-xs">{u.role}</td>
                    <td className="py-3 px-3">
                      <span
                        className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${
                          u.is_active
                            ? "bg-emerald-500/15 text-emerald-300"
                            : "bg-slate-800 text-slate-400"
                        }`}
                      >
                        {u.is_active ? "Activo" : "Inactivo"}
                      </span>
                    </td>
                    <td className="py-3 pl-3 text-right">
                      {u.id !== currentUser.id && (
                        <button
                          type="button"
                          onClick={() => void handleToggleUserActive(u)}
                          className="px-2.5 py-1 rounded-md text-xs bg-slate-800 hover:bg-slate-700 border border-slate-700"
                        >
                          {u.is_active ? "Desactivar" : "Reactivar"}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : subTab === "credentials" ? (
        <div className="space-y-6">
          {revealedSecret && (
            <div className="rounded-2xl bg-emerald-500/15 border border-emerald-500/40 p-4 flex flex-wrap items-center justify-between gap-4">
              <div className="space-y-1">
                <p className="text-sm font-semibold text-emerald-200">
                  Contraseña delegada generada para {revealedSecret.assignedTo}
                </p>
                <p className="text-xs text-emerald-200/80">
                  Guárdala ahora: por seguridad se almacena hasheada y no volverá a mostrarse.
                </p>
                <code className="inline-block mt-1 px-3 py-1.5 rounded-lg bg-slate-950 border border-emerald-500/40 text-sm font-mono text-emerald-300">
                  {revealedSecret.secret}
                </code>
              </div>
              <button
                type="button"
                onClick={() => void handleCopySecret(revealedSecret.secret)}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white"
              >
                {copiedSecret ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                {copiedSecret ? "Copiada" : "Copiar clave"}
              </button>
            </div>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            <form
              onSubmit={handleCreateCredential}
              className="lg:col-span-4 bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4 h-fit"
            >
              <div>
                <h3 className="font-semibold text-base flex items-center gap-2">
                  <KeyRound className="w-4 h-4 text-indigo-400" />
                  Crear Contraseña Delegada
                </h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  Delega la revocación biométrica sin compartir tu contraseña de administrador.
                </p>
              </div>

              <div>
                <label className="block text-xs text-slate-400 mb-1">Etiqueta o motivo</label>
                <input
                  type="text"
                  required
                  value={credLabel}
                  onChange={(e) => setCredLabel(e.target.value)}
                  placeholder="Ej. Encargado de turno matutino"
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                />
              </div>

              <div>
                <label className="block text-xs text-slate-400 mb-1">Asignar a subordinado</label>
                <select
                  value={assignedUserId}
                  onChange={(e) => setAssignedUserId(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                >
                  <option value="">Nombre manual (otro subordinado)</option>
                  {orgSubordinates.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.full_name} ({u.role})
                    </option>
                  ))}
                </select>
              </div>

              {!assignedUserId && (
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Nombre de quien la usará</label>
                  <input
                    type="text"
                    required
                    value={assignedCustomName}
                    onChange={(e) => setAssignedCustomName(e.target.value)}
                    placeholder="Nombre del responsable"
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                  />
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Expira en (días)</label>
                  <input
                    type="number"
                    min={1}
                    max={3650}
                    value={expiresDays}
                    onChange={(e) => setExpiresDays(e.target.value)}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Clave manual (opc.)</label>
                  <input
                    type="text"
                    minLength={6}
                    value={customSecret}
                    onChange={(e) => setCustomSecret(e.target.value)}
                    placeholder="Auto IDN-..."
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={creatingCred}
                className="w-full py-2.5 rounded-lg text-sm font-semibold bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50"
              >
                {creatingCred ? "Generando..." : "Generar credencial"}
              </button>
            </form>

            <div className="lg:col-span-8 bg-slate-900 border border-slate-800 rounded-2xl p-5 overflow-x-auto">
              <h3 className="font-semibold text-base mb-4">Credenciales registradas</h3>
              <table className="w-full text-sm text-left">
                <thead className="text-xs uppercase text-slate-400 border-b border-slate-800">
                  <tr>
                    <th className="py-2 pr-3">Etiqueta</th>
                    <th className="py-2 px-3">Creada por</th>
                    <th className="py-2 px-3">Asignada a</th>
                    <th className="py-2 px-3">Estado</th>
                    <th className="py-2 pl-3 text-right">Acción</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/70">
                  {credentials.map((c) => (
                    <tr key={c.id} className="hover:bg-slate-800/30">
                      <td className="py-3 pr-3">
                        <p className="font-medium">{c.label}</p>
                        <code className="text-[11px] text-slate-400">{c.secret_prefix}••••</code>
                      </td>
                      <td className="py-3 px-3 text-xs text-slate-300">
                        {c.created_by_name ?? "—"}
                      </td>
                      <td className="py-3 px-3 text-xs text-slate-300">{c.assigned_to_name}</td>
                      <td className="py-3 px-3">
                        <span
                          className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${
                            c.status === "active"
                              ? "bg-emerald-500/15 text-emerald-300"
                              : "bg-red-500/15 text-red-300"
                          }`}
                        >
                          {c.status}
                        </span>
                      </td>
                      <td className="py-3 pl-3 text-right">
                        {c.status === "active" && (
                          <button
                            type="button"
                            onClick={() => void handleRevokeCredential(c.id)}
                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs bg-red-500/15 hover:bg-red-500/25 text-red-300 border border-red-500/30"
                          >
                            <ShieldAlert className="w-3.5 h-3.5" />
                            Revocar
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      ) : (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 overflow-x-auto">
          <h3 className="font-semibold text-base mb-4">Bitácora de Auditoría</h3>
          <table className="w-full text-sm text-left">
            <thead className="text-xs uppercase text-slate-400 border-b border-slate-800">
              <tr>
                <th className="py-2 pr-3">Fecha</th>
                <th className="py-2 px-3">Acción</th>
                <th className="py-2 px-3">Objetivo</th>
                <th className="py-2 px-3">Ejecutado por</th>
                <th className="py-2 px-3">Autorizado por</th>
                <th className="py-2 pl-3">Detalles</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/70">
              {auditLogs.map((log) => (
                <tr key={log.id} className="hover:bg-slate-800/30">
                  <td className="py-2.5 pr-3 text-xs text-slate-400 whitespace-nowrap">
                    {new Date(log.created_at).toLocaleString()}
                  </td>
                  <td className="py-2.5 px-3 text-xs font-mono text-indigo-300">{log.action}</td>
                  <td className="py-2.5 px-3 text-xs font-medium">{log.target_summary ?? "—"}</td>
                  <td className="py-2.5 px-3 text-xs text-slate-300">
                    {log.executed_by_name ?? "—"}
                  </td>
                  <td className="py-2.5 px-3 text-xs text-slate-300">
                    {log.authorized_by_name ?? "—"}
                    {log.delegated_credential_prefix && (
                      <span className="block text-[10px] text-amber-300">
                        Clave {log.delegated_credential_prefix} ({log.delegated_assigned_to_name})
                      </span>
                    )}
                  </td>
                  <td className="py-2.5 pl-3 text-xs text-slate-400">{log.details ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
