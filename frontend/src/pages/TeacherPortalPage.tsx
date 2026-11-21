/**
 * Portal exclusivo para usuarios con rol docente (`teacher`).
 * Muestra la clase en curso o próxima de hoy, la agenda semanal del día y
 * el listado de asignaturas y grupos asignados para abrir el kiosco con un clic.
 */
import { useCallback, useEffect, useState } from "react";
import {
  BookOpen,
  CalendarClock,
  Clock,
  GraduationCap,
  RefreshCw,
  ScanFace,
  Users,
} from "lucide-react";
import { clienteApi } from "../lib/api";
import type {
  Organizacion,
  RespuestaAgendaDocente,
  UsuarioAutenticado,
} from "../types/api";

/** Propiedades recibidas por `PaginaPortalDocente` desde la aplicación raíz. */
interface PropiedadesPaginaPortalDocente {
  /** Docente autenticado actualmente en sesión. */
  usuarioActual: UsuarioAutenticado;
  /** Organización educativa seleccionada como contexto. */
  organizacion: Organizacion;
  /** Callback para refrescar sesiones y catálogos tras abrir pase de lista. */
  alRecargarTodo: () => Promise<void>;
  /** Callback para navegar al kiosco con una sesión de clase recién abierta. */
  alAbrirSesionEnKiosco: (idSesion: number) => void;
}

/** Nombres de los días de la semana indexados de lunes (0) a domingo (6). */
const NOMBRES_DIAS = [
  "Lunes",
  "Martes",
  "Miércoles",
  "Jueves",
  "Viernes",
  "Sábado",
  "Domingo",
];

/**
 * Obtiene la fecha (`YYYY-MM-DD`) y hora local (`HH:MM`) del dispositivo para
 * calcular en servidor cuál bloque horario está en curso o próximo.
 */
function obtenerFechaYHoraLocal(): { fechaObjetivo: string; horaActual: string } {
  const ahora = new Date();
  const anio = ahora.getFullYear();
  const mes = String(ahora.getMonth() + 1).padStart(2, "0");
  const dia = String(ahora.getDate()).padStart(2, "0");
  const horas = String(ahora.getHours()).padStart(2, "0");
  const minutos = String(ahora.getMinutes()).padStart(2, "0");
  return { fechaObjetivo: `${anio}-${mes}-${dia}`, horaActual: `${horas}:${minutos}` };
}

/**
 * Vista personalizada del docente con acceso restringido únicamente a sus
 * materias, horarios y grupos asignados.
 */
export function PaginaPortalDocente({
  usuarioActual,
  organizacion,
  alRecargarTodo,
  alAbrirSesionEnKiosco,
}: PropiedadesPaginaPortalDocente) {
  const [agenda, establecerAgenda] = useState<RespuestaAgendaDocente | null>(null);
  const [cargando, establecerCargando] = useState(true);
  const [claveIniciando, establecerClaveIniciando] = useState<string | null>(null);
  const [mensajeError, establecerMensajeError] = useState<string | null>(null);

  /** Consulta al backend la agenda diaria y cursos asignados al docente actual. */
  const cargarAgenda = useCallback(async () => {
    establecerCargando(true);
    establecerMensajeError(null);
    try {
      const { fechaObjetivo, horaActual } = obtenerFechaYHoraLocal();
      const respuesta = await clienteApi.obtenerAgendaDocente({
        id_organizacion: organizacion.id,
        fecha_objetivo: fechaObjetivo,
        hora_actual: horaActual,
      });
      establecerAgenda(respuesta);
    } catch (errorCarga) {
      establecerMensajeError(
        errorCarga instanceof Error
          ? errorCarga.message
          : "No se pudo cargar tu agenda docente."
      );
    } finally {
      establecerCargando(false);
    }
  }, [organizacion.id]);

  useEffect(() => {
    void cargarAgenda();
  }, [cargarAgenda]);

  /**
   * Crea o reutiliza la sesión del día para la asignatura/bloque elegido y
   * redirige al kiosco biométrico en vivo.
   */
  async function manejarInicioAsistencia(
    idCurso: number,
    idHorario?: number | null,
    claveBoton?: string
  ) {
    establecerClaveIniciando(claveBoton ?? `curso-${idCurso}`);
    establecerMensajeError(null);
    try {
      const { fechaObjetivo } = obtenerFechaYHoraLocal();
      const sesionCreada = await clienteApi.iniciarSesionCurso(idCurso, {
        id_horario: idHorario ?? null,
        fecha_sesion: agenda?.fecha_objetivo ?? fechaObjetivo,
      });
      await alRecargarTodo();
      alAbrirSesionEnKiosco(sesionCreada.id);
    } catch (errorApertura) {
      establecerMensajeError(
        errorApertura instanceof Error
          ? errorApertura.message
          : "No se pudo abrir la sesión de clase."
      );
    } finally {
      establecerClaveIniciando(null);
    }
  }

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <BookOpen className="w-6 h-6 text-indigo-400" />
            Mi Agenda Docente
          </h2>
          <p className="text-sm text-slate-400">
            Hola, <strong className="text-slate-200">{usuarioActual.nombre_completo}</strong> ·
            Acceso exclusivo a tus asignaturas y grupos asignados
          </p>
        </div>

        <button
          type="button"
          onClick={() => void cargarAgenda()}
          className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-medium"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          Actualizar horario
        </button>
      </div>

      {mensajeError && (
        <div className="rounded-xl bg-red-500/15 border border-red-500/40 px-4 py-3 text-sm text-red-200">
          {mensajeError}
        </div>
      )}

      {cargando ? (
        <div className="py-12 text-center text-sm text-slate-400">Cargando tu horario...</div>
      ) : !agenda ? null : (
        <>
          {/* Tarjeta destacada: tu clase en curso o próxima inmediata */}
          {agenda.bloque_actual ? (
            <div className="rounded-3xl bg-gradient-to-br from-indigo-950/80 via-slate-900 to-slate-900 border border-indigo-500/40 p-6 flex flex-col md:flex-row md:items-center justify-between gap-5 shadow-lg">
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <span
                    className={`px-2.5 py-0.5 rounded-full text-xs font-semibold ${
                      agenda.bloque_actual.estado_bloque === "in_progress"
                        ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                        : "bg-amber-500/20 text-amber-300 border border-amber-500/40"
                    }`}
                  >
                    {agenda.bloque_actual.estado_bloque === "in_progress"
                      ? "Tu clase ahora (En curso)"
                      : "Próxima clase de hoy"}
                  </span>
                  <span className="text-xs text-slate-400">
                    {agenda.bloque_actual.hora_inicio} – {agenda.bloque_actual.hora_fin}
                    {agenda.bloque_actual.aula ? ` · ${agenda.bloque_actual.aula}` : ""}
                  </span>
                </div>

                <h3 className="text-2xl font-bold tracking-tight">
                  {agenda.bloque_actual.nombre_materia}{" "}
                  <span className="text-base font-normal text-indigo-300">
                    ({agenda.bloque_actual.codigo_materia})
                  </span>
                </h3>

                <p className="text-sm text-slate-300">
                  Grupo <strong>{agenda.bloque_actual.nombre_grupo}</strong>
                  {agenda.bloque_actual.nombre_carrera
                    ? ` · ${agenda.bloque_actual.nombre_carrera}`
                    : ""}{" "}
                  · {agenda.bloque_actual.cantidad_estudiantes} alumnos inscritos
                </p>
              </div>

              <button
                type="button"
                disabled={claveIniciando === `hero-${agenda.bloque_actual.id_horario}`}
                onClick={() =>
                  void manejarInicioAsistencia(
                    agenda.bloque_actual!.id_asignacion_curso,
                    agenda.bloque_actual!.id_horario,
                    `hero-${agenda.bloque_actual!.id_horario}`
                  )
                }
                className="inline-flex items-center justify-center gap-2 px-6 py-3.5 rounded-2xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-semibold text-sm shrink-0 shadow-md"
              >
                <ScanFace className="w-5 h-5" />
                {claveIniciando === `hero-${agenda.bloque_actual.id_horario}`
                  ? "Abriendo kiosco..."
                  : "Tomar asistencia ahora"}
              </button>
            </div>
          ) : (
            <div className="rounded-2xl bg-slate-900 border border-slate-800 p-5 text-sm text-slate-400">
              No tienes clases programadas activas o próximas para lo que resta de hoy (
              <span className="text-slate-200">{agenda.fecha_objetivo}</span>). Aún puedes abrir el
              pase de lista directamente desde tus materias asignadas abajo.
            </div>
          )}

          {/* Lista de bloques horarios de hoy */}
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3">
            <h3 className="font-semibold text-base flex items-center gap-2">
              <CalendarClock className="w-4 h-4 text-indigo-400" />
              Clases de hoy ({agenda.bloques_hoy.length})
            </h3>

            {agenda.bloques_hoy.length === 0 ? (
              <p className="text-xs text-slate-500 py-3">
                Hoy (
                {NOMBRES_DIAS[(new Date(`${agenda.fecha_objetivo}T12:00:00`).getDay() + 6) % 7]}) no
                tienes bloques en tu horario semanal.
              </p>
            ) : (
              <div className="space-y-2.5">
                {agenda.bloques_hoy.map((bloque) => {
                  const claveBloque = `bloque-${bloque.id_horario}`;
                  return (
                    <div
                      key={bloque.id_horario}
                      className="rounded-xl bg-slate-800/50 border border-slate-800 px-4 py-3 flex flex-wrap items-center justify-between gap-3"
                    >
                      <div className="space-y-0.5">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-xs font-mono text-indigo-300">
                            {bloque.hora_inicio}–{bloque.hora_fin}
                          </span>
                          <span className="font-semibold text-sm">{bloque.nombre_materia}</span>
                          <span className="text-xs text-slate-400">· {bloque.nombre_grupo}</span>
                          <span
                            className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${
                              bloque.estado_bloque === "in_progress"
                                ? "bg-emerald-500/20 text-emerald-300"
                                : bloque.estado_bloque === "upcoming"
                                  ? "bg-amber-500/20 text-amber-300"
                                  : "bg-slate-700 text-slate-300"
                            }`}
                          >
                            {bloque.estado_bloque === "in_progress"
                              ? "En curso"
                              : bloque.estado_bloque === "upcoming"
                                ? "Próxima"
                                : "Finalizada"}
                          </span>
                        </div>
                        <p className="text-xs text-slate-400">
                          {bloque.aula ? `${bloque.aula} · ` : ""}
                          {bloque.cantidad_estudiantes} alumnos
                          {bloque.sesion
                            ? ` · Sesión ${
                                bloque.sesion.estado === "open" ? "abierta" : "cerrada"
                              } (${bloque.sesion.cantidad_eventos} registros)`
                            : ""}
                        </p>
                      </div>

                      <button
                        type="button"
                        disabled={claveIniciando === claveBloque}
                        onClick={() =>
                          void manejarInicioAsistencia(
                            bloque.id_asignacion_curso,
                            bloque.id_horario,
                            claveBloque
                          )
                        }
                        className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-xs font-semibold text-white"
                      >
                        <ScanFace className="w-3.5 h-3.5" />
                        {claveIniciando === claveBloque ? "Abriendo..." : "Tomar asistencia"}
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Catálogo completo de materias y grupos asignados al docente */}
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3">
            <h3 className="font-semibold text-base flex items-center gap-2">
              <GraduationCap className="w-4 h-4 text-indigo-400" />
              Mis materias y grupos ({agenda.cursos.length})
            </h3>

            {agenda.cursos.length === 0 ? (
              <p className="text-xs text-slate-500 py-4 text-center">
                Aún no tienes materias asignadas. Solicita al administrador de la institución que
                te asigne tus cursos en <em>Estructura Académica</em>.
              </p>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {agenda.cursos.map((curso) => {
                  const claveCurso = `curso-${curso.id}`;
                  return (
                    <div
                      key={curso.id}
                      className="rounded-xl bg-slate-800/40 border border-slate-800 p-4 space-y-3"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <span className="px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 text-[11px] font-semibold">
                            {curso.codigo_materia}
                          </span>
                          <h4 className="font-bold text-base mt-1">{curso.nombre_materia}</h4>
                          <p className="text-xs text-slate-400">
                            Grupo <strong className="text-slate-200">{curso.nombre_grupo}</strong>
                            {curso.nombre_carrera ? ` · ${curso.nombre_carrera}` : ""}
                          </p>
                        </div>
                        <span className="inline-flex items-center gap-1 text-xs text-slate-300 bg-slate-800 px-2.5 py-1 rounded-lg">
                          <Users className="w-3.5 h-3.5 text-indigo-400" />
                          {curso.cantidad_estudiantes}
                        </span>
                      </div>

                      <div className="space-y-1">
                        {curso.horarios.length === 0 ? (
                          <p className="text-[11px] text-slate-500">
                            Sin bloques semanales definidos
                          </p>
                        ) : (
                          curso.horarios.map((horario) => (
                            <p
                              key={horario.id}
                              className="text-xs text-slate-300 flex items-center gap-1.5"
                            >
                              <Clock className="w-3 h-3 text-slate-400" />
                              {NOMBRES_DIAS[horario.dia_semana] ?? `Día ${horario.dia_semana}`}{" "}
                              {horario.hora_inicio}–{horario.hora_fin}
                              {horario.aula ? ` · ${horario.aula}` : ""}
                            </p>
                          ))
                        )}
                      </div>

                      <button
                        type="button"
                        disabled={claveIniciando === claveCurso}
                        onClick={() => void manejarInicioAsistencia(curso.id, null, claveCurso)}
                        className="w-full inline-flex items-center justify-center gap-1.5 py-2 rounded-xl bg-emerald-600/20 border border-emerald-500/40 hover:bg-emerald-600/30 text-emerald-300 text-xs font-semibold"
                      >
                        <ScanFace className="w-3.5 h-3.5" />
                        {claveIniciando === claveCurso ? "Iniciando..." : "Abrir pase de lista"}
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
