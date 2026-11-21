/**
 * Módulo de Seguridad, Control de Acceso Basado en Roles (RBAC),
 * Contraseñas Delegadas Trazables y Bitácora de Auditoría de IdentIA.
 */
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
import { EntradaContrasena } from "../components/PasswordInput";
import { clienteApi } from "../lib/api";
import type {
  CredencialDelegada,
  EntradaBitacoraAuditoria,
  Organizacion,
  RolUsuario,
  UsuarioAutenticado,
} from "../types/api";

/** Propiedades recibidas por `PaginaSeguridad`. */
interface PropiedadesPaginaSeguridad {
  /** Usuario autenticado con permisos administrativos (`superadmin` u `org_admin`). */
  usuarioActual: UsuarioAutenticado;
  /** Organización activa cuyo directorio de cuentas y bitácora se administran. */
  organizacion: Organizacion;
}

/** Subpestañas disponibles dentro del panel de seguridad. */
type SubPestanaSeguridad = "users" | "credentials" | "audit";

/** Etiquetas legibles para presentar el rol asignado a cada cuenta. */
const ETIQUETAS_ROL_USUARIO: Record<RolUsuario, string> = {
  superadmin: "Superadmin Global",
  org_admin: "Admin de Organización",
  supervisor: "Supervisor",
  teacher: "Profesor",
  operator: "Operador / Kiosco",
};

/**
 * Renderiza la administración de cuentas organizacionales, generación y
 * revocación de credenciales delegadas y consulta de bitácora de auditoría.
 */
export function PaginaSeguridad({
  usuarioActual,
  organizacion,
}: PropiedadesPaginaSeguridad) {
  const [subPestana, establecerSubPestana] = useState<SubPestanaSeguridad>("users");
  const [usuarios, establecerUsuarios] = useState<UsuarioAutenticado[]>([]);
  const [credenciales, establecerCredenciales] = useState<CredencialDelegada[]>([]);
  const [registrosAuditoria, establecerRegistrosAuditoria] = useState<
    EntradaBitacoraAuditoria[]
  >([]);
  const [cargando, establecerCargando] = useState(true);
  const [mensajeError, establecerMensajeError] = useState<string | null>(null);

  // Estado del formulario para alta de cuentas RBAC.
  const [nuevoNombreCompleto, establecerNuevoNombreCompleto] = useState("");
  const [nuevoCorreo, establecerNuevoCorreo] = useState("");
  const [nuevaContrasena, establecerNuevaContrasena] = useState("");
  const [nuevoRol, establecerNuevoRol] = useState<RolUsuario>("operator");
  const [creandoUsuario, establecerCreandoUsuario] = useState(false);

  // Estado del formulario y secreto temporal para credenciales delegadas.
  const [etiquetaCredencial, establecerEtiquetaCredencial] = useState("");
  const [idUsuarioAsignado, establecerIdUsuarioAsignado] = useState<string>("");
  const [nombrePersonalizadoAsignado, establecerNombrePersonalizadoAsignado] =
    useState("");
  const [secretoPersonalizado, establecerSecretoPersonalizado] = useState("");
  const [diasExpiracion, establecerDiasExpiracion] = useState<string>("30");
  const [creandoCredencial, establecerCreandoCredencial] = useState(false);
  const [secretoRevelado, establecerSecretoRevelado] = useState<{
    secreto: string;
    asignadoA: string;
  } | null>(null);
  const [secretoCopiado, establecerSecretoCopiado] = useState(false);

  /** Carga en paralelo usuarios, credenciales delegadas y bitácora de auditoría. */
  const cargarDatosSeguridad = useCallback(async () => {
    establecerCargando(true);
    establecerMensajeError(null);
    try {
      const [listaUsuarios, listaCredenciales, listaAuditoria] = await Promise.all([
        clienteApi.listarUsuarios(organizacion.id),
        clienteApi.listarCredencialesDelegadas(organizacion.id),
        clienteApi.listarBitacoraAuditoria(organizacion.id),
      ]);
      establecerUsuarios(listaUsuarios);
      establecerCredenciales(listaCredenciales);
      establecerRegistrosAuditoria(listaAuditoria);
    } catch (errorCarga) {
      establecerMensajeError(
        errorCarga instanceof Error
          ? errorCarga.message
          : "No se pudieron cargar los datos de seguridad."
      );
    } finally {
      establecerCargando(false);
    }
  }, [organizacion.id]);

  useEffect(() => {
    establecerSecretoRevelado(null);
    void cargarDatosSeguridad();
  }, [cargarDatosSeguridad]);

  // Ajusta el rol por defecto al cambiar entre modo escolar y empresarial.
  useEffect(() => {
    establecerNuevoRol((previo) => {
      if (organizacion.modo === "enterprise" && previo === "teacher") return "supervisor";
      if (organizacion.modo === "education" && previo === "supervisor") return "teacher";
      return previo;
    });
  }, [organizacion.modo]);

  /** Registra una nueva cuenta administrativa o operativa vinculada a la organización. */
  async function manejarCrearUsuario(evento: FormEvent) {
    evento.preventDefault();
    establecerCreandoUsuario(true);
    establecerMensajeError(null);
    try {
      await clienteApi.crearUsuario({
        nombre_completo: nuevoNombreCompleto.trim(),
        correo: nuevoCorreo.trim(),
        contrasena: nuevaContrasena,
        rol: nuevoRol,
        id_organizacion: nuevoRol === "superadmin" ? null : organizacion.id,
      });
      establecerNuevoNombreCompleto("");
      establecerNuevoCorreo("");
      establecerNuevaContrasena("");
      await cargarDatosSeguridad();
    } catch (errorCreacion) {
      establecerMensajeError(
        errorCreacion instanceof Error
          ? errorCreacion.message
          : "No se pudo crear el usuario."
      );
    } finally {
      establecerCreandoUsuario(false);
    }
  }

  /** Activa o desactiva temporalmente la cuenta de un usuario existente. */
  async function manejarAlternarUsuarioActivo(usuario: UsuarioAutenticado) {
    establecerMensajeError(null);
    try {
      await clienteApi.actualizarUsuario(usuario.id, {
        esta_activo: !usuario.esta_activo,
      });
      await cargarDatosSeguridad();
    } catch (errorActualizacion) {
      establecerMensajeError(
        errorActualizacion instanceof Error
          ? errorActualizacion.message
          : "No se pudo actualizar el usuario."
      );
    }
  }

  /** Genera una contraseña delegada trazable y revela su texto plano una sola vez. */
  async function manejarCrearCredencial(evento: FormEvent) {
    evento.preventDefault();
    establecerCreandoCredencial(true);
    establecerMensajeError(null);
    establecerSecretoCopiado(false);
    try {
      const respuesta = await clienteApi.crearCredencialDelegada({
        id_organizacion: organizacion.id,
        etiqueta: etiquetaCredencial.trim(),
        id_usuario_asignado: idUsuarioAsignado ? Number(idUsuarioAsignado) : null,
        nombre_asignado: !idUsuarioAsignado ? nombrePersonalizadoAsignado.trim() : null,
        secreto_personalizado: secretoPersonalizado.trim() || null,
        expira_en_dias: diasExpiracion ? Number(diasExpiracion) : null,
      });
      establecerEtiquetaCredencial("");
      establecerNombrePersonalizadoAsignado("");
      establecerSecretoPersonalizado("");
      establecerSecretoRevelado({
        secreto: respuesta.secreto_plano,
        asignadoA: respuesta.credencial.nombre_asignado,
      });
      await cargarDatosSeguridad();
    } catch (errorCredencial) {
      establecerMensajeError(
        errorCredencial instanceof Error
          ? errorCredencial.message
          : "No se pudo crear la contraseña delegada."
      );
    } finally {
      establecerCreandoCredencial(false);
    }
  }

  /** Invalida de forma inmediata una credencial delegada activa. */
  async function manejarRevocarCredencial(idCredencial: number) {
    if (
      !window.confirm(
        "¿Revocar esta contraseña delegada? Dejará de funcionar de inmediato."
      )
    ) {
      return;
    }
    establecerMensajeError(null);
    try {
      await clienteApi.revocarCredencialDelegada(idCredencial);
      await cargarDatosSeguridad();
    } catch (errorRevocacion) {
      establecerMensajeError(
        errorRevocacion instanceof Error
          ? errorRevocacion.message
          : "No se pudo revocar la credencial."
      );
    }
  }

  /** Copia al portapapeles el secreto generado para compartirlo con el delegado. */
  async function manejarCopiarSecreto(secreto: string) {
    await navigator.clipboard.writeText(secreto);
    establecerSecretoCopiado(true);
  }

  const subordinadosOrganizacion = usuarios.filter(
    (usuario) => usuario.esta_activo && usuario.id_organizacion === organizacion.id
  );

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">
            Seguridad, Usuarios y Auditoría
          </h2>
          <p className="text-sm text-slate-400">
            Control de acceso aislado para {organizacion.nombre} y contraseñas delegadas
            trazables
          </p>
        </div>

        <div className="flex items-center gap-1.5 bg-slate-900 border border-slate-800 rounded-xl p-1">
          <button
            type="button"
            onClick={() => establecerSubPestana("users")}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium ${
              subPestana === "users"
                ? "bg-indigo-600 text-white"
                : "text-slate-300 hover:bg-slate-800"
            }`}
          >
            <Users className="w-3.5 h-3.5" />
            Usuarios ({usuarios.length})
          </button>
          <button
            type="button"
            onClick={() => establecerSubPestana("credentials")}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium ${
              subPestana === "credentials"
                ? "bg-indigo-600 text-white"
                : "text-slate-300 hover:bg-slate-800"
            }`}
          >
            <KeyRound className="w-3.5 h-3.5" />
            Contraseñas Delegadas ({credenciales.length})
          </button>
          <button
            type="button"
            onClick={() => establecerSubPestana("audit")}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium ${
              subPestana === "audit"
                ? "bg-indigo-600 text-white"
                : "text-slate-300 hover:bg-slate-800"
            }`}
          >
            <FileSpreadsheet className="w-3.5 h-3.5" />
            Auditoría ({registrosAuditoria.length})
          </button>
        </div>
      </div>

      {mensajeError && (
        <div className="rounded-xl bg-red-500/15 border border-red-500/40 px-4 py-3 text-sm text-red-200">
          {mensajeError}
        </div>
      )}

      {cargando ? (
        <div className="py-16 text-center text-sm text-slate-400">
          Cargando panel de seguridad...
        </div>
      ) : subPestana === "users" ? (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          <form
            onSubmit={manejarCrearUsuario}
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
                value={nuevoNombreCompleto}
                onChange={(evento) => establecerNuevoNombreCompleto(evento.target.value)}
                placeholder="Nombre y apellidos"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              />
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1">
                Correo electrónico
              </label>
              <input
                type="email"
                required
                value={nuevoCorreo}
                onChange={(evento) => establecerNuevoCorreo(evento.target.value)}
                placeholder="usuario@organizacion.com"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              />
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1">Contraseña</label>
              <EntradaContrasena
                required
                minLength={6}
                value={nuevaContrasena}
                onChange={(evento) => establecerNuevaContrasena(evento.target.value)}
                placeholder="Mínimo 6 caracteres"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              />
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1">Rol</label>
              <select
                value={nuevoRol}
                onChange={(evento) => establecerNuevoRol(evento.target.value as RolUsuario)}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              >
                <option value="org_admin">Admin de Organización</option>
                {organizacion.modo === "enterprise" ? (
                  <option value="supervisor">Supervisor</option>
                ) : (
                  <option value="teacher">Profesor</option>
                )}
                <option value="operator">Operador / Kiosco</option>
                {usuarioActual.rol === "superadmin" && (
                  <option value="superadmin">Superadmin Global</option>
                )}
              </select>
            </div>

            <button
              type="submit"
              disabled={creandoUsuario}
              className="w-full inline-flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-semibold bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50"
            >
              <Plus className="w-4 h-4" />
              {creandoUsuario ? "Creando..." : "Crear usuario"}
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
                {usuarios.map((usuario) => (
                  <tr key={usuario.id} className="hover:bg-slate-800/30">
                    <td className="py-3 pr-3">
                      <p className="font-medium">{usuario.nombre_completo}</p>
                      <p className="text-xs text-slate-400">{usuario.correo}</p>
                    </td>
                    <td className="py-3 px-3 text-xs">
                      {ETIQUETAS_ROL_USUARIO[usuario.rol] ?? usuario.rol}
                    </td>
                    <td className="py-3 px-3">
                      <span
                        className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${
                          usuario.esta_activo
                            ? "bg-emerald-500/15 text-emerald-300"
                            : "bg-slate-800 text-slate-400"
                        }`}
                      >
                        {usuario.esta_activo ? "Activo" : "Inactivo"}
                      </span>
                    </td>
                    <td className="py-3 pl-3 text-right">
                      {usuario.id !== usuarioActual.id && (
                        <button
                          type="button"
                          onClick={() => void manejarAlternarUsuarioActivo(usuario)}
                          className="px-2.5 py-1 rounded-md text-xs bg-slate-800 hover:bg-slate-700 border border-slate-700"
                        >
                          {usuario.esta_activo ? "Desactivar" : "Reactivar"}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : subPestana === "credentials" ? (
        <div className="space-y-6">
          {secretoRevelado && (
            <div className="rounded-2xl bg-emerald-500/15 border border-emerald-500/40 p-4 flex flex-wrap items-center justify-between gap-4">
              <div className="space-y-1">
                <p className="text-sm font-semibold text-emerald-200">
                  Contraseña delegada generada para {secretoRevelado.asignadoA}
                </p>
                <p className="text-xs text-emerald-200/80">
                  Guárdala ahora: por seguridad se almacena hasheada y no volverá a
                  mostrarse.
                </p>
                <code className="inline-block mt-1 px-3 py-1.5 rounded-lg bg-slate-950 border border-emerald-500/40 text-sm font-mono text-emerald-300">
                  {secretoRevelado.secreto}
                </code>
              </div>
              <button
                type="button"
                onClick={() => void manejarCopiarSecreto(secretoRevelado.secreto)}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white"
              >
                {secretoCopiado ? (
                  <Check className="w-4 h-4" />
                ) : (
                  <Copy className="w-4 h-4" />
                )}
                {secretoCopiado ? "Copiada" : "Copiar clave"}
              </button>
            </div>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            <form
              onSubmit={manejarCrearCredencial}
              className="lg:col-span-4 bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4 h-fit"
            >
              <div>
                <h3 className="font-semibold text-base flex items-center gap-2">
                  <KeyRound className="w-4 h-4 text-indigo-400" />
                  Crear Contraseña Delegada
                </h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  Delega la revocación biométrica sin compartir tu contraseña de
                  administrador.
                </p>
              </div>

              <div>
                <label className="block text-xs text-slate-400 mb-1">
                  Etiqueta o motivo
                </label>
                <input
                  type="text"
                  required
                  value={etiquetaCredencial}
                  onChange={(evento) => establecerEtiquetaCredencial(evento.target.value)}
                  placeholder="Ej. Encargado de turno matutino"
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                />
              </div>

              <div>
                <label className="block text-xs text-slate-400 mb-1">
                  Asignar a subordinado
                </label>
                <select
                  value={idUsuarioAsignado}
                  onChange={(evento) => establecerIdUsuarioAsignado(evento.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                >
                  <option value="">Nombre manual (otro subordinado)</option>
                  {subordinadosOrganizacion.map((usuario) => (
                    <option key={usuario.id} value={usuario.id}>
                      {usuario.nombre_completo} (
                      {ETIQUETAS_ROL_USUARIO[usuario.rol] ?? usuario.rol})
                    </option>
                  ))}
                </select>
              </div>

              {!idUsuarioAsignado && (
                <div>
                  <label className="block text-xs text-slate-400 mb-1">
                    Nombre de quien la usará
                  </label>
                  <input
                    type="text"
                    required
                    value={nombrePersonalizadoAsignado}
                    onChange={(evento) =>
                      establecerNombrePersonalizadoAsignado(evento.target.value)
                    }
                    placeholder="Nombre del responsable"
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                  />
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs text-slate-400 mb-1">
                    Expira en (días)
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={3650}
                    value={diasExpiracion}
                    onChange={(evento) => establecerDiasExpiracion(evento.target.value)}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">
                    Clave manual (opc.)
                  </label>
                  <input
                    type="text"
                    minLength={6}
                    value={secretoPersonalizado}
                    onChange={(evento) =>
                      establecerSecretoPersonalizado(evento.target.value)
                    }
                    placeholder="Auto IDN-..."
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={creandoCredencial}
                className="w-full py-2.5 rounded-lg text-sm font-semibold bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50"
              >
                {creandoCredencial ? "Generando..." : "Generar credencial"}
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
                  {credenciales.map((credencial) => (
                    <tr key={credencial.id} className="hover:bg-slate-800/30">
                      <td className="py-3 pr-3">
                        <p className="font-medium">{credencial.etiqueta}</p>
                        <code className="text-[11px] text-slate-400">
                          {credencial.prefijo_secreto}••••
                        </code>
                      </td>
                      <td className="py-3 px-3 text-xs text-slate-300">
                        {credencial.nombre_creador ?? "—"}
                      </td>
                      <td className="py-3 px-3 text-xs text-slate-300">
                        {credencial.nombre_asignado}
                      </td>
                      <td className="py-3 px-3">
                        <span
                          className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${
                            credencial.estado === "active"
                              ? "bg-emerald-500/15 text-emerald-300"
                              : "bg-red-500/15 text-red-300"
                          }`}
                        >
                          {credencial.estado}
                        </span>
                      </td>
                      <td className="py-3 pl-3 text-right">
                        {credencial.estado === "active" && (
                          <button
                            type="button"
                            onClick={() => void manejarRevocarCredencial(credencial.id)}
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
              {registrosAuditoria.map((registro) => (
                <tr key={registro.id} className="hover:bg-slate-800/30">
                  <td className="py-2.5 pr-3 text-xs text-slate-400 whitespace-nowrap">
                    {new Date(registro.creado_en).toLocaleString()}
                  </td>
                  <td className="py-2.5 px-3 text-xs font-mono text-indigo-300">
                    {registro.accion}
                  </td>
                  <td className="py-2.5 px-3 text-xs font-medium">
                    {registro.resumen_objetivo ?? "—"}
                  </td>
                  <td className="py-2.5 px-3 text-xs text-slate-300">
                    {registro.nombre_ejecutor ?? "—"}
                  </td>
                  <td className="py-2.5 px-3 text-xs text-slate-300">
                    {registro.nombre_autorizador ?? "—"}
                    {registro.prefijo_credencial_delegada && (
                      <span className="block text-[10px] text-amber-300">
                        Clave {registro.prefijo_credencial_delegada} (
                        {registro.nombre_asignado_credencial})
                      </span>
                    )}
                  </td>
                  <td className="py-2.5 pl-3 text-xs text-slate-400">
                    {registro.detalles ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
