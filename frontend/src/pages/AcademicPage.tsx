/**
 * Módulo de Estructura Académica y Estadísticas Escolares de IdentIA.
 * Administra la jerarquía Institución -> Carreras -> Grupos -> Asignaturas,
 * docentes y múltiples bloques de horario semanal (incluyendo aulas editables),
 * el cambio protegido de régimen académico (bimestral/trimestral/cuatrimestral/
 * semestral/ciclo) con contraseña de administrador y los tableros de asistencia.
 */
import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  ArrowUpDown,
  BarChart3,
  BookOpen,
  CalendarCheck,
  ChevronDown,
  ChevronUp,
  Clock,
  GraduationCap,
  Layers,
  Lock,
  Pencil,
  Plus,
  ScanFace,
  Trash2,
  X,
} from "lucide-react";
import { EntradaContrasena } from "../components/PasswordInput";
import {
  compararPeriodosNatural,
  formatearEtiquetaPeriodoGrupo,
  obtenerMetadatosPeriodo,
  OPCIONES_PERIODO_ACADEMICO,
} from "../lib/academicPeriods";
import { clienteApi } from "../lib/api";
import type {
  AsignacionCurso,
  Carrera,
  Grupo,
  Materia,
  Organizacion,
  RespuestaEstadisticasAcademicas,
  TipoPeriodoAcademico,
  UsuarioAutenticado,
} from "../types/api";

/** Propiedades recibidas por `PaginaAcademico`. */
interface PropiedadesPaginaAcademico {
  /** Usuario administrador autenticado actualmente. */
  usuarioActual: UsuarioAutenticado;
  /** Organización educativa seleccionada. */
  organizacion: Organizacion;
  /** Grupos académicos cargados para la institución. */
  grupos: Grupo[];
  /** Callback para recargar los datos compartidos tras cambios estructurales. */
  alRecargarOrganizacion: () => Promise<void>;
  /** Callback para abrir en el kiosco la sesión generada de un curso. */
  alAbrirSesionEnKiosco: (idSesion: number) => void;
}

type SubPestanaAcademica = "structure" | "courses" | "stats";
type CampoOrdenMateria = "career_period" | "period_career" | "rate" | "subject";
type CampoOrdenGrupo = "career_period" | "period_career" | "rate" | "group";

/** Borrador temporal de un bloque semanal antes de crear la asignación de curso. */
interface BorradorHorarioPendiente {
  dia_semana: number;
  hora_inicio: string;
  hora_fin: string;
  aula: string;
}

/** Representa una solicitud pendiente de cambio de periodo protegida por secreto admin. */
type CambioPeriodoPendiente =
  | {
      alcance: "organization";
      siguienteTipoPeriodo: TipoPeriodoAcademico;
      resumen: string;
    }
  | {
      alcance: "career";
      idCarrera: number;
      nombreCarrera: string;
      siguienteTipoPeriodo: string;
      resumen: string;
    }
  | {
      alcance: "group";
      idGrupo: number;
      nombreGrupo: string;
      siguienteTipoPeriodo: string;
      semestre: string | null;
      aula: string | null;
      resumen: string;
    };

/** Catálogo semanal de días hábiles y fin de semana (`0 = Lunes` .. `6 = Domingo`). */
const DIAS_SEMANA = [
  { valor: 0, corto: "Lun", inicial: "L", etiqueta: "Lunes" },
  { valor: 1, corto: "Mar", inicial: "M", etiqueta: "Martes" },
  { valor: 2, corto: "Mié", inicial: "X", etiqueta: "Miércoles" },
  { valor: 3, corto: "Jue", inicial: "J", etiqueta: "Jueves" },
  { valor: 4, corto: "Vie", inicial: "V", etiqueta: "Viernes" },
  { valor: 5, corto: "Sáb", inicial: "S", etiqueta: "Sábado" },
  { valor: 6, corto: "Dom", inicial: "D", etiqueta: "Domingo" },
];

/** Convierte el índice numérico del día (0-6) a su nombre completo en español. */
function etiquetaDiaSemana(dia: number): string {
  return (
    DIAS_SEMANA.find((elemento) => elemento.valor === dia)?.etiqueta ?? `Día ${dia}`
  );
}

/** Devuelve la fecha local de hoy en formato ISO (`YYYY-MM-DD`). */
function obtenerHoyIso(): string {
  const ahora = new Date();
  const anio = ahora.getFullYear();
  const mes = String(ahora.getMonth() + 1).padStart(2, "0");
  const dia = String(ahora.getDate()).padStart(2, "0");
  return `${anio}-${mes}-${dia}`;
}

/** Convierte `Date.getDay()` al índice `0 = Lunes` .. `6 = Domingo` del backend. */
function obtenerDiaSemanaPorDefecto(): number {
  const diaJs = new Date().getDay();
  return diaJs === 0 ? 6 : diaJs - 1;
}

/**
 * Renderiza las sub-pestañas de Carreras/Grupos, Materias/Horarios y Estadísticas
 * Académicas con ordenamiento natural por periodo escolar.
 */
export function PaginaAcademico({
  organizacion,
  grupos,
  alRecargarOrganizacion,
  alAbrirSesionEnKiosco,
}: PropiedadesPaginaAcademico) {
  const [subPestana, establecerSubPestana] = useState<SubPestanaAcademica>("structure");
  const [carreras, establecerCarreras] = useState<Carrera[]>([]);
  const [materias, establecerMaterias] = useState<Materia[]>([]);
  const [cursos, establecerCursos] = useState<AsignacionCurso[]>([]);
  const [docentes, establecerDocentes] = useState<UsuarioAutenticado[]>([]);
  const [estadisticas, establecerEstadisticas] =
    useState<RespuestaEstadisticasAcademicas | null>(null);
  const [cargando, establecerCargando] = useState(true);
  const [mensajeEstado, establecerMensajeEstado] = useState<string | null>(null);
  const [mensajeError, establecerMensajeError] = useState<string | null>(null);

  // Régimen académico general de la institución.
  const [tipoPeriodoOrg, establecerTipoPeriodoOrg] = useState<TipoPeriodoAcademico>(
    organizacion.tipo_periodo_academico ?? "semestral"
  );

  // Formulario de alta de carrera.
  const [nombreCarrera, establecerNombreCarrera] = useState("");
  const [codigoCarrera, establecerCodigoCarrera] = useState("");
  const [descripcionCarrera, establecerDescripcionCarrera] = useState("");
  const [tipoPeriodoCarrera, establecerTipoPeriodoCarrera] = useState<string>("");

  // Formulario de alta de grupo académico.
  const [nombreGrupo, establecerNombreGrupo] = useState("");
  const [codigoGrupo, establecerCodigoGrupo] = useState("");
  const [idCarreraGrupo, establecerIdCarreraGrupo] = useState<string>("");
  const [semestreGrupo, establecerSemestreGrupo] = useState("");
  const [tipoPeriodoGrupo, establecerTipoPeriodoGrupo] = useState<string>("");
  const [aulaDefectoGrupo, establecerAulaDefectoGrupo] = useState("");

  // Edición rápida de grupo (aula fija, semestre y régimen propio).
  const [idGrupoEditando, establecerIdGrupoEditando] = useState<number | null>(null);
  const [semestreGrupoEditado, establecerSemestreGrupoEditado] = useState("");
  const [tipoPeriodoGrupoEditado, establecerTipoPeriodoGrupoEditado] = useState<string>("");
  const [aulaGrupoEditada, establecerAulaGrupoEditada] = useState("");

  // Modal de autorización con contraseña de administrador al modificar periodos.
  const [cambioPeriodoPendiente, establecerCambioPeriodoPendiente] =
    useState<CambioPeriodoPendiente | null>(null);
  const [secretoAutorizacionPeriodo, establecerSecretoAutorizacionPeriodo] = useState("");
  const [errorAutorizacionPeriodo, establecerErrorAutorizacionPeriodo] = useState<
    string | null
  >(null);
  const [enviandoAutorizacionPeriodo, establecerEnviandoAutorizacionPeriodo] =
    useState(false);

  // Formulario de alta de asignatura.
  const [nombreMateria, establecerNombreMateria] = useState("");
  const [codigoMateria, establecerCodigoMateria] = useState("");
  const [idCarreraMateria, establecerIdCarreraMateria] = useState<string>("");

  // Formulario de asignación de curso (Grupo + Materia + Docente + horarios multi-día).
  const [idGrupoCurso, establecerIdGrupoCurso] = useState<string>("");
  const [idMateriaCurso, establecerIdMateriaCurso] = useState<string>("");
  const [idDocenteCurso, establecerIdDocenteCurso] = useState<string>("");
  const [periodoLectivoCurso, establecerPeriodoLectivoCurso] = useState("");
  const [diasSeleccionados, establecerDiasSeleccionados] = useState<number[]>([
    obtenerDiaSemanaPorDefecto(),
  ]);
  const [horaInicioInicial, establecerHoraInicioInicial] = useState("10:00");
  const [horaFinInicial, establecerHoraFinInicial] = useState("11:00");
  const [aulaInicial, establecerAulaInicial] = useState("");
  const [horariosPendientes, establecerHorariosPendientes] = useState<
    BorradorHorarioPendiente[]
  >([]);

  // Borradores inline para agregar bloques horarios a asignaciones existentes.
  const [borradoresHorarioCurso, establecerBorradoresHorarioCurso] = useState<
    Record<
      number,
      { dias: number[]; inicio: string; fin: string; aula?: string }
    >
  >({});

  // Filtros, acordeones y criterios de ordenamiento en Estadísticas Académicas.
  const [fechaDesdeEstadisticas, establecerFechaDesdeEstadisticas] = useState("");
  const [fechaHastaEstadisticas, establecerFechaHastaEstadisticas] = useState("");
  const [idCarreraEstadisticas, establecerIdCarreraEstadisticas] = useState<string>("");
  const [idGrupoEstadisticas, establecerIdGrupoEstadisticas] = useState<string>("");
  const [gruposExpandidos, establecerGruposExpandidos] = useState<
    Record<number, boolean>
  >({});
  const [ordenMateriaPor, establecerOrdenMateriaPor] =
    useState<CampoOrdenMateria>("career_period");
  const [ordenMateriaAscendente, establecerOrdenMateriaAscendente] = useState(true);
  const [ordenGrupoPor, establecerOrdenGrupoPor] =
    useState<CampoOrdenGrupo>("career_period");
  const [ordenGrupoAscendente, establecerOrdenGrupoAscendente] = useState(true);

  useEffect(() => {
    establecerTipoPeriodoOrg(organizacion.tipo_periodo_academico ?? "semestral");
  }, [organizacion.tipo_periodo_academico, organizacion.id]);

  /** Carga carreras, asignaturas, asignaciones de curso y usuarios docentes disponibles. */
  const cargarDatosAcademicos = useCallback(async () => {
    establecerCargando(true);
    establecerMensajeError(null);
    try {
      const [listaCarreras, listaMaterias, listaCursos, listaUsuarios] = await Promise.all([
        clienteApi.listarCarreras(organizacion.id),
        clienteApi.listarMaterias(organizacion.id),
        clienteApi.listarCursos(organizacion.id),
        clienteApi.listarUsuarios(organizacion.id),
      ]);
      establecerCarreras(listaCarreras);
      establecerMaterias(listaMaterias);
      establecerCursos(listaCursos);
      establecerDocentes(
        listaUsuarios.filter(
          (usuario) =>
            usuario.esta_activo &&
            (usuario.rol === "teacher" || usuario.rol === "org_admin")
        )
      );
    } catch (errorCarga) {
      establecerMensajeError(
        errorCarga instanceof Error
          ? errorCarga.message
          : "No se pudo cargar la estructura académica."
      );
    } finally {
      establecerCargando(false);
    }
  }, [organizacion.id]);

  /** Consulta estadísticas agregadas por asignatura, grupo y desglose por estudiante. */
  const cargarEstadisticas = useCallback(async () => {
    try {
      const respuesta = await clienteApi.obtenerEstadisticasAcademicas({
        id_organizacion: organizacion.id,
        fecha_desde: fechaDesdeEstadisticas || null,
        fecha_hasta: fechaHastaEstadisticas || null,
        id_carrera: idCarreraEstadisticas ? Number(idCarreraEstadisticas) : null,
        id_grupo: idGrupoEstadisticas ? Number(idGrupoEstadisticas) : null,
      });
      establecerEstadisticas(respuesta);
    } catch (errorCarga) {
      establecerMensajeError(
        errorCarga instanceof Error ? errorCarga.message : "Error cargando estadísticas."
      );
    }
  }, [
    organizacion.id,
    idCarreraEstadisticas,
    fechaDesdeEstadisticas,
    fechaHastaEstadisticas,
    idGrupoEstadisticas,
  ]);

  useEffect(() => {
    void cargarDatosAcademicos();
  }, [cargarDatosAcademicos]);

  useEffect(() => {
    if (subPestana === "stats") {
      void cargarEstadisticas();
    }
  }, [subPestana, cargarEstadisticas]);

  /** Abre confirmación con clave admin para modificar el tipo de periodo institucional. */
  function solicitarCambioPeriodoOrganizacion(evento: FormEvent) {
    evento.preventDefault();
    establecerMensajeError(null);
    establecerMensajeEstado(null);
    const periodoActualOrg = organizacion.tipo_periodo_academico ?? "semestral";
    if (tipoPeriodoOrg === periodoActualOrg) {
      establecerMensajeEstado(
        `El periodo general actual ya es ${obtenerMetadatosPeriodo(tipoPeriodoOrg).etiqueta}.`
      );
      return;
    }
    establecerSecretoAutorizacionPeriodo("");
    establecerErrorAutorizacionPeriodo(null);
    establecerCambioPeriodoPendiente({
      alcance: "organization",
      siguienteTipoPeriodo: tipoPeriodoOrg,
      resumen: `Institución "${organizacion.nombre}": ${
        obtenerMetadatosPeriodo(periodoActualOrg).etiqueta
      } → ${obtenerMetadatosPeriodo(tipoPeriodoOrg).etiqueta}`,
    });
  }

  /** Crea una nueva carrera o programa académico dentro de la institución. */
  async function manejarCrearCarrera(evento: FormEvent) {
    evento.preventDefault();
    establecerMensajeError(null);
    establecerMensajeEstado(null);
    try {
      await clienteApi.crearCarrera({
        id_organizacion: organizacion.id,
        nombre: nombreCarrera.trim(),
        codigo: codigoCarrera.trim(),
        descripcion: descripcionCarrera.trim() || null,
        tipo_periodo: tipoPeriodoCarrera
          ? (tipoPeriodoCarrera as TipoPeriodoAcademico)
          : null,
      });
      establecerNombreCarrera("");
      establecerCodigoCarrera("");
      establecerDescripcionCarrera("");
      establecerTipoPeriodoCarrera("");
      establecerMensajeEstado("Carrera registrada.");
      await cargarDatosAcademicos();
    } catch (errorCreacion) {
      establecerMensajeError(
        errorCreacion instanceof Error ? errorCreacion.message : "Error creando carrera."
      );
    }
  }

  /** Abre confirmación con clave admin antes de cambiar el régimen de una carrera. */
  function solicitarCambioPeriodoCarrera(carrera: Carrera, siguienteValor: string) {
    const valorActual = carrera.tipo_periodo ?? "";
    if (siguienteValor === valorActual) return;
    establecerMensajeError(null);
    establecerMensajeEstado(null);
    const etiquetaSiguiente = siguienteValor
      ? obtenerMetadatosPeriodo(siguienteValor).etiqueta
      : `Heredar general (${
          obtenerMetadatosPeriodo(organizacion.tipo_periodo_academico).etiqueta
        })`;
    establecerSecretoAutorizacionPeriodo("");
    establecerErrorAutorizacionPeriodo(null);
    establecerCambioPeriodoPendiente({
      alcance: "career",
      idCarrera: carrera.id,
      nombreCarrera: carrera.nombre,
      siguienteTipoPeriodo: siguienteValor,
      resumen: `Carrera "${carrera.nombre}": ${
        obtenerMetadatosPeriodo(carrera.tipo_periodo_efectivo).etiqueta
      } → ${etiquetaSiguiente}`,
    });
  }

  /** Envía al backend la actualización de periodo respaldada por secreto administrativo. */
  async function manejarConfirmarCambioPeriodo(evento: FormEvent) {
    evento.preventDefault();
    if (!cambioPeriodoPendiente) return;
    establecerErrorAutorizacionPeriodo(null);
    establecerEnviandoAutorizacionPeriodo(true);
    try {
      if (cambioPeriodoPendiente.alcance === "organization") {
        await clienteApi.actualizarOrganizacion(organizacion.id, {
          tipo_periodo_academico: cambioPeriodoPendiente.siguienteTipoPeriodo,
          secreto_autorizacion: secretoAutorizacionPeriodo,
        });
        establecerMensajeEstado(
          `Periodo académico general actualizado a ${
            obtenerMetadatosPeriodo(cambioPeriodoPendiente.siguienteTipoPeriodo).etiqueta
          }.`
        );
      } else if (cambioPeriodoPendiente.alcance === "career") {
        await clienteApi.actualizarCarrera(cambioPeriodoPendiente.idCarrera, {
          tipo_periodo: cambioPeriodoPendiente.siguienteTipoPeriodo
            ? (cambioPeriodoPendiente.siguienteTipoPeriodo as TipoPeriodoAcademico)
            : null,
          secreto_autorizacion: secretoAutorizacionPeriodo,
        });
        establecerMensajeEstado(
          `Tipo de periodo de "${cambioPeriodoPendiente.nombreCarrera}" actualizado.`
        );
      } else {
        await clienteApi.actualizarGrupo(cambioPeriodoPendiente.idGrupo, {
          semestre: cambioPeriodoPendiente.semestre,
          aula_defecto: cambioPeriodoPendiente.aula,
          tipo_periodo: cambioPeriodoPendiente.siguienteTipoPeriodo
            ? (cambioPeriodoPendiente.siguienteTipoPeriodo as TipoPeriodoAcademico)
            : null,
          secreto_autorizacion: secretoAutorizacionPeriodo,
        });
        establecerIdGrupoEditando(null);
        establecerMensajeEstado(
          `Tipo de periodo de "${cambioPeriodoPendiente.nombreGrupo}" actualizado.`
        );
      }
      establecerCambioPeriodoPendiente(null);
      establecerSecretoAutorizacionPeriodo("");
      await Promise.all([alRecargarOrganizacion(), cargarDatosAcademicos()]);
    } catch (errorAutorizacion) {
      establecerErrorAutorizacionPeriodo(
        errorAutorizacion instanceof Error
          ? errorAutorizacion.message
          : "No se pudo autorizar el cambio de periodo."
      );
    } finally {
      establecerEnviandoAutorizacionPeriodo(false);
    }
  }

  /** Elimina una carrera del catálogo institucional. */
  async function manejarEliminarCarrera(idCarrera: number) {
    establecerMensajeError(null);
    try {
      await clienteApi.eliminarCarrera(idCarrera);
      await Promise.all([cargarDatosAcademicos(), alRecargarOrganizacion()]);
    } catch (errorEliminacion) {
      establecerMensajeError(
        errorEliminacion instanceof Error
          ? errorEliminacion.message
          : "No se pudo eliminar la carrera."
      );
    }
  }

  /** Crea un nuevo grupo escolar vinculado opcionalmente a una carrera y aula fija. */
  async function manejarCrearGrupo(evento: FormEvent) {
    evento.preventDefault();
    establecerMensajeError(null);
    establecerMensajeEstado(null);
    try {
      await clienteApi.crearGrupo({
        id_organizacion: organizacion.id,
        nombre: nombreGrupo.trim(),
        codigo: codigoGrupo.trim(),
        id_carrera: idCarreraGrupo ? Number(idCarreraGrupo) : null,
        semestre: semestreGrupo.trim() || null,
        tipo_periodo: tipoPeriodoGrupo
          ? (tipoPeriodoGrupo as TipoPeriodoAcademico)
          : null,
        aula_defecto: aulaDefectoGrupo.trim() || null,
        hora_inicio_horario: "07:00",
        hora_fin_horario: "15:00",
      });
      establecerNombreGrupo("");
      establecerCodigoGrupo("");
      establecerSemestreGrupo("");
      establecerTipoPeriodoGrupo("");
      establecerAulaDefectoGrupo("");
      establecerMensajeEstado("Grupo académico creado.");
      await Promise.all([alRecargarOrganizacion(), cargarDatosAcademicos()]);
    } catch (errorCreacion) {
      establecerMensajeError(
        errorCreacion instanceof Error ? errorCreacion.message : "Error creando grupo."
      );
    }
  }

  /** Activa el panel inline de edición de semestre, tipo de periodo y aula de un grupo. */
  function iniciarEdicionGrupo(grupo: Grupo) {
    establecerIdGrupoEditando(grupo.id);
    establecerSemestreGrupoEditado(grupo.semestre ?? "");
    establecerTipoPeriodoGrupoEditado(grupo.tipo_periodo_personalizado ?? "");
    establecerAulaGrupoEditada(grupo.aula_defecto ?? "");
  }

  /** Guarda modificaciones de grupo o pide autorización admin si cambió su régimen. */
  async function manejarGuardarEdicionGrupo(grupo: Grupo) {
    establecerMensajeError(null);
    const personalizadoActual = grupo.tipo_periodo_personalizado ?? "";
    const semestreLimpio = semestreGrupoEditado.trim() || null;
    const aulaLimpia = aulaGrupoEditada.trim() || null;

    if (tipoPeriodoGrupoEditado !== personalizadoActual) {
      const etiquetaSiguiente = tipoPeriodoGrupoEditado
        ? obtenerMetadatosPeriodo(tipoPeriodoGrupoEditado).etiqueta
        : "Heredar de carrera/institución";
      establecerSecretoAutorizacionPeriodo("");
      establecerErrorAutorizacionPeriodo(null);
      establecerCambioPeriodoPendiente({
        alcance: "group",
        idGrupo: grupo.id,
        nombreGrupo: grupo.nombre,
        siguienteTipoPeriodo: tipoPeriodoGrupoEditado,
        semestre: semestreLimpio,
        aula: aulaLimpia,
        resumen: `Grupo "${grupo.nombre}": ${
          obtenerMetadatosPeriodo(grupo.tipo_periodo).etiqueta
        } → ${etiquetaSiguiente}`,
      });
      return;
    }

    try {
      await clienteApi.actualizarGrupo(grupo.id, {
        semestre: semestreLimpio,
        aula_defecto: aulaLimpia,
      });
      establecerIdGrupoEditando(null);
      await Promise.all([alRecargarOrganizacion(), cargarDatosAcademicos()]);
    } catch (errorActualizacion) {
      establecerMensajeError(
        errorActualizacion instanceof Error
          ? errorActualizacion.message
          : "No se pudo actualizar el grupo."
      );
    }
  }

  /** Asocia rápidamente un grupo sin carrera a una carrera existente. */
  async function manejarVincularGrupoACarrera(idGrupo: number, valorIdCarrera: string) {
    establecerMensajeError(null);
    try {
      await clienteApi.actualizarGrupo(idGrupo, {
        id_carrera: valorIdCarrera ? Number(valorIdCarrera) : null,
      });
      await Promise.all([alRecargarOrganizacion(), cargarDatosAcademicos()]);
    } catch (errorVinculo) {
      establecerMensajeError(
        errorVinculo instanceof Error
          ? errorVinculo.message
          : "No se pudo actualizar la carrera del grupo."
      );
    }
  }

  /** Elimina un grupo académico por su identificador. */
  async function manejarEliminarGrupo(idGrupo: number) {
    establecerMensajeError(null);
    try {
      await clienteApi.eliminarGrupo(idGrupo);
      await Promise.all([alRecargarOrganizacion(), cargarDatosAcademicos()]);
    } catch (errorEliminacion) {
      establecerMensajeError(
        errorEliminacion instanceof Error
          ? errorEliminacion.message
          : "Error eliminando grupo."
      );
    }
  }

  /** Crea una nueva asignatura en el catálogo institucional. */
  async function manejarCrearMateria(evento: FormEvent) {
    evento.preventDefault();
    establecerMensajeError(null);
    establecerMensajeEstado(null);
    try {
      await clienteApi.crearMateria({
        id_organizacion: organizacion.id,
        id_carrera: idCarreraMateria ? Number(idCarreraMateria) : null,
        nombre: nombreMateria.trim(),
        codigo: codigoMateria.trim(),
      });
      establecerNombreMateria("");
      establecerCodigoMateria("");
      establecerMensajeEstado("Asignatura agregada al catálogo.");
      await cargarDatosAcademicos();
    } catch (errorCreacion) {
      establecerMensajeError(
        errorCreacion instanceof Error
          ? errorCreacion.message
          : "Error creando asignatura."
      );
    }
  }

  /** Elimina una asignatura del catálogo. */
  async function manejarEliminarMateria(idMateria: number) {
    establecerMensajeError(null);
    try {
      await clienteApi.eliminarMateria(idMateria);
      await cargarDatosAcademicos();
    } catch (errorEliminacion) {
      establecerMensajeError(
        errorEliminacion instanceof Error
          ? errorEliminacion.message
          : "Error eliminando asignatura."
      );
    }
  }

  /** Al elegir un grupo en el formulario de curso, prellena su aula fija si existe. */
  function manejarSeleccionarGrupoCurso(valorIdGrupo: string) {
    establecerIdGrupoCurso(valorIdGrupo);
    const grupoSeleccionado = grupos.find(
      (grupo) => String(grupo.id) === valorIdGrupo
    );
    establecerAulaInicial(grupoSeleccionado?.aula_defecto ?? "");
  }

  /** Alterna un día semanal dentro del selector de horarios para nuevo curso. */
  function alternarDiaSeleccionado(dia: number) {
    establecerDiasSeleccionados((previos) =>
      previos.includes(dia)
        ? previos.filter((elemento) => elemento !== dia)
        : [...previos, dia].sort((diaA, diaB) => diaA - diaB)
    );
  }

  /** Acumula los días actualmente marcados como borradores antes de guardar el curso. */
  function agregarDiasSeleccionadosAPendientes() {
    if (diasSeleccionados.length === 0) return;
    establecerHorariosPendientes((previos) => {
      const siguientes = [...previos];
      const clavesExistentes = new Set(
        siguientes.map(
          (bloque) =>
            `${bloque.dia_semana}-${bloque.hora_inicio}-${bloque.hora_fin}`
        )
      );
      for (const dia of [...diasSeleccionados].sort((diaA, diaB) => diaA - diaB)) {
        const clave = `${dia}-${horaInicioInicial}-${horaFinInicial}`;
        if (!clavesExistentes.has(clave)) {
          siguientes.push({
            dia_semana: dia,
            hora_inicio: horaInicioInicial,
            hora_fin: horaFinInicial,
            aula: aulaInicial.trim(),
          });
          clavesExistentes.add(clave);
        }
      }
      return siguientes;
    });
    establecerDiasSeleccionados([]);
  }

  /** Crea la asignación de curso combinando los bloques acumulados y los días seleccionados. */
  async function manejarCrearCurso(evento: FormEvent) {
    evento.preventDefault();
    if (!idGrupoCurso || !idMateriaCurso) return;
    establecerMensajeError(null);
    establecerMensajeEstado(null);

    const bloquesCombinados: BorradorHorarioPendiente[] = [...horariosPendientes];
    const clavesVistas = new Set(
      bloquesCombinados.map(
        (bloque) => `${bloque.dia_semana}-${bloque.hora_inicio}-${bloque.hora_fin}`
      )
    );
    for (const dia of [...diasSeleccionados].sort((diaA, diaB) => diaA - diaB)) {
      const clave = `${dia}-${horaInicioInicial}-${horaFinInicial}`;
      if (!clavesVistas.has(clave)) {
        bloquesCombinados.push({
          dia_semana: dia,
          hora_inicio: horaInicioInicial,
          hora_fin: horaFinInicial,
          aula: aulaInicial.trim(),
        });
        clavesVistas.add(clave);
      }
    }

    if (bloquesCombinados.length === 0) {
      establecerMensajeError(
        "Selecciona al menos un día para el horario de la materia."
      );
      return;
    }

    try {
      await clienteApi.crearCurso({
        id_organizacion: organizacion.id,
        id_grupo: Number(idGrupoCurso),
        id_materia: Number(idMateriaCurso),
        id_usuario_docente: idDocenteCurso ? Number(idDocenteCurso) : null,
        periodo_lectivo: periodoLectivoCurso.trim() || null,
        horarios: bloquesCombinados.map((bloque) => ({
          dia_semana: bloque.dia_semana,
          hora_inicio: bloque.hora_inicio,
          hora_fin: bloque.hora_fin,
          aula: bloque.aula.trim() || null,
        })),
      });
      const grupoEncontrado = grupos.find(
        (grupo) => String(grupo.id) === idGrupoCurso
      );
      establecerHorariosPendientes([]);
      establecerDiasSeleccionados([obtenerDiaSemanaPorDefecto()]);
      establecerAulaInicial(grupoEncontrado?.aula_defecto ?? "");
      establecerMensajeEstado(
        `Asignatura vinculada al grupo con ${bloquesCombinados.length} bloque${
          bloquesCombinados.length === 1 ? "" : "s"
        } de horario.`
      );
      await Promise.all([cargarDatosAcademicos(), alRecargarOrganizacion()]);
    } catch (errorCreacion) {
      establecerMensajeError(
        errorCreacion instanceof Error
          ? errorCreacion.message
          : "Error asignando asignatura."
      );
    }
  }

  /** Reasigna inmediatamente el profesor responsable de una asignatura. */
  async function manejarReasignarDocente(idCurso: number, valorIdDocente: string) {
    establecerMensajeError(null);
    try {
      await clienteApi.actualizarCurso(idCurso, {
        id_usuario_docente: valorIdDocente ? Number(valorIdDocente) : null,
      });
      await cargarDatosAcademicos();
    } catch (errorReasignacion) {
      establecerMensajeError(
        errorReasignacion instanceof Error
          ? errorReasignacion.message
          : "No se pudo cambiar el profesor."
      );
    }
  }

  /** Obtiene o inicializa el estado local para añadir horarios inline en un curso. */
  function obtenerBorradorHorarioCurso(curso: AsignacionCurso) {
    return (
      borradoresHorarioCurso[curso.id] ?? {
        dias: [0],
        inicio: "08:00",
        fin: "09:00",
        aula: curso.aula_defecto_grupo ?? "",
      }
    );
  }

  /** Marca o desmarca un día en el editor inline de horarios de un curso existente. */
  function alternarDiaBorradorInline(curso: AsignacionCurso, dia: number) {
    const borrador = obtenerBorradorHorarioCurso(curso);
    const siguientesDias = borrador.dias.includes(dia)
      ? borrador.dias.filter((elemento) => elemento !== dia)
      : [...borrador.dias, dia].sort((diaA, diaB) => diaA - diaB);
    establecerBorradoresHorarioCurso((previos) => ({
      ...previos,
      [curso.id]: { ...borrador, dias: siguientesDias },
    }));
  }

  /** Agrega uno o varios bloques semanales a un curso existente desde la tarjeta inline. */
  async function manejarAgregarHorariosACurso(curso: AsignacionCurso) {
    const borrador = obtenerBorradorHorarioCurso(curso);
    if (borrador.dias.length === 0) {
      establecerMensajeError("Marca al menos un día para agregar el horario.");
      return;
    }
    establecerMensajeError(null);
    const aulaResuelta =
      (borrador.aula ?? curso.aula_defecto_grupo ?? "").trim() || null;
    try {
      for (const dia of borrador.dias) {
        await clienteApi.agregarHorarioCurso(curso.id, {
          dia_semana: dia,
          hora_inicio: borrador.inicio,
          hora_fin: borrador.fin,
          aula: aulaResuelta,
        });
      }
      establecerBorradoresHorarioCurso((previos) => ({
        ...previos,
        [curso.id]: {
          ...borrador,
          dias: [],
          aula: curso.aula_defecto_grupo ?? "",
        },
      }));
      await cargarDatosAcademicos();
    } catch (errorHorario) {
      establecerMensajeError(
        errorHorario instanceof Error ? errorHorario.message : "Error agregando horario."
      );
    }
  }

  /** Elimina un bloque horario semanal específico. */
  async function manejarEliminarHorario(idHorario: number) {
    establecerMensajeError(null);
    try {
      await clienteApi.eliminarHorario(idHorario);
      await cargarDatosAcademicos();
    } catch (errorEliminacion) {
      establecerMensajeError(
        errorEliminacion instanceof Error
          ? errorEliminacion.message
          : "Error eliminando horario."
      );
    }
  }

  /** Elimina la asignación completa de una materia en un grupo. */
  async function manejarEliminarCurso(idCurso: number) {
    establecerMensajeError(null);
    try {
      await clienteApi.eliminarCurso(idCurso);
      await Promise.all([cargarDatosAcademicos(), alRecargarOrganizacion()]);
    } catch (errorEliminacion) {
      establecerMensajeError(
        errorEliminacion instanceof Error
          ? errorEliminacion.message
          : "Error eliminando asignación."
      );
    }
  }

  /** Genera en lote todas las sesiones programadas para la fecha de hoy. */
  async function manejarGenerarSesionesHoy() {
    establecerMensajeError(null);
    establecerMensajeEstado(null);
    try {
      const respuesta = await clienteApi.generarSesionesAcademicas({
        id_organizacion: organizacion.id,
        fecha_objetivo: obtenerHoyIso(),
      });
      establecerMensajeEstado(
        `Sesiones del ${respuesta.fecha_objetivo}: ${respuesta.cantidad_creadas} creadas, ${respuesta.cantidad_existentes} ya existían.`
      );
      await alRecargarOrganizacion();
    } catch (errorGeneracion) {
      establecerMensajeError(
        errorGeneracion instanceof Error
          ? errorGeneracion.message
          : "No se pudieron generar las sesiones."
      );
    }
  }

  /** Abre o reutiliza la sesión de clase del día y redirige al kiosco biométrico. */
  async function manejarAbrirCursoEnKiosco(idCurso: number) {
    establecerMensajeError(null);
    try {
      const sesion = await clienteApi.iniciarSesionCurso(idCurso, {
        fecha_sesion: obtenerHoyIso(),
      });
      await alRecargarOrganizacion();
      alAbrirSesionEnKiosco(sesion.id);
    } catch (errorApertura) {
      establecerMensajeError(
        errorApertura instanceof Error
          ? errorApertura.message
          : "No se pudo abrir la sesión en Kiosco."
      );
    }
  }

  const carreraSeleccionadaNuevoGrupo = carreras.find(
    (carrera) => String(carrera.id) === idCarreraGrupo
  );
  const metadatosPeriodoNuevoGrupo = obtenerMetadatosPeriodo(
    tipoPeriodoGrupo ||
      carreraSeleccionadaNuevoGrupo?.tipo_periodo_efectivo ||
      tipoPeriodoOrg
  );
  const metadatosPeriodoOrg = obtenerMetadatosPeriodo(tipoPeriodoOrg);

  const materiasOrdenadas = estadisticas
    ? [...estadisticas.por_materia].sort((primerItem, segundoItem) => {
        const direccion = ordenMateriaAscendente ? 1 : -1;
        let comparacion = 0;
        if (ordenMateriaPor === "career_period") {
          comparacion = (primerItem.nombre_carrera ?? "ZZZ").localeCompare(
            segundoItem.nombre_carrera ?? "ZZZ",
            "es"
          );
          if (comparacion === 0)
            comparacion = compararPeriodosNatural(
              primerItem.semestre,
              segundoItem.semestre
            );
          if (comparacion === 0)
            comparacion = primerItem.nombre_materia.localeCompare(
              segundoItem.nombre_materia,
              "es"
            );
        } else if (ordenMateriaPor === "period_career") {
          comparacion = compararPeriodosNatural(
            primerItem.semestre,
            segundoItem.semestre
          );
          if (comparacion === 0) {
            comparacion = (primerItem.nombre_carrera ?? "ZZZ").localeCompare(
              segundoItem.nombre_carrera ?? "ZZZ",
              "es"
            );
          }
          if (comparacion === 0)
            comparacion = primerItem.nombre_materia.localeCompare(
              segundoItem.nombre_materia,
              "es"
            );
        } else if (ordenMateriaPor === "rate") {
          comparacion = primerItem.tasa_asistencia - segundoItem.tasa_asistencia;
        } else {
          comparacion = primerItem.nombre_materia.localeCompare(
            segundoItem.nombre_materia,
            "es"
          );
        }
        return comparacion * direccion;
      })
    : [];

  const gruposOrdenados = estadisticas
    ? [...estadisticas.por_grupo].sort((primerGrupo, segundoGrupo) => {
        const direccion = ordenGrupoAscendente ? 1 : -1;
        let comparacion = 0;
        if (ordenGrupoPor === "career_period") {
          comparacion = (primerGrupo.nombre_carrera ?? "ZZZ").localeCompare(
            segundoGrupo.nombre_carrera ?? "ZZZ",
            "es"
          );
          if (comparacion === 0)
            comparacion = compararPeriodosNatural(
              primerGrupo.semestre,
              segundoGrupo.semestre
            );
          if (comparacion === 0) {
            comparacion = primerGrupo.nombre_grupo.localeCompare(
              segundoGrupo.nombre_grupo,
              "es",
              { numeric: true }
            );
          }
        } else if (ordenGrupoPor === "period_career") {
          comparacion = compararPeriodosNatural(
            primerGrupo.semestre,
            segundoGrupo.semestre
          );
          if (comparacion === 0) {
            comparacion = (primerGrupo.nombre_carrera ?? "ZZZ").localeCompare(
              segundoGrupo.nombre_carrera ?? "ZZZ",
              "es"
            );
          }
          if (comparacion === 0) {
            comparacion = primerGrupo.nombre_grupo.localeCompare(
              segundoGrupo.nombre_grupo,
              "es",
              { numeric: true }
            );
          }
        } else if (ordenGrupoPor === "rate") {
          comparacion =
            primerGrupo.tasa_asistencia_general - segundoGrupo.tasa_asistencia_general;
        } else {
          comparacion = primerGrupo.nombre_grupo.localeCompare(
            segundoGrupo.nombre_grupo,
            "es",
            { numeric: true }
          );
        }
        return comparacion * direccion;
      })
    : [];

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <GraduationCap className="w-6 h-6 text-indigo-400" />
            Estructura Académica y Estadísticas
          </h2>
          <p className="text-sm text-slate-400">
            Jerarquía: Institución ({metadatosPeriodoOrg.etiqueta}) → Carrera → Grupo →
            Materias, Profesores y Horarios
          </p>
        </div>

        <button
          type="button"
          onClick={() => void manejarGenerarSesionesHoy()}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-semibold"
        >
          <CalendarCheck className="w-4 h-4" />
          Generar sesiones de hoy
        </button>
      </div>

      {/* Sub-pestañas */}
      <div className="flex flex-wrap gap-2 bg-slate-900 border border-slate-800 rounded-xl p-1.5 w-fit">
        {[
          { id: "structure" as const, etiqueta: "Carreras y Grupos", icono: Layers },
          { id: "courses" as const, etiqueta: "Materias y Horarios", icono: BookOpen },
          { id: "stats" as const, etiqueta: "Estadísticas", icono: BarChart3 },
        ].map((pestana) => {
          const Icono = pestana.icono;
          const activa = subPestana === pestana.id;
          return (
            <button
              key={pestana.id}
              type="button"
              onClick={() => establecerSubPestana(pestana.id)}
              className={`inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                activa ? "bg-indigo-600 text-white" : "text-slate-300 hover:bg-slate-800"
              }`}
            >
              <Icono className="w-4 h-4" />
              {pestana.etiqueta}
            </button>
          );
        })}
      </div>

      {mensajeEstado && (
        <div className="rounded-xl bg-emerald-500/15 border border-emerald-500/40 px-4 py-3 text-sm text-emerald-200">
          {mensajeEstado}
        </div>
      )}
      {mensajeError && (
        <div className="rounded-xl bg-red-500/15 border border-red-500/40 px-4 py-3 text-sm text-red-200">
          {mensajeError}
        </div>
      )}

      {cargando ? (
        <div className="py-10 text-center text-sm text-slate-400">
          Cargando estructura académica...
        </div>
      ) : (
        <>
          {subPestana === "structure" && (
            <div className="space-y-6">
              {/* Periodo general de la institución */}
              <form
                onSubmit={solicitarCambioPeriodoOrganizacion}
                className="bg-slate-900 border border-slate-800 rounded-2xl p-4 flex flex-wrap items-center justify-between gap-4"
              >
                <div>
                  <h3 className="font-semibold text-sm flex items-center gap-1.5">
                    Periodo académico general de la institución
                    <span title="Requiere contraseña de administrador para cambiar">
                      <Lock className="w-3.5 h-3.5 text-amber-400" />
                    </span>
                  </h3>
                  <p className="text-xs text-slate-400">
                    Se hereda por defecto en carreras y grupos (cada carrera o grupo puede
                    usar otro sistema; cambiarlo requiere contraseña admin).
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <select
                    value={tipoPeriodoOrg}
                    onChange={(evento) =>
                      establecerTipoPeriodoOrg(evento.target.value as TipoPeriodoAcademico)
                    }
                    className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                  >
                    {OPCIONES_PERIODO_ACADEMICO.map((opcion) => (
                      <option key={opcion.valor} value={opcion.valor}>
                        {opcion.etiqueta}
                      </option>
                    ))}
                  </select>
                  <button
                    type="submit"
                    disabled={
                      tipoPeriodoOrg ===
                      (organizacion.tipo_periodo_academico ?? "semestral")
                    }
                    className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-xs font-semibold"
                  >
                    Cambiar periodo
                  </button>
                </div>
              </form>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Alta de Carrera */}
                <form
                  onSubmit={manejarCrearCarrera}
                  className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3"
                >
                  <h3 className="font-semibold text-base">Nueva Carrera</h3>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                    <input
                      type="text"
                      required
                      value={nombreCarrera}
                      onChange={(evento) => establecerNombreCarrera(evento.target.value)}
                      placeholder="Ej. Ingeniería en Software"
                      className="sm:col-span-2 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                    />
                    <input
                      type="text"
                      required
                      value={codigoCarrera}
                      onChange={(evento) => establecerCodigoCarrera(evento.target.value)}
                      placeholder="Código (ISW)"
                      className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm uppercase"
                    />
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                    <input
                      type="text"
                      value={descripcionCarrera}
                      onChange={(evento) =>
                        establecerDescripcionCarrera(evento.target.value)
                      }
                      placeholder="Descripción opcional"
                      className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                    />
                    <select
                      value={tipoPeriodoCarrera}
                      onChange={(evento) =>
                        establecerTipoPeriodoCarrera(evento.target.value)
                      }
                      className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                    >
                      <option value="">
                        Usar general ({metadatosPeriodoOrg.etiqueta})
                      </option>
                      {OPCIONES_PERIODO_ACADEMICO.map((opcion) => (
                        <option key={opcion.valor} value={opcion.valor}>
                          {opcion.etiqueta}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="flex justify-end">
                    <button
                      type="submit"
                      className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-sm font-semibold"
                    >
                      <Plus className="w-4 h-4" />
                      Crear Carrera
                    </button>
                  </div>
                </form>

                {/* Alta de Grupo Académico */}
                <form
                  onSubmit={manejarCrearGrupo}
                  className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3"
                >
                  <h3 className="font-semibold text-base">Nuevo Grupo Académico</h3>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                    <input
                      type="text"
                      required
                      value={nombreGrupo}
                      onChange={(evento) => establecerNombreGrupo(evento.target.value)}
                      placeholder="Nombre (Ej. 21026 IS)"
                      className="sm:col-span-2 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                    />
                    <input
                      type="text"
                      required
                      value={codigoGrupo}
                      onChange={(evento) => establecerCodigoGrupo(evento.target.value)}
                      placeholder="Código"
                      className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                    />
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2.5">
                    <select
                      value={idCarreraGrupo}
                      onChange={(evento) => establecerIdCarreraGrupo(evento.target.value)}
                      className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                    >
                      <option value="">Sin carrera vinculada</option>
                      {carreras.map((carrera) => (
                        <option key={carrera.id} value={carrera.id}>
                          {carrera.nombre} ({carrera.codigo})
                        </option>
                      ))}
                    </select>
                    <select
                      value={tipoPeriodoGrupo}
                      onChange={(evento) =>
                        establecerTipoPeriodoGrupo(evento.target.value)
                      }
                      className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                      title="Tipo de periodo del grupo"
                    >
                      <option value="">
                        Heredar (
                        {
                          obtenerMetadatosPeriodo(
                            carreraSeleccionadaNuevoGrupo?.tipo_periodo_efectivo ??
                              tipoPeriodoOrg
                          ).etiqueta
                        }
                        )
                      </option>
                      {OPCIONES_PERIODO_ACADEMICO.map((opcion) => (
                        <option key={opcion.valor} value={opcion.valor}>
                          {opcion.etiqueta}
                        </option>
                      ))}
                    </select>
                    <input
                      type="text"
                      value={semestreGrupo}
                      onChange={(evento) => establecerSemestreGrupo(evento.target.value)}
                      placeholder={metadatosPeriodoNuevoGrupo.marcadorEjemplo}
                      title={metadatosPeriodoNuevoGrupo.singular}
                      className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                    />
                    <input
                      type="text"
                      value={aulaDefectoGrupo}
                      onChange={(evento) =>
                        establecerAulaDefectoGrupo(evento.target.value)
                      }
                      placeholder="Aula fija (ej. Aula 33)"
                      className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                    />
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] text-slate-400">
                      Periodo aplicable:{" "}
                      <strong>{metadatosPeriodoNuevoGrupo.singular}</strong> (
                      {metadatosPeriodoNuevoGrupo.etiqueta})
                    </span>
                    <button
                      type="submit"
                      className="inline-flex items-center justify-center gap-1.5 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-sm font-semibold"
                    >
                      <Plus className="w-4 h-4" />
                      Crear Grupo
                    </button>
                  </div>
                </form>
              </div>

              {/* Árbol Carrera -> Grupos */}
              <div className="space-y-4">
                {carreras.length === 0 ? (
                  <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 text-center text-sm text-slate-400">
                    Aún no hay carreras registradas. Crea la primera carrera arriba y vincula
                    sus grupos.
                  </div>
                ) : (
                  carreras.map((carrera) => {
                    const gruposCarrera = grupos
                      .filter((grupo) => grupo.id_carrera === carrera.id)
                      .sort((grupoA, grupoB) =>
                        compararPeriodosNatural(grupoA.semestre, grupoB.semestre)
                      );
                    const metaCarrera = obtenerMetadatosPeriodo(
                      carrera.tipo_periodo_efectivo
                    );
                    return (
                      <div
                        key={carrera.id}
                        className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3"
                      >
                        <div className="flex flex-wrap items-start justify-between gap-4">
                          <div>
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 text-xs font-semibold">
                                {carrera.codigo}
                              </span>
                              <h4 className="text-base font-bold">{carrera.nombre}</h4>
                              <span className="px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-[11px] text-slate-300">
                                {metaCarrera.etiqueta}
                                {carrera.tipo_periodo ? "" : " (heredado)"}
                              </span>
                            </div>
                            {carrera.descripcion && (
                              <p className="text-xs text-slate-400 mt-1">
                                {carrera.descripcion}
                              </p>
                            )}
                          </div>
                          <div className="flex items-center gap-2">
                            <select
                              value={carrera.tipo_periodo ?? ""}
                              onChange={(evento) =>
                                solicitarCambioPeriodoCarrera(carrera, evento.target.value)
                              }
                              className="bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1 text-xs"
                              title="Tipo de periodo de esta carrera (requiere contraseña de administrador)"
                            >
                              <option value="">
                                Usar general (
                                {
                                  obtenerMetadatosPeriodo(
                                    organizacion.tipo_periodo_academico
                                  ).etiqueta
                                }
                                )
                              </option>
                              {OPCIONES_PERIODO_ACADEMICO.map((opcion) => (
                                <option key={opcion.valor} value={opcion.valor}>
                                  {opcion.etiqueta}
                                </option>
                              ))}
                            </select>
                            <button
                              type="button"
                              onClick={() => void manejarEliminarCarrera(carrera.id)}
                              className="p-1.5 rounded-lg text-slate-400 hover:text-red-400 hover:bg-red-500/10"
                              title="Eliminar carrera"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </div>
                        </div>

                        {gruposCarrera.length === 0 ? (
                          <p className="text-xs text-slate-500 italic">
                            Sin grupos vinculados todavía.
                          </p>
                        ) : (
                          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                            {gruposCarrera.map((grupo) => {
                              const metaGrupo = obtenerMetadatosPeriodo(grupo.tipo_periodo);
                              const periodoFormateado = formatearEtiquetaPeriodoGrupo(
                                grupo.semestre,
                                grupo.tipo_periodo
                              );
                              return (
                                <div
                                  key={grupo.id}
                                  className="rounded-xl bg-slate-800/60 border border-slate-700/70 p-3.5 space-y-2"
                                >
                                  <div className="flex items-start justify-between gap-2">
                                    <div>
                                      <p className="text-sm font-semibold">
                                        {grupo.nombre}{" "}
                                        <span className="text-xs font-normal text-slate-400">
                                          ({grupo.codigo})
                                        </span>
                                      </p>
                                      <p className="text-xs text-slate-400 mt-0.5">
                                        {periodoFormateado ? (
                                          <span className="text-indigo-300 font-medium">
                                            {periodoFormateado}
                                            {grupo.tipo_periodo_personalizado
                                              ? " (propio)"
                                              : ""}{" "}
                                            ·{" "}
                                          </span>
                                        ) : (
                                          <span>
                                            {metaGrupo.etiqueta}
                                            {grupo.tipo_periodo_personalizado
                                              ? " (propio)"
                                              : ""}{" "}
                                            ·{" "}
                                          </span>
                                        )}
                                        {grupo.aula_defecto
                                          ? `${grupo.aula_defecto} · `
                                          : ""}
                                        {grupo.cantidad_integrantes} alumnos ·{" "}
                                        {grupo.cantidad_cursos} materias
                                      </p>
                                    </div>
                                    <div className="flex items-center gap-1">
                                      <button
                                        type="button"
                                        onClick={() =>
                                          idGrupoEditando === grupo.id
                                            ? establecerIdGrupoEditando(null)
                                            : iniciarEdicionGrupo(grupo)
                                        }
                                        className="p-1 text-slate-500 hover:text-indigo-300"
                                        title="Editar periodo, tipo de periodo y aula fija"
                                      >
                                        <Pencil className="w-3.5 h-3.5" />
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() => void manejarEliminarGrupo(grupo.id)}
                                        className="p-1 text-slate-500 hover:text-red-400"
                                        title="Eliminar grupo"
                                      >
                                        <Trash2 className="w-3.5 h-3.5" />
                                      </button>
                                    </div>
                                  </div>

                                  {idGrupoEditando === grupo.id && (
                                    <div className="grid grid-cols-2 gap-1.5 pt-2 border-t border-slate-700/60">
                                      <select
                                        value={tipoPeriodoGrupoEditado}
                                        onChange={(evento) =>
                                          establecerTipoPeriodoGrupoEditado(
                                            evento.target.value
                                          )
                                        }
                                        className="col-span-2 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs"
                                        title="Cambiar tipo de periodo requiere contraseña de administrador"
                                      >
                                        <option value="">
                                          Heredar de carrera/institución
                                        </option>
                                        {OPCIONES_PERIODO_ACADEMICO.map((opcion) => (
                                          <option key={opcion.valor} value={opcion.valor}>
                                            {opcion.etiqueta}
                                          </option>
                                        ))}
                                      </select>
                                      <input
                                        type="text"
                                        value={semestreGrupoEditado}
                                        onChange={(evento) =>
                                          establecerSemestreGrupoEditado(
                                            evento.target.value
                                          )
                                        }
                                        placeholder={`Núm. (${
                                          obtenerMetadatosPeriodo(
                                            tipoPeriodoGrupoEditado || grupo.tipo_periodo
                                          ).prefijo
                                        } ...)`}
                                        className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs"
                                      />
                                      <input
                                        type="text"
                                        value={aulaGrupoEditada}
                                        onChange={(evento) =>
                                          establecerAulaGrupoEditada(evento.target.value)
                                        }
                                        placeholder="Aula fija (ej. Aula 33)"
                                        className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs"
                                      />
                                      <button
                                        type="button"
                                        onClick={() => void manejarGuardarEdicionGrupo(grupo)}
                                        className="col-span-2 py-1 rounded bg-indigo-600 hover:bg-indigo-500 text-xs font-semibold"
                                      >
                                        {tipoPeriodoGrupoEditado !==
                                        (grupo.tipo_periodo_personalizado ?? "")
                                          ? "Continuar (requiere clave admin)"
                                          : "Guardar cambios"}
                                      </button>
                                    </div>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    );
                  })
                )}

                {grupos.some((grupo) => grupo.id_carrera === null) && (
                  <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3">
                    <h4 className="text-sm font-semibold text-slate-300">
                      Grupos sin carrera asignada
                    </h4>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      {grupos
                        .filter((grupo) => grupo.id_carrera === null)
                        .map((grupo) => {
                          const metaGrupo = obtenerMetadatosPeriodo(grupo.tipo_periodo);
                          const periodoFormateado = formatearEtiquetaPeriodoGrupo(
                            grupo.semestre,
                            grupo.tipo_periodo
                          );
                          return (
                            <div
                              key={grupo.id}
                              className="rounded-xl bg-slate-800/50 border border-slate-700/60 p-3 space-y-2"
                            >
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <div>
                                  <p className="text-sm font-medium">
                                    {grupo.nombre}{" "}
                                    <span className="text-xs text-slate-400">
                                      ({grupo.codigo})
                                    </span>
                                  </p>
                                  <p className="text-xs text-slate-400">
                                    {periodoFormateado ? (
                                      <span className="text-indigo-300 font-medium">
                                        {periodoFormateado} ·{" "}
                                      </span>
                                    ) : (
                                      <span>{metaGrupo.etiqueta} · </span>
                                    )}
                                    {grupo.aula_defecto ? `${grupo.aula_defecto} · ` : ""}
                                    {grupo.cantidad_integrantes} alumnos ·{" "}
                                    {grupo.cantidad_cursos} materias
                                  </p>
                                </div>
                                <div className="flex items-center gap-1.5">
                                  <button
                                    type="button"
                                    onClick={() =>
                                      idGrupoEditando === grupo.id
                                        ? establecerIdGrupoEditando(null)
                                        : iniciarEdicionGrupo(grupo)
                                    }
                                    className="p-1 text-slate-500 hover:text-indigo-300"
                                    title="Editar periodo, tipo de periodo y aula fija"
                                  >
                                    <Pencil className="w-3.5 h-3.5" />
                                  </button>
                                  <select
                                    defaultValue=""
                                    onChange={(evento) =>
                                      void manejarVincularGrupoACarrera(
                                        grupo.id,
                                        evento.target.value
                                      )
                                    }
                                    className="bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs"
                                  >
                                    <option value="">Asignar carrera...</option>
                                    {carreras.map((carrera) => (
                                      <option key={carrera.id} value={carrera.id}>
                                        {carrera.nombre}
                                      </option>
                                    ))}
                                  </select>
                                </div>
                              </div>

                              {idGrupoEditando === grupo.id && (
                                <div className="grid grid-cols-2 gap-1.5 pt-2 border-t border-slate-700/60">
                                  <select
                                    value={tipoPeriodoGrupoEditado}
                                    onChange={(evento) =>
                                      establecerTipoPeriodoGrupoEditado(
                                        evento.target.value
                                      )
                                    }
                                    className="col-span-2 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs"
                                  >
                                    <option value="">
                                      Heredar de carrera/institución
                                    </option>
                                    {OPCIONES_PERIODO_ACADEMICO.map((opcion) => (
                                      <option key={opcion.valor} value={opcion.valor}>
                                        {opcion.etiqueta}
                                      </option>
                                    ))}
                                  </select>
                                  <input
                                    type="text"
                                    value={semestreGrupoEditado}
                                    onChange={(evento) =>
                                      establecerSemestreGrupoEditado(evento.target.value)
                                    }
                                    placeholder={`Núm. (${
                                      obtenerMetadatosPeriodo(
                                        tipoPeriodoGrupoEditado || grupo.tipo_periodo
                                      ).prefijo
                                    } ...)`}
                                    className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs"
                                  />
                                  <input
                                    type="text"
                                    value={aulaGrupoEditada}
                                    onChange={(evento) =>
                                      establecerAulaGrupoEditada(evento.target.value)
                                    }
                                    placeholder="Aula fija (ej. Aula 33)"
                                    className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs"
                                  />
                                  <button
                                    type="button"
                                    onClick={() => void manejarGuardarEdicionGrupo(grupo)}
                                    className="col-span-2 py-1 rounded bg-indigo-600 hover:bg-indigo-500 text-xs font-semibold"
                                  >
                                    {tipoPeriodoGrupoEditado !==
                                    (grupo.tipo_periodo_personalizado ?? "")
                                      ? "Continuar (requiere clave admin)"
                                      : "Guardar cambios"}
                                  </button>
                                </div>
                              )}
                            </div>
                          );
                        })}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {subPestana === "courses" && (
            <div className="space-y-6">
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Catálogo de Asignaturas */}
                <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
                  <h3 className="font-semibold text-base">Catálogo de Asignaturas</h3>
                  <form onSubmit={manejarCrearMateria} className="space-y-2.5">
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                      <input
                        type="text"
                        required
                        value={nombreMateria}
                        onChange={(evento) => establecerNombreMateria(evento.target.value)}
                        placeholder="Ej. Arquitectura de Software"
                        className="sm:col-span-2 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                      />
                      <input
                        type="text"
                        required
                        value={codigoMateria}
                        onChange={(evento) => establecerCodigoMateria(evento.target.value)}
                        placeholder="Clave (ARQ-101)"
                        className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm uppercase"
                      />
                    </div>
                    <div className="flex gap-2.5">
                      <select
                        value={idCarreraMateria}
                        onChange={(evento) =>
                          establecerIdCarreraMateria(evento.target.value)
                        }
                        className="flex-1 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                      >
                        <option value="">Carrera general / Todas</option>
                        {carreras.map((carrera) => (
                          <option key={carrera.id} value={carrera.id}>
                            {carrera.nombre}
                          </option>
                        ))}
                      </select>
                      <button
                        type="submit"
                        className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-sm font-semibold"
                      >
                        <Plus className="w-4 h-4" />
                        Agregar
                      </button>
                    </div>
                  </form>

                  <div className="space-y-2 max-h-64 overflow-y-auto">
                    {materias.map((materia) => (
                      <div
                        key={materia.id}
                        className="flex items-center justify-between px-3 py-2 rounded-xl bg-slate-800/50 border border-slate-800"
                      >
                        <div>
                          <p className="text-sm font-medium">
                            {materia.nombre}{" "}
                            <span className="text-xs text-indigo-300">
                              ({materia.codigo})
                            </span>
                          </p>
                          {materia.nombre_carrera && (
                            <p className="text-[11px] text-slate-400">
                              {materia.nombre_carrera}
                            </p>
                          )}
                        </div>
                        <button
                          type="button"
                          onClick={() => void manejarEliminarMateria(materia.id)}
                          className="p-1 text-slate-400 hover:text-red-400"
                          title="Eliminar asignatura"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    ))}
                    {materias.length === 0 && (
                      <p className="text-xs text-slate-500 text-center py-4">
                        Agrega las materias que se imparten en la institución.
                      </p>
                    )}
                  </div>
                </div>

                {/* Vincular Grupo + Materia + Profesor + Múltiples Días */}
                <form
                  onSubmit={manejarCrearCurso}
                  className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3"
                >
                  <h3 className="font-semibold text-base">
                    Asignar Materia y Profesor a un Grupo
                  </h3>

                  {docentes.filter((docente) => docente.rol === "teacher").length ===
                    0 && (
                    <div className="rounded-xl bg-amber-500/10 border border-amber-500/30 px-3 py-2 text-xs text-amber-200">
                      Tip: crea cuentas con rol <strong>Profesor</strong> en la pestaña{" "}
                      <em>Seguridad y Usuarios</em> para que cada docente vea únicamente sus
                      materias.
                    </div>
                  )}

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                    <div>
                      <label className="block text-[11px] text-slate-400 mb-1">
                        Grupo
                      </label>
                      <select
                        required
                        value={idGrupoCurso}
                        onChange={(evento) =>
                          manejarSeleccionarGrupoCurso(evento.target.value)
                        }
                        className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                      >
                        <option value="">Selecciona grupo...</option>
                        {grupos.map((grupo) => (
                          <option key={grupo.id} value={grupo.id}>
                            {grupo.nombre} ({grupo.codigo})
                            {grupo.aula_defecto ? ` · ${grupo.aula_defecto}` : ""}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-[11px] text-slate-400 mb-1">
                        Asignatura
                      </label>
                      <select
                        required
                        value={idMateriaCurso}
                        onChange={(evento) => establecerIdMateriaCurso(evento.target.value)}
                        className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                      >
                        <option value="">Selecciona materia...</option>
                        {materias.map((materia) => (
                          <option key={materia.id} value={materia.id}>
                            {materia.nombre} ({materia.codigo})
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                    <div>
                      <label className="block text-[11px] text-slate-400 mb-1">
                        Profesor
                      </label>
                      <select
                        value={idDocenteCurso}
                        onChange={(evento) => establecerIdDocenteCurso(evento.target.value)}
                        className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                      >
                        <option value="">Sin asignar aún</option>
                        {docentes.map((docente) => (
                          <option key={docente.id} value={docente.id}>
                            {docente.nombre_completo} (
                            {docente.rol === "teacher" ? "Profesor" : "Admin"})
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-[11px] text-slate-400 mb-1">
                        Clave de periodo / ciclo
                      </label>
                      <input
                        type="text"
                        value={periodoLectivoCurso}
                        onChange={(evento) =>
                          establecerPeriodoLectivoCurso(evento.target.value)
                        }
                        placeholder="Ej. 2026-3"
                        className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                      />
                    </div>
                  </div>

                  <div className="pt-2 border-t border-slate-800 space-y-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-xs font-semibold text-slate-300">
                        Días y horario de clase (marca uno o varios días)
                      </p>
                      <span className="text-[11px] text-slate-400">
                        {diasSeleccionados.length} día
                        {diasSeleccionados.length === 1 ? "" : "s"}
                      </span>
                    </div>

                    <div className="flex flex-wrap gap-1.5">
                      {DIAS_SEMANA.map((dia) => {
                        const activo = diasSeleccionados.includes(dia.valor);
                        return (
                          <button
                            key={dia.valor}
                            type="button"
                            onClick={() => alternarDiaSeleccionado(dia.valor)}
                            className={`px-2.5 py-1 rounded-lg text-xs font-medium border transition-colors ${
                              activo
                                ? "bg-indigo-600 border-indigo-500 text-white"
                                : "bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700"
                            }`}
                          >
                            {dia.corto}
                          </button>
                        );
                      })}
                    </div>

                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 items-end">
                      <div>
                        <label className="block text-[10px] text-slate-400 mb-1">
                          Inicio
                        </label>
                        <input
                          type="time"
                          value={horaInicioInicial}
                          onChange={(evento) =>
                            establecerHoraInicioInicial(evento.target.value)
                          }
                          className="w-full bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-2 text-xs"
                        />
                      </div>
                      <div>
                        <label className="block text-[10px] text-slate-400 mb-1">
                          Fin
                        </label>
                        <input
                          type="time"
                          value={horaFinInicial}
                          onChange={(evento) =>
                            establecerHoraFinInicial(evento.target.value)
                          }
                          className="w-full bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-2 text-xs"
                        />
                      </div>
                      <div>
                        <label className="block text-[10px] text-slate-400 mb-1">
                          Aula (editable)
                        </label>
                        <input
                          type="text"
                          value={aulaInicial}
                          onChange={(evento) => establecerAulaInicial(evento.target.value)}
                          placeholder="Aula / Lab"
                          className="w-full bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-2 text-xs"
                        />
                      </div>
                      <button
                        type="button"
                        disabled={diasSeleccionados.length === 0}
                        onClick={agregarDiasSeleccionadosAPendientes}
                        className="inline-flex items-center justify-center gap-1.5 px-3.5 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 border border-emerald-400/50 text-white shadow-md shadow-emerald-950/50 ring-1 ring-emerald-400/30 disabled:opacity-40 disabled:shadow-none text-xs font-semibold transition-all"
                        title="Añade estos días para combinar con otros horarios o aulas distintas"
                      >
                        <Plus className="w-3.5 h-3.5 shrink-0" />
                        Agregar horario(s)
                      </button>
                    </div>

                    {horariosPendientes.length > 0 && (
                      <div className="space-y-1.5 rounded-xl bg-slate-800/40 border border-slate-800 p-2.5">
                        <p className="text-[11px] text-slate-400">
                          Horarios acumulados para esta materia (
                          {horariosPendientes.length}):
                        </p>
                        <div className="flex flex-wrap gap-1.5">
                          {horariosPendientes.map((bloque, indice) => (
                            <span
                              key={`${bloque.dia_semana}-${bloque.hora_inicio}-${indice}`}
                              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-indigo-500/15 border border-indigo-500/30 text-[11px] text-indigo-200"
                            >
                              <strong>{etiquetaDiaSemana(bloque.dia_semana)}</strong>{" "}
                              {bloque.hora_inicio}–{bloque.hora_fin}
                              {bloque.aula ? ` · ${bloque.aula}` : ""}
                              <button
                                type="button"
                                onClick={() =>
                                  establecerHorariosPendientes((previos) =>
                                    previos.filter((_, pos) => pos !== indice)
                                  )
                                }
                                className="text-indigo-300 hover:text-white"
                              >
                                <X className="w-3 h-3" />
                              </button>
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>

                  <button
                    type="submit"
                    className="w-full py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-sm font-semibold"
                  >
                    Asignar Materia al Grupo
                  </button>
                </form>
              </div>

              {/* Lista de asignaciones activas con editor inline de bloques */}
              <div className="space-y-3">
                <h3 className="font-semibold text-base">
                  Asignaciones y Horarios ({cursos.length})
                </h3>

                {cursos.length === 0 ? (
                  <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 text-center text-sm text-slate-400">
                    No hay asignaturas vinculadas a grupos todavía.
                  </div>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {cursos.map((curso) => {
                      const borrador = obtenerBorradorHorarioCurso(curso);
                      const aulaInline =
                        borrador.aula ?? curso.aula_defecto_grupo ?? "";
                      return (
                        <div
                          key={curso.id}
                          className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3"
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div>
                              <div className="flex items-center gap-2 flex-wrap">
                                <span className="px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 text-xs font-semibold">
                                  {curso.codigo_materia}
                                </span>
                                <h4 className="font-bold text-base">
                                  {curso.nombre_materia}
                                </h4>
                              </div>
                              <p className="text-xs text-slate-400 mt-1">
                                Grupo:{" "}
                                <strong className="text-slate-200">
                                  {curso.nombre_grupo}
                                </strong>
                                {curso.nombre_carrera ? ` · ${curso.nombre_carrera}` : ""}
                                {curso.semestre
                                  ? ` · ${formatearEtiquetaPeriodoGrupo(
                                      curso.semestre,
                                      curso.tipo_periodo
                                    )}`
                                  : ""}
                                {curso.aula_defecto_grupo
                                  ? ` · Aula base: ${curso.aula_defecto_grupo}`
                                  : ""}{" "}
                                · {curso.cantidad_estudiantes} alumnos heredados
                              </p>
                            </div>

                            <div className="flex items-center gap-1.5">
                              <button
                                type="button"
                                onClick={() => void manejarAbrirCursoEnKiosco(curso.id)}
                                className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-emerald-600/20 border border-emerald-500/40 hover:bg-emerald-600/30 text-emerald-300 text-xs font-semibold"
                                title="Abrir pase de lista en Kiosco"
                              >
                                <ScanFace className="w-3.5 h-3.5" />
                                Abrir pase
                              </button>
                              <button
                                type="button"
                                onClick={() => void manejarEliminarCurso(curso.id)}
                                className="p-1.5 rounded-lg text-slate-400 hover:text-red-400 hover:bg-red-500/10"
                                title="Eliminar asignación"
                              >
                                <Trash2 className="w-4 h-4" />
                              </button>
                            </div>
                          </div>

                          <div className="flex items-center gap-2 text-xs">
                            <span className="text-slate-400">Profesor:</span>
                            <select
                              value={curso.id_usuario_docente ?? ""}
                              onChange={(evento) =>
                                void manejarReasignarDocente(curso.id, evento.target.value)
                              }
                              className="flex-1 bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1 text-xs"
                            >
                              <option value="">Sin profesor asignado</option>
                              {docentes.map((docente) => (
                                <option key={docente.id} value={docente.id}>
                                  {docente.nombre_completo}
                                </option>
                              ))}
                            </select>
                          </div>

                          {/* Bloques de horario semanales */}
                          <div className="space-y-1.5 pt-1">
                            {curso.horarios.map((horario) => (
                              <div
                                key={horario.id}
                                className="flex items-center justify-between px-3 py-1.5 rounded-lg bg-slate-800/60 text-xs"
                              >
                                <span className="flex items-center gap-2">
                                  <Clock className="w-3.5 h-3.5 text-indigo-400" />
                                  <strong>
                                    {etiquetaDiaSemana(horario.dia_semana)}
                                  </strong>{" "}
                                  {horario.hora_inicio} – {horario.hora_fin}
                                  {horario.aula && (
                                    <span className="text-slate-400">
                                      · {horario.aula}
                                    </span>
                                  )}
                                </span>
                                <button
                                  type="button"
                                  onClick={() => void manejarEliminarHorario(horario.id)}
                                  className="text-slate-500 hover:text-red-400"
                                  title="Quitar bloque"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              </div>
                            ))}

                            <div className="pt-1.5 space-y-1.5 border-t border-slate-800/70">
                              <div className="flex flex-wrap gap-1">
                                {DIAS_SEMANA.map((dia) => {
                                  const marcado = borrador.dias.includes(dia.valor);
                                  return (
                                    <button
                                      key={dia.valor}
                                      type="button"
                                      onClick={() =>
                                        alternarDiaBorradorInline(curso, dia.valor)
                                      }
                                      className={`px-2 py-0.5 rounded text-[11px] font-medium border ${
                                        marcado
                                          ? "bg-indigo-600 border-indigo-500 text-white"
                                          : "bg-slate-800 border-slate-700 text-slate-400 hover:text-slate-200"
                                      }`}
                                      title={dia.etiqueta}
                                    >
                                      {dia.inicial}
                                    </button>
                                  );
                                })}
                              </div>
                              <div className="grid grid-cols-4 gap-1.5">
                                <input
                                  type="time"
                                  value={borrador.inicio}
                                  onChange={(evento) =>
                                    establecerBorradoresHorarioCurso((previos) => ({
                                      ...previos,
                                      [curso.id]: {
                                        ...borrador,
                                        inicio: evento.target.value,
                                      },
                                    }))
                                  }
                                  className="bg-slate-800 border border-slate-700 rounded px-1.5 py-1 text-[11px]"
                                />
                                <input
                                  type="time"
                                  value={borrador.fin}
                                  onChange={(evento) =>
                                    establecerBorradoresHorarioCurso((previos) => ({
                                      ...previos,
                                      [curso.id]: {
                                        ...borrador,
                                        fin: evento.target.value,
                                      },
                                    }))
                                  }
                                  className="bg-slate-800 border border-slate-700 rounded px-1.5 py-1 text-[11px]"
                                />
                                <input
                                  type="text"
                                  value={aulaInline}
                                  onChange={(evento) =>
                                    establecerBorradoresHorarioCurso((previos) => ({
                                      ...previos,
                                      [curso.id]: {
                                        ...borrador,
                                        aula: evento.target.value,
                                      },
                                    }))
                                  }
                                  placeholder="Aula"
                                  className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-[11px]"
                                />
                                <button
                                  type="button"
                                  onClick={() =>
                                    void manejarAgregarHorariosACurso(curso)
                                  }
                                  className="inline-flex items-center justify-center gap-1 rounded bg-emerald-600 hover:bg-emerald-500 border border-emerald-400/40 text-white text-[11px] font-semibold px-2 py-1 shadow-sm"
                                >
                                  <Plus className="w-3 h-3" />
                                  Hora(s)
                                </button>
                              </div>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          )}

          {subPestana === "stats" && (
            <div className="space-y-6">
              {/* Filtros */}
              <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 grid grid-cols-1 sm:grid-cols-5 gap-3 items-end">
                <div>
                  <label className="block text-[11px] text-slate-400 mb-1">Desde</label>
                  <input
                    type="date"
                    value={fechaDesdeEstadisticas}
                    onChange={(evento) =>
                      establecerFechaDesdeEstadisticas(evento.target.value)
                    }
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-xs"
                  />
                </div>
                <div>
                  <label className="block text-[11px] text-slate-400 mb-1">Hasta</label>
                  <input
                    type="date"
                    value={fechaHastaEstadisticas}
                    onChange={(evento) =>
                      establecerFechaHastaEstadisticas(evento.target.value)
                    }
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-xs"
                  />
                </div>
                <div>
                  <label className="block text-[11px] text-slate-400 mb-1">Carrera</label>
                  <select
                    value={idCarreraEstadisticas}
                    onChange={(evento) =>
                      establecerIdCarreraEstadisticas(evento.target.value)
                    }
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-xs"
                  >
                    <option value="">Todas</option>
                    {carreras.map((carrera) => (
                      <option key={carrera.id} value={carrera.id}>
                        {carrera.nombre}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-[11px] text-slate-400 mb-1">Grupo</label>
                  <select
                    value={idGrupoEstadisticas}
                    onChange={(evento) =>
                      establecerIdGrupoEstadisticas(evento.target.value)
                    }
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-xs"
                  >
                    <option value="">Todos</option>
                    {grupos.map((grupo) => (
                      <option key={grupo.id} value={grupo.id}>
                        {grupo.nombre}
                      </option>
                    ))}
                  </select>
                </div>
                <button
                  type="button"
                  onClick={() => void cargarEstadisticas()}
                  className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-xs font-semibold"
                >
                  Aplicar filtros
                </button>
              </div>

              {estadisticas && (
                <>
                  {/* KPIs globales */}
                  <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
                    {[
                      { etiqueta: "Carreras", valor: estadisticas.resumen.total_carreras },
                      { etiqueta: "Grupos", valor: estadisticas.resumen.total_grupos },
                      {
                        etiqueta: "Materias activas",
                        valor: estadisticas.resumen.total_cursos,
                      },
                      { etiqueta: "Sesiones", valor: estadisticas.resumen.total_sesiones },
                      {
                        etiqueta: "Asistencia global",
                        valor: `${estadisticas.resumen.tasa_asistencia_general.toFixed(1)}%`,
                      },
                    ].map((indicador) => (
                      <div
                        key={indicador.etiqueta}
                        className="bg-slate-900 border border-slate-800 rounded-2xl p-4"
                      >
                        <p className="text-xs text-slate-400">{indicador.etiqueta}</p>
                        <p className="text-2xl font-bold mt-1">{indicador.valor}</p>
                      </div>
                    ))}
                  </div>

                  {/* Por Asignatura */}
                  <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <h3 className="font-semibold text-base">
                        Asistencia por Asignatura
                      </h3>
                      <div className="flex items-center gap-2 text-xs">
                        <span className="text-slate-400">Ordenar por:</span>
                        <select
                          value={ordenMateriaPor}
                          onChange={(evento) =>
                            establecerOrdenMateriaPor(
                              evento.target.value as CampoOrdenMateria
                            )
                          }
                          className="bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1 text-xs"
                        >
                          <option value="career_period">Carrera y Periodo</option>
                          <option value="period_career">Periodo y Carrera</option>
                          <option value="rate">% Asistencia</option>
                          <option value="subject">Asignatura</option>
                        </select>
                        <button
                          type="button"
                          onClick={() =>
                            establecerOrdenMateriaAscendente((previa) => !previa)
                          }
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-slate-800 border border-slate-700 hover:bg-slate-700 text-xs"
                        >
                          <ArrowUpDown className="w-3.5 h-3.5" />
                          {ordenMateriaAscendente ? "Asc" : "Desc"}
                        </button>
                      </div>
                    </div>

                    <div className="overflow-x-auto">
                      <table className="w-full text-sm text-left">
                        <thead className="text-xs text-slate-400 border-b border-slate-800">
                          <tr>
                            <th className="py-2 pr-3">Carrera</th>
                            <th className="py-2 pr-3">Periodo</th>
                            <th className="py-2 pr-3">Grupo</th>
                            <th className="py-2 pr-3">Materia</th>
                            <th className="py-2 pr-3">Profesor</th>
                            <th className="py-2 pr-3">Sesiones</th>
                            <th className="py-2 pr-3">Asistencias</th>
                            <th className="py-2 pr-3">Retardos</th>
                            <th className="py-2 pr-3">Faltas</th>
                            <th className="py-2 pr-3">% Asistencia</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-800/80">
                          {materiasOrdenadas.map((fila) => (
                            <tr key={fila.id_asignacion_curso}>
                              <td className="py-2.5 pr-3 text-xs text-slate-300">
                                {fila.nombre_carrera ?? "—"}
                              </td>
                              <td className="py-2.5 pr-3 text-xs text-slate-300">
                                {formatearEtiquetaPeriodoGrupo(
                                  fila.semestre,
                                  fila.tipo_periodo
                                ) ?? obtenerMetadatosPeriodo(fila.tipo_periodo).etiqueta}
                              </td>
                              <td className="py-2.5 pr-3 text-xs font-medium">
                                {fila.nombre_grupo}
                              </td>
                              <td className="py-2.5 pr-3">
                                <span className="font-medium">{fila.nombre_materia}</span>{" "}
                                <span className="text-xs text-slate-400">
                                  ({fila.codigo_materia})
                                </span>
                              </td>
                              <td className="py-2.5 pr-3 text-xs text-slate-300">
                                {fila.nombre_docente ?? "—"}
                              </td>
                              <td className="py-2.5 pr-3 text-xs">
                                {fila.cantidad_sesiones}
                              </td>
                              <td className="py-2.5 pr-3 text-xs text-emerald-300">
                                {fila.cantidad_asistencias} / {fila.registros_esperados}
                              </td>
                              <td className="py-2.5 pr-3 text-xs text-amber-300">
                                {fila.cantidad_retardos}
                              </td>
                              <td className="py-2.5 pr-3 text-xs text-red-300">
                                {fila.cantidad_faltas}
                              </td>
                              <td className="py-2.5 pr-3 font-semibold text-indigo-300">
                                {fila.tasa_asistencia.toFixed(1)}%
                              </td>
                            </tr>
                          ))}
                          {materiasOrdenadas.length === 0 && (
                            <tr>
                              <td
                                colSpan={10}
                                className="py-6 text-center text-xs text-slate-500"
                              >
                                No hay asignaturas para mostrar con estos filtros.
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  {/* Consolidado por Grupo */}
                  <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <h3 className="font-semibold text-base">
                        Consolidado por Grupo (todas sus materias)
                      </h3>
                      <div className="flex items-center gap-2 text-xs">
                        <span className="text-slate-400">Ordenar por:</span>
                        <select
                          value={ordenGrupoPor}
                          onChange={(evento) =>
                            establecerOrdenGrupoPor(evento.target.value as CampoOrdenGrupo)
                          }
                          className="bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1 text-xs"
                        >
                          <option value="career_period">Carrera y Periodo</option>
                          <option value="period_career">Periodo y Carrera</option>
                          <option value="rate">% Asistencia</option>
                          <option value="group">Grupo</option>
                        </select>
                        <button
                          type="button"
                          onClick={() =>
                            establecerOrdenGrupoAscendente((previa) => !previa)
                          }
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-slate-800 border border-slate-700 hover:bg-slate-700 text-xs"
                        >
                          <ArrowUpDown className="w-3.5 h-3.5" />
                          {ordenGrupoAscendente ? "Asc" : "Desc"}
                        </button>
                      </div>
                    </div>

                    <div className="space-y-3">
                      {gruposOrdenados.map((grupoStat) => {
                        const expandido = Boolean(gruposExpandidos[grupoStat.id_grupo]);
                        const metaGrupo = obtenerMetadatosPeriodo(grupoStat.tipo_periodo);
                        return (
                          <div
                            key={grupoStat.id_grupo}
                            className="rounded-xl bg-slate-800/40 border border-slate-800 overflow-hidden"
                          >
                            <button
                              type="button"
                              onClick={() =>
                                establecerGruposExpandidos((previos) => ({
                                  ...previos,
                                  [grupoStat.id_grupo]: !expandido,
                                }))
                              }
                              className="w-full px-4 py-3 flex flex-wrap items-center justify-between gap-3 text-left hover:bg-slate-800/70"
                            >
                              <div>
                                <p className="font-semibold text-sm">
                                  {grupoStat.nombre_grupo}{" "}
                                  <span className="text-xs text-slate-400">
                                    ({grupoStat.codigo_grupo})
                                  </span>
                                </p>
                                <p className="text-xs text-slate-400">
                                  {grupoStat.nombre_carrera ?? "Sin carrera"} ·{" "}
                                  {formatearEtiquetaPeriodoGrupo(
                                    grupoStat.semestre,
                                    grupoStat.tipo_periodo
                                  ) ?? `${metaGrupo.etiqueta} (sin núm.)`}{" "}
                                  · {grupoStat.cantidad_materias} materias ·{" "}
                                  {grupoStat.cantidad_estudiantes} alumnos ·{" "}
                                  {grupoStat.total_sesiones} sesiones
                                </p>
                              </div>
                              <div className="flex items-center gap-4 text-xs">
                                <span className="text-emerald-300">
                                  {grupoStat.total_asistencias}/
                                  {grupoStat.total_esperados} asist.
                                </span>
                                <span className="px-2.5 py-1 rounded-full bg-indigo-500/20 text-indigo-300 font-bold">
                                  {grupoStat.tasa_asistencia_general.toFixed(1)}%
                                </span>
                                {expandido ? (
                                  <ChevronUp className="w-4 h-4 text-slate-400" />
                                ) : (
                                  <ChevronDown className="w-4 h-4 text-slate-400" />
                                )}
                              </div>
                            </button>

                            {expandido && (
                              <div className="px-4 pb-3 border-t border-slate-800/80 pt-2.5">
                                {grupoStat.desglose_estudiantes.length === 0 ? (
                                  <p className="text-xs text-slate-500">
                                    Sin alumnos asignados a este grupo.
                                  </p>
                                ) : (
                                  <table className="w-full text-xs">
                                    <thead className="text-slate-400 border-b border-slate-800">
                                      <tr>
                                        <th className="py-1.5 text-left">Matrícula</th>
                                        <th className="py-1.5 text-left">Alumno</th>
                                        <th className="py-1.5 text-left">Asistencias</th>
                                        <th className="py-1.5 text-left">Retardos</th>
                                        <th className="py-1.5 text-left">Faltas</th>
                                        <th className="py-1.5 text-left">% General</th>
                                      </tr>
                                    </thead>
                                    <tbody className="divide-y divide-slate-800/60">
                                      {grupoStat.desglose_estudiantes.map((alumno) => (
                                        <tr key={alumno.id_persona}>
                                          <td className="py-1.5 font-mono text-slate-300">
                                            {alumno.identificador_externo}
                                          </td>
                                          <td className="py-1.5 font-medium">
                                            {alumno.nombre_completo}
                                          </td>
                                          <td className="py-1.5 text-emerald-300">
                                            {alumno.cantidad_asistencias} /{" "}
                                            {alumno.registros_esperados}
                                          </td>
                                          <td className="py-1.5 text-amber-300">
                                            {alumno.cantidad_retardos}
                                          </td>
                                          <td className="py-1.5 text-red-300">
                                            {alumno.cantidad_faltas}
                                          </td>
                                          <td className="py-1.5 font-semibold text-indigo-300">
                                            {alumno.tasa_asistencia.toFixed(1)}%
                                          </td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                )}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </>
              )}
            </div>
          )}
        </>
      )}

      {cambioPeriodoPendiente && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <form
            onSubmit={manejarConfirmarCambioPeriodo}
            className="w-full max-w-md bg-slate-900 border border-amber-500/40 rounded-2xl p-6 space-y-4 shadow-2xl"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-xl bg-amber-500/15 border border-amber-500/30 flex items-center justify-center text-amber-400 shrink-0">
                  <Lock className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="font-bold text-base">Autorización de Administrador</h3>
                  <p className="text-xs text-slate-400">
                    Cambiar el tipo de periodo académico requiere contraseña de
                    administrador.
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => {
                  establecerCambioPeriodoPendiente(null);
                  establecerSecretoAutorizacionPeriodo("");
                  establecerErrorAutorizacionPeriodo(null);
                }}
                className="text-slate-400 hover:text-white"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="rounded-xl bg-slate-800/70 border border-slate-700 px-3.5 py-2.5 text-xs text-slate-200">
              {cambioPeriodoPendiente.resumen}
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1">
                Contraseña de administrador
              </label>
              <EntradaContrasena
                required
                autoFocus
                value={secretoAutorizacionPeriodo}
                onChange={(evento) =>
                  establecerSecretoAutorizacionPeriodo(evento.target.value)
                }
                placeholder="Ingresa la contraseña de administrador"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-500"
              />
            </div>

            {errorAutorizacionPeriodo && (
              <p className="text-xs text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">
                {errorAutorizacionPeriodo}
              </p>
            )}

            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  establecerCambioPeriodoPendiente(null);
                  establecerSecretoAutorizacionPeriodo("");
                  establecerErrorAutorizacionPeriodo(null);
                }}
                className="px-4 py-2 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={
                  enviandoAutorizacionPeriodo || !secretoAutorizacionPeriodo.trim()
                }
                className="px-4 py-2 rounded-lg text-xs font-semibold bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white"
              >
                {enviandoAutorizacionPeriodo ? "Validando..." : "Confirmar cambio"}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
