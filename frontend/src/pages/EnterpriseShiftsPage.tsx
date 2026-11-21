/**
 * Módulo de Turnos y Jornadas Empresariales de IdentIA.
 * Permite configurar turnos diurnos o nocturnos (con cruce de medianoche),
 * asignarlos por defecto a departamentos o individual/masivamente a empleados,
 * abrir jornadas del turno directo en el kiosco y analizar métricas de puntualidad.
 */
import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  ArrowUpDown,
  BarChart3,
  Briefcase,
  CalendarCheck,
  Clock,
  Moon,
  Pencil,
  Plus,
  ScanFace,
  Sun,
  Trash2,
  Users,
  X,
} from "lucide-react";
import { clienteApi } from "../lib/api";
import type {
  Grupo,
  Organizacion,
  Persona,
  RespuestaEstadisticasEmpresariales,
  TurnoLaboral,
  UsuarioAutenticado,
} from "../types/api";

/** Propiedades recibidas por `PaginaTurnosEmpresariales`. */
interface PropiedadesPaginaTurnosEmpresariales {
  /** Usuario autenticado para restringir acciones de escritura a administradores. */
  usuarioActual: UsuarioAutenticado;
  /** Organización empresarial seleccionada actualmente. */
  organizacion: Organizacion;
  /** Catálogo de departamentos o áreas de la empresa. */
  grupos: Grupo[];
  /** Empleados activos en la empresa. */
  personas: Persona[];
  /** Callback para recargar el estado compartido de grupos, personas y sesiones. */
  alRecargarOrganizacion: () => Promise<void>;
  /** Callback para abrir en el kiosco la jornada recién iniciada de un turno. */
  alAbrirSesionEnKiosco: (idSesion: number) => void;
}

type SubPestanaEmpresa = "shifts" | "assignments" | "stats";
type CampoOrdenEmpleado = "name" | "shift" | "attendance" | "absences" | "worked";

/** Catálogo ordenado de días de la semana (`0 = Lunes` a `6 = Domingo`). */
const DIAS_SEMANA = [
  { valor: 0, corto: "Lun", inicial: "L", etiqueta: "Lunes" },
  { valor: 1, corto: "Mar", inicial: "M", etiqueta: "Martes" },
  { valor: 2, corto: "Mié", inicial: "X", etiqueta: "Miércoles" },
  { valor: 3, corto: "Jue", inicial: "J", etiqueta: "Jueves" },
  { valor: 4, corto: "Vie", inicial: "V", etiqueta: "Viernes" },
  { valor: 5, corto: "Sáb", inicial: "S", etiqueta: "Sábado" },
  { valor: 6, corto: "Dom", inicial: "D", etiqueta: "Domingo" },
];

/** Da formato compacto en horas y minutos (`8h 30m` o `45m`) a una duración en minutos. */
function formatearDuracion(totalMinutos: number): string {
  const minutos = Math.max(0, Math.round(totalMinutos));
  const horas = Math.floor(minutos / 60);
  const restoMinutos = minutos % 60;
  if (horas === 0) return `${restoMinutos}m`;
  return `${horas}h ${String(restoMinutos).padStart(2, "0")}m`;
}

/**
 * Calcula en cliente si un turno cruza la medianoche y cuál es su duración esperada
 * antes de guardarlo en servidor.
 */
function calcularVistaPreviaTurno(
  horaInicio: string,
  horaFin: string
): {
  valido: boolean;
  cruzaMedianoche: boolean;
  duracionMinutos: number;
} {
  if (!/^\d{2}:\d{2}$/.test(horaInicio) || !/^\d{2}:\d{2}$/.test(horaFin)) {
    return { valido: false, cruzaMedianoche: false, duracionMinutos: 0 };
  }
  const [horaIniNum, minIniNum] = horaInicio.split(":").map(Number);
  const [horaFinNum, minFinNum] = horaFin.split(":").map(Number);
  const minutosInicio = horaIniNum * 60 + minIniNum;
  const minutosFin = horaFinNum * 60 + minFinNum;
  if (minutosInicio === minutosFin) {
    return { valido: false, cruzaMedianoche: false, duracionMinutos: 0 };
  }
  const cruzaMedianoche = minutosFin < minutosInicio;
  const duracionMinutos = cruzaMedianoche
    ? 1440 - minutosInicio + minutosFin
    : minutosFin - minutosInicio;
  return { valido: true, cruzaMedianoche, duracionMinutos };
}

/** Devuelve una fecha ISO (`YYYY-MM-DD`) desplazada `deltaDias` respecto a hoy. */
function obtenerFechaIsoDesplazada(deltaDias: number): string {
  const fecha = new Date();
  fecha.setDate(fecha.getDate() + deltaDias);
  const anio = fecha.getFullYear();
  const mes = String(fecha.getMonth() + 1).padStart(2, "0");
  const dia = String(fecha.getDate()).padStart(2, "0");
  return `${anio}-${mes}-${dia}`;
}

/**
 * Renderiza la gestión integral de turnos laborales, asignación heredada/directa
 * y tablero estadístico de asistencias, retardos y horas trabajadas.
 */
export function PaginaTurnosEmpresariales({
  usuarioActual,
  organizacion,
  grupos,
  personas,
  alRecargarOrganizacion,
  alAbrirSesionEnKiosco,
}: PropiedadesPaginaTurnosEmpresariales) {
  const puedeGestionar =
    usuarioActual.rol === "superadmin" || usuarioActual.rol === "org_admin";

  const [subPestana, establecerSubPestana] = useState<SubPestanaEmpresa>("shifts");
  const [turnos, establecerTurnos] = useState<TurnoLaboral[]>([]);
  const [estadisticas, establecerEstadisticas] =
    useState<RespuestaEstadisticasEmpresariales | null>(null);
  const [cargando, establecerCargando] = useState(false);
  const [cargandoEstadisticas, establecerCargandoEstadisticas] = useState(false);
  const [mensajeEstado, establecerMensajeEstado] = useState<string | null>(null);
  const [mensajeError, establecerMensajeError] = useState<string | null>(null);

  // Estado del formulario de creación o edición de turno laboral.
  const [idTurnoEditando, establecerIdTurnoEditando] = useState<number | null>(null);
  const [nombreTurno, establecerNombreTurno] = useState("");
  const [codigoTurno, establecerCodigoTurno] = useState("");
  const [horaInicio, establecerHoraInicio] = useState("09:00");
  const [horaFin, establecerHoraFin] = useState("18:00");
  const [diasSemana, establecerDiasSemana] = useState<number[]>([0, 1, 2, 3, 4]);
  const [toleranciaRetardo, establecerToleranciaRetardo] = useState<string>("");
  const [toleranciaSalidaAnticipada, establecerToleranciaSalidaAnticipada] =
    useState<number>(10);
  const [turnoActivo, establecerTurnoActivo] = useState(true);
  const [guardandoTurno, establecerGuardandoTurno] = useState(false);

  // Estado de filtros y asignación masiva a empleados y áreas.
  const [busquedaEmpleado, establecerBusquedaEmpleado] = useState("");
  const [filtroGrupoEmpleado, establecerFiltroGrupoEmpleado] = useState<string>("");
  const [filtroTurnoEmpleado, establecerFiltroTurnoEmpleado] = useState<string>("");
  const [idsPersonasSeleccionadas, establecerIdsPersonasSeleccionadas] = useState<
    number[]
  >([]);
  const [idTurnoMasivo, establecerIdTurnoMasivo] = useState<string>("");

  // Filtros y ordenamiento de estadísticas empresariales.
  const [fechaDesde, establecerFechaDesde] = useState<string>(() =>
    obtenerFechaIsoDesplazada(-6)
  );
  const [fechaHasta, establecerFechaHasta] = useState<string>(() =>
    obtenerFechaIsoDesplazada(0)
  );
  const [filtroTurnoEstadisticas, establecerFiltroTurnoEstadisticas] =
    useState<string>("");
  const [filtroGrupoEstadisticas, establecerFiltroGrupoEstadisticas] =
    useState<string>("");
  const [campoOrdenEmpleado, establecerCampoOrdenEmpleado] =
    useState<CampoOrdenEmpleado>("attendance");
  const [direccionOrdenEmpleado, establecerDireccionOrdenEmpleado] = useState<
    "asc" | "desc"
  >("desc");

  /** Carga el catálogo de turnos laborales de la organización. */
  const cargarTurnos = useCallback(async () => {
    establecerCargando(true);
    try {
      const lista = await clienteApi.listarTurnosLaborales(organizacion.id);
      establecerTurnos(lista);
      establecerMensajeError(null);
    } catch (errorCarga) {
      establecerMensajeError(
        errorCarga instanceof Error
          ? errorCarga.message
          : "Error cargando turnos laborales."
      );
    } finally {
      establecerCargando(false);
    }
  }, [organizacion.id]);

  /** Consulta métricas de asistencia y horas trabajadas para el rango filtrado. */
  const cargarEstadisticas = useCallback(async () => {
    establecerCargandoEstadisticas(true);
    try {
      const datos = await clienteApi.obtenerEstadisticasEmpresariales({
        id_organizacion: organizacion.id,
        fecha_desde: fechaDesde || null,
        fecha_hasta: fechaHasta || null,
        id_turno_laboral: filtroTurnoEstadisticas
          ? Number(filtroTurnoEstadisticas)
          : null,
        id_grupo: filtroGrupoEstadisticas ? Number(filtroGrupoEstadisticas) : null,
      });
      establecerEstadisticas(datos);
    } catch (errorCarga) {
      establecerMensajeError(
        errorCarga instanceof Error
          ? errorCarga.message
          : "No se pudieron cargar las estadísticas."
      );
    } finally {
      establecerCargandoEstadisticas(false);
    }
  }, [
    fechaDesde,
    fechaHasta,
    organizacion.id,
    filtroGrupoEstadisticas,
    filtroTurnoEstadisticas,
  ]);

  useEffect(() => {
    reiniciarFormularioTurno();
    establecerIdsPersonasSeleccionadas([]);
    establecerEstadisticas(null);
    void cargarTurnos();
  }, [cargarTurnos, organizacion.id]);

  useEffect(() => {
    if (subPestana === "stats") {
      void cargarEstadisticas();
    }
  }, [cargarEstadisticas, subPestana]);

  useEffect(() => {
    if (!idTurnoMasivo && turnos.length > 0) {
      const primerActivo = turnos.find((turno) => turno.esta_activo) ?? turnos[0];
      establecerIdTurnoMasivo(String(primerActivo.id));
    }
  }, [idTurnoMasivo, turnos]);

  /** Restablece el formulario de alta/edición de turno a sus valores por defecto. */
  function reiniciarFormularioTurno() {
    establecerIdTurnoEditando(null);
    establecerNombreTurno("");
    establecerCodigoTurno("");
    establecerHoraInicio("09:00");
    establecerHoraFin("18:00");
    establecerDiasSemana([0, 1, 2, 3, 4]);
    establecerToleranciaRetardo("");
    establecerToleranciaSalidaAnticipada(10);
    establecerTurnoActivo(true);
  }

  /** Carga los datos de un turno existente en el formulario para editarlo. */
  function iniciarEdicionTurno(turno: TurnoLaboral) {
    establecerIdTurnoEditando(turno.id);
    establecerNombreTurno(turno.nombre);
    establecerCodigoTurno(turno.codigo);
    establecerHoraInicio(turno.hora_inicio);
    establecerHoraFin(turno.hora_fin);
    establecerDiasSemana([...turno.dias_semana]);
    establecerToleranciaRetardo(
      turno.minutos_tolerancia_retardo !== null
        ? String(turno.minutos_tolerancia_retardo)
        : ""
    );
    establecerToleranciaSalidaAnticipada(turno.minutos_tolerancia_salida_anticipada);
    establecerTurnoActivo(turno.esta_activo);
    establecerMensajeEstado(null);
    establecerMensajeError(null);
  }

  /** Activa o desactiva un día laboral dentro de la selección semanal del turno. */
  function alternarDiaSemana(valorDia: number) {
    establecerDiasSemana((previos) =>
      previos.includes(valorDia)
        ? previos.filter((dia) => dia !== valorDia)
        : [...previos, valorDia].sort((diaA, diaB) => diaA - diaB)
    );
  }

  const vistaPrevia = calcularVistaPreviaTurno(horaInicio, horaFin);

  /** Crea o actualiza el turno laboral validando horario y días seleccionados. */
  async function manejarGuardarTurno(evento: FormEvent) {
    evento.preventDefault();
    if (!nombreTurno.trim() || !codigoTurno.trim()) return;
    if (!vistaPrevia.valido) {
      establecerMensajeError("La hora de entrada y salida no pueden ser iguales.");
      return;
    }
    if (diasSemana.length === 0) {
      establecerMensajeError("Selecciona al menos un día laboral para el turno.");
      return;
    }

    establecerMensajeError(null);
    establecerMensajeEstado(null);
    establecerGuardandoTurno(true);
    try {
      const toleranciaRetardoParseada =
        toleranciaRetardo.trim() === "" ? null : Number(toleranciaRetardo);
      if (idTurnoEditando !== null) {
        await clienteApi.actualizarTurnoLaboral(idTurnoEditando, {
          nombre: nombreTurno.trim(),
          codigo: codigoTurno.trim().toUpperCase(),
          hora_inicio: horaInicio,
          hora_fin: horaFin,
          dias_semana: diasSemana,
          minutos_tolerancia_retardo: toleranciaRetardoParseada,
          minutos_tolerancia_salida_anticipada: Number(toleranciaSalidaAnticipada),
          esta_activo: turnoActivo,
        });
        establecerMensajeEstado(
          `Turno "${nombreTurno.trim()}" actualizado correctamente.`
        );
      } else {
        await clienteApi.crearTurnoLaboral({
          id_organizacion: organizacion.id,
          nombre: nombreTurno.trim(),
          codigo: codigoTurno.trim().toUpperCase(),
          hora_inicio: horaInicio,
          hora_fin: horaFin,
          dias_semana: diasSemana,
          minutos_tolerancia_retardo: toleranciaRetardoParseada,
          minutos_tolerancia_salida_anticipada: Number(toleranciaSalidaAnticipada),
          esta_activo: turnoActivo,
        });
        establecerMensajeEstado(`Turno "${nombreTurno.trim()}" creado correctamente.`);
      }
      reiniciarFormularioTurno();
      await Promise.all([cargarTurnos(), alRecargarOrganizacion()]);
    } catch (errorGuardado) {
      establecerMensajeError(
        errorGuardado instanceof Error
          ? errorGuardado.message
          : "No se pudo guardar el turno."
      );
    } finally {
      establecerGuardandoTurno(false);
    }
  }

  /** Pausa o reactiva un turno para la generación automática de jornadas. */
  async function manejarAlternarTurnoActivo(turno: TurnoLaboral) {
    establecerMensajeError(null);
    try {
      await clienteApi.actualizarTurnoLaboral(turno.id, {
        esta_activo: !turno.esta_activo,
      });
      await Promise.all([cargarTurnos(), alRecargarOrganizacion()]);
    } catch (errorCambio) {
      establecerMensajeError(
        errorCambio instanceof Error
          ? errorCambio.message
          : "No se pudo cambiar el estado del turno."
      );
    }
  }

  /** Elimina un turno tras confirmar con el administrador. */
  async function manejarEliminarTurno(turno: TurnoLaboral) {
    if (
      !window.confirm(
        `¿Eliminar el turno "${turno.nombre} (${turno.codigo})"? Los empleados y áreas vinculados quedarán sin este turno asignado.`
      )
    ) {
      return;
    }
    establecerMensajeError(null);
    try {
      await clienteApi.eliminarTurnoLaboral(turno.id);
      if (idTurnoEditando === turno.id) reiniciarFormularioTurno();
      establecerMensajeEstado(`Turno "${turno.nombre}" eliminado.`);
      await Promise.all([cargarTurnos(), alRecargarOrganizacion()]);
    } catch (errorEliminacion) {
      establecerMensajeError(
        errorEliminacion instanceof Error
          ? errorEliminacion.message
          : "No se pudo eliminar el turno."
      );
    }
  }

  /** Abre la sesión diaria del turno y navega al kiosco biométrico. */
  async function manejarAbrirTurnoEnKiosco(idTurno: number) {
    establecerMensajeError(null);
    try {
      const sesion = await clienteApi.iniciarSesionTurno(idTurno, {
        fecha_sesion: obtenerFechaIsoDesplazada(0),
      });
      await alRecargarOrganizacion();
      alAbrirSesionEnKiosco(sesion.id);
    } catch (errorApertura) {
      establecerMensajeError(
        errorApertura instanceof Error
          ? errorApertura.message
          : "No se pudo abrir la jornada del turno."
      );
    }
  }

  /** Genera las jornadas correspondientes al día de hoy para todos los turnos activos. */
  async function manejarGenerarJornadasHoy() {
    establecerMensajeError(null);
    establecerMensajeEstado(null);
    try {
      const respuesta = await clienteApi.generarSesionesEmpresariales({
        id_organizacion: organizacion.id,
        fecha_objetivo: obtenerFechaIsoDesplazada(0),
      });
      establecerMensajeEstado(
        `Jornadas del ${respuesta.fecha_objetivo}: ${respuesta.cantidad_creadas} nuevas, ${respuesta.cantidad_existentes} existentes.`
      );
      await alRecargarOrganizacion();
    } catch (errorGeneracion) {
      establecerMensajeError(
        errorGeneracion instanceof Error
          ? errorGeneracion.message
          : "No se pudieron generar las jornadas."
      );
    }
  }

  /** Actualiza el turno heredado por defecto para un área o departamento. */
  async function manejarCambioTurnoDefectoGrupo(
    idGrupo: number,
    valorIdTurno: string
  ) {
    establecerMensajeError(null);
    try {
      await clienteApi.actualizarGrupo(idGrupo, {
        id_turno_laboral_defecto: valorIdTurno ? Number(valorIdTurno) : null,
      });
      await Promise.all([cargarTurnos(), alRecargarOrganizacion()]);
      establecerMensajeEstado("Turno por defecto del departamento actualizado.");
    } catch (errorCambio) {
      establecerMensajeError(
        errorCambio instanceof Error
          ? errorCambio.message
          : "No se pudo actualizar el turno del departamento."
      );
    }
  }

  /** Cambia el turno directo asignado a un empleado específico. */
  async function manejarCambioTurnoDirectoPersona(
    idPersona: number,
    valorIdTurno: string
  ) {
    establecerMensajeError(null);
    try {
      await clienteApi.actualizarPersona(idPersona, {
        id_turno_laboral: valorIdTurno ? Number(valorIdTurno) : null,
      });
      await Promise.all([cargarTurnos(), alRecargarOrganizacion()]);
    } catch (errorAsignacion) {
      establecerMensajeError(
        errorAsignacion instanceof Error
          ? errorAsignacion.message
          : "No se pudo asignar el turno al empleado."
      );
    }
  }

  /** Asigna o limpia el turno directo para todos los empleados marcados en bloque. */
  async function manejarAsignacionMasiva(limpiarTurno: boolean) {
    if (idsPersonasSeleccionadas.length === 0) return;
    const idTurnoObjetivo = limpiarTurno
      ? turnos[0]?.id
      : idTurnoMasivo
        ? Number(idTurnoMasivo)
        : turnos[0]?.id;
    if (!idTurnoObjetivo) {
      establecerMensajeError("Crea primero al menos un turno en el catálogo.");
      return;
    }

    establecerMensajeError(null);
    try {
      const respuesta = await clienteApi.asignarTurnoAPersonas(idTurnoObjetivo, {
        ids_personas: idsPersonasSeleccionadas,
        limpiar_turno: limpiarTurno,
      });
      establecerIdsPersonasSeleccionadas([]);
      establecerMensajeEstado(
        limpiarTurno
          ? `Se removió el turno directo en ${respuesta.cantidad_actualizados} empleado(s) (ahora heredan su departamento).`
          : `Se asignó "${respuesta.nombre_turno_laboral}" a ${respuesta.cantidad_actualizados} empleado(s).`
      );
      await Promise.all([cargarTurnos(), alRecargarOrganizacion()]);
    } catch (errorMasivo) {
      establecerMensajeError(
        errorMasivo instanceof Error
          ? errorMasivo.message
          : "Error en asignación masiva."
      );
    }
  }

  const mapaNombresGrupo = new Map(grupos.map((grupo) => [grupo.id, grupo.nombre]));
  const personasFiltradas = personas.filter((persona) => {
    if (
      filtroGrupoEmpleado &&
      !persona.ids_grupos.includes(Number(filtroGrupoEmpleado))
    ) {
      return false;
    }
    if (
      filtroTurnoEmpleado === "__none__" &&
      persona.id_turno_laboral_efectivo !== null
    ) {
      return false;
    }
    if (
      filtroTurnoEmpleado &&
      filtroTurnoEmpleado !== "__none__" &&
      String(persona.id_turno_laboral_efectivo ?? "") !== filtroTurnoEmpleado
    ) {
      return false;
    }
    const consulta = busquedaEmpleado.trim().toLowerCase();
    if (!consulta) return true;
    return (
      persona.nombre_completo.toLowerCase().includes(consulta) ||
      persona.identificador_externo.toLowerCase().includes(consulta)
    );
  });

  /** Marca o desmarca un colaborador en la tabla de asignación masiva. */
  function alternarSeleccionPersona(idPersona: number) {
    establecerIdsPersonasSeleccionadas((previos) =>
      previos.includes(idPersona)
        ? previos.filter((id) => id !== idPersona)
        : [...previos, idPersona]
    );
  }

  /** Selecciona o deselecciona a todos los colaboradores actualmente filtrados. */
  function alternarSeleccionarTodosVisibles() {
    const idsVisibles = personasFiltradas.map((persona) => persona.id);
    const todosSeleccionados =
      idsVisibles.length > 0 &&
      idsVisibles.every((id) => idsPersonasSeleccionadas.includes(id));
    if (todosSeleccionados) {
      establecerIdsPersonasSeleccionadas((previos) =>
        previos.filter((id) => !idsVisibles.includes(id))
      );
    } else {
      establecerIdsPersonasSeleccionadas((previos) =>
        Array.from(new Set([...previos, ...idsVisibles]))
      );
    }
  }

  const estadisticasEmpleadosOrdenadas = estadisticas
    ? [...estadisticas.por_empleado].sort((primerEmp, segundoEmp) => {
        const direccion = direccionOrdenEmpleado === "asc" ? 1 : -1;
        switch (campoOrdenEmpleado) {
          case "name":
            return (
              primerEmp.nombre_completo.localeCompare(segundoEmp.nombre_completo, "es") *
              direccion
            );
          case "shift":
            return (
              (primerEmp.nombre_turno ?? "zzz").localeCompare(
                segundoEmp.nombre_turno ?? "zzz",
                "es"
              ) * direccion
            );
          case "absences":
            return (primerEmp.dias_falta - segundoEmp.dias_falta) * direccion;
          case "worked":
            return (
              (primerEmp.total_minutos_trabajados -
                segundoEmp.total_minutos_trabajados) *
              direccion
            );
          case "attendance":
          default:
            return (primerEmp.tasa_asistencia - segundoEmp.tasa_asistencia) * direccion;
        }
      })
    : [];

  /** Alterna el campo y sentido de ordenamiento del detalle por colaborador. */
  function manejarOrdenarEmpleados(campo: CampoOrdenEmpleado) {
    if (campoOrdenEmpleado === campo) {
      establecerDireccionOrdenEmpleado((previa) => (previa === "asc" ? "desc" : "asc"));
    } else {
      establecerCampoOrdenEmpleado(campo);
      establecerDireccionOrdenEmpleado(
        campo === "name" || campo === "shift" ? "asc" : "desc"
      );
    }
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight flex items-center gap-2.5">
            <Briefcase className="w-6 h-6 text-indigo-400" />
            Turnos y Jornadas Empresariales
          </h2>
          <p className="text-sm text-slate-400 mt-0.5">
            Configura turnos diurnos o nocturnos, asígnalos a áreas y empleados y audita
            puntualidad y horas trabajadas.
          </p>
        </div>

        <button
          type="button"
          onClick={() => void manejarGenerarJornadasHoy()}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-emerald-600 hover:bg-emerald-500 text-white"
        >
          <CalendarCheck className="w-4 h-4" />
          Generar jornadas de hoy
        </button>
      </div>

      {/* Sub-pestañas del módulo empresarial */}
      <div className="flex flex-wrap gap-2 border-b border-slate-800 pb-3">
        {[
          { id: "shifts" as const, etiqueta: "Catálogo de Turnos", icono: Clock },
          {
            id: "assignments" as const,
            etiqueta: "Asignación a Personal y Áreas",
            icono: Users,
          },
          { id: "stats" as const, etiqueta: "Estadísticas de Jornada", icono: BarChart3 },
        ].map((pestana) => {
          const Icono = pestana.icono;
          const activa = subPestana === pestana.id;
          return (
            <button
              key={pestana.id}
              type="button"
              onClick={() => establecerSubPestana(pestana.id)}
              className={`inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                activa
                  ? "bg-indigo-600 text-white"
                  : "bg-slate-900 border border-slate-800 text-slate-300 hover:bg-slate-800"
              }`}
            >
              <Icono className="w-4 h-4" />
              {pestana.etiqueta}
            </button>
          );
        })}
      </div>

      {mensajeEstado && (
        <div className="rounded-xl bg-emerald-500/15 border border-emerald-500/40 px-4 py-2.5 text-xs text-emerald-200 flex items-center justify-between gap-2">
          <span>{mensajeEstado}</span>
          <button
            type="button"
            onClick={() => establecerMensajeEstado(null)}
            className="text-emerald-300 hover:underline"
          >
            Cerrar
          </button>
        </div>
      )}
      {mensajeError && (
        <div className="rounded-xl bg-red-500/15 border border-red-500/40 px-4 py-2.5 text-xs text-red-200 flex items-center justify-between gap-2">
          <span>{mensajeError}</span>
          <button
            type="button"
            onClick={() => establecerMensajeError(null)}
            className="text-red-300 hover:underline"
          >
            Cerrar
          </button>
        </div>
      )}

      {/* Sub-pestaña 1: Catálogo de Turnos */}
      {subPestana === "shifts" && (
        <div className="space-y-6">
          {puedeGestionar && (
            <form
              onSubmit={manejarGuardarTurno}
              className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="font-semibold text-base">
                  {idTurnoEditando !== null
                    ? "Editar Turno Laboral"
                    : "Nuevo Turno Laboral"}
                </h3>
                {idTurnoEditando !== null && (
                  <button
                    type="button"
                    onClick={reiniciarFormularioTurno}
                    className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-white"
                  >
                    <X className="w-3.5 h-3.5" />
                    Cancelar edición
                  </button>
                )}
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                <div>
                  <label className="block text-xs text-slate-400 mb-1">
                    Nombre del turno
                  </label>
                  <input
                    type="text"
                    required
                    value={nombreTurno}
                    onChange={(evento) => establecerNombreTurno(evento.target.value)}
                    placeholder="Ej. Matutino Planta / Nocturno"
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">
                    Código único
                  </label>
                  <input
                    type="text"
                    required
                    value={codigoTurno}
                    onChange={(evento) =>
                      establecerCodigoTurno(evento.target.value.toUpperCase())
                    }
                    placeholder="Ej. MAT-01"
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm uppercase"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">
                    Hora de entrada
                  </label>
                  <input
                    type="time"
                    required
                    value={horaInicio}
                    onChange={(evento) => establecerHoraInicio(evento.target.value)}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-400 mb-1">
                    Hora de salida
                  </label>
                  <input
                    type="time"
                    required
                    value={horaFin}
                    onChange={(evento) => establecerHoraFin(evento.target.value)}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                  />
                </div>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-3 bg-slate-950/60 border border-slate-800 rounded-xl px-3.5 py-2.5 text-xs">
                {!vistaPrevia.valido ? (
                  <span className="text-red-300">
                    La hora de entrada y salida deben ser distintas.
                  </span>
                ) : vistaPrevia.cruzaMedianoche ? (
                  <span className="inline-flex items-center gap-2 text-indigo-300 font-medium">
                    <Moon className="w-4 h-4 text-indigo-400" />
                    Turno nocturno (cruza medianoche: la salida se evalúa al día siguiente) ·
                    Duración: <strong>{formatearDuracion(vistaPrevia.duracionMinutos)}</strong>
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-2 text-emerald-300 font-medium">
                    <Sun className="w-4 h-4 text-emerald-400" />
                    Turno diurno/mixto (mismo día) · Duración:{" "}
                    <strong>{formatearDuracion(vistaPrevia.duracionMinutos)}</strong>
                  </span>
                )}
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-end">
                <div className="lg:col-span-1">
                  <div className="flex items-center justify-between mb-1.5">
                    <label className="text-xs text-slate-400">Días laborales</label>
                    <div className="flex gap-1.5 text-[11px]">
                      <button
                        type="button"
                        onClick={() => establecerDiasSemana([0, 1, 2, 3, 4])}
                        className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300"
                      >
                        L-V
                      </button>
                      <button
                        type="button"
                        onClick={() => establecerDiasSemana([0, 1, 2, 3, 4, 5])}
                        className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300"
                      >
                        L-S
                      </button>
                      <button
                        type="button"
                        onClick={() => establecerDiasSemana([0, 1, 2, 3, 4, 5, 6])}
                        className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300"
                      >
                        Todos
                      </button>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {DIAS_SEMANA.map((dia) => {
                      const activo = diasSemana.includes(dia.valor);
                      return (
                        <button
                          key={dia.valor}
                          type="button"
                          onClick={() => alternarDiaSemana(dia.valor)}
                          title={dia.etiqueta}
                          className={`px-2.5 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${
                            activo
                              ? "bg-indigo-600 border-indigo-500 text-white"
                              : "bg-slate-800 border-slate-700 text-slate-400 hover:text-white"
                          }`}
                        >
                          {dia.corto}
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div>
                  <label className="block text-xs text-slate-400 mb-1">
                    Tolerancia retardo (min, vacío = usar org:{" "}
                    {organizacion.minutos_tolerancia_retardo}m)
                  </label>
                  <input
                    type="number"
                    min={0}
                    max={180}
                    value={toleranciaRetardo}
                    onChange={(evento) =>
                      establecerToleranciaRetardo(evento.target.value)
                    }
                    placeholder={`Heredar (${organizacion.minutos_tolerancia_retardo} min)`}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                  />
                </div>

                <div className="flex items-end gap-3">
                  <div className="flex-1">
                    <label className="block text-xs text-slate-400 mb-1">
                      Tolerancia salida anticipada (min)
                    </label>
                    <input
                      type="number"
                      min={0}
                      max={180}
                      required
                      value={toleranciaSalidaAnticipada}
                      onChange={(evento) =>
                        establecerToleranciaSalidaAnticipada(Number(evento.target.value))
                      }
                      className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm"
                    />
                  </div>
                  <button
                    type="submit"
                    disabled={guardandoTurno || !vistaPrevia.valido}
                    className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-semibold bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white whitespace-nowrap"
                  >
                    <Plus className="w-4 h-4" />
                    {idTurnoEditando !== null ? "Guardar cambios" : "Crear turno"}
                  </button>
                </div>
              </div>

              {idTurnoEditando !== null && (
                <label className="inline-flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={turnoActivo}
                    onChange={(evento) => establecerTurnoActivo(evento.target.checked)}
                    className="rounded border-slate-600 bg-slate-800 text-indigo-600"
                  />
                  Turno activo para generación de jornadas
                </label>
              )}
            </form>
          )}

          {cargando ? (
            <p className="text-sm text-slate-400 py-8 text-center">Cargando turnos...</p>
          ) : turnos.length === 0 ? (
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-8 text-center text-sm text-slate-400">
              No hay turnos configurados en esta empresa. Crea el primero arriba (por
              ejemplo <span className="text-slate-200">Matutino 08:00–16:00</span> o{" "}
              <span className="text-slate-200">Nocturno 22:00–06:00</span>).
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {turnos.map((turno) => (
                <div
                  key={turno.id}
                  className={`bg-slate-900 border rounded-2xl p-5 space-y-3 ${
                    turno.esta_activo
                      ? "border-slate-800"
                      : "border-slate-800/60 opacity-75"
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h4 className="font-semibold text-base">{turno.nombre}</h4>
                        <span className="px-2 py-0.5 rounded-full text-[11px] font-mono bg-slate-800 text-slate-300 border border-slate-700">
                          {turno.codigo}
                        </span>
                        {turno.cruza_medianoche ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] bg-indigo-500/15 text-indigo-300 border border-indigo-500/30">
                            <Moon className="w-3 h-3" />
                            Cruza medianoche
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
                            <Sun className="w-3 h-3" />
                            Diurno
                          </span>
                        )}
                        {!turno.esta_activo && (
                          <span className="px-2 py-0.5 rounded-full text-[11px] bg-amber-500/15 text-amber-300 border border-amber-500/30">
                            Inactivo
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-slate-200 font-mono mt-1.5">
                        {turno.hora_inicio} → {turno.hora_fin}{" "}
                        <span className="text-xs text-slate-400 font-sans">
                          ({formatearDuracion(turno.duracion_esperada_minutos)})
                        </span>
                      </p>
                    </div>

                    {puedeGestionar && (
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => iniciarEdicionTurno(turno)}
                          className="p-1.5 rounded-lg text-slate-400 hover:text-indigo-300 hover:bg-indigo-500/10"
                          title="Editar turno"
                        >
                          <Pencil className="w-4 h-4" />
                        </button>
                        <button
                          type="button"
                          onClick={() => void manejarEliminarTurno(turno)}
                          className="p-1.5 rounded-lg text-slate-400 hover:text-red-400 hover:bg-red-500/10"
                          title="Eliminar turno"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    )}
                  </div>

                  <div className="flex flex-wrap gap-1">
                    {DIAS_SEMANA.map((dia) => {
                      const diaActivo = turno.dias_semana.includes(dia.valor);
                      return (
                        <span
                          key={dia.valor}
                          className={`px-2 py-0.5 rounded text-[11px] font-medium ${
                            diaActivo
                              ? "bg-indigo-600/20 text-indigo-300 border border-indigo-500/30"
                              : "bg-slate-800/60 text-slate-600"
                          }`}
                        >
                          {dia.inicial}
                        </span>
                      );
                    })}
                  </div>

                  <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-slate-800 text-xs text-slate-400">
                    <div className="space-y-0.5">
                      <p>
                        Retardo:{" "}
                        <strong className="text-slate-200">
                          {turno.minutos_tolerancia_retardo_efectiva} min
                        </strong>
                        {turno.minutos_tolerancia_retardo === null ? " (org)" : ""} · Salida
                        ant.:{" "}
                        <strong className="text-slate-200">
                          {turno.minutos_tolerancia_salida_anticipada} min
                        </strong>
                      </p>
                      <p>
                        <strong className="text-slate-200">
                          {turno.cantidad_empleados_asignados}
                        </strong>{" "}
                        empleados directos ·{" "}
                        <strong className="text-slate-200">
                          {turno.cantidad_grupos_por_defecto}
                        </strong>{" "}
                        áreas por defecto
                      </p>
                    </div>

                    <div className="flex items-center gap-2">
                      {puedeGestionar && (
                        <button
                          type="button"
                          onClick={() => void manejarAlternarTurnoActivo(turno)}
                          className="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 text-xs"
                        >
                          {turno.esta_activo ? "Pausar" : "Activar"}
                        </button>
                      )}
                      {turno.esta_activo && (
                        <button
                          type="button"
                          onClick={() => void manejarAbrirTurnoEnKiosco(turno.id)}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold"
                        >
                          <ScanFace className="w-3.5 h-3.5" />
                          Abrir en Kiosco
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Sub-pestaña 2: Asignación a Personal y Departamentos */}
      {subPestana === "assignments" && (
        <div className="space-y-6">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3">
            <div>
              <h3 className="font-semibold text-base">
                Turno por Defecto por Área / Departamento
              </h3>
              <p className="text-xs text-slate-400">
                Todo empleado sin turno individual asignado hereda automáticamente el turno
                del primer departamento al que pertenezca.
              </p>
            </div>
            {grupos.length === 0 ? (
              <p className="text-xs text-slate-500">No hay departamentos registrados.</p>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {grupos.map((grupo) => (
                  <div
                    key={grupo.id}
                    className="rounded-xl bg-slate-800/60 border border-slate-800 p-3.5 space-y-2"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-sm font-medium truncate">
                        {grupo.nombre}{" "}
                        <span className="text-xs text-slate-400">({grupo.codigo})</span>
                      </p>
                      <span className="text-[11px] text-slate-400 shrink-0">
                        {grupo.cantidad_integrantes} pers.
                      </span>
                    </div>
                    <select
                      disabled={!puedeGestionar}
                      value={
                        grupo.id_turno_laboral_defecto
                          ? String(grupo.id_turno_laboral_defecto)
                          : ""
                      }
                      onChange={(evento) =>
                        void manejarCambioTurnoDefectoGrupo(grupo.id, evento.target.value)
                      }
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs disabled:opacity-60"
                    >
                      <option value="">Sin turno por defecto</option>
                      {turnos.map((turno) => (
                        <option key={turno.id} value={turno.id}>
                          {turno.nombre} ({turno.hora_inicio}-{turno.hora_fin})
                        </option>
                      ))}
                    </select>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="font-semibold text-base">
                  Asignación de Turno por Empleado
                </h3>
                <p className="text-xs text-slate-400">
                  Asigna individualmente o marca varios empleados para asignar/limpiar en
                  lote.
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <input
                  type="text"
                  value={busquedaEmpleado}
                  onChange={(evento) => establecerBusquedaEmpleado(evento.target.value)}
                  placeholder="Buscar empleado o ID..."
                  className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-xs"
                />
                <select
                  value={filtroGrupoEmpleado}
                  onChange={(evento) =>
                    establecerFiltroGrupoEmpleado(evento.target.value)
                  }
                  className="bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs"
                >
                  <option value="">Todos los departamentos</option>
                  {grupos.map((grupo) => (
                    <option key={grupo.id} value={grupo.id}>
                      {grupo.nombre}
                    </option>
                  ))}
                </select>
                <select
                  value={filtroTurnoEmpleado}
                  onChange={(evento) =>
                    establecerFiltroTurnoEmpleado(evento.target.value)
                  }
                  className="bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs"
                >
                  <option value="">Todos los turnos</option>
                  <option value="__none__">Sin turno asignado</option>
                  {turnos.map((turno) => (
                    <option key={turno.id} value={turno.id}>
                      {turno.nombre} ({turno.codigo})
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {puedeGestionar &&
              idsPersonasSeleccionadas.length > 0 &&
              turnos.length > 0 && (
                <div className="rounded-xl bg-indigo-500/10 border border-indigo-500/40 px-4 py-3 flex flex-wrap items-center justify-between gap-3">
                  <span className="text-xs font-medium text-indigo-200">
                    {idsPersonasSeleccionadas.length} empleado(s) seleccionado(s)
                  </span>
                  <div className="flex flex-wrap items-center gap-2">
                    <select
                      value={idTurnoMasivo}
                      onChange={(evento) => establecerIdTurnoMasivo(evento.target.value)}
                      className="bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs"
                    >
                      {turnos.map((turno) => (
                        <option key={turno.id} value={turno.id}>
                          {turno.nombre} ({turno.hora_inicio}-{turno.hora_fin})
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => void manejarAsignacionMasiva(false)}
                      className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold"
                    >
                      Asignar turno
                    </button>
                    <button
                      type="button"
                      onClick={() => void manejarAsignacionMasiva(true)}
                      className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 text-xs"
                    >
                      Quitar turno directo (heredar)
                    </button>
                  </div>
                </div>
              )}

            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead className="text-xs uppercase text-slate-400 border-b border-slate-800">
                  <tr>
                    {puedeGestionar && (
                      <th className="py-2 pr-2 w-8">
                        <input
                          type="checkbox"
                          checked={
                            personasFiltradas.length > 0 &&
                            personasFiltradas.every((persona) =>
                              idsPersonasSeleccionadas.includes(persona.id)
                            )
                          }
                          onChange={alternarSeleccionarTodosVisibles}
                          className="rounded border-slate-600 bg-slate-800 text-indigo-600"
                          title="Seleccionar visibles"
                        />
                      </th>
                    )}
                    <th className="py-2 pr-3">Empleado</th>
                    <th className="py-2 px-3">Departamentos</th>
                    <th className="py-2 px-3">Turno Efectivo</th>
                    <th className="py-2 pl-3">Turno Directo</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/70">
                  {personasFiltradas.length === 0 ? (
                    <tr>
                      <td
                        colSpan={puedeGestionar ? 5 : 4}
                        className="py-6 text-center text-xs text-slate-500"
                      >
                        No hay empleados que coincidan con el filtro.
                      </td>
                    </tr>
                  ) : (
                    personasFiltradas.map((persona) => (
                      <tr key={persona.id} className="hover:bg-slate-800/30">
                        {puedeGestionar && (
                          <td className="py-2.5 pr-2">
                            <input
                              type="checkbox"
                              checked={idsPersonasSeleccionadas.includes(persona.id)}
                              onChange={() => alternarSeleccionPersona(persona.id)}
                              className="rounded border-slate-600 bg-slate-800 text-indigo-600"
                            />
                          </td>
                        )}
                        <td className="py-2.5 pr-3">
                          <p className="font-medium leading-tight">
                            {persona.nombre_completo}
                          </p>
                          <p className="text-xs text-slate-500">
                            {persona.identificador_externo}
                          </p>
                        </td>
                        <td className="py-2.5 px-3 text-xs text-slate-300">
                          {persona.ids_grupos.length > 0
                            ? persona.ids_grupos
                                .map(
                                  (idGrupo) =>
                                    mapaNombresGrupo.get(idGrupo) ?? `#${idGrupo}`
                                )
                                .join(", ")
                            : "—"}
                        </td>
                        <td className="py-2.5 px-3 text-xs">
                          {persona.nombre_turno_laboral_efectivo ? (
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className="font-medium text-slate-100">
                                {persona.nombre_turno_laboral_efectivo}
                              </span>
                              <span
                                className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${
                                  persona.origen_turno === "direct"
                                    ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/30"
                                    : "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
                                }`}
                              >
                                {persona.origen_turno === "direct"
                                  ? "Directo"
                                  : "Heredado de área"}
                              </span>
                            </div>
                          ) : (
                            <span className="px-2 py-0.5 rounded-full text-[10px] bg-slate-800 text-slate-400">
                              Sin turno
                            </span>
                          )}
                        </td>
                        <td className="py-2.5 pl-3">
                          <select
                            disabled={!puedeGestionar}
                            value={
                              persona.id_turno_laboral
                                ? String(persona.id_turno_laboral)
                                : ""
                            }
                            onChange={(evento) =>
                              void manejarCambioTurnoDirectoPersona(
                                persona.id,
                                evento.target.value
                              )
                            }
                            className="bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs disabled:opacity-60"
                          >
                            <option value="">
                              (Heredar de departamento / Sin turno)
                            </option>
                            {turnos.map((turno) => (
                              <option key={turno.id} value={turno.id}>
                                {turno.nombre} ({turno.hora_inicio}-{turno.hora_fin})
                              </option>
                            ))}
                          </select>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Sub-pestaña 3: Estadísticas de Jornada */}
      {subPestana === "stats" && (
        <div className="space-y-6">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 flex flex-wrap items-end justify-between gap-3">
            <div className="flex flex-wrap items-center gap-1.5">
              <button
                type="button"
                onClick={() => {
                  const hoy = obtenerFechaIsoDesplazada(0);
                  establecerFechaDesde(hoy);
                  establecerFechaHasta(hoy);
                }}
                className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs"
              >
                Hoy
              </button>
              <button
                type="button"
                onClick={() => {
                  establecerFechaDesde(obtenerFechaIsoDesplazada(-6));
                  establecerFechaHasta(obtenerFechaIsoDesplazada(0));
                }}
                className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs"
              >
                Últimos 7 días
              </button>
              <button
                type="button"
                onClick={() => {
                  establecerFechaDesde(obtenerFechaIsoDesplazada(-29));
                  establecerFechaHasta(obtenerFechaIsoDesplazada(0));
                }}
                className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs"
              >
                Últimos 30 días
              </button>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 w-full lg:w-auto">
              <div>
                <label className="block text-[11px] text-slate-400 mb-1">Desde</label>
                <input
                  type="date"
                  value={fechaDesde}
                  onChange={(evento) => establecerFechaDesde(evento.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs"
                />
              </div>
              <div>
                <label className="block text-[11px] text-slate-400 mb-1">Hasta</label>
                <input
                  type="date"
                  value={fechaHasta}
                  onChange={(evento) => establecerFechaHasta(evento.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs"
                />
              </div>
              <div>
                <label className="block text-[11px] text-slate-400 mb-1">Turno</label>
                <select
                  value={filtroTurnoEstadisticas}
                  onChange={(evento) =>
                    establecerFiltroTurnoEstadisticas(evento.target.value)
                  }
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs"
                >
                  <option value="">Todos los turnos</option>
                  {turnos.map((turno) => (
                    <option key={turno.id} value={turno.id}>
                      {turno.nombre}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-[11px] text-slate-400 mb-1">
                  Departamento
                </label>
                <select
                  value={filtroGrupoEstadisticas}
                  onChange={(evento) =>
                    establecerFiltroGrupoEstadisticas(evento.target.value)
                  }
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs"
                >
                  <option value="">Todos</option>
                  {grupos.map((grupo) => (
                    <option key={grupo.id} value={grupo.id}>
                      {grupo.nombre}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          {cargandoEstadisticas || !estadisticas ? (
            <p className="text-sm text-slate-400 py-8 text-center">
              Calculando métricas...
            </p>
          ) : (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4">
                  <p className="text-xs text-slate-400 uppercase">Turnos Activos</p>
                  <p className="text-2xl font-bold mt-1">
                    {estadisticas.resumen.turnos_activos}{" "}
                    <span className="text-sm font-normal text-slate-400">
                      / {estadisticas.resumen.total_turnos}
                    </span>
                  </p>
                </div>
                <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4">
                  <p className="text-xs text-slate-400 uppercase">Empleados con Turno</p>
                  <p className="text-2xl font-bold mt-1">
                    {estadisticas.resumen.empleados_asignados}{" "}
                    <span className="text-sm font-normal text-slate-400">
                      / {estadisticas.resumen.total_empleados}
                    </span>
                  </p>
                </div>
                <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4">
                  <p className="text-xs text-slate-400 uppercase">
                    Asistencia del Periodo
                  </p>
                  <p className="text-2xl font-bold mt-1 text-emerald-300">
                    {estadisticas.resumen.tasa_asistencia.toFixed(1)}%
                  </p>
                  <p className="text-[11px] text-slate-500 mt-0.5">
                    {estadisticas.resumen.dias_asistidos} /{" "}
                    {estadisticas.resumen.dias_empleado_programados} jornadas
                  </p>
                </div>
                <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4">
                  <p className="text-xs text-slate-400 uppercase">Puntualidad</p>
                  <p className="text-2xl font-bold mt-1 text-indigo-300">
                    {estadisticas.resumen.tasa_puntualidad.toFixed(1)}%
                  </p>
                  <p className="text-[11px] text-slate-500 mt-0.5">
                    Total trabajado:{" "}
                    {formatearDuracion(estadisticas.resumen.total_minutos_trabajados)}
                  </p>
                </div>
              </div>

              <div className="flex flex-wrap gap-2 text-xs">
                <span className="px-3 py-1 rounded-full bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
                  A tiempo: <strong>{estadisticas.resumen.dias_puntuales}</strong>
                </span>
                <span className="px-3 py-1 rounded-full bg-amber-500/15 text-amber-300 border border-amber-500/30">
                  Retardos: <strong>{estadisticas.resumen.dias_con_retardo}</strong>
                </span>
                <span className="px-3 py-1 rounded-full bg-orange-500/15 text-orange-300 border border-orange-500/30">
                  Salidas anticipadas:{" "}
                  <strong>{estadisticas.resumen.dias_salida_anticipada}</strong>
                </span>
                <span className="px-3 py-1 rounded-full bg-red-500/15 text-red-300 border border-red-500/30">
                  Faltas: <strong>{estadisticas.resumen.dias_falta}</strong>
                </span>
                <span className="px-3 py-1 rounded-full bg-slate-800 text-slate-300 border border-slate-700">
                  Sin salida registrada:{" "}
                  <strong>{estadisticas.resumen.dias_sin_salida}</strong>
                </span>
              </div>

              {/* Resumen por Turno */}
              <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3">
                <h3 className="font-semibold text-base">Resumen por Turno</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm text-left">
                    <thead className="text-xs uppercase text-slate-400 border-b border-slate-800">
                      <tr>
                        <th className="py-2 pr-3">Turno</th>
                        <th className="py-2 px-2">Horario</th>
                        <th className="py-2 px-2 text-right">Empl.</th>
                        <th className="py-2 px-2 text-right">Prog.</th>
                        <th className="py-2 px-2 text-right">Asist.</th>
                        <th className="py-2 px-2 text-right">Retardos</th>
                        <th className="py-2 px-2 text-right">Sal. Ant.</th>
                        <th className="py-2 px-2 text-right">Faltas</th>
                        <th className="py-2 px-2 text-right">Prom.</th>
                        <th className="py-2 pl-2 text-right">Asist. / Punt.</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/70">
                      {estadisticas.por_turno.map((fila) => (
                        <tr
                          key={fila.id_turno_laboral ?? "unassigned"}
                          className="hover:bg-slate-800/30"
                        >
                          <td className="py-2.5 pr-3 font-medium">
                            {fila.nombre_turno}
                            {fila.codigo_turno && (
                              <span className="ml-1.5 text-xs text-slate-400">
                                ({fila.codigo_turno})
                              </span>
                            )}
                          </td>
                          <td className="py-2.5 px-2 text-xs text-slate-300">
                            {fila.hora_inicio && fila.hora_fin
                              ? `${fila.hora_inicio}-${fila.hora_fin}${
                                  fila.cruza_medianoche ? " 🌙" : ""
                                }`
                              : "—"}
                          </td>
                          <td className="py-2.5 px-2 text-right text-xs">
                            {fila.cantidad_empleados}
                          </td>
                          <td className="py-2.5 px-2 text-right text-xs">
                            {fila.dias_programados}
                          </td>
                          <td className="py-2.5 px-2 text-right text-xs">
                            {fila.dias_asistidos}
                          </td>
                          <td className="py-2.5 px-2 text-right text-xs text-amber-300">
                            {fila.dias_con_retardo}
                          </td>
                          <td className="py-2.5 px-2 text-right text-xs text-orange-300">
                            {fila.dias_salida_anticipada}
                          </td>
                          <td className="py-2.5 px-2 text-right text-xs text-red-300">
                            {fila.dias_falta}
                          </td>
                          <td className="py-2.5 px-2 text-right text-xs text-slate-300">
                            {fila.promedio_minutos_trabajados > 0
                              ? formatearDuracion(fila.promedio_minutos_trabajados)
                              : "—"}
                          </td>
                          <td className="py-2.5 pl-2 text-right text-xs font-semibold">
                            <span className="text-emerald-300">
                              {fila.tasa_asistencia}%
                            </span>
                            <span className="text-slate-500"> / </span>
                            <span className="text-indigo-300">
                              {fila.tasa_puntualidad}%
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Detalle ordenable por Empleado */}
              <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="font-semibold text-base">Detalle por Empleado</h3>
                  <div className="flex flex-wrap items-center gap-1.5 text-xs">
                    <span className="text-slate-400 mr-1">Ordenar por:</span>
                    {(
                      [
                        { id: "attendance", etiqueta: "% Asistencia" },
                        { id: "name", etiqueta: "Nombre" },
                        { id: "shift", etiqueta: "Turno" },
                        { id: "absences", etiqueta: "Faltas" },
                        { id: "worked", etiqueta: "Horas trabajadas" },
                      ] as const
                    ).map((opcion) => (
                      <button
                        key={opcion.id}
                        type="button"
                        onClick={() => manejarOrdenarEmpleados(opcion.id)}
                        className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border ${
                          campoOrdenEmpleado === opcion.id
                            ? "bg-indigo-600/20 border-indigo-500/40 text-indigo-300"
                            : "bg-slate-800 border-slate-700 text-slate-300"
                        }`}
                      >
                        {opcion.etiqueta}
                        {campoOrdenEmpleado === opcion.id && (
                          <ArrowUpDown className="w-3 h-3" />
                        )}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-sm text-left">
                    <thead className="text-xs uppercase text-slate-400 border-b border-slate-800">
                      <tr>
                        <th className="py-2 pr-3">Empleado</th>
                        <th className="py-2 px-2">Turno</th>
                        <th className="py-2 px-2 text-right">Prog.</th>
                        <th className="py-2 px-2 text-right">Asist.</th>
                        <th className="py-2 px-2 text-right">Retardos</th>
                        <th className="py-2 px-2 text-right">Sal. Ant.</th>
                        <th className="py-2 px-2 text-right">Faltas</th>
                        <th className="py-2 px-2 text-right">Trabajado</th>
                        <th className="py-2 pl-2 text-right">Asist.</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/70">
                      {estadisticasEmpleadosOrdenadas.map((empleado) => (
                        <tr key={empleado.id_persona} className="hover:bg-slate-800/30">
                          <td className="py-2.5 pr-3">
                            <p className="font-medium leading-tight">
                              {empleado.nombre_completo}
                            </p>
                            <p className="text-[11px] text-slate-500">
                              {empleado.identificador_externo}
                              {empleado.nombres_grupos.length > 0
                                ? ` · ${empleado.nombres_grupos.join(", ")}`
                                : ""}
                            </p>
                          </td>
                          <td className="py-2.5 px-2 text-xs">
                            {empleado.nombre_turno ? (
                              <span>
                                {empleado.nombre_turno}{" "}
                                <span className="text-[10px] text-slate-400">
                                  ({empleado.origen_turno === "direct" ? "directo" : "área"}
                                  )
                                </span>
                              </span>
                            ) : (
                              <span className="text-slate-500">Sin turno</span>
                            )}
                          </td>
                          <td className="py-2.5 px-2 text-right text-xs">
                            {empleado.dias_programados}
                          </td>
                          <td className="py-2.5 px-2 text-right text-xs">
                            {empleado.dias_asistidos}
                          </td>
                          <td className="py-2.5 px-2 text-right text-xs text-amber-300">
                            {empleado.dias_con_retardo}
                            {empleado.total_minutos_retardo > 0
                              ? ` (${empleado.total_minutos_retardo}m)`
                              : ""}
                          </td>
                          <td className="py-2.5 px-2 text-right text-xs text-orange-300">
                            {empleado.dias_salida_anticipada}
                            {empleado.total_minutos_salida_anticipada > 0
                              ? ` (${empleado.total_minutos_salida_anticipada}m)`
                              : ""}
                          </td>
                          <td className="py-2.5 px-2 text-right text-xs text-red-300">
                            {empleado.dias_falta}
                          </td>
                          <td className="py-2.5 px-2 text-right text-xs text-slate-200">
                            {formatearDuracion(empleado.total_minutos_trabajados)}
                          </td>
                          <td className="py-2.5 pl-2 text-right text-xs font-semibold text-emerald-300">
                            {empleado.tasa_asistencia}%
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
