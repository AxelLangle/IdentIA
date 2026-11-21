/**
 * Módulo de Padrón de Personas y Asistente Guiado de Enrolamiento Facial (6 poses).
 * Permite registrar empleados o alumnos vinculados a departamentos/grupos escolares,
 * capturar las 6 poses faciales con validación geométrica e iluminación en vivo
 * (modo manual o auto-captura por estabilidad) y revocar biometría de forma auditable.
 */
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import {
  AlertTriangle,
  Camera,
  Check,
  CheckCircle2,
  KeyRound,
  Plus,
  RotateCcw,
  Search,
  ShieldAlert,
  Sparkles,
  Trash2,
  UserCheck,
  X,
} from "lucide-react";
import { VistaCamara, type ControlVistaCamara } from "../components/CameraView";
import { EntradaContrasena } from "../components/PasswordInput";
import {
  compararPeriodosNatural,
  formatearEtiquetaPeriodoGrupo,
  obtenerMetadatosPeriodo,
} from "../lib/academicPeriods";
import { clienteApi } from "../lib/api";
import type {
  AsignacionCurso,
  EtiquetaPose,
  Grupo,
  Organizacion,
  Persona,
  RespuestaEnrolarFrame,
  RolPersona,
  TurnoLaboral,
  UsuarioAutenticado,
} from "../types/api";

/** Propiedades recibidas por `PaginaEnrolamiento`. */
interface PropiedadesPaginaEnrolamiento {
  /** Usuario autenticado para determinar permisos de alta y eliminación. */
  usuarioActual: UsuarioAutenticado;
  /** Organización activa sobre la cual se administra el padrón. */
  organizacion: Organizacion;
  /** Lista de grupos escolares o áreas disponibles para asociar. */
  grupos: Grupo[];
  /** Personas actualmente cargadas en el padrón de la organización. */
  personas: Persona[];
  /** Callback para recargar la lista de personas y contadores tras enrolar o revocar. */
  alRecargarPersonas: () => Promise<void>;
}

/** Catálogo ordenado de las 6 poses requeridas para un perfil facial robusto. */
const POSES_REQUERIDAS: {
  clave: EtiquetaPose;
  titulo: string;
  etiquetaCorta: string;
  instruccion: string;
}[] = [
  {
    clave: "frontal",
    titulo: "1. Frontal",
    etiquetaCorta: "Frontal",
    instruccion: "Mira directamente al centro de la cámara con rostro nivelado.",
  },
  {
    clave: "left",
    titulo: "2. Izquierda",
    etiquetaCorta: "Izquierda",
    instruccion: "Gira suavemente la cabeza hacia tu izquierda manteniendo los ojos visibles.",
  },
  {
    clave: "right",
    titulo: "3. Derecha",
    etiquetaCorta: "Derecha",
    instruccion: "Gira suavemente la cabeza hacia tu derecha manteniendo los ojos visibles.",
  },
  {
    clave: "up",
    titulo: "4. Arriba",
    etiquetaCorta: "Arriba",
    instruccion: "Levanta ligeramente el mentón mirando un poco hacia arriba.",
  },
  {
    clave: "down",
    titulo: "5. Abajo",
    etiquetaCorta: "Abajo",
    instruccion: "Inclina suavemente la cabeza mirando ligeramente hacia abajo.",
  },
  {
    clave: "smile",
    titulo: "6. Sonrisa",
    etiquetaCorta: "Sonrisa",
    instruccion: "Mira al frente y sonríe de forma marcada y natural.",
  },
];

/** Número total de poses requeridas por perfil biométrico. */
const TOTAL_POSES = POSES_REQUERIDAS.length;

/**
 * Renderiza el directorio buscable de personas junto con el asistente interactivo
 * de captura de 6 poses y el modal de revocación protegida por contraseña.
 */
export function PaginaEnrolamiento({
  usuarioActual,
  organizacion,
  grupos,
  personas,
  alRecargarPersonas,
}: PropiedadesPaginaEnrolamiento) {
  const referenciaCamara = useRef<ControlVistaCamara | null>(null);
  const peticionEnCursoRef = useRef(false);
  const pausarHastaRef = useRef(0);
  const contadorEstabilidadRef = useRef(0);
  const vistasPreviasRef = useRef<Partial<Record<EtiquetaPose, string>>>({});

  const [busqueda, establecerBusqueda] = useState("");
  const [mostrarFormularioAlta, establecerMostrarFormularioAlta] = useState(false);

  // Estado del formulario de alta en el padrón.
  const [identificadorExterno, establecerIdentificadorExterno] = useState("");
  const [nombreCompleto, establecerNombreCompleto] = useState("");
  const [correo, establecerCorreo] = useState("");
  const [rolPersona, establecerRolPersona] = useState<RolPersona>(
    organizacion.modo === "education" ? "student" : "employee"
  );
  const [idsGruposSeleccionados, establecerIdsGruposSeleccionados] = useState<number[]>(
    []
  );
  const [consentimientoBiometrico, establecerConsentimientoBiometrico] = useState(true);
  const [errorFormulario, establecerErrorFormulario] = useState<string | null>(null);
  const [creandoPersona, establecerCreandoPersona] = useState(false);

  // Estado del asistente de enrolamiento guiado.
  const [idPersonaActiva, establecerIdPersonaActiva] = useState<number | null>(null);
  const [indicePose, establecerIndicePose] = useState(0);
  const [guardarAvatar, establecerGuardarAvatar] = useState(
    organizacion.guardar_avatar_por_defecto
  );
  const [camaraLista, establecerCamaraLista] = useState(false);
  const [capturando, establecerCapturando] = useState(false);
  const [capturaAutomatica, establecerCapturaAutomatica] = useState(false);
  const [conteoEstabilidad, establecerConteoEstabilidad] = useState(0);
  const [estadoEnrolamiento, establecerEstadoEnrolamiento] =
    useState<RespuestaEnrolarFrame | null>(null);
  const [errorEnrolamiento, establecerErrorEnrolamiento] = useState<string | null>(null);
  const [vistasPreviasPose, establecerVistasPreviasPose] = useState<
    Partial<Record<EtiquetaPose, string>>
  >({});
  const [bannerCompletado, establecerBannerCompletado] = useState<string | null>(null);

  // Estado del modal de revocación individual o por lote.
  const [seleccionadasRevocar, establecerSeleccionadasRevocar] = useState<number[]>([]);
  const [objetivosRevocar, establecerObjetivosRevocar] = useState<Persona[] | null>(null);
  const [secretoRevocacion, establecerSecretoRevocacion] = useState("");
  const [motivoRevocacion, establecerMotivoRevocacion] = useState("");
  const [errorRevocacion, establecerErrorRevocacion] = useState<string | null>(null);
  const [revocando, establecerRevocando] = useState(false);

  // Asignaciones académicas heredadas, turnos laborales y filtros auxiliares.
  const [cursos, establecerCursos] = useState<AsignacionCurso[]>([]);
  const [turnosLaborales, establecerTurnosLaborales] = useState<TurnoLaboral[]>([]);
  const [idTurnoSeleccionado, establecerIdTurnoSeleccionado] = useState<string>("");
  const [filtroCarreraFormulario, establecerFiltroCarreraFormulario] = useState<string>("");
  const [filtroGrupoLista, establecerFiltroGrupoLista] = useState<string>("");
  const [filtroTurnoLista, establecerFiltroTurnoLista] = useState<string>("");

  const puedeGestionarPersonas = [
    "superadmin",
    "org_admin",
    "supervisor",
    "operator",
  ].includes(usuarioActual.rol);
  const puedeEliminarPersonas = ["superadmin", "org_admin"].includes(usuarioActual.rol);

  const personaActiva =
    personas.find((persona) => persona.id === idPersonaActiva) ?? null;
  const poseActual = POSES_REQUERIDAS[indicePose] ?? POSES_REQUERIDAS[0];

  /** Libera las URL temporales (`blob:`) creadas para previsualizar poses en RAM. */
  const revocarTodasVistasPrevias = useCallback(() => {
    Object.values(vistasPreviasRef.current).forEach((url) => {
      if (url) URL.revokeObjectURL(url);
    });
    vistasPreviasRef.current = {};
    establecerVistasPreviasPose({});
  }, []);

  useEffect(() => {
    return () => {
      revocarTodasVistasPrevias();
    };
  }, [revocarTodasVistasPrevias]);

  // Carga materias asignadas a los grupos en organizaciones educativas.
  useEffect(() => {
    if (organizacion.modo !== "education" || usuarioActual.rol === "teacher") {
      establecerCursos([]);
      return;
    }
    let cancelado = false;
    clienteApi
      .listarCursos(organizacion.id)
      .then((lista) => {
        if (!cancelado) establecerCursos(lista);
      })
      .catch(() => {
        if (!cancelado) establecerCursos([]);
      });
    return () => {
      cancelado = true;
    };
  }, [usuarioActual.rol, organizacion.id, organizacion.modo]);

  // Carga turnos disponibles en organizaciones empresariales.
  useEffect(() => {
    if (organizacion.modo !== "enterprise") {
      establecerTurnosLaborales([]);
      return;
    }
    let cancelado = false;
    clienteApi
      .listarTurnosLaborales(organizacion.id)
      .then((lista) => {
        if (!cancelado) establecerTurnosLaborales(lista);
      })
      .catch(() => {
        if (!cancelado) establecerTurnosLaborales([]);
      });
    return () => {
      cancelado = true;
    };
  }, [organizacion.id, organizacion.modo]);

  // Reinicia estados locales al cambiar de organización activa.
  useEffect(() => {
    establecerRolPersona(organizacion.modo === "education" ? "student" : "employee");
    establecerGuardarAvatar(organizacion.guardar_avatar_por_defecto);
    establecerIdPersonaActiva(null);
    establecerCapturaAutomatica(false);
    establecerBannerCompletado(null);
    establecerSeleccionadasRevocar([]);
    establecerObjetivosRevocar(null);
    establecerIdTurnoSeleccionado("");
    establecerFiltroCarreraFormulario("");
    establecerFiltroGrupoLista("");
    establecerFiltroTurnoLista("");
    revocarTodasVistasPrevias();
  }, [
    organizacion.id,
    organizacion.modo,
    organizacion.guardar_avatar_por_defecto,
    revocarTodasVistasPrevias,
  ]);

  const personasFiltradas = personas.filter((persona) => {
    if (filtroGrupoLista && !persona.ids_grupos.includes(Number(filtroGrupoLista))) {
      return false;
    }
    if (organizacion.modo === "enterprise" && filtroTurnoLista) {
      if (
        filtroTurnoLista === "__none__" &&
        persona.id_turno_laboral_efectivo !== null
      ) {
        return false;
      }
      if (
        filtroTurnoLista !== "__none__" &&
        String(persona.id_turno_laboral_efectivo ?? "") !== filtroTurnoLista
      ) {
        return false;
      }
    }
    const consulta = busqueda.trim().toLowerCase();
    if (!consulta) return true;
    return (
      persona.nombre_completo.toLowerCase().includes(consulta) ||
      persona.identificador_externo.toLowerCase().includes(consulta)
    );
  });

  // Agrupación jerárquica Carrera -> Periodo -> Grupos para el selector escolar.
  const opcionesFiltroCarrera = Array.from(
    new Map(
      grupos
        .filter((grupo) => grupo.id_carrera !== null && grupo.nombre_carrera)
        .map((grupo) => [String(grupo.id_carrera), grupo.nombre_carrera!])
    ).entries()
  ).sort((primerPar, segundoPar) => primerPar[1].localeCompare(segundoPar[1], "es"));

  const cubetasAcademicasAgrupadas = (() => {
    const gruposFiltrados = filtroCarreraFormulario
      ? grupos.filter((grupo) =>
          filtroCarreraFormulario === "__none__"
            ? grupo.id_carrera === null
            : String(grupo.id_carrera) === filtroCarreraFormulario
        )
      : grupos;

    const mapaCarreras = new Map<
      string,
      { etiquetaCarrera: string; tipoPeriodo: string; periodos: Map<string, Grupo[]> }
    >();

    for (const grupo of gruposFiltrados) {
      const claveCarrera =
        grupo.id_carrera !== null ? String(grupo.id_carrera) : "__none__";
      const etiquetaCarrera = grupo.nombre_carrera ?? "Sin carrera asignada";
      if (!mapaCarreras.has(claveCarrera)) {
        mapaCarreras.set(claveCarrera, {
          etiquetaCarrera,
          tipoPeriodo: grupo.tipo_periodo,
          periodos: new Map(),
        });
      }
      const cubeta = mapaCarreras.get(claveCarrera)!;
      const clavePeriodo =
        formatearEtiquetaPeriodoGrupo(grupo.semestre, grupo.tipo_periodo) ??
        "Sin periodo";
      const listaPeriodo = cubeta.periodos.get(clavePeriodo) ?? [];
      listaPeriodo.push(grupo);
      cubeta.periodos.set(clavePeriodo, listaPeriodo);
    }

    return Array.from(mapaCarreras.entries())
      .sort(([claveA, cubetaA], [claveB, cubetaB]) => {
        if (claveA === "__none__") return 1;
        if (claveB === "__none__") return -1;
        return cubetaA.etiquetaCarrera.localeCompare(cubetaB.etiquetaCarrera, "es");
      })
      .map(([claveCarrera, cubeta]) => ({
        claveCarrera,
        etiquetaCarrera: cubeta.etiquetaCarrera,
        metadatosPeriodo: obtenerMetadatosPeriodo(cubeta.tipoPeriodo),
        periodos: Array.from(cubeta.periodos.entries())
          .sort(([periodoA], [periodoB]) => {
            if (periodoA === "Sin periodo") return 1;
            if (periodoB === "Sin periodo") return -1;
            return compararPeriodosNatural(periodoA, periodoB);
          })
          .map(([etiquetaPeriodo, gruposPeriodo]) => ({
            etiquetaPeriodo,
            grupos: [...gruposPeriodo].sort((grupoA, grupoB) =>
              grupoA.nombre.localeCompare(grupoB.nombre, "es", { numeric: true })
            ),
          })),
      }));
  })();

  /** Inicia el asistente de enrolamiento posicionándolo en la primera pose faltante. */
  function iniciarEnrolamientoPara(persona: Persona) {
    revocarTodasVistasPrevias();
    contadorEstabilidadRef.current = 0;
    establecerConteoEstabilidad(0);
    establecerBannerCompletado(null);
    establecerIdPersonaActiva(persona.id);
    establecerCapturaAutomatica(false);
    establecerEstadoEnrolamiento(null);
    establecerErrorEnrolamiento(null);
    const siguienteFaltante = POSES_REQUERIDAS.findIndex(
      (pose) => !persona.poses_completadas.includes(pose.clave)
    );
    establecerIndicePose(siguienteFaltante === -1 ? 0 : siguienteFaltante);
  }

  /** Cierra el asistente tras completar las poses y muestra confirmación en pantalla. */
  function finalizarEnrolamiento() {
    if (!personaActiva) return;
    const nombrePersona = personaActiva.nombre_completo;
    const cantidad = personaActiva.poses_completadas.length;
    establecerCapturaAutomatica(false);
    establecerIdPersonaActiva(null);
    establecerEstadoEnrolamiento(null);
    establecerErrorEnrolamiento(null);
    contadorEstabilidadRef.current = 0;
    establecerConteoEstabilidad(0);
    revocarTodasVistasPrevias();
    establecerBannerCompletado(
      `Enrolamiento de ${nombrePersona} finalizado (${cantidad}/${TOTAL_POSES} poses guardadas en memoria vectorial).`
    );
  }

  /** Registra una persona en el padrón y abre el enrolamiento si otorgó consentimiento. */
  async function manejarCrearPersona(evento: FormEvent) {
    evento.preventDefault();
    establecerErrorFormulario(null);
    establecerCreandoPersona(true);
    try {
      const personaCreada = await clienteApi.crearPersona({
        id_organizacion: organizacion.id,
        identificador_externo: identificadorExterno.trim(),
        nombre_completo: nombreCompleto.trim(),
        correo: correo.trim() || null,
        rol: rolPersona,
        consentimiento_biometrico: consentimientoBiometrico,
        ids_grupos: idsGruposSeleccionados,
        id_turno_laboral:
          organizacion.modo === "enterprise" && idTurnoSeleccionado
            ? Number(idTurnoSeleccionado)
            : null,
      });
      establecerIdentificadorExterno("");
      establecerNombreCompleto("");
      establecerCorreo("");
      establecerIdsGruposSeleccionados([]);
      establecerIdTurnoSeleccionado("");
      establecerMostrarFormularioAlta(false);
      await alRecargarPersonas();
      if (personaCreada.consentimiento_biometrico) {
        iniciarEnrolamientoPara(personaCreada);
      }
    } catch (errorAlta) {
      establecerErrorFormulario(
        errorAlta instanceof Error ? errorAlta.message : "No se pudo crear el registro."
      );
    } finally {
      establecerCreandoPersona(false);
    }
  }

  /** Guarda en memoria del navegador una vista previa temporal de la pose capturada. */
  const guardarVistaPreviaMemoria = useCallback(
    (clavePose: EtiquetaPose, archivoBlob: Blob) => {
      const urlPrevia = vistasPreviasRef.current[clavePose];
      if (urlPrevia) URL.revokeObjectURL(urlPrevia);
      const nuevaUrl = URL.createObjectURL(archivoBlob);
      vistasPreviasRef.current = { ...vistasPreviasRef.current, [clavePose]: nuevaUrl };
      establecerVistasPreviasPose({ ...vistasPreviasRef.current });
    },
    []
  );

  /**
   * Envía un fotograma para validación geométrica (`soloValidacion=true`) o registro
   * definitivo del embedding facial. En modo automático confirma al reunir 2 frames estables.
   */
  const enviarCapturaPose = useCallback(
    async (clavePose: EtiquetaPose, soloValidacion: boolean) => {
      if (!personaActiva || !camaraLista || peticionEnCursoRef.current) return;
      const camara = referenciaCamara.current;
      if (!camara) return;

      peticionEnCursoRef.current = true;
      if (!soloValidacion) establecerCapturando(true);
      establecerErrorEnrolamiento(null);
      try {
        const archivoBlob = await camara.capturarBlob();
        if (!archivoBlob) return;

        const respuesta = await clienteApi.enrolarFrame(
          personaActiva.id,
          archivoBlob,
          clavePose,
          guardarAvatar,
          soloValidacion
        );
        establecerEstadoEnrolamiento(respuesta);

        if (soloValidacion) {
          if (respuesta.pose_valida) {
            contadorEstabilidadRef.current += 1;
            establecerConteoEstabilidad(contadorEstabilidadRef.current);
            if (contadorEstabilidadRef.current >= 2) {
              contadorEstabilidadRef.current = 0;
              establecerConteoEstabilidad(0);
              establecerCapturando(true);
              const respuestaGuardado = await clienteApi.enrolarFrame(
                personaActiva.id,
                archivoBlob,
                clavePose,
                guardarAvatar,
                false
              );
              establecerEstadoEnrolamiento(respuestaGuardado);
              if (respuestaGuardado.aceptado) {
                guardarVistaPreviaMemoria(clavePose, archivoBlob);
                pausarHastaRef.current = Date.now() + 1100;
                await alRecargarPersonas();
                const siguienteIndice = POSES_REQUERIDAS.findIndex(
                  (pose) => !respuestaGuardado.poses_completadas.includes(pose.clave)
                );
                if (siguienteIndice !== -1) {
                  establecerIndicePose(siguienteIndice);
                } else {
                  establecerCapturaAutomatica(false);
                }
              }
            }
          } else {
            contadorEstabilidadRef.current = 0;
            establecerConteoEstabilidad(0);
          }
          return;
        }

        if (respuesta.aceptado) {
          guardarVistaPreviaMemoria(clavePose, archivoBlob);
          pausarHastaRef.current = Date.now() + 900;
          await alRecargarPersonas();
          const siguienteIndice = POSES_REQUERIDAS.findIndex(
            (pose) => !respuesta.poses_completadas.includes(pose.clave)
          );
          if (siguienteIndice !== -1) {
            establecerIndicePose(siguienteIndice);
          } else {
            establecerCapturaAutomatica(false);
          }
        }
      } catch (errorCaptura) {
        establecerErrorEnrolamiento(
          errorCaptura instanceof Error
            ? errorCaptura.message
            : "Error al enviar captura."
        );
        establecerCapturaAutomatica(false);
        contadorEstabilidadRef.current = 0;
        establecerConteoEstabilidad(0);
      } finally {
        peticionEnCursoRef.current = false;
        establecerCapturando(false);
      }
    },
    [
      personaActiva,
      camaraLista,
      alRecargarPersonas,
      guardarVistaPreviaMemoria,
      guardarAvatar,
    ]
  );

  // Sondeo periódico automático para modo de auto-captura guiada.
  useEffect(() => {
    if (!capturaAutomatica || !personaActiva || !camaraLista) return;
    const temporizador = window.setInterval(() => {
      if (Date.now() < pausarHastaRef.current) return;
      void enviarCapturaPose(poseActual.clave, true);
    }, 450);
    return () => window.clearInterval(temporizador);
  }, [personaActiva, capturaAutomatica, camaraLista, poseActual.clave, enviarCapturaPose]);

  /** Abre el modal de confirmación con contraseña para revocar vectores biométricos. */
  function abrirModalRevocacion(objetivos: Persona[]) {
    establecerObjetivosRevocar(objetivos);
    establecerSecretoRevocacion("");
    establecerMotivoRevocacion("");
    establecerErrorRevocacion(null);
  }

  /** Ejecuta la revocación biométrica auditable validada con secreto de admin o delegado. */
  async function manejarConfirmarRevocacion(evento: FormEvent) {
    evento.preventDefault();
    if (!objetivosRevocar || objetivosRevocar.length === 0) return;
    establecerRevocando(true);
    establecerErrorRevocacion(null);
    try {
      const idsObjetivo = objetivosRevocar.map((persona) => persona.id);
      const respuesta = await clienteApi.revocarBiometriaLote({
        ids_personas: idsObjetivo,
        secreto_autorizacion: secretoRevocacion,
        motivo: motivoRevocacion.trim() || undefined,
      });
      if (idPersonaActiva !== null && idsObjetivo.includes(idPersonaActiva)) {
        establecerEstadoEnrolamiento(null);
        revocarTodasVistasPrevias();
      }
      establecerSeleccionadasRevocar((previas) =>
        previas.filter((id) => !idsObjetivo.includes(id))
      );
      establecerObjetivosRevocar(null);
      await alRecargarPersonas();
      establecerBannerCompletado(
        `Biometría revocada para ${respuesta.cantidad_personas_revocadas} persona(s) (${respuesta.vectores_eliminados} vectores eliminados). Autorizado por: ${
          respuesta.nombre_autorizador ?? "Administrador"
        }.`
      );
    } catch (errorAutorizacion) {
      establecerErrorRevocacion(
        errorAutorizacion instanceof Error
          ? errorAutorizacion.message
          : "No se pudo autorizar la revocación."
      );
    } finally {
      establecerRevocando(false);
    }
  }

  /** Marca o desmarca una persona dentro de la selección múltiple de revocación. */
  function alternarSeleccionRevocar(idPersona: number) {
    establecerSeleccionadasRevocar((previas) =>
      previas.includes(idPersona)
        ? previas.filter((id) => id !== idPersona)
        : [...previas, idPersona]
    );
  }

  /** Elimina permanentemente a una persona del padrón organizacional. */
  async function manejarEliminarPersona(persona: Persona) {
    if (!window.confirm(`¿Eliminar permanentemente a ${persona.nombre_completo}?`)) return;
    await clienteApi.eliminarPersona(persona.id);
    if (idPersonaActiva === persona.id) {
      establecerIdPersonaActiva(null);
      establecerCapturaAutomatica(false);
      revocarTodasVistasPrevias();
    }
    await alRecargarPersonas();
  }

  /** Agrega o quita un grupo en el formulario de alta de persona. */
  function alternarSeleccionGrupo(idGrupo: number) {
    establecerIdsGruposSeleccionados((previos) =>
      previos.includes(idGrupo)
        ? previos.filter((id) => id !== idGrupo)
        : [...previos, idGrupo]
    );
  }

  const cantidadCompletadas = personaActiva?.poses_completadas.length ?? 0;
  const todasPosesCompletas = cantidadCompletadas >= TOTAL_POSES;
  const porcentajeProgreso = Math.round((cantidadCompletadas / TOTAL_POSES) * 100);

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">
            Personas y Registro Biométrico
          </h2>
          <p className="text-sm text-slate-400">
            Asistente guiado de {TOTAL_POSES} poses con validación geométrica e iluminación
            (sin guardar fotos crudas)
          </p>
        </div>

        {puedeGestionarPersonas && (
          <button
            type="button"
            onClick={() => establecerMostrarFormularioAlta((visible) => !visible)}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-indigo-600 hover:bg-indigo-500 text-white"
          >
            <Plus className="w-4 h-4" />
            Nueva Persona
          </button>
        )}
      </div>

      {bannerCompletado && (
        <div className="rounded-2xl bg-emerald-500/15 border border-emerald-500/40 px-4 py-3 flex items-center justify-between gap-3 text-sm text-emerald-200">
          <div className="flex items-center gap-2.5">
            <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
            <span>{bannerCompletado}</span>
          </div>
          <button
            type="button"
            onClick={() => establecerBannerCompletado(null)}
            className="text-xs text-emerald-300 hover:underline shrink-0"
          >
            Ocultar
          </button>
        </div>
      )}

      {mostrarFormularioAlta && (
        <form
          onSubmit={manejarCrearPersona}
          className="bg-slate-900 border border-indigo-500/40 rounded-2xl p-5 space-y-4"
        >
          <h3 className="font-semibold text-base">Registrar Persona</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div>
              <label className="block text-xs text-slate-400 mb-1">
                {organizacion.modo === "education"
                  ? "Matrícula / ID"
                  : "Núm. Empleado / ID"}
              </label>
              <input
                type="text"
                required
                value={identificadorExterno}
                onChange={(evento) => establecerIdentificadorExterno(evento.target.value)}
                placeholder="Ej. A-2025-01"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              />
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1">Nombre completo</label>
              <input
                type="text"
                required
                value={nombreCompleto}
                onChange={(evento) => establecerNombreCompleto(evento.target.value)}
                placeholder="Nombre y apellidos"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              />
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1">
                Correo (opcional)
              </label>
              <input
                type="email"
                value={correo}
                onChange={(evento) => establecerCorreo(evento.target.value)}
                placeholder="correo@ejemplo.com"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              />
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1">Rol</label>
              <select
                value={rolPersona}
                onChange={(evento) =>
                  establecerRolPersona(evento.target.value as RolPersona)
                }
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              >
                <option value="employee">Empleado</option>
                <option value="student">Alumno</option>
                <option value="teacher">Docente</option>
                <option value="admin">Administrador</option>
              </select>
            </div>
          </div>

          {grupos.length > 0 && (
            <div className="space-y-2.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs text-slate-400">
                  {organizacion.modo === "education"
                    ? "Asignar a grupo académico (ordenado por carrera y periodo; heredará sus materias)"
                    : "Asignar a grupos / departamentos"}
                </p>
                {organizacion.modo === "education" &&
                  opcionesFiltroCarrera.length > 1 && (
                    <select
                      value={filtroCarreraFormulario}
                      onChange={(evento) =>
                        establecerFiltroCarreraFormulario(evento.target.value)
                      }
                      className="bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1 text-xs"
                    >
                      <option value="">Todas las carreras</option>
                      {opcionesFiltroCarrera.map(([idCarrera, nombreCarrera]) => (
                        <option key={idCarrera} value={idCarrera}>
                          {nombreCarrera}
                        </option>
                      ))}
                      {grupos.some((grupo) => grupo.id_carrera === null) && (
                        <option value="__none__">Sin carrera asignada</option>
                      )}
                    </select>
                  )}
              </div>

              {organizacion.modo === "education" ? (
                <div className="space-y-3 max-h-60 overflow-y-auto pr-1">
                  {cubetasAcademicasAgrupadas.map((cubetaCarrera) => (
                    <div
                      key={cubetaCarrera.claveCarrera}
                      className="rounded-xl bg-slate-800/40 border border-slate-800 p-3 space-y-2"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-xs font-semibold text-indigo-300">
                          {cubetaCarrera.etiquetaCarrera}
                        </p>
                        <span className="text-[10px] text-slate-400">
                          Sistema {cubetaCarrera.metadatosPeriodo.etiqueta.toLowerCase()}
                        </span>
                      </div>

                      <div className="space-y-2">
                        {cubetaCarrera.periodos.map((cubetaPeriodo) => (
                          <div
                            key={cubetaPeriodo.etiquetaPeriodo}
                            className="space-y-1"
                          >
                            <p className="text-[11px] font-medium text-slate-400">
                              {cubetaPeriodo.etiquetaPeriodo}
                            </p>
                            <div className="flex flex-wrap gap-1.5">
                              {cubetaPeriodo.grupos.map((grupo) => {
                                const seleccionado = idsGruposSeleccionados.includes(
                                  grupo.id
                                );
                                return (
                                  <button
                                    key={grupo.id}
                                    type="button"
                                    onClick={() => alternarSeleccionGrupo(grupo.id)}
                                    className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                                      seleccionado
                                        ? "bg-indigo-600 border-indigo-500 text-white"
                                        : "bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700"
                                    }`}
                                  >
                                    {grupo.nombre}
                                    {grupo.aula_defecto ? ` · ${grupo.aula_defecto}` : ""}
                                  </button>
                                );
                              })}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {grupos.map((grupo) => {
                    const seleccionado = idsGruposSeleccionados.includes(grupo.id);
                    return (
                      <button
                        key={grupo.id}
                        type="button"
                        onClick={() => alternarSeleccionGrupo(grupo.id)}
                        className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                          seleccionado
                            ? "bg-indigo-600 border-indigo-500 text-white"
                            : "bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700"
                        }`}
                      >
                        {grupo.nombre}
                        {grupo.codigo_turno_laboral_defecto
                          ? ` · ${grupo.codigo_turno_laboral_defecto}`
                          : ""}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {organizacion.modo === "enterprise" &&
            turnosLaborales.some((turno) => turno.esta_activo) && (
              <div className="sm:max-w-sm">
                <label className="block text-xs text-slate-400 mb-1">
                  Turno laboral directo (opcional)
                </label>
                <select
                  value={idTurnoSeleccionado}
                  onChange={(evento) => establecerIdTurnoSeleccionado(evento.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                >
                  <option value="">Heredar de departamento / Sin turno</option>
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
            )}

          <label className="flex items-start gap-2.5 text-xs text-slate-300 bg-slate-800/60 border border-slate-700 rounded-xl p-3 cursor-pointer">
            <input
              type="checkbox"
              checked={consentimientoBiometrico}
              onChange={(evento) =>
                establecerConsentimientoBiometrico(evento.target.checked)
              }
              className="mt-0.5 rounded border-slate-600 bg-slate-800 text-indigo-600"
            />
            <span>
              <strong>Consentimiento biométrico informado:</strong> La persona autoriza
              generar sus vectores matemáticos faciales. Las capturas de cámara se
              procesan en memoria RAM y no se almacenan fotografías crudas en el servidor.
            </span>
          </label>

          {errorFormulario && (
            <p className="text-xs text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">
              {errorFormulario}
            </p>
          )}

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => establecerMostrarFormularioAlta(false)}
              className="px-4 py-2 rounded-lg text-sm bg-slate-800 hover:bg-slate-700"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={creandoPersona}
              className="px-4 py-2 rounded-lg text-sm font-semibold bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50"
            >
              {creandoPersona ? "Guardando..." : "Guardar y continuar"}
            </button>
          </div>
        </form>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Lista buscable del padrón organizacional */}
        <div className="lg:col-span-5 bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
          <div className="flex flex-col sm:flex-row gap-2">
            <div className="relative flex-1">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={busqueda}
                onChange={(evento) => establecerBusqueda(evento.target.value)}
                placeholder="Buscar por nombre o matrícula/ID..."
                className="w-full bg-slate-800 border border-slate-700 rounded-lg pl-9 pr-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
            {organizacion.modo === "education" && grupos.length > 0 && (
              <select
                value={filtroGrupoLista}
                onChange={(evento) => establecerFiltroGrupoLista(evento.target.value)}
                className="sm:w-48 bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-2 text-xs"
              >
                <option value="">Todos los grupos</option>
                {cubetasAcademicasAgrupadas.map((cubetaCarrera) =>
                  cubetaCarrera.periodos.map((cubetaPeriodo) => (
                    <optgroup
                      key={`${cubetaCarrera.claveCarrera}-${cubetaPeriodo.etiquetaPeriodo}`}
                      label={`${cubetaCarrera.etiquetaCarrera} — ${cubetaPeriodo.etiquetaPeriodo}`}
                    >
                      {cubetaPeriodo.grupos.map((grupo) => (
                        <option key={grupo.id} value={grupo.id}>
                          {grupo.nombre}
                        </option>
                      ))}
                    </optgroup>
                  ))
                )}
              </select>
            )}
            {organizacion.modo === "enterprise" && turnosLaborales.length > 0 && (
              <select
                value={filtroTurnoLista}
                onChange={(evento) => establecerFiltroTurnoLista(evento.target.value)}
                className="sm:w-48 bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-2 text-xs"
              >
                <option value="">Todos los turnos</option>
                <option value="__none__">Sin turno asignado</option>
                {turnosLaborales.map((turno) => (
                  <option key={turno.id} value={turno.id}>
                    {turno.nombre} ({turno.codigo})
                  </option>
                ))}
              </select>
            )}
          </div>

          {seleccionadasRevocar.length > 0 && (
            <div className="flex items-center justify-between gap-2 rounded-xl bg-amber-500/10 border border-amber-500/30 px-3 py-2 text-xs">
              <span className="text-amber-200">
                {seleccionadasRevocar.length} seleccionado(s) con biometría
              </span>
              <button
                type="button"
                onClick={() => {
                  const objetivos = personas.filter((persona) =>
                    seleccionadasRevocar.includes(persona.id)
                  );
                  if (objetivos.length > 0) abrirModalRevocacion(objetivos);
                }}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md font-semibold bg-amber-600 hover:bg-amber-500 text-white"
              >
                <ShieldAlert className="w-3.5 h-3.5" />
                Revocar lote
              </button>
            </div>
          )}

          <div className="space-y-2.5 max-h-[640px] overflow-y-auto pr-1">
            {personasFiltradas.length === 0 ? (
              <p className="text-sm text-slate-500 py-10 text-center">
                No hay personas registradas que coincidan con la búsqueda.
              </p>
            ) : (
              personasFiltradas.map((persona) => {
                const estaSeleccionada = idPersonaActiva === persona.id;
                const estaMarcada = seleccionadasRevocar.includes(persona.id);
                const gruposPersona = grupos.filter((grupo) =>
                  persona.ids_grupos.includes(grupo.id)
                );
                const cursosHeredados =
                  organizacion.modo === "education"
                    ? cursos.filter((curso) => persona.ids_grupos.includes(curso.id_grupo))
                    : [];
                return (
                  <div
                    key={persona.id}
                    className={`p-3.5 rounded-xl border transition-colors ${
                      estaSeleccionada
                        ? "bg-indigo-600/10 border-indigo-500/50"
                        : "bg-slate-800/40 border-slate-800 hover:border-slate-700"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex items-center gap-3 min-w-0">
                        {persona.cantidad_vectores > 0 && (
                          <input
                            type="checkbox"
                            checked={estaMarcada}
                            onChange={() => alternarSeleccionRevocar(persona.id)}
                            className="rounded border-slate-600 bg-slate-800 text-amber-500 shrink-0"
                            title="Seleccionar para revocación en lote"
                          />
                        )}
                        {persona.avatar_base64 ? (
                          <img
                            src={persona.avatar_base64}
                            alt={persona.nombre_completo}
                            className="w-10 h-10 rounded-full object-cover border border-slate-700 shrink-0"
                          />
                        ) : (
                          <div className="w-10 h-10 rounded-full bg-slate-800 flex items-center justify-center text-sm font-bold text-slate-300 shrink-0">
                            {persona.nombre_completo.slice(0, 1).toUpperCase()}
                          </div>
                        )}
                        <div className="min-w-0">
                          <p className="font-semibold text-sm truncate">
                            {persona.nombre_completo}
                          </p>
                          <p className="text-xs text-slate-400">
                            {persona.identificador_externo} · {persona.rol}
                            {gruposPersona.length > 0
                              ? ` · ${gruposPersona
                                  .map(
                                    (grupo) =>
                                      `${grupo.nombre}${
                                        grupo.semestre
                                          ? ` (${formatearEtiquetaPeriodoGrupo(
                                              grupo.semestre,
                                              grupo.tipo_periodo
                                            )})`
                                          : ""
                                      }`
                                  )
                                  .join(", ")}`
                              : ""}
                          </p>
                        </div>
                      </div>

                      <span
                        className={`px-2.5 py-1 rounded-full text-xs font-medium shrink-0 ${
                          persona.cantidad_vectores >= TOTAL_POSES
                            ? "bg-emerald-500/15 text-emerald-300"
                            : persona.cantidad_vectores > 0
                              ? "bg-amber-500/15 text-amber-300"
                              : "bg-slate-800 text-slate-400"
                        }`}
                      >
                        {persona.cantidad_vectores}/{TOTAL_POSES} poses
                      </span>
                    </div>

                    {organizacion.modo === "enterprise" &&
                      persona.nombre_turno_laboral_efectivo && (
                        <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px]">
                          <span className="text-slate-400">Turno:</span>
                          <span
                            className={`px-2 py-0.5 rounded border ${
                              persona.origen_turno === "direct"
                                ? "bg-indigo-500/15 text-indigo-300 border-indigo-500/25"
                                : "bg-emerald-500/15 text-emerald-300 border-emerald-500/25"
                            }`}
                          >
                            {persona.nombre_turno_laboral_efectivo}
                            {persona.codigo_turno_laboral_efectivo
                              ? ` (${persona.codigo_turno_laboral_efectivo})`
                              : ""}{" "}
                            · {persona.origen_turno === "direct" ? "directo" : "heredado"}
                          </span>
                        </div>
                      )}

                    {cursosHeredados.length > 0 && (
                      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px]">
                        <span className="text-slate-400">
                          Hereda {cursosHeredados.length} materia
                          {cursosHeredados.length === 1 ? "" : "s"}:
                        </span>
                        {cursosHeredados.map((curso) => (
                          <span
                            key={curso.id}
                            className="px-2 py-0.5 rounded bg-indigo-500/15 text-indigo-300 border border-indigo-500/20"
                            title={curso.nombre_materia}
                          >
                            {curso.codigo_materia}
                          </span>
                        ))}
                      </div>
                    )}

                    <div className="flex flex-wrap items-center justify-between gap-2 mt-3 pt-2.5 border-t border-slate-800/80">
                      <div className="text-[11px] text-slate-400">
                        {!persona.consentimiento_biometrico ? (
                          <span className="text-amber-400">
                            Sin consentimiento biométrico
                          </span>
                        ) : persona.requiere_reenrolamiento ? (
                          <span className="text-amber-300">
                            Actualiza rostro (nueva normalización)
                          </span>
                        ) : persona.cantidad_vectores >= TOTAL_POSES ? (
                          <span className="text-emerald-300">
                            Registro biométrico completo
                          </span>
                        ) : (
                          <span>Listo para captura</span>
                        )}
                      </div>

                      <div className="flex items-center gap-1.5">
                        {puedeGestionarPersonas && (
                          <button
                            type="button"
                            disabled={!persona.consentimiento_biometrico}
                            onClick={() => iniciarEnrolamientoPara(persona)}
                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white"
                          >
                            <Camera className="w-3.5 h-3.5" />
                            Enrolar
                          </button>
                        )}

                        {persona.cantidad_vectores > 0 && (
                          <button
                            type="button"
                            onClick={() => abrirModalRevocacion([persona])}
                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium bg-slate-800 hover:bg-amber-600/20 text-amber-300 border border-slate-700"
                            title="Revocar biometría (requiere contraseña)"
                          >
                            <ShieldAlert className="w-3.5 h-3.5" />
                            Revocar
                          </button>
                        )}

                        {puedeEliminarPersonas && (
                          <button
                            type="button"
                            onClick={() => void manejarEliminarPersona(persona)}
                            className="p-1.5 rounded-md text-slate-400 hover:text-red-400 hover:bg-red-500/10"
                            title="Eliminar persona"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Asistente interactivo de 6 poses */}
        <div className="lg:col-span-7 bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
          {!personaActiva ? (
            <div className="h-full min-h-[420px] flex flex-col items-center justify-center text-center text-slate-400 p-6">
              <UserCheck className="w-12 h-12 text-indigo-400/70 mb-3" />
              <h3 className="font-semibold text-base text-slate-200">
                Selecciona una persona para enrolar
              </h3>
              <p className="text-xs text-slate-500 max-w-sm mt-1">
                Capturaremos {TOTAL_POSES} poses distintas verificadas en tiempo real para
                que el reconocimiento sea preciso incluso con cambios de ángulo o luz.
              </p>
            </div>
          ) : (
            <>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="font-semibold text-base">
                    {personaActiva.nombre_completo}
                  </h3>
                  <p className="text-xs text-slate-400">
                    Progreso: {cantidadCompletadas} de {TOTAL_POSES} poses completadas (
                    {porcentajeProgreso}%)
                  </p>
                </div>

                <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={guardarAvatar}
                    onChange={(evento) => establecerGuardarAvatar(evento.target.checked)}
                    className="rounded border-slate-600 bg-slate-800 text-indigo-600"
                  />
                  Guardar avatar (frontal)
                </label>
              </div>

              {/* Barra de progreso */}
              <div className="w-full h-2 rounded-full bg-slate-800 overflow-hidden">
                <div
                  className={`h-full transition-all duration-300 ${
                    todasPosesCompletas ? "bg-emerald-500" : "bg-indigo-500"
                  }`}
                  style={{ width: `${porcentajeProgreso}%` }}
                />
              </div>

              {/* Banner destacado cuando se completan todas las poses */}
              {todasPosesCompletas && (
                <div className="rounded-2xl bg-emerald-500/15 border border-emerald-500/40 p-4 flex flex-wrap items-center justify-between gap-3">
                  <div className="space-y-1">
                    <p className="font-semibold text-sm text-emerald-200 flex items-center gap-2">
                      <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                      ¡Enrolamiento biométrico completado ({TOTAL_POSES}/{TOTAL_POSES})!
                    </p>
                    <p className="text-xs text-emerald-200/80">
                      Los vectores ya están almacenados sin guardar fotos crudas. Puedes
                      repetir cualquier toma abajo o finalizar el registro.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={finalizarEnrolamiento}
                    className="px-4 py-2 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white shrink-0"
                  >
                    Finalizar enrolamiento
                  </button>
                </div>
              )}

              {/* Instrucción guiada de la pose actual + medidor de estabilidad */}
              <div className="rounded-xl bg-indigo-500/10 border border-indigo-500/30 px-3.5 py-2.5 flex items-center justify-between gap-3 text-xs text-indigo-200">
                <div>
                  <strong>{poseActual.titulo}:</strong> {poseActual.instruccion}
                </div>
                {capturaAutomatica && (
                  <span className="px-2 py-0.5 rounded-full bg-indigo-600/40 text-[11px] font-semibold shrink-0">
                    Estabilidad {conteoEstabilidad}/2
                  </span>
                )}
              </div>

              <VistaCamara
                ref={referenciaCamara}
                activa={Boolean(personaActiva)}
                cuadroRostro={estadoEnrolamiento?.cuadro_rostro ?? null}
                estadoCuadro={
                  estadoEnrolamiento
                    ? estadoEnrolamiento.aceptado || estadoEnrolamiento.pose_valida
                      ? "ok"
                      : "warning"
                    : "idle"
                }
                etiqueta={
                  estadoEnrolamiento?.calidad
                    ? estadoEnrolamiento.pose_valida
                      ? `Pose OK · ${poseActual.etiquetaCorta}`
                      : `Detectado: ${estadoEnrolamiento.calidad.pose_estimada}`
                    : undefined
                }
                alCambiarDisponibilidad={establecerCamaraLista}
                alOcurrirError={establecerErrorEnrolamiento}
              />

              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  disabled={!camaraLista || capturando}
                  onClick={() => void enviarCapturaPose(poseActual.clave, false)}
                  className="flex-1 inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white"
                >
                  <Camera className="w-4 h-4" />
                  {capturando ? "Procesando..." : `Capturar ${poseActual.titulo}`}
                </button>

                <button
                  type="button"
                  disabled={!camaraLista}
                  onClick={() => {
                    contadorEstabilidadRef.current = 0;
                    establecerConteoEstabilidad(0);
                    establecerCapturaAutomatica((activa) => !activa);
                  }}
                  className={`inline-flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold border transition-colors ${
                    capturaAutomatica
                      ? "bg-amber-600 border-amber-500 text-white"
                      : "bg-slate-800 border-slate-700 text-slate-200 hover:bg-slate-700"
                  }`}
                >
                  <Sparkles className="w-4 h-4" />
                  {capturaAutomatica ? "Detener Auto" : "Auto-captura guiada"}
                </button>
              </div>

              {errorEnrolamiento && (
                <p className="text-xs text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">
                  {errorEnrolamiento}
                </p>
              )}

              {estadoEnrolamiento && (
                <div
                  className={`rounded-xl border px-3.5 py-2.5 text-xs ${
                    estadoEnrolamiento.aceptado || estadoEnrolamiento.pose_valida
                      ? "bg-emerald-500/10 border-emerald-500/40 text-emerald-200"
                      : "bg-amber-500/10 border-amber-500/40 text-amber-200"
                  }`}
                >
                  <div className="flex items-center gap-2 font-medium">
                    {estadoEnrolamiento.calidad?.contraluz_detectado && (
                      <AlertTriangle className="w-4 h-4 text-amber-300 shrink-0" />
                    )}
                    <span>{estadoEnrolamiento.mensaje}</span>
                  </div>
                  {estadoEnrolamiento.calidad && (
                    <p className="text-[11px] opacity-80 mt-0.5">
                      Nitidez: {estadoEnrolamiento.calidad.puntaje_nitidez} · Brillo:{" "}
                      {estadoEnrolamiento.calidad.brillo} · Asimetría luz:{" "}
                      {estadoEnrolamiento.calidad.asimetria_sombra} · Tamaño:{" "}
                      {estadoEnrolamiento.calidad.ancho_rostro}×
                      {estadoEnrolamiento.calidad.alto_rostro}px
                    </p>
                  )}
                </div>
              )}

              {/* Revisión temporal en RAM de las 6 poses */}
              <div className="space-y-2 pt-1">
                <p className="text-xs text-slate-400">
                  Revisión de tomas (vista temporal en navegador; pulsa Repetir si deseas
                  rehacer alguna pose):
                </p>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
                  {POSES_REQUERIDAS.map((pose, indice) => {
                    const completada = personaActiva.poses_completadas.includes(
                      pose.clave
                    );
                    const seleccionada = indice === indicePose;
                    const urlPrevia = vistasPreviasPose[pose.clave];
                    return (
                      <div
                        key={pose.clave}
                        className={`rounded-xl border p-2.5 flex items-center justify-between gap-2 transition-colors ${
                          seleccionada
                            ? "bg-indigo-600/15 border-indigo-400"
                            : completada
                              ? "bg-emerald-500/10 border-emerald-500/30"
                              : "bg-slate-800/50 border-slate-800"
                        }`}
                      >
                        <button
                          type="button"
                          onClick={() => {
                            contadorEstabilidadRef.current = 0;
                            establecerConteoEstabilidad(0);
                            establecerIndicePose(indice);
                          }}
                          className="flex items-center gap-2 min-w-0 text-left flex-1"
                        >
                          {urlPrevia ? (
                            <img
                              src={urlPrevia}
                              alt={pose.etiquetaCorta}
                              className="w-9 h-9 rounded-lg object-cover border border-slate-700 scale-x-[-1] shrink-0"
                            />
                          ) : (
                            <div
                              className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 ${
                                completada
                                  ? "bg-emerald-500/20 text-emerald-300"
                                  : "bg-slate-800 text-slate-500"
                              }`}
                            >
                              {completada ? (
                                <Check className="w-4 h-4" />
                              ) : (
                                <span className="text-xs font-semibold">
                                  {indice + 1}
                                </span>
                              )}
                            </div>
                          )}
                          <div className="min-w-0">
                            <p className="text-xs font-medium truncate">
                              {pose.etiquetaCorta}
                            </p>
                            <p className="text-[10px] text-slate-400">
                              {completada ? "Lista" : "Pendiente"}
                            </p>
                          </div>
                        </button>

                        {completada && (
                          <button
                            type="button"
                            onClick={() => {
                              contadorEstabilidadRef.current = 0;
                              establecerConteoEstabilidad(0);
                              establecerIndicePose(indice);
                            }}
                            className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 shrink-0"
                            title={`Repetir ${pose.etiquetaCorta}`}
                          >
                            <RotateCcw className="w-3 h-3" />
                            Repetir
                          </button>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Modal de autorización para revocación biométrica */}
      {objetivosRevocar && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <form
            onSubmit={manejarConfirmarRevocacion}
            className="w-full max-w-md bg-slate-900 border border-amber-500/40 rounded-2xl p-6 space-y-4 shadow-2xl"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-xl bg-amber-500/15 border border-amber-500/30 flex items-center justify-center text-amber-300">
                  <KeyRound className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="font-semibold text-base">
                    Autorizar revocación biométrica
                  </h3>
                  <p className="text-xs text-slate-400">
                    {objetivosRevocar.length === 1
                      ? objetivosRevocar[0].nombre_completo
                      : `${objetivosRevocar.length} personas seleccionadas`}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => establecerObjetivosRevocar(null)}
                className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="rounded-xl bg-slate-800/60 border border-slate-800 p-3 text-xs text-slate-300 max-h-28 overflow-y-auto space-y-1">
              {objetivosRevocar.map((objetivo) => (
                <p key={objetivo.id}>
                  • <strong>{objetivo.nombre_completo}</strong> (
                  {objetivo.identificador_externo})
                </p>
              ))}
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1">
                Contraseña de seguridad (Admin, Superadmin o Clave Delegada)
              </label>
              <EntradaContrasena
                required
                autoFocus
                value={secretoRevocacion}
                onChange={(evento) => establecerSecretoRevocacion(evento.target.value)}
                placeholder="Ingresa contraseña de autorización"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-500"
              />
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1">
                Motivo (opcional)
              </label>
              <input
                type="text"
                value={motivoRevocacion}
                onChange={(evento) => establecerMotivoRevocacion(evento.target.value)}
                placeholder="Ej. Re-enrolamiento o baja del padrón"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
              />
            </div>

            {errorRevocacion && (
              <p className="text-xs text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">
                {errorRevocacion}
              </p>
            )}

            <div className="flex justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={() => establecerObjetivosRevocar(null)}
                className="px-4 py-2 rounded-lg text-sm bg-slate-800 hover:bg-slate-700"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={revocando}
                className="px-4 py-2 rounded-lg text-sm font-semibold bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white"
              >
                {revocando ? "Validando..." : "Confirmar revocación"}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
