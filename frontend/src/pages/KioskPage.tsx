/**
 * Kiosco Biométrico en Vivo de IdentIA.
 * Captura fotogramas periódicos desde WebRTC sin almacenar imágenes en disco,
 * los envía al backend ONNX (YuNet + SFace), dibuja el estado del rostro y
 * actualiza en tiempo real la bitácora reciente de asistencias.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Pause, Play, Volume2, VolumeX } from "lucide-react";
import {
  VistaCamara,
  type ControlVistaCamara,
  type EstadoCuadroRostro,
} from "../components/CameraView";
import { clienteApi } from "../lib/api";
import type {
  EventoAsistencia,
  Grupo,
  ModoAccion,
  Organizacion,
  RespuestaReconocerFrame,
  SesionAsistencia,
  UsuarioAutenticado,
} from "../types/api";

/** Propiedades recibidas por `PaginaKiosco` desde `Aplicacion`. */
interface PropiedadesPaginaKiosco {
  /** Usuario autenticado para distinguir reglas específicas del rol docente. */
  usuarioActual: UsuarioAutenticado;
  /** Organización activa sobre la que se ejecuta el reconocimiento. */
  organizacion: Organizacion;
  /** Catálogo de grupos o departamentos disponibles para filtrar alcance. */
  grupos: Grupo[];
  /** Lista de sesiones abiertas y cerradas de la organización. */
  sesiones: SesionAsistencia[];
  /** Eventos recientes mostrados en el panel lateral en vivo. */
  eventos: EventoAsistencia[];
  /** Sesión preseleccionada al abrir desde agenda docente o turnos. */
  idSesionInicial?: number | null;
  /** Callback para recargar los eventos cuando se confirma una nueva asistencia. */
  alRecargarEventos: () => Promise<void>;
}

/**
 * Emite un tono breve mediante Web Audio API cuando se registra una asistencia
 * válida, ignorando silenciosamente restricciones de reproducción del navegador.
 */
function reproducirPitidoExito() {
  try {
    const ConstructorAudio =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    if (!ConstructorAudio) return;
    const contextoAudio = new ConstructorAudio();
    const oscilador = contextoAudio.createOscillator();
    const ganancia = contextoAudio.createGain();
    oscilador.type = "sine";
    oscilador.frequency.setValueAtTime(880, contextoAudio.currentTime);
    ganancia.gain.setValueAtTime(0.06, contextoAudio.currentTime);
    ganancia.gain.exponentialRampToValueAtTime(0.001, contextoAudio.currentTime + 0.16);
    oscilador.connect(ganancia);
    ganancia.connect(contextoAudio.destination);
    oscilador.start();
    oscilador.stop(contextoAudio.currentTime + 0.16);
  } catch {
    // Silencio si el navegador bloquea la inicialización automática de AudioContext.
  }
}

/**
 * Renderiza el kiosco de reconocimiento continuo con selector de sesión,
 * filtro de grupo/departamento, modo de movimiento y feed reciente.
 */
export function PaginaKiosco({
  usuarioActual,
  organizacion,
  grupos,
  sesiones,
  eventos,
  idSesionInicial,
  alRecargarEventos,
}: PropiedadesPaginaKiosco) {
  const referenciaCamara = useRef<ControlVistaCamara | null>(null);
  const peticionEnCursoRef = useRef(false);
  const esDocente = usuarioActual.rol === "teacher";

  const [camaraLista, establecerCamaraLista] = useState(false);
  const [kioscoActivo, establecerKioscoActivo] = useState(true);
  const [sonidoHabilitado, establecerSonidoHabilitado] = useState(true);

  const [idSesionSeleccionada, establecerIdSesionSeleccionada] = useState<string>(
    idSesionInicial ? String(idSesionInicial) : ""
  );
  const [idGrupoSeleccionado, establecerIdGrupoSeleccionado] = useState<string>("");
  const [modoAccion, establecerModoAccion] = useState<ModoAccion>(
    organizacion.modo === "education" ? "present" : "auto"
  );

  const [ultimoResultado, establecerUltimoResultado] =
    useState<RespuestaReconocerFrame | null>(null);
  const [mensajeError, establecerMensajeError] = useState<string | null>(null);

  const sesionesAbiertas = sesiones.filter((sesion) => sesion.estado === "open");
  const sesionSeleccionada =
    sesionesAbiertas.find((sesion) => String(sesion.id) === idSesionSeleccionada) ?? null;

  // Reinicia selección de sesión y modo cuando cambia de organización.
  useEffect(() => {
    establecerModoAccion(organizacion.modo === "education" ? "present" : "auto");
    establecerIdSesionSeleccionada(idSesionInicial ? String(idSesionInicial) : "");
    establecerIdGrupoSeleccionado("");
    establecerUltimoResultado(null);
  }, [organizacion.id, organizacion.modo]);

  // Sincroniza preselección externa cuando se navega desde otra pestaña.
  useEffect(() => {
    if (idSesionInicial) {
      establecerIdSesionSeleccionada(String(idSesionInicial));
      establecerMensajeError(null);
    }
  }, [idSesionInicial]);

  // Para docentes, preselecciona automáticamente su primera sesión abierta si existe.
  useEffect(() => {
    if (esDocente && !idSesionSeleccionada && sesionesAbiertas.length > 0) {
      establecerIdSesionSeleccionada(String(sesionesAbiertas[0].id));
    }
  }, [esDocente, sesionesAbiertas, idSesionSeleccionada]);

  /**
   * Captura un fotograma de la cámara, consulta el endpoint de reconocimiento
   * y actualiza el recuadro facial y la bitácora si se grabó asistencia.
   */
  const ejecutarPasoReconocimiento = useCallback(async () => {
    if (!kioscoActivo || !camaraLista || peticionEnCursoRef.current) return;
    if (esDocente && !idSesionSeleccionada) return;
    const camara = referenciaCamara.current;
    if (!camara) return;

    peticionEnCursoRef.current = true;
    try {
      const blobImagen = await camara.capturarBlob();
      if (!blobImagen) return;

      const respuesta = await clienteApi.reconocerFrame({
        blobImagen,
        idOrganizacion: organizacion.id,
        idSesion: idSesionSeleccionada ? Number(idSesionSeleccionada) : null,
        idGrupo:
          !idSesionSeleccionada && idGrupoSeleccionado
            ? Number(idGrupoSeleccionado)
            : null,
        modoAccion,
      });
      establecerUltimoResultado(respuesta);
      establecerMensajeError(null);

      if (respuesta.accion_asistencia === "recorded") {
        if (sonidoHabilitado) reproducirPitidoExito();
        await alRecargarEventos();
      }
    } catch (errorPeticion) {
      establecerMensajeError(
        errorPeticion instanceof Error
          ? errorPeticion.message
          : "Error de conexión con la API."
      );
    } finally {
      peticionEnCursoRef.current = false;
    }
  }, [
    modoAccion,
    camaraLista,
    esDocente,
    kioscoActivo,
    alRecargarEventos,
    organizacion.id,
    idGrupoSeleccionado,
    idSesionSeleccionada,
    sonidoHabilitado,
  ]);

  // Temporizador de captura periódica (~450 ms) mientras el kiosco permanece activo.
  useEffect(() => {
    if (!kioscoActivo || !camaraLista) return;
    const temporizador = window.setInterval(() => {
      void ejecutarPasoReconocimiento();
    }, 450);
    return () => window.clearInterval(temporizador);
  }, [camaraLista, kioscoActivo, ejecutarPasoReconocimiento]);

  // Calcula el color y texto del recuadro delimitador según la última respuesta ONNX.
  let estadoCuadro: EstadoCuadroRostro = "idle";
  let etiquetaCuadro: string | undefined;

  if (ultimoResultado?.cuadro_rostro) {
    if (ultimoResultado.estado_coincidencia === "matched") {
      estadoCuadro =
        ultimoResultado.accion_asistencia === "recorded" ? "ok" : "warning";
      etiquetaCuadro = `${ultimoResultado.persona?.nombre_completo ?? "Identificado"} · ${(
        ultimoResultado.confianza * 100
      ).toFixed(0)}%`;
    } else if (ultimoResultado.estado_coincidencia === "unknown") {
      estadoCuadro = "error";
      etiquetaCuadro = "No reconocido";
    } else {
      estadoCuadro = "warning";
      if (ultimoResultado.estado_coincidencia === "ambiguous") {
        etiquetaCuadro = "Coincidencia ambigua";
      } else if (ultimoResultado.mensaje.includes("borrosa")) {
        etiquetaCuadro = "Imagen borrosa";
      } else if (ultimoResultado.mensaje.includes("Acércate")) {
        etiquetaCuadro = "Acércate más";
      } else if (ultimoResultado.mensaje.includes("Contraluz")) {
        etiquetaCuadro = "Contraluz fuerte";
      } else if (ultimoResultado.mensaje.includes("iluminación")) {
        etiquetaCuadro = "Poca luz";
      } else {
        etiquetaCuadro = "Calidad baja";
      }
    }
  }

  return (
    <div className="max-w-6xl mx-auto space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Kiosco Biométrico en Vivo</h2>
          <p className="text-sm text-slate-400">
            Detección y reconocimiento individual en tiempo real (YuNet + SFace ONNX)
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => establecerSonidoHabilitado((previo) => !previo)}
            className="p-2.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200"
            title={sonidoHabilitado ? "Silenciar aviso" : "Activar aviso sonoro"}
          >
            {sonidoHabilitado ? (
              <Volume2 className="w-4 h-4" />
            ) : (
              <VolumeX className="w-4 h-4" />
            )}
          </button>

          <button
            type="button"
            onClick={() => establecerKioscoActivo((activo) => !activo)}
            className={`inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-colors ${
              kioscoActivo
                ? "bg-amber-600 hover:bg-amber-500 text-white"
                : "bg-emerald-600 hover:bg-emerald-500 text-white"
            }`}
          >
            {kioscoActivo ? (
              <>
                <Pause className="w-4 h-4" />
                Pausar Kiosco
              </>
            ) : (
              <>
                <Play className="w-4 h-4" />
                Reanudar Kiosco
              </>
            )}
          </button>
        </div>
      </div>

      {/* Controles de sesión, alcance por grupo y modo de registro */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 bg-slate-900 border border-slate-800 rounded-2xl p-4">
        <div>
          <label className="block text-xs text-slate-400 mb-1">Sesión activa</label>
          <select
            value={idSesionSeleccionada}
            onChange={(evento) => establecerIdSesionSeleccionada(evento.target.value)}
            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
          >
            {!esDocente && <option value="">Automática del día</option>}
            {esDocente && sesionesAbiertas.length === 0 && (
              <option value="">Sin sesiones abiertas</option>
            )}
            {sesionesAbiertas.map((sesion) => (
              <option key={sesion.id} value={sesion.id}>
                {sesion.titulo}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs text-slate-400 mb-1">Alcance por grupo</label>
          <select
            value={idGrupoSeleccionado}
            disabled={esDocente || Boolean(idSesionSeleccionada)}
            onChange={(evento) => establecerIdGrupoSeleccionado(evento.target.value)}
            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm disabled:opacity-50"
          >
            <option value="">Toda la organización</option>
            {grupos.map((grupo) => (
              <option key={grupo.id} value={grupo.id}>
                {grupo.nombre} ({grupo.codigo})
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs text-slate-400 mb-1">Tipo de movimiento</label>
          <select
            value={modoAccion}
            onChange={(evento) => establecerModoAccion(evento.target.value as ModoAccion)}
            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
          >
            {organizacion.modo === "enterprise" ? (
              <>
                <option value="auto">Automático (Entrada ↔ Salida)</option>
                <option value="check_in">Solo Entrada (Check-in)</option>
                <option value="check_out">Solo Salida (Check-out)</option>
              </>
            ) : (
              <>
                <option value="present">Pase de lista (Presente)</option>
                <option value="auto">Automático</option>
              </>
            )}
          </select>
        </div>
      </div>

      {esDocente && !sesionSeleccionada && (
        <div className="rounded-xl bg-amber-500/15 border border-amber-500/40 px-4 py-3 text-sm text-amber-200">
          Para tomar asistencia como docente, primero abre una de tus materias desde{" "}
          <strong>Mi Agenda Docente</strong> (o selecciona una sesión abierta arriba).
        </div>
      )}

      {sesionSeleccionada && sesionSeleccionada.nombre_materia && (
        <div className="rounded-xl bg-indigo-500/15 border border-indigo-500/40 px-4 py-2.5 text-xs text-indigo-200 flex flex-wrap items-center gap-3">
          <span>
            Materia: <strong>{sesionSeleccionada.nombre_materia}</strong>
            {sesionSeleccionada.codigo_materia
              ? ` (${sesionSeleccionada.codigo_materia})`
              : ""}
          </span>
          {sesionSeleccionada.nombre_grupo && (
            <span>
              · Grupo: <strong>{sesionSeleccionada.nombre_grupo}</strong>
            </span>
          )}
          {sesionSeleccionada.nombre_carrera && (
            <span>· {sesionSeleccionada.nombre_carrera}</span>
          )}
          {sesionSeleccionada.nombre_docente && (
            <span>
              · Docente: <strong>{sesionSeleccionada.nombre_docente}</strong>
            </span>
          )}
        </div>
      )}

      {sesionSeleccionada && sesionSeleccionada.nombre_turno_laboral && (
        <div className="rounded-xl bg-indigo-500/15 border border-indigo-500/40 px-4 py-2.5 text-xs text-indigo-200 flex flex-wrap items-center gap-3">
          <span>
            Turno laboral: <strong>{sesionSeleccionada.nombre_turno_laboral}</strong>
            {sesionSeleccionada.codigo_turno_laboral
              ? ` (${sesionSeleccionada.codigo_turno_laboral})`
              : ""}
          </span>
          {sesionSeleccionada.hora_inicio_esperada && (
            <span>
              · Entrada esperada:{" "}
              <strong>{sesionSeleccionada.hora_inicio_esperada}</strong>
            </span>
          )}
          {sesionSeleccionada.turno_cruza_medianoche && (
            <span className="px-2 py-0.5 rounded-full bg-indigo-600/30 border border-indigo-400/30">
              🌙 Turno nocturno (cruza medianoche)
            </span>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* Vista de cámara y tarjeta de resultado del último fotograma */}
        <div className="lg:col-span-3 space-y-4">
          <VistaCamara
            ref={referenciaCamara}
            activa={kioscoActivo}
            cuadroRostro={ultimoResultado?.cuadro_rostro ?? null}
            estadoCuadro={estadoCuadro}
            etiqueta={etiquetaCuadro}
            alCambiarDisponibilidad={establecerCamaraLista}
            alOcurrirError={establecerMensajeError}
          />

          {mensajeError && (
            <div className="rounded-xl bg-red-500/15 border border-red-500/40 px-4 py-3 text-sm text-red-200">
              {mensajeError}
            </div>
          )}

          {ultimoResultado && (
            <div
              className={`rounded-2xl border p-4 flex items-center justify-between gap-4 ${
                ultimoResultado.accion_asistencia === "recorded"
                  ? "bg-emerald-500/10 border-emerald-500/40"
                  : ultimoResultado.estado_coincidencia === "unknown"
                    ? "bg-red-500/10 border-red-500/40"
                    : "bg-slate-900 border-slate-800"
              }`}
            >
              <div className="flex items-center gap-3.5 min-w-0">
                {ultimoResultado.persona?.avatar_base64 && (
                  <img
                    src={ultimoResultado.persona.avatar_base64}
                    alt={ultimoResultado.persona.nombre_completo}
                    className="w-12 h-12 rounded-full object-cover border border-slate-700 shrink-0"
                  />
                )}
                <div className="min-w-0">
                  <p className="font-semibold text-sm truncate">
                    {ultimoResultado.mensaje}
                  </p>
                  <p className="text-xs text-slate-400 mt-0.5">
                    Estado:{" "}
                    <span className="text-slate-200">
                      {ultimoResultado.estado_coincidencia}
                    </span>
                    {ultimoResultado.confianza > 0 && (
                      <>
                        {" "}
                        · Similitud: {(ultimoResultado.confianza * 100).toFixed(1)}%
                      </>
                    )}
                    {ultimoResultado.nombre_turno && (
                      <> · Turno: {ultimoResultado.nombre_turno}</>
                    )}
                    {ultimoResultado.minutos_retardo !== null &&
                      ultimoResultado.minutos_retardo > 0 && (
                        <span className="text-amber-300">
                          {" "}
                          · Retardo: +{ultimoResultado.minutos_retardo} min
                        </span>
                      )}
                    {ultimoResultado.minutos_salida_anticipada !== null &&
                      ultimoResultado.minutos_salida_anticipada > 0 && (
                        <span className="text-orange-300">
                          {" "}
                          · Salida anticipada: -{ultimoResultado.minutos_salida_anticipada}{" "}
                          min
                        </span>
                      )}
                    {ultimoResultado.minutos_trabajados !== null && (
                      <> · Jornada: {ultimoResultado.minutos_trabajados} min</>
                    )}
                    {ultimoResultado.estado_coincidencia === "low_quality" &&
                      ultimoResultado.calidad && (
                        <>
                          {" "}
                          · Nitidez: {ultimoResultado.calidad.puntaje_nitidez} · Brillo:{" "}
                          {ultimoResultado.calidad.brillo}
                        </>
                      )}
                  </p>
                  {ultimoResultado.calidad?.contraluz_detectado && (
                    <span className="inline-block mt-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-amber-500/15 text-amber-300 border border-amber-500/30">
                      Contraluz detectado · compensación activa
                    </span>
                  )}
                </div>
              </div>
              <span className="text-xs font-mono text-slate-400 shrink-0">
                {ultimoResultado.latencia_ms.toFixed(0)} ms
              </span>
            </div>
          )}
        </div>

        {/* Feed lateral en tiempo real con los últimos 15 registros */}
        <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-2xl p-5 flex flex-col">
          <h3 className="font-semibold text-base mb-1">Registros Recientes</h3>
          <p className="text-xs text-slate-400 mb-4">
            Actualización automática al confirmar rostro
          </p>

          <div className="space-y-2.5 overflow-y-auto max-h-[460px] pr-1">
            {eventos.length === 0 ? (
              <p className="text-sm text-slate-500 py-8 text-center">
                Esperando el primer reconocimiento...
              </p>
            ) : (
              eventos.slice(0, 15).map((evento) => (
                <div
                  key={evento.id}
                  className="flex items-center justify-between gap-3 p-3 rounded-xl bg-slate-800/50 border border-slate-800"
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    {evento.avatar_base64_persona ? (
                      <img
                        src={evento.avatar_base64_persona}
                        alt={evento.nombre_persona}
                        className="w-9 h-9 rounded-full object-cover border border-slate-700 shrink-0"
                      />
                    ) : (
                      <div className="w-9 h-9 rounded-full bg-indigo-600/20 text-indigo-300 flex items-center justify-center text-xs font-bold shrink-0">
                        {evento.nombre_persona.slice(0, 1).toUpperCase()}
                      </div>
                    )}
                    <div className="min-w-0">
                      <p className="text-sm font-medium truncate">
                        {evento.nombre_persona}
                      </p>
                      <p className="text-[11px] text-slate-400">
                        {evento.tipo_evento === "check_in"
                          ? "Entrada"
                          : evento.tipo_evento === "check_out"
                            ? "Salida"
                            : "Presente"}{" "}
                        ·{" "}
                        {evento.estado === "on_time"
                          ? "A tiempo"
                          : evento.estado === "late"
                            ? "Retardo"
                            : evento.estado === "early_exit"
                              ? "Salida anticipada"
                              : "Manual"}
                        {evento.nombre_turno_laboral
                          ? ` · ${evento.nombre_turno_laboral}`
                          : ""}
                        {evento.minutos_trabajados !== null
                          ? ` · ${evento.minutos_trabajados} min`
                          : ""}
                      </p>
                    </div>
                  </div>
                  <span className="text-xs text-slate-400 shrink-0">
                    {new Date(evento.fecha_hora).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                      second: "2-digit",
                    })}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
