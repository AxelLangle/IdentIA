/**
 * Gestión de Grupos/Departamentos, Sesiones de Asistencia, Registro Manual
 * de Respaldo y Bitácora Histórica de Eventos con exportación CSV.
 */
import { useEffect, useState, type FormEvent } from "react";
import {
  CalendarCheck,
  CalendarPlus,
  Download,
  Lock,
  Plus,
  Trash2,
} from "lucide-react";
import { formatearEtiquetaPeriodoGrupo } from "../lib/academicPeriods";
import { clienteApi } from "../lib/api";
import type {
  AsignacionCurso,
  EventoAsistencia,
  Grupo,
  Organizacion,
  Persona,
  SesionAsistencia,
  TurnoLaboral,
  UsuarioAutenticado,
} from "../types/api";

/** Propiedades recibidas por `PaginaSesiones`. */
interface PropiedadesPaginaSesiones {
  /** Usuario autenticado para aplicar reglas según rol. */
  usuarioActual: UsuarioAutenticado;
  /** Organización activa en el espacio de trabajo. */
  organizacion: Organizacion;
  /** Catálogo de grupos escolares o departamentos empresariales. */
  grupos: Grupo[];
  /** Lista de sesiones abiertas y cerradas. */
  sesiones: SesionAsistencia[];
  /** Padrón completo de personas activas en la organización. */
  personas: Persona[];
  /** Historial reciente de eventos registrados. */
  eventos: EventoAsistencia[];
  /** Callback para refrescar catálogos compartidos tras crear o cerrar elementos. */
  alRecargarTodo: () => Promise<void>;
}

/**
 * Renderiza la gestión diaria de sesiones, creación rápida de grupos/áreas,
 * pase manual de respaldo e historial filtrable por sesión.
 */
export function PaginaSesiones({
  usuarioActual,
  organizacion,
  grupos,
  sesiones,
  personas,
  eventos,
  alRecargarTodo,
}: PropiedadesPaginaSesiones) {
  const esDocente = usuarioActual.rol === "teacher";
  const esEducacion = organizacion.modo === "education";
  const esEmpresa = organizacion.modo === "enterprise";
  const puedeGestionarGrupos =
    usuarioActual.rol === "superadmin" || usuarioActual.rol === "org_admin";
  const puedeGenerarAcademicas =
    esEducacion && ["superadmin", "org_admin", "teacher"].includes(usuarioActual.rol);
  const puedeGenerarEmpresariales =
    esEmpresa &&
    ["superadmin", "org_admin", "supervisor", "operator"].includes(usuarioActual.rol);

  const [cursos, establecerCursos] = useState<AsignacionCurso[]>([]);
  const [turnosLaborales, establecerTurnosLaborales] = useState<TurnoLaboral[]>([]);

  // Formulario para crear grupo escolar o departamento.
  const [nombreGrupo, establecerNombreGrupo] = useState("");
  const [codigoGrupo, establecerCodigoGrupo] = useState("");
  const [idTurnoDefectoGrupo, establecerIdTurnoDefectoGrupo] = useState<string>("");

  // Formulario para abrir sesión manual o vinculada a curso/turno.
  const [tituloSesion, establecerTituloSesion] = useState("");
  const [idCursoSesion, establecerIdCursoSesion] = useState<string>("");
  const [idTurnoSesion, establecerIdTurnoSesion] = useState<string>("");
  const [idGrupoSesion, establecerIdGrupoSesion] = useState<string>("");
  const [horaInicioEsperada, establecerHoraInicioEsperada] = useState("");

  // Formulario de registro manual de respaldo.
  const [idSesionManual, establecerIdSesionManual] = useState<string>("");
  const [idPersonaManual, establecerIdPersonaManual] = useState<string>("");
  const [tipoEventoManual, establecerTipoEventoManual] = useState<
    "present" | "check_in" | "check_out"
  >(organizacion.modo === "education" ? "present" : "check_in");
  const [notasManuales, establecerNotasManuales] = useState("");
  const [idSesionFiltro, establecerIdSesionFiltro] = useState<string>("");
  const [mensajeEstado, establecerMensajeEstado] = useState<string | null>(null);
  const [mensajeError, establecerMensajeError] = useState<string | null>(null);

  // Carga cursos o turnos laborales según el modo de la organización activa.
  useEffect(() => {
    establecerIdTurnoDefectoGrupo("");
    establecerIdCursoSesion("");
    establecerIdTurnoSesion("");
    establecerIdGrupoSesion("");
    establecerIdSesionManual("");
    establecerIdPersonaManual("");
    let cancelado = false;

    if (esEducacion) {
      establecerTurnosLaborales([]);
      clienteApi
        .listarCursos(organizacion.id)
        .then((lista) => {
          if (!cancelado) establecerCursos(lista);
        })
        .catch(() => {
          if (!cancelado) establecerCursos([]);
        });
    } else {
      establecerCursos([]);
      clienteApi
        .listarTurnosLaborales(organizacion.id)
        .then((lista) => {
          if (!cancelado) establecerTurnosLaborales(lista);
        })
        .catch(() => {
          if (!cancelado) establecerTurnosLaborales([]);
        });
    }

    return () => {
      cancelado = true;
    };
  }, [esEducacion, organizacion.id]);

  const sesionesAbiertas = sesiones.filter((sesion) => sesion.estado === "open");
  const eventosFiltrados = idSesionFiltro
    ? eventos.filter((evento) => evento.id_sesion === Number(idSesionFiltro))
    : eventos;

  const sesionManualSeleccionada =
    sesionesAbiertas.find((sesion) => String(sesion.id) === idSesionManual) ?? null;
  const opcionesPersonaManual =
    sesionManualSeleccionada && sesionManualSeleccionada.id_grupo !== null
      ? personas.filter((persona) =>
          persona.ids_grupos.includes(sesionManualSeleccionada.id_grupo!)
        )
      : personas;

  /** Dispara la generación automática de sesiones de clase o jornadas de hoy. */
  async function manejarGenerarSesionesHoy() {
    establecerMensajeError(null);
    establecerMensajeEstado(null);
    try {
      const ahora = new Date();
      const fechaHoyIso = `${ahora.getFullYear()}-${String(ahora.getMonth() + 1).padStart(
        2,
        "0"
      )}-${String(ahora.getDate()).padStart(2, "0")}`;
      const respuesta = esEducacion
        ? await clienteApi.generarSesionesAcademicas({
            id_organizacion: organizacion.id,
            fecha_objetivo: fechaHoyIso,
          })
        : await clienteApi.generarSesionesEmpresariales({
            id_organizacion: organizacion.id,
            fecha_objetivo: fechaHoyIso,
          });
      establecerMensajeEstado(
        `${esEducacion ? "Sesiones" : "Jornadas"} del ${respuesta.fecha_objetivo}: ${
          respuesta.cantidad_creadas
        } nuevas, ${respuesta.cantidad_existentes} existentes.`
      );
      await alRecargarTodo();
    } catch (errorGeneracion) {
      establecerMensajeError(
        errorGeneracion instanceof Error
          ? errorGeneracion.message
          : "No se pudieron generar sesiones."
      );
    }
  }

  /** Crea un nuevo grupo escolar o área/departamento empresarial. */
  async function manejarCrearGrupo(evento: FormEvent) {
    evento.preventDefault();
    if (!nombreGrupo.trim() || !codigoGrupo.trim()) return;
    establecerMensajeError(null);
    establecerMensajeEstado(null);
    try {
      await clienteApi.crearGrupo({
        id_organizacion: organizacion.id,
        nombre: nombreGrupo.trim(),
        codigo: codigoGrupo.trim(),
        ...(esEmpresa && idTurnoDefectoGrupo
          ? { id_turno_laboral_defecto: Number(idTurnoDefectoGrupo) }
          : {}),
      });
      establecerNombreGrupo("");
      establecerCodigoGrupo("");
      establecerIdTurnoDefectoGrupo("");
      establecerMensajeEstado(
        esEmpresa ? "Área / departamento creado." : "Grupo creado."
      );
      await alRecargarTodo();
    } catch (errorCreacion) {
      establecerMensajeError(
        errorCreacion instanceof Error
          ? errorCreacion.message
          : "No se pudo crear el registro."
      );
    }
  }

  /** Elimina un grupo o departamento existente por identificador. */
  async function manejarEliminarGrupo(idGrupo: number) {
    await clienteApi.eliminarGrupo(idGrupo);
    await alRecargarTodo();
  }

  /** Abre manualmente una nueva sesión vinculada opcionalmente a curso, turno o grupo. */
  async function manejarCrearSesion(evento: FormEvent) {
    evento.preventDefault();
    if (!tituloSesion.trim()) return;
    establecerMensajeError(null);
    try {
      await clienteApi.crearSesion({
        id_organizacion: organizacion.id,
        id_grupo: !idCursoSesion && idGrupoSesion ? Number(idGrupoSesion) : null,
        id_asignacion_curso: idCursoSesion ? Number(idCursoSesion) : null,
        id_turno_laboral: esEmpresa && idTurnoSesion ? Number(idTurnoSesion) : null,
        titulo: tituloSesion.trim(),
        hora_inicio_esperada: horaInicioEsperada || null,
      });
      establecerTituloSesion("");
      establecerIdCursoSesion("");
      establecerIdTurnoSesion("");
      establecerHoraInicioEsperada("");
      await alRecargarTodo();
    } catch (errorSesion) {
      establecerMensajeError(
        errorSesion instanceof Error ? errorSesion.message : "No se pudo abrir la sesión."
      );
    }
  }

  /** Cierra una sesión abierta para impedir nuevos registros en ella. */
  async function manejarCerrarSesion(idSesion: number) {
    await clienteApi.cerrarSesion(idSesion);
    await alRecargarTodo();
  }

  /** Registra una asistencia manual de respaldo en caso de falla física o excepción. */
  async function manejarAsistenciaManual(evento: FormEvent) {
    evento.preventDefault();
    if (!idSesionManual || !idPersonaManual) return;
    establecerMensajeError(null);
    try {
      await clienteApi.crearAsistenciaManual({
        id_sesion: Number(idSesionManual),
        id_persona: Number(idPersonaManual),
        tipo_evento: tipoEventoManual,
        estado: "manual",
        notas: notasManuales.trim() || undefined,
      });
      establecerNotasManuales("");
      establecerMensajeEstado("Asistencia manual registrada.");
      await alRecargarTodo();
    } catch (errorManual) {
      establecerMensajeError(
        errorManual instanceof Error
          ? errorManual.message
          : "No se pudo registrar asistencia manual."
      );
    }
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">
            {esDocente ? "Mis Sesiones e Historial" : "Grupos, Sesiones e Historial"}
          </h2>
          <p className="text-sm text-slate-400">
            {esDocente
              ? "Sesiones y registros de tus asignaturas asignadas"
              : "Administra materias/departamentos, sesiones de asistencia y respaldo manual"}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {(puedeGenerarAcademicas ||
            (puedeGenerarEmpresariales && turnosLaborales.length > 0)) && (
            <button
              type="button"
              onClick={() => void manejarGenerarSesionesHoy()}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-emerald-600 hover:bg-emerald-500 text-white"
            >
              <CalendarCheck className="w-4 h-4" />
              {esEducacion ? "Generar sesiones de hoy" : "Generar jornadas de hoy"}
            </button>
          )}
          <button
            type="button"
            onClick={() =>
              void clienteApi.descargarCsv(
                organizacion.id,
                idSesionFiltro ? Number(idSesionFiltro) : null
              )
            }
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-indigo-600 hover:bg-indigo-500 text-white"
          >
            <Download className="w-4 h-4" />
            Descargar CSV
          </button>
        </div>
      </div>

      {mensajeEstado && (
        <div className="rounded-xl bg-emerald-500/15 border border-emerald-500/40 px-4 py-2.5 text-xs text-emerald-200">
          {mensajeEstado}
        </div>
      )}
      {mensajeError && (
        <div className="rounded-xl bg-red-500/15 border border-red-500/40 px-4 py-2.5 text-xs text-red-200">
          {mensajeError}
        </div>
      )}

      {/* Grupos / Departamentos y Sesiones */}
      <div className={`grid grid-cols-1 ${esDocente ? "" : "lg:grid-cols-2"} gap-6`}>
        {!esDocente && (
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
            <h3 className="font-semibold text-base">
              {organizacion.modo === "education"
                ? "Grupos / Materias"
                : "Áreas / Departamentos"}
            </h3>

            {puedeGestionarGrupos && (
              <form
                onSubmit={manejarCrearGrupo}
                className="grid grid-cols-2 sm:grid-cols-4 gap-2.5"
              >
                <input
                  type="text"
                  required
                  value={nombreGrupo}
                  onChange={(evento) => establecerNombreGrupo(evento.target.value)}
                  placeholder={esEmpresa ? "Nombre del área / departamento" : "Nombre"}
                  className="col-span-2 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                />
                <input
                  type="text"
                  required
                  value={codigoGrupo}
                  onChange={(evento) => establecerCodigoGrupo(evento.target.value)}
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
                {esEmpresa ? (
                  turnosLaborales.some((turno) => turno.esta_activo) ? (
                    <div className="col-span-2 sm:col-span-4">
                      <label className="block text-[11px] text-slate-400 mb-1">
                        Turno laboral por defecto (opcional)
                      </label>
                      <select
                        value={idTurnoDefectoGrupo}
                        onChange={(evento) =>
                          establecerIdTurnoDefectoGrupo(evento.target.value)
                        }
                        className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm"
                      >
                        <option value="">
                          Sin turno por defecto (definir por empleado)
                        </option>
                        {turnosLaborales
                          .filter((turno) => turno.esta_activo)
                          .map((turno) => (
                            <option key={turno.id} value={turno.id}>
                              {turno.nombre} ({turno.hora_inicio}–{turno.hora_fin}
                              {turno.cruza_medianoche ? " 🌙" : ""})
                            </option>
                          ))}
                      </select>
                    </div>
                  ) : (
                    <p className="col-span-2 sm:col-span-4 text-[11px] text-slate-500">
                      Los horarios laborales se configuran en Turnos y Jornadas.
                    </p>
                  )
                ) : (
                  <p className="col-span-2 sm:col-span-4 text-[11px] text-slate-500">
                    Los horarios y materias se gestionan en Estructura Académica.
                  </p>
                )}
              </form>
            )}

            <div className="space-y-2 max-h-56 overflow-y-auto">
              {grupos.map((grupo) => {
                const turnoVinculado = esEmpresa
                  ? turnosLaborales.find(
                      (turno) => turno.id === grupo.id_turno_laboral_defecto
                    )
                  : null;
                const etiquetaPeriodo = esEducacion
                  ? formatearEtiquetaPeriodoGrupo(grupo.semestre, grupo.tipo_periodo)
                  : null;
                return (
                  <div
                    key={grupo.id}
                    className="flex items-center justify-between px-3.5 py-2.5 rounded-xl bg-slate-800/50 border border-slate-800"
                  >
                    <div>
                      <p className="text-sm font-medium">
                        {grupo.nombre}{" "}
                        <span className="text-xs text-slate-400">({grupo.codigo})</span>
                      </p>
                      <p className="text-xs text-slate-500">
                        {esEmpresa ? (
                          <>
                            {grupo.cantidad_integrantes} integrantes ·{" "}
                            {grupo.nombre_turno_laboral_defecto
                              ? `Turno por defecto: ${grupo.nombre_turno_laboral_defecto}${
                                  turnoVinculado
                                    ? ` (${turnoVinculado.hora_inicio}–${turnoVinculado.hora_fin})`
                                    : ""
                                }`
                              : "Sin turno por defecto"}
                          </>
                        ) : (
                          <>
                            {grupo.nombre_carrera ? `${grupo.nombre_carrera} · ` : ""}
                            {etiquetaPeriodo ? `${etiquetaPeriodo} · ` : ""}
                            {grupo.cantidad_integrantes} integrantes ·{" "}
                            {grupo.cantidad_cursos} materias
                            {grupo.aula_defecto ? ` · Aula ${grupo.aula_defecto}` : ""}
                          </>
                        )}
                      </p>
                    </div>
                    {puedeGestionarGrupos && (
                      <button
                        type="button"
                        onClick={() => void manejarEliminarGrupo(grupo.id)}
                        className="p-1.5 rounded-md text-slate-400 hover:text-red-400 hover:bg-red-500/10"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
          <h3 className="font-semibold text-base">Sesiones de Asistencia</h3>

          <form
            onSubmit={manejarCrearSesion}
            className="grid grid-cols-1 sm:grid-cols-3 gap-2.5"
          >
            {esEducacion && (
              <select
                required={esDocente}
                value={idCursoSesion}
                onChange={(evento) => {
                  const valor = evento.target.value;
                  establecerIdCursoSesion(valor);
                  if (valor && !tituloSesion.trim()) {
                    const cursoCoincidente = cursos.find(
                      (curso) => String(curso.id) === valor
                    );
                    if (cursoCoincidente) {
                      establecerTituloSesion(
                        `${cursoCoincidente.nombre_materia} — ${cursoCoincidente.nombre_grupo}`
                      );
                    }
                  }
                }}
                className="sm:col-span-3 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              >
                <option value="">
                  {esDocente
                    ? "Selecciona asignatura asignada..."
                    : "Opcional: vincular a asignatura de curso"}
                </option>
                {cursos.map((curso) => (
                  <option key={curso.id} value={curso.id}>
                    {curso.nombre_materia} ({curso.codigo_materia}) · {curso.nombre_grupo}
                  </option>
                ))}
              </select>
            )}
            {esEmpresa && turnosLaborales.length > 0 && (
              <select
                value={idTurnoSesion}
                onChange={(evento) => {
                  const valor = evento.target.value;
                  establecerIdTurnoSesion(valor);
                  const turnoCoincidente = turnosLaborales.find(
                    (turno) => String(turno.id) === valor
                  );
                  if (turnoCoincidente) {
                    if (!tituloSesion.trim()) {
                      establecerTituloSesion(
                        `${turnoCoincidente.nombre} (${turnoCoincidente.hora_inicio}-${turnoCoincidente.hora_fin})`
                      );
                    }
                    if (!horaInicioEsperada) {
                      establecerHoraInicioEsperada(turnoCoincidente.hora_inicio);
                    }
                  }
                }}
                className="sm:col-span-3 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              >
                <option value="">Opcional: vincular a turno laboral</option>
                {turnosLaborales.map((turno) => (
                  <option key={turno.id} value={turno.id}>
                    {turno.nombre} ({turno.hora_inicio}–{turno.hora_fin}
                    {turno.cruza_medianoche ? " 🌙" : ""})
                  </option>
                ))}
              </select>
            )}
            <input
              type="text"
              required
              value={tituloSesion}
              onChange={(evento) => establecerTituloSesion(evento.target.value)}
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
            {!esDocente && (
              <select
                value={idGrupoSesion}
                disabled={Boolean(idCursoSesion)}
                onChange={(evento) => establecerIdGrupoSesion(evento.target.value)}
                className="sm:col-span-2 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm disabled:opacity-50"
              >
                <option value="">Sin grupo específico</option>
                {grupos.map((grupo) => (
                  <option key={grupo.id} value={grupo.id}>
                    {grupo.nombre}
                  </option>
                ))}
              </select>
            )}
            <input
              type="time"
              value={horaInicioEsperada}
              onChange={(evento) => establecerHoraInicioEsperada(evento.target.value)}
              className={`${
                esDocente ? "sm:col-span-3" : ""
              } bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm`}
              title="Hora esperada de inicio"
            />
          </form>

          <div className="space-y-2 max-h-56 overflow-y-auto">
            {sesiones.map((sesion) => (
              <div
                key={sesion.id}
                className="flex items-center justify-between px-3.5 py-2.5 rounded-xl bg-slate-800/50 border border-slate-800"
              >
                <div>
                  <p className="text-sm font-medium">{sesion.titulo}</p>
                  {sesion.nombre_materia && (
                    <p className="text-[11px] text-indigo-300 mt-0.5">
                      {sesion.nombre_materia}
                      {sesion.nombre_grupo ? ` · ${sesion.nombre_grupo}` : ""}
                      {sesion.nombre_docente ? ` · ${sesion.nombre_docente}` : ""}
                    </p>
                  )}
                  {sesion.nombre_turno_laboral && (
                    <p className="text-[11px] text-indigo-300 mt-0.5">
                      Turno: {sesion.nombre_turno_laboral}
                      {sesion.codigo_turno_laboral
                        ? ` (${sesion.codigo_turno_laboral})`
                        : ""}
                      {sesion.turno_cruza_medianoche ? " 🌙" : ""}
                    </p>
                  )}
                  <p className="text-xs text-slate-500">
                    {sesion.fecha_sesion} · {sesion.cantidad_eventos} eventos ·{" "}
                    <span
                      className={
                        sesion.estado === "open" ? "text-emerald-400" : "text-slate-400"
                      }
                    >
                      {sesion.estado === "open" ? "Abierta" : "Cerrada"}
                    </span>
                  </p>
                </div>
                {sesion.estado === "open" && (
                  <button
                    type="button"
                    onClick={() => void manejarCerrarSesion(sesion.id)}
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

      {/* Registro manual de respaldo */}
      <form
        onSubmit={manejarAsistenciaManual}
        className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3"
      >
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-base">Registro Manual de Respaldo</h3>
          {mensajeEstado && (
            <span className="text-xs text-emerald-300">{mensajeEstado}</span>
          )}
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
          <select
            required
            value={idSesionManual}
            onChange={(evento) => {
              establecerIdSesionManual(evento.target.value);
              establecerIdPersonaManual("");
            }}
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
          >
            <option value="">Selecciona sesión abierta...</option>
            {sesionesAbiertas.map((sesion) => (
              <option key={sesion.id} value={sesion.id}>
                {sesion.titulo}
              </option>
            ))}
          </select>

          <select
            required
            value={idPersonaManual}
            onChange={(evento) => establecerIdPersonaManual(evento.target.value)}
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
          >
            <option value="">Selecciona persona...</option>
            {opcionesPersonaManual.map((persona) => (
              <option key={persona.id} value={persona.id}>
                {persona.nombre_completo} ({persona.identificador_externo})
              </option>
            ))}
          </select>

          <select
            value={tipoEventoManual}
            onChange={(evento) =>
              establecerTipoEventoManual(
                evento.target.value as "present" | "check_in" | "check_out"
              )
            }
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
          >
            <option value="present">Asistencia</option>
            <option value="check_in">Entrada</option>
            <option value="check_out">Salida</option>
          </select>

          <input
            type="text"
            value={notasManuales}
            onChange={(evento) => establecerNotasManuales(evento.target.value)}
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
            value={idSesionFiltro}
            onChange={(evento) => establecerIdSesionFiltro(evento.target.value)}
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm"
          >
            <option value="">Todas las sesiones</option>
            {sesiones.map((sesion) => (
              <option key={sesion.id} value={sesion.id}>
                {sesion.titulo}
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
              {eventosFiltrados.map((evento) => (
                <tr key={evento.id} className="hover:bg-slate-800/30">
                  <td className="py-2.5 pr-3 text-xs text-slate-300">
                    {new Date(evento.fecha_hora).toLocaleString()}
                  </td>
                  <td className="py-2.5 px-3 text-xs text-slate-400">
                    {evento.titulo_sesion}
                  </td>
                  <td className="py-2.5 px-3 font-medium">
                    {evento.nombre_persona}{" "}
                    <span className="text-xs text-slate-500">
                      ({evento.identificador_externo_persona})
                    </span>
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
                  <td className="py-2.5 px-3 text-xs">
                    <span
                      className={
                        evento.estado === "on_time"
                          ? "text-emerald-300"
                          : evento.estado === "late"
                            ? "text-amber-300"
                            : evento.estado === "early_exit"
                              ? "text-orange-300"
                              : "text-sky-300"
                      }
                    >
                      {evento.estado === "on_time"
                        ? "A tiempo"
                        : evento.estado === "late"
                          ? "Retardo"
                          : evento.estado === "early_exit"
                            ? "Salida anticipada"
                            : "Manual"}
                    </span>
                    {evento.minutos_retardo !== null && evento.minutos_retardo > 0 && (
                      <span className="block text-[11px] text-amber-400">
                        +{evento.minutos_retardo} min
                      </span>
                    )}
                    {evento.minutos_salida_anticipada !== null &&
                      evento.minutos_salida_anticipada > 0 && (
                        <span className="block text-[11px] text-orange-400">
                          -{evento.minutos_salida_anticipada} min
                        </span>
                      )}
                    {evento.minutos_trabajados !== null && (
                      <span className="block text-[11px] text-slate-400">
                        {evento.minutos_trabajados} min trabajados
                      </span>
                    )}
                  </td>
                  <td className="py-2.5 px-3 text-xs text-slate-400">
                    {evento.modo_captura}
                  </td>
                  <td className="py-2.5 pl-3 text-right text-xs">
                    {evento.puntaje_confianza !== null
                      ? `${(evento.puntaje_confianza * 100).toFixed(1)}%`
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
