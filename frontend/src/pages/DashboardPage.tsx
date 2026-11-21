/**
 * Panel General operativo de IdentIA.
 * Presenta indicadores clave de cobertura biométrica, acceso directo al kiosco,
 * descarga CSV, configuración de reglas organizacionales y creación de nuevas
 * organizaciones (exclusivo para `superadmin`).
 */
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
import type { PestanaNavegacion } from "../components/Layout";
import { EntradaContrasena } from "../components/PasswordInput";
import { OPCIONES_PERIODO_ACADEMICO } from "../lib/academicPeriods";
import { clienteApi } from "../lib/api";
import type {
  EventoAsistencia,
  ModoOrganizacion,
  Organizacion,
  Persona,
  RespuestaSalud,
  TipoPeriodoAcademico,
  UsuarioAutenticado,
} from "../types/api";

/** Propiedades recibidas por `PaginaPanelGeneral`. */
interface PropiedadesPaginaPanelGeneral {
  /** Usuario actualmente autenticado en sesión. */
  usuarioActual: UsuarioAutenticado;
  /** Organización activa mostrada en el tablero. */
  organizacion: Organizacion;
  /** Diagnóstico más reciente de modelos ONNX y conteos globales. */
  estadoSalud: RespuestaSalud | null;
  /** Lista completa de personas registradas en la organización actual. */
  personas: Persona[];
  /** Últimos movimientos de asistencia registrados. */
  eventos: EventoAsistencia[];
  /** Recarga catálogos tras actualizar reglas de la organización. */
  alRecargarTodo: () => Promise<void>;
  /** Cambia el espacio de trabajo hacia una organización recién creada. */
  alCrearOrganizacion: (idOrganizacion: number) => Promise<void>;
  /** Navega programáticamente hacia otra pestaña de la aplicación. */
  alNavegarPestana: (pestana: PestanaNavegacion) => void;
}

/**
 * Renderiza el tablero resumen, reglas de tolerancia/enfriamiento/periodo y la
 * tabla de últimos movimientos de asistencia.
 */
export function PaginaPanelGeneral({
  usuarioActual,
  organizacion,
  estadoSalud,
  personas,
  eventos,
  alRecargarTodo,
  alCrearOrganizacion,
  alNavegarPestana,
}: PropiedadesPaginaPanelGeneral) {
  const [modo, establecerModo] = useState<ModoOrganizacion>(organizacion.modo);
  const [tipoPeriodoAcademico, establecerTipoPeriodoAcademico] =
    useState<TipoPeriodoAcademico>(organizacion.tipo_periodo_academico);
  const [secretoAutorizacionPeriodo, establecerSecretoAutorizacionPeriodo] = useState("");
  const [toleranciaRetardo, establecerToleranciaRetardo] = useState<number>(
    organizacion.minutos_tolerancia_retardo
  );
  const [tiempoEnfriamiento, establecerTiempoEnfriamiento] = useState<number>(
    organizacion.segundos_enfriamiento
  );
  const [guardarAvatar, establecerGuardarAvatar] = useState<boolean>(
    organizacion.guardar_avatar_por_defecto
  );
  const [guardando, establecerGuardando] = useState(false);
  const [mensajeRetroalimentacion, establecerMensajeRetroalimentacion] = useState<
    string | null
  >(null);

  // Estado del formulario colapsable para crear otra organización (solo superadmin).
  const [mostrarNuevaOrg, establecerMostrarNuevaOrg] = useState(false);
  const [nombreNuevaOrg, establecerNombreNuevaOrg] = useState("");
  const [modoNuevaOrg, establecerModoNuevaOrg] = useState<ModoOrganizacion>("education");
  const [periodoNuevaOrg, establecerPeriodoNuevaOrg] =
    useState<TipoPeriodoAcademico>("semestral");
  const [crearAdminInicial, establecerCrearAdminInicial] = useState(true);
  const [nombreCompletoAdmin, establecerNombreCompletoAdmin] = useState("");
  const [correoAdmin, establecerCorreoAdmin] = useState("");
  const [contrasenaAdmin, establecerContrasenaAdmin] = useState("");
  const [errorFormularioOrg, establecerErrorFormularioOrg] = useState<string | null>(null);
  const [creandoOrg, establecerCreandoOrg] = useState(false);

  const esSuperadmin = usuarioActual.rol === "superadmin";
  const puedeEditarOrg = esSuperadmin || usuarioActual.rol === "org_admin";

  // Sincroniza los campos editables cuando el superadmin cambia de organización.
  useEffect(() => {
    establecerModo(organizacion.modo);
    establecerTipoPeriodoAcademico(organizacion.tipo_periodo_academico ?? "semestral");
    establecerSecretoAutorizacionPeriodo("");
    establecerToleranciaRetardo(organizacion.minutos_tolerancia_retardo);
    establecerTiempoEnfriamiento(organizacion.segundos_enfriamiento);
    establecerGuardarAvatar(organizacion.guardar_avatar_por_defecto);
    establecerMensajeRetroalimentacion(null);
  }, [organizacion]);

  const personasActivas = personas.filter((persona) => persona.esta_activo);
  const personasEnroladas = personasActivas.filter(
    (persona) => persona.cantidad_vectores > 0
  );
  const porcentajeCobertura =
    personasActivas.length > 0
      ? Math.round((personasEnroladas.length / personasActivas.length) * 100)
      : 0;

  /** Persiste cambios en reglas operativas, requiriendo secreto si cambia el régimen escolar. */
  async function manejarGuardarConfiguracion(evento: FormEvent) {
    evento.preventDefault();
    establecerGuardando(true);
    establecerMensajeRetroalimentacion(null);
    const cambioTipoPeriodo =
      modo === "education" &&
      tipoPeriodoAcademico !== (organizacion.tipo_periodo_academico ?? "semestral");
    try {
      await clienteApi.actualizarOrganizacion(organizacion.id, {
        modo,
        tipo_periodo_academico: tipoPeriodoAcademico,
        minutos_tolerancia_retardo: Number(toleranciaRetardo),
        segundos_enfriamiento: Number(tiempoEnfriamiento),
        guardar_avatar_por_defecto: guardarAvatar,
        ...(cambioTipoPeriodo
          ? { secreto_autorizacion: secretoAutorizacionPeriodo }
          : {}),
      });
      establecerSecretoAutorizacionPeriodo("");
      await alRecargarTodo();
      establecerMensajeRetroalimentacion("Configuración actualizada correctamente.");
    } catch (errorGuardado) {
      establecerMensajeRetroalimentacion(
        errorGuardado instanceof Error ? errorGuardado.message : "Error al guardar."
      );
    } finally {
      establecerGuardando(false);
    }
  }

  /** Registra una nueva organización junto con su usuario administrador inicial opcional. */
  async function manejarCrearOrganizacion(evento: FormEvent) {
    evento.preventDefault();
    if (!nombreNuevaOrg.trim()) return;
    establecerErrorFormularioOrg(null);
    establecerCreandoOrg(true);
    try {
      const orgCreada = await clienteApi.crearOrganizacion({
        nombre: nombreNuevaOrg.trim(),
        modo: modoNuevaOrg,
        tipo_periodo_academico:
          modoNuevaOrg === "education" ? periodoNuevaOrg : "semestral",
        usuario_administrador: crearAdminInicial
          ? {
              nombre_completo: nombreCompletoAdmin.trim(),
              correo: correoAdmin.trim(),
              contrasena: contrasenaAdmin,
            }
          : null,
      });
      establecerNombreNuevaOrg("");
      establecerNombreCompletoAdmin("");
      establecerCorreoAdmin("");
      establecerContrasenaAdmin("");
      establecerMostrarNuevaOrg(false);
      await alCrearOrganizacion(orgCreada.id);
    } catch (errorCreacion) {
      establecerErrorFormularioOrg(
        errorCreacion instanceof Error
          ? errorCreacion.message
          : "No se pudo crear la organización."
      );
    } finally {
      establecerCreandoOrg(false);
    }
  }

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Panel General</h2>
          <p className="text-sm text-slate-400 mt-0.5">
            Resumen operativo y configuración biométrica de {organizacion.nombre}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {esSuperadmin && (
            <button
              type="button"
              onClick={() => establecerMostrarNuevaOrg((visible) => !visible)}
              className="inline-flex items-center gap-2 px-3.5 py-2 rounded-lg text-sm font-medium bg-slate-800 hover:bg-slate-700 border border-slate-700 transition-colors"
            >
              <Plus className="w-4 h-4" />
              Nueva Organización
            </button>
          )}
          {organizacion.modo === "enterprise" &&
            (puedeEditarOrg || usuarioActual.rol === "supervisor") && (
              <button
                type="button"
                onClick={() => alNavegarPestana("enterprise_shifts")}
                className="inline-flex items-center gap-2 px-3.5 py-2 rounded-lg text-sm font-medium bg-slate-800 hover:bg-slate-700 border border-slate-700 transition-colors"
              >
                <Briefcase className="w-4 h-4 text-indigo-400" />
                Turnos y Jornadas
              </button>
            )}
          <button
            type="button"
            onClick={() => void clienteApi.descargarCsv(organizacion.id)}
            className="inline-flex items-center gap-2 px-3.5 py-2 rounded-lg text-sm font-medium bg-slate-800 hover:bg-slate-700 border border-slate-700 transition-colors"
          >
            <Download className="w-4 h-4" />
            Exportar CSV
          </button>
          <button
            type="button"
            onClick={() => alNavegarPestana("kiosk")}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-indigo-600 hover:bg-indigo-500 text-white transition-colors"
          >
            <ScanFace className="w-4 h-4" />
            Abrir Kiosco
          </button>
        </div>
      </div>

      {esSuperadmin && mostrarNuevaOrg && (
        <form
          onSubmit={manejarCrearOrganizacion}
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
                value={nombreNuevaOrg}
                onChange={(evento) => establecerNombreNuevaOrg(evento.target.value)}
                placeholder="Ej. Ingeniería en Software — UPT"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1">Modo operativo</label>
              <select
                value={modoNuevaOrg}
                onChange={(evento) =>
                  establecerModoNuevaOrg(evento.target.value as ModoOrganizacion)
                }
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              >
                <option value="education">Escuela (Pase de lista)</option>
                <option value="enterprise">Empresa (Check-in / Check-out)</option>
              </select>
            </div>
          </div>

          {modoNuevaOrg === "education" && (
            <div className="sm:max-w-xs">
              <label className="block text-xs text-slate-400 mb-1">
                Periodo académico general
              </label>
              <select
                value={periodoNuevaOrg}
                onChange={(evento) =>
                  establecerPeriodoNuevaOrg(evento.target.value as TipoPeriodoAcademico)
                }
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              >
                {OPCIONES_PERIODO_ACADEMICO.map((opcion) => (
                  <option key={opcion.valor} value={opcion.valor}>
                    {opcion.etiqueta}
                  </option>
                ))}
              </select>
            </div>
          )}

          <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
            <input
              type="checkbox"
              checked={crearAdminInicial}
              onChange={(evento) => establecerCrearAdminInicial(evento.target.checked)}
              className="rounded border-slate-600 bg-slate-800 text-indigo-600"
            />
            Crear administrador exclusivo para esta organización
          </label>

          {crearAdminInicial && (
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-1">
              <input
                type="text"
                required
                value={nombreCompletoAdmin}
                onChange={(evento) => establecerNombreCompletoAdmin(evento.target.value)}
                placeholder="Nombre del administrador"
                className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              />
              <input
                type="email"
                required
                value={correoAdmin}
                onChange={(evento) => establecerCorreoAdmin(evento.target.value)}
                placeholder="admin@nuevaorg.com"
                className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              />
              <EntradaContrasena
                required
                minLength={6}
                value={contrasenaAdmin}
                onChange={(evento) => establecerContrasenaAdmin(evento.target.value)}
                placeholder="Contraseña (mín. 6)"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              />
            </div>
          )}

          {errorFormularioOrg && (
            <p className="text-xs text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">
              {errorFormularioOrg}
            </p>
          )}

          <div className="flex justify-end">
            <button
              type="submit"
              disabled={creandoOrg}
              className="px-4 py-2 rounded-lg text-sm font-semibold bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50"
            >
              {creandoOrg ? "Creando..." : "Crear Organización"}
            </button>
          </div>
        </form>
      )}

      {/* Indicadores clave (KPIs) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5">
          <div className="flex items-center justify-between text-slate-400 text-xs font-medium uppercase">
            <span>Personas Activas</span>
            <Users className="w-4 h-4 text-indigo-400" />
          </div>
          <p className="text-3xl font-bold mt-2">{personasActivas.length}</p>
          <p className="text-xs text-slate-500 mt-1">Padrón en esta organización</p>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5">
          <div className="flex items-center justify-between text-slate-400 text-xs font-medium uppercase">
            <span>Biometría Lista</span>
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
          </div>
          <p className="text-3xl font-bold mt-2">
            {personasEnroladas.length}{" "}
            <span className="text-sm font-normal text-slate-400">
              ({porcentajeCobertura}%)
            </span>
          </p>
          <p className="text-xs text-slate-500 mt-1">Perfiles con embeddings ONNX</p>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5">
          <div className="flex items-center justify-between text-slate-400 text-xs font-medium uppercase">
            <span>Eventos Recientes</span>
            <CheckCircle2 className="w-4 h-4 text-sky-400" />
          </div>
          <p className="text-3xl font-bold mt-2">{eventos.length}</p>
          <p className="text-xs text-slate-500 mt-1">Últimos 100 registros</p>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5">
          <div className="flex items-center justify-between text-slate-400 text-xs font-medium uppercase">
            <span>Motor ONNX</span>
            <Activity className="w-4 h-4 text-emerald-400" />
          </div>
          <p className="text-lg font-bold mt-2 text-emerald-300">
            {estadoSalud?.modelos_cargados ? "YuNet + SFace Listo" : "Sin inicializar"}
          </p>
          <p className="text-xs text-slate-500 mt-1">
            {estadoSalud?.cantidad_vectores ?? 0} vectores totales
          </p>
        </div>
      </div>

      {/* Configuración organizacional + tabla de últimos movimientos */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <form
          onSubmit={manejarGuardarConfiguracion}
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
              value={modo}
              disabled={!puedeEditarOrg}
              onChange={(evento) =>
                establecerModo(evento.target.value as ModoOrganizacion)
              }
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm disabled:opacity-60"
            >
              <option value="enterprise">Empresa (Entrada y Salida)</option>
              <option value="education">Escuela (Pase de lista único)</option>
            </select>
          </div>

          {modo === "education" && (
            <div className="space-y-2.5">
              <div>
                <label className="block text-xs text-slate-400 mb-1">
                  Periodo académico general
                </label>
                <select
                  value={tipoPeriodoAcademico}
                  disabled={!puedeEditarOrg}
                  onChange={(evento) =>
                    establecerTipoPeriodoAcademico(
                      evento.target.value as TipoPeriodoAcademico
                    )
                  }
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm disabled:opacity-60"
                >
                  {OPCIONES_PERIODO_ACADEMICO.map((opcion) => (
                    <option key={opcion.valor} value={opcion.valor}>
                      {opcion.etiqueta}
                    </option>
                  ))}
                </select>
              </div>
              {puedeEditarOrg &&
                tipoPeriodoAcademico !==
                  (organizacion.tipo_periodo_academico ?? "semestral") && (
                  <div className="rounded-xl bg-amber-500/10 border border-amber-500/30 p-3 space-y-1.5">
                    <label className="block text-[11px] font-medium text-amber-200">
                      Contraseña de administrador requerida para cambiar el tipo de periodo
                    </label>
                    <EntradaContrasena
                      required
                      value={secretoAutorizacionPeriodo}
                      onChange={(evento) =>
                        establecerSecretoAutorizacionPeriodo(evento.target.value)
                      }
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
                disabled={!puedeEditarOrg}
                value={toleranciaRetardo}
                onChange={(evento) =>
                  establecerToleranciaRetardo(Number(evento.target.value))
                }
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm disabled:opacity-60"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1">Cooldown (seg)</label>
              <input
                type="number"
                min={5}
                max={3600}
                disabled={!puedeEditarOrg}
                value={tiempoEnfriamiento}
                onChange={(evento) =>
                  establecerTiempoEnfriamiento(Number(evento.target.value))
                }
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm disabled:opacity-60"
              />
            </div>
          </div>

          <label className="flex items-start gap-2.5 text-xs text-slate-300 cursor-pointer">
            <input
              type="checkbox"
              disabled={!puedeEditarOrg}
              checked={guardarAvatar}
              onChange={(evento) => establecerGuardarAvatar(evento.target.checked)}
              className="mt-0.5 rounded border-slate-600 bg-slate-800 text-indigo-600"
            />
            <span>
              Guardar miniatura visual (200×200) en toma frontal. Las capturas crudas nunca
              se almacenan en disco.
            </span>
          </label>

          {mensajeRetroalimentacion && (
            <p className="text-xs text-emerald-300 bg-emerald-500/10 border border-emerald-500/30 rounded-lg px-3 py-2">
              {mensajeRetroalimentacion}
            </p>
          )}

          {puedeEditarOrg && (
            <button
              type="submit"
              disabled={guardando}
              className="w-full py-2 rounded-lg text-sm font-semibold bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 transition-colors"
            >
              {guardando ? "Guardando..." : "Guardar configuración"}
            </button>
          )}
        </form>

        <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-2xl p-5 flex flex-col">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="font-semibold text-base">Últimos Movimientos</h3>
              <p className="text-xs text-slate-400">
                Registros recientes por reconocimiento o manual
              </p>
            </div>
            <button
              type="button"
              onClick={() => alNavegarPestana("sessions")}
              className="text-xs text-indigo-400 hover:text-indigo-300 font-medium"
            >
              Ver historial completo →
            </button>
          </div>

          {eventos.length === 0 ? (
            <div className="flex-1 flex flex-col items-center justify-center py-12 text-center text-slate-500 text-sm">
              <p>Aún no hay asistencias registradas.</p>
              <button
                type="button"
                onClick={() => alNavegarPestana("enrollment")}
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
                  {eventos.slice(0, 8).map((evento) => (
                    <tr key={evento.id} className="hover:bg-slate-800/30">
                      <td className="py-2.5 pr-3">
                        <div className="flex items-center gap-2.5">
                          {evento.avatar_base64_persona ? (
                            <img
                              src={evento.avatar_base64_persona}
                              alt={evento.nombre_persona}
                              className="w-7 h-7 rounded-full object-cover border border-slate-700"
                            />
                          ) : (
                            <div className="w-7 h-7 rounded-full bg-slate-800 flex items-center justify-center text-xs font-semibold text-slate-300">
                              {evento.nombre_persona.slice(0, 1).toUpperCase()}
                            </div>
                          )}
                          <div>
                            <p className="font-medium leading-tight">
                              {evento.nombre_persona}
                            </p>
                            <p className="text-[11px] text-slate-500">
                              {evento.identificador_externo_persona}
                            </p>
                          </div>
                        </div>
                      </td>
                      <td className="py-2.5 px-3 text-xs">
                        {evento.tipo_evento === "check_in"
                          ? "Entrada"
                          : evento.tipo_evento === "check_out"
                            ? "Salida"
                            : "Asistencia"}
                        {evento.nombre_turno_laboral && (
                          <span className="block text-[11px] text-slate-400">
                            {evento.nombre_turno_laboral}
                          </span>
                        )}
                      </td>
                      <td className="py-2.5 px-3">
                        <span
                          className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${
                            evento.estado === "on_time"
                              ? "bg-emerald-500/15 text-emerald-300"
                              : evento.estado === "late"
                                ? "bg-amber-500/15 text-amber-300"
                                : evento.estado === "early_exit"
                                  ? "bg-orange-500/15 text-orange-300"
                                  : "bg-sky-500/15 text-sky-300"
                          }`}
                        >
                          {evento.estado === "on_time"
                            ? "A tiempo"
                            : evento.estado === "late"
                              ? "Retardo"
                              : evento.estado === "early_exit"
                                ? "Salida anticipada"
                                : "Manual"}
                        </span>
                      </td>
                      <td className="py-2.5 px-3 text-xs text-slate-300">
                        {evento.puntaje_confianza !== null
                          ? `${(evento.puntaje_confianza * 100).toFixed(1)}%`
                          : "—"}
                      </td>
                      <td className="py-2.5 pl-3 text-right text-xs text-slate-400">
                        {new Date(evento.fecha_hora).toLocaleTimeString([], {
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
