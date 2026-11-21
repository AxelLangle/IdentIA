/**
 * Cliente HTTP centralizado para comunicarse con la API REST de IdentIA.
 *
 * Adjunta automáticamente el token JWT almacenado en `localStorage`, intercepta
 * respuestas `401 Unauthorized` para cerrar sesiones expiradas y expone métodos
 * tipados para autenticación, seguridad, organizaciones, biometría, sesiones,
 * dominio académico y turnos empresariales.
 */
import type {
  AsignacionCurso,
  Carrera,
  CredencialDelegada,
  CredencialDelegadaCreada,
  EntradaBitacoraAuditoria,
  EtiquetaPose,
  EventoAsistencia,
  Grupo,
  HorarioClase,
  Materia,
  ModoAccion,
  ModoOrganizacion,
  Organizacion,
  Persona,
  RespuestaAgendaDocente,
  RespuestaAsignacionMasivaTurno,
  RespuestaEnrolarFrame,
  RespuestaEstadisticasAcademicas,
  RespuestaEstadisticasEmpresariales,
  RespuestaGenerarSesiones,
  RespuestaInicioSesion,
  RespuestaReconocerFrame,
  RespuestaRevocarBiometriaLote,
  RespuestaSalud,
  RolPersona,
  RolUsuario,
  SesionAsistencia,
  TipoPeriodoAcademico,
  TurnoLaboral,
  UsuarioAutenticado,
} from "../types/api";

const CLAVE_ALMACENAMIENTO_TOKEN = "identia_token";
let manejadorNoAutorizado: (() => void) | null = null;

/** Obtiene el token JWT almacenado localmente en el navegador. */
export function obtenerTokenAlmacenado(): string | null {
  return window.localStorage.getItem(CLAVE_ALMACENAMIENTO_TOKEN);
}

/** Persiste o elimina el token JWT en `localStorage`. */
export function guardarTokenAlmacenado(token: string | null): void {
  if (token) {
    window.localStorage.setItem(CLAVE_ALMACENAMIENTO_TOKEN, token);
  } else {
    window.localStorage.removeItem(CLAVE_ALMACENAMIENTO_TOKEN);
  }
}

/** Registra una función callback que se dispara ante cualquier HTTP 401 protegido. */
export function registrarManejadorNoAutorizado(manejador: (() => void) | null): void {
  manejadorNoAutorizado = manejador;
}

/** Ejecuta `fetch` añadiendo el encabezado `Authorization: Bearer` si existe token. */
async function peticionConAutenticacion(
  url: string,
  configuracion: RequestInit = {}
): Promise<Response> {
  const token = obtenerTokenAlmacenado();
  const encabezados = new Headers(configuracion.headers);
  if (token && !encabezados.has("Authorization")) {
    encabezados.set("Authorization", `Bearer ${token}`);
  }
  const respuesta = await fetch(url, { ...configuracion, headers: encabezados });
  if (respuesta.status === 401 && !url.endsWith("/api/auth/login")) {
    guardarTokenAlmacenado(null);
    manejadorNoAutorizado?.();
  }
  return respuesta;
}

/** Envuelve `peticionConAutenticacion`, decodifica JSON y extrae mensajes `detail` en errores. */
async function solicitarJson<T>(url: string, configuracion?: RequestInit): Promise<T> {
  const respuesta = await peticionConAutenticacion(url, configuracion);
  if (!respuesta.ok) {
    let detalleError = `Error HTTP ${respuesta.status}`;
    try {
      const cuerpoError = (await respuesta.json()) as { detail?: string };
      if (cuerpoError.detail) detalleError = cuerpoError.detail;
    } catch {
      // Ignora error de parseo si el cuerpo de respuesta no es JSON válido
    }
    throw new Error(detalleError);
  }
  if (respuesta.status === 204) {
    return undefined as T;
  }
  return (await respuesta.json()) as T;
}

/** Colección completa de llamadas REST tipadas contra el backend de IdentIA. */
export const clienteApi = {
  // --- Salud y Autenticación ---
  obtenerSalud: () => solicitarJson<RespuestaSalud>("/api/health"),

  iniciarSesion: async (
    correo: string,
    contrasena: string
  ): Promise<RespuestaInicioSesion> => {
    const respuesta = await solicitarJson<RespuestaInicioSesion>("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ correo, contrasena }),
    });
    guardarTokenAlmacenado(respuesta.token_acceso);
    return respuesta;
  },
  obtenerPerfilActual: () => solicitarJson<UsuarioAutenticado>("/api/auth/me"),

  // --- Usuarios RBAC ---
  listarUsuarios: (idOrganizacion?: number | null) => {
    const parametros = new URLSearchParams();
    if (idOrganizacion !== undefined && idOrganizacion !== null) {
      parametros.set("id_organizacion", String(idOrganizacion));
    }
    const cadenaConsulta = parametros.toString();
    return solicitarJson<UsuarioAutenticado[]>(
      `/api/users${cadenaConsulta ? `?${cadenaConsulta}` : ""}`
    );
  },
  crearUsuario: (datos: {
    correo: string;
    nombre_completo: string;
    contrasena: string;
    rol: RolUsuario;
    id_organizacion?: number | null;
  }) =>
    solicitarJson<UsuarioAutenticado>("/api/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(datos),
    }),
  actualizarUsuario: (
    idUsuario: number,
    datos: Partial<{
      nombre_completo: string;
      contrasena: string;
      rol: RolUsuario;
      esta_activo: boolean;
    }>
  ) =>
    solicitarJson<UsuarioAutenticado>(`/api/users/${idUsuario}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(datos),
    }),

  // --- Seguridad Delegada y Auditoría ---
  listarCredencialesDelegadas: (idOrganizacion?: number | null) => {
    const parametros = new URLSearchParams();
    if (idOrganizacion !== undefined && idOrganizacion !== null) {
      parametros.set("id_organizacion", String(idOrganizacion));
    }
    const cadenaConsulta = parametros.toString();
    return solicitarJson<CredencialDelegada[]>(
      `/api/security/delegated-credentials${cadenaConsulta ? `?${cadenaConsulta}` : ""}`
    );
  },
  crearCredencialDelegada: (datos: {
    id_organizacion?: number | null;
    etiqueta: string;
    id_usuario_asignado?: number | null;
    nombre_asignado?: string | null;
    secreto_personalizado?: string | null;
    expira_en_dias?: number | null;
  }) =>
    solicitarJson<CredencialDelegadaCreada>("/api/security/delegated-credentials", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(datos),
    }),
  revocarCredencialDelegada: (idCredencial: number) =>
    solicitarJson<CredencialDelegada>(
      `/api/security/delegated-credentials/${idCredencial}/revoke`,
      { method: "POST" }
    ),
  listarBitacoraAuditoria: (idOrganizacion?: number | null, limite = 100) => {
    const parametros = new URLSearchParams({ limite: String(limite) });
    if (idOrganizacion !== undefined && idOrganizacion !== null) {
      parametros.set("id_organizacion", String(idOrganizacion));
    }
    return solicitarJson<EntradaBitacoraAuditoria[]>(
      `/api/security/audit-logs?${parametros.toString()}`
    );
  },

  // --- Organizaciones y Grupos / Departamentos ---
  listarOrganizaciones: () => solicitarJson<Organizacion[]>("/api/organizations"),
  crearOrganizacion: (datos: {
    nombre: string;
    modo: ModoOrganizacion;
    tipo_periodo_academico?: TipoPeriodoAcademico;
    minutos_tolerancia_retardo?: number;
    segundos_enfriamiento?: number;
    guardar_avatar_por_defecto?: boolean;
    usuario_administrador?: {
      nombre_completo: string;
      correo: string;
      contrasena: string;
    } | null;
  }) =>
    solicitarJson<Organizacion>("/api/organizations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(datos),
    }),
  actualizarOrganizacion: (
    idOrganizacion: number,
    datos: Partial<
      Pick<
        Organizacion,
        | "nombre"
        | "modo"
        | "tipo_periodo_academico"
        | "minutos_tolerancia_retardo"
        | "segundos_enfriamiento"
        | "guardar_avatar_por_defecto"
      >
    > & { secreto_autorizacion?: string }
  ) =>
    solicitarJson<Organizacion>(`/api/organizations/${idOrganizacion}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(datos),
    }),

  listarGrupos: (idOrganizacion: number) =>
    solicitarJson<Grupo[]>(`/api/groups?id_organizacion=${idOrganizacion}`),
  crearGrupo: (datos: {
    id_organizacion: number;
    nombre: string;
    codigo: string;
    hora_inicio_horario?: string;
    hora_fin_horario?: string;
    id_carrera?: number | null;
    semestre?: string | null;
    tipo_periodo?: TipoPeriodoAcademico | null;
    aula_defecto?: string | null;
    id_turno_laboral_defecto?: number | null;
  }) =>
    solicitarJson<Grupo>("/api/groups", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(datos),
    }),
  actualizarGrupo: (
    idGrupo: number,
    datos: Partial<{
      nombre: string;
      codigo: string;
      hora_inicio_horario: string;
      hora_fin_horario: string;
      id_carrera: number | null;
      semestre: string | null;
      tipo_periodo: TipoPeriodoAcademico | null;
      aula_defecto: string | null;
      id_turno_laboral_defecto: number | null;
      secreto_autorizacion: string;
    }>
  ) =>
    solicitarJson<Grupo>(`/api/groups/${idGrupo}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(datos),
    }),
  eliminarGrupo: (idGrupo: number) =>
    solicitarJson<void>(`/api/groups/${idGrupo}`, { method: "DELETE" }),

  // --- Personas, Enrolamiento y Revocación ---
  listarPersonas: (
    idOrganizacion: number,
    busqueda?: string,
    idGrupo?: number | null,
    idTurnoLaboral?: number | null
  ) => {
    const parametros = new URLSearchParams({ id_organizacion: String(idOrganizacion) });
    if (busqueda && busqueda.trim()) parametros.set("busqueda", busqueda.trim());
    if (idGrupo !== undefined && idGrupo !== null) parametros.set("id_grupo", String(idGrupo));
    if (idTurnoLaboral !== undefined && idTurnoLaboral !== null) {
      parametros.set("id_turno_laboral", String(idTurnoLaboral));
    }
    return solicitarJson<Persona[]>(`/api/persons?${parametros.toString()}`);
  },
  crearPersona: (datos: {
    id_organizacion: number;
    identificador_externo: string;
    nombre_completo: string;
    correo?: string | null;
    rol: RolPersona;
    consentimiento_biometrico: boolean;
    ids_grupos: number[];
    id_turno_laboral?: number | null;
  }) =>
    solicitarJson<Persona>("/api/persons", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(datos),
    }),
  actualizarPersona: (
    idPersona: number,
    datos: Partial<{
      nombre_completo: string;
      correo: string | null;
      rol: RolPersona;
      consentimiento_biometrico: boolean;
      esta_activo: boolean;
      ids_grupos: number[];
      id_turno_laboral: number | null;
    }>
  ) =>
    solicitarJson<Persona>(`/api/persons/${idPersona}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(datos),
    }),
  eliminarPersona: (idPersona: number) =>
    solicitarJson<void>(`/api/persons/${idPersona}`, { method: "DELETE" }),

  enrolarFrame: (
    idPersona: number,
    blobImagen: Blob,
    etiquetaPose: EtiquetaPose,
    guardarAvatar?: boolean,
    soloValidacion = false
  ) => {
    const formulario = new FormData();
    formulario.append("imagen", blobImagen, "frame.jpg");
    formulario.append("etiqueta_pose", etiquetaPose);
    if (guardarAvatar !== undefined) {
      formulario.append("guardar_avatar", String(guardarAvatar));
    }
    if (soloValidacion) {
      formulario.append("solo_validacion", "true");
    }
    return solicitarJson<RespuestaEnrolarFrame>(`/api/persons/${idPersona}/enroll-frame`, {
      method: "POST",
      body: formulario,
    });
  },
  revocarBiometriaLote: (datos: {
    ids_personas: number[];
    secreto_autorizacion: string;
    motivo?: string;
  }) =>
    solicitarJson<RespuestaRevocarBiometriaLote>("/api/persons/biometrics/revoke", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(datos),
    }),

  // --- Sesiones, Reconocimiento y Reportes ---
  listarSesiones: (idOrganizacion: number, estado?: "open" | "closed") => {
    const parametros = new URLSearchParams({ id_organizacion: String(idOrganizacion) });
    if (estado) parametros.set("estado", estado);
    return solicitarJson<SesionAsistencia[]>(`/api/sessions?${parametros.toString()}`);
  },
  crearSesion: (datos: {
    id_organizacion: number;
    id_grupo?: number | null;
    id_asignacion_curso?: number | null;
    id_horario?: number | null;
    id_turno_laboral?: number | null;
    titulo: string;
    hora_inicio_esperada?: string | null;
  }) =>
    solicitarJson<SesionAsistencia>("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(datos),
    }),
  cerrarSesion: (idSesion: number) =>
    solicitarJson<SesionAsistencia>(`/api/sessions/${idSesion}/close`, { method: "POST" }),

  reconocerFrame: (parametros: {
    blobImagen: Blob;
    idOrganizacion: number;
    idSesion?: number | null;
    idGrupo?: number | null;
    modoAccion?: ModoAccion;
  }) => {
    const formulario = new FormData();
    formulario.append("imagen", parametros.blobImagen, "frame.jpg");
    formulario.append("id_organizacion", String(parametros.idOrganizacion));
    if (parametros.idSesion !== undefined && parametros.idSesion !== null) {
      formulario.append("id_sesion", String(parametros.idSesion));
    }
    if (parametros.idGrupo !== undefined && parametros.idGrupo !== null) {
      formulario.append("id_grupo", String(parametros.idGrupo));
    }
    formulario.append("modo_accion", parametros.modoAccion ?? "auto");
    return solicitarJson<RespuestaReconocerFrame>("/api/attendance/recognize-frame", {
      method: "POST",
      body: formulario,
    });
  },

  listarEventos: (idOrganizacion: number, idSesion?: number | null, limite = 100) => {
    const parametros = new URLSearchParams({
      id_organizacion: String(idOrganizacion),
      limite: String(limite),
    });
    if (idSesion !== undefined && idSesion !== null) {
      parametros.set("id_sesion", String(idSesion));
    }
    return solicitarJson<EventoAsistencia[]>(
      `/api/attendance/events?${parametros.toString()}`
    );
  },

  crearAsistenciaManual: (datos: {
    id_sesion: number;
    id_persona: number;
    tipo_evento: "check_in" | "check_out" | "present";
    estado?: "on_time" | "late" | "early_exit" | "manual";
    notas?: string;
  }) =>
    solicitarJson<EventoAsistencia>("/api/attendance/manual", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(datos),
    }),

  descargarCsv: async (idOrganizacion: number, idSesion?: number | null): Promise<void> => {
    const parametros = new URLSearchParams({ id_organizacion: String(idOrganizacion) });
    if (idSesion !== undefined && idSesion !== null) {
      parametros.set("id_sesion", String(idSesion));
    }
    const respuesta = await peticionConAutenticacion(
      `/api/attendance/export.csv?${parametros.toString()}`
    );
    if (!respuesta.ok) {
      throw new Error(`No se pudo descargar el reporte (HTTP ${respuesta.status}).`);
    }
    const archivoBlob = await respuesta.blob();
    const urlTemporal = URL.createObjectURL(archivoBlob);
    const enlaceDescarga = document.createElement("a");
    enlaceDescarga.href = urlTemporal;
    enlaceDescarga.download = "asistencia_identia.csv";
    document.body.appendChild(enlaceDescarga);
    enlaceDescarga.click();
    enlaceDescarga.remove();
    URL.revokeObjectURL(urlTemporal);
  },

  // --- Modelo Educativo Completo ---
  listarCarreras: (idOrganizacion: number) =>
    solicitarJson<Carrera[]>(`/api/academic/careers?id_organizacion=${idOrganizacion}`),
  crearCarrera: (datos: {
    id_organizacion: number;
    nombre: string;
    codigo: string;
    descripcion?: string | null;
    tipo_periodo?: TipoPeriodoAcademico | null;
  }) =>
    solicitarJson<Carrera>("/api/academic/careers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(datos),
    }),
  actualizarCarrera: (
    idCarrera: number,
    datos: Partial<{
      nombre: string;
      codigo: string;
      descripcion: string | null;
      tipo_periodo: TipoPeriodoAcademico | null;
      secreto_autorizacion: string;
    }>
  ) =>
    solicitarJson<Carrera>(`/api/academic/careers/${idCarrera}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(datos),
    }),
  eliminarCarrera: (idCarrera: number) =>
    solicitarJson<void>(`/api/academic/careers/${idCarrera}`, { method: "DELETE" }),

  listarMaterias: (idOrganizacion: number, idCarrera?: number | null) => {
    const parametros = new URLSearchParams({ id_organizacion: String(idOrganizacion) });
    if (idCarrera !== undefined && idCarrera !== null) {
      parametros.set("id_carrera", String(idCarrera));
    }
    return solicitarJson<Materia[]>(`/api/academic/subjects?${parametros.toString()}`);
  },
  crearMateria: (datos: {
    id_organizacion: number;
    id_carrera?: number | null;
    nombre: string;
    codigo: string;
  }) =>
    solicitarJson<Materia>("/api/academic/subjects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(datos),
    }),
  eliminarMateria: (idMateria: number) =>
    solicitarJson<void>(`/api/academic/subjects/${idMateria}`, { method: "DELETE" }),

  listarCursos: (
    idOrganizacion: number,
    idGrupo?: number | null,
    idUsuarioDocente?: number | null
  ) => {
    const parametros = new URLSearchParams({ id_organizacion: String(idOrganizacion) });
    if (idGrupo !== undefined && idGrupo !== null) parametros.set("id_grupo", String(idGrupo));
    if (idUsuarioDocente !== undefined && idUsuarioDocente !== null) {
      parametros.set("id_usuario_docente", String(idUsuarioDocente));
    }
    return solicitarJson<AsignacionCurso[]>(`/api/academic/courses?${parametros.toString()}`);
  },
  crearCurso: (datos: {
    id_organizacion: number;
    id_grupo: number;
    id_materia: number;
    id_usuario_docente?: number | null;
    periodo_lectivo?: string | null;
    horarios: {
      dia_semana: number;
      hora_inicio: string;
      hora_fin: string;
      aula?: string | null;
    }[];
  }) =>
    solicitarJson<AsignacionCurso>("/api/academic/courses", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(datos),
    }),
  actualizarCurso: (
    idCurso: number,
    datos: Partial<{
      id_usuario_docente: number | null;
      periodo_lectivo: string | null;
      esta_activo: boolean;
    }>
  ) =>
    solicitarJson<AsignacionCurso>(`/api/academic/courses/${idCurso}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(datos),
    }),
  eliminarCurso: (idCurso: number) =>
    solicitarJson<void>(`/api/academic/courses/${idCurso}`, { method: "DELETE" }),

  agregarHorarioCurso: (
    idCurso: number,
    datos: {
      dia_semana: number;
      hora_inicio: string;
      hora_fin: string;
      aula?: string | null;
    }
  ) =>
    solicitarJson<HorarioClase>(`/api/academic/courses/${idCurso}/schedules`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(datos),
    }),
  eliminarHorario: (idHorario: number) =>
    solicitarJson<void>(`/api/academic/schedules/${idHorario}`, { method: "DELETE" }),

  obtenerCursosAlumno: (idPersona: number) =>
    solicitarJson<AsignacionCurso[]>(`/api/academic/students/${idPersona}/courses`),

  generarSesionesAcademicas: (datos: {
    id_organizacion: number;
    fecha_objetivo?: string | null;
    id_asignacion_curso?: number | null;
  }) =>
    solicitarJson<RespuestaGenerarSesiones>("/api/academic/sessions/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(datos),
    }),

  iniciarSesionCurso: (
    idCurso: number,
    datos?: { id_horario?: number | null; fecha_sesion?: string | null }
  ) =>
    solicitarJson<SesionAsistencia>(`/api/academic/courses/${idCurso}/start-session`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(datos ?? {}),
    }),

  obtenerAgendaDocente: (parametros: {
    id_organizacion: number;
    fecha_objetivo?: string | null;
    hora_actual?: string | null;
    id_usuario_docente?: number | null;
  }) => {
    const consulta = new URLSearchParams({
      id_organizacion: String(parametros.id_organizacion),
    });
    if (parametros.fecha_objetivo) consulta.set("fecha_objetivo", parametros.fecha_objetivo);
    if (parametros.hora_actual) consulta.set("hora_actual", parametros.hora_actual);
    if (
      parametros.id_usuario_docente !== undefined &&
      parametros.id_usuario_docente !== null
    ) {
      consulta.set("id_usuario_docente", String(parametros.id_usuario_docente));
    }
    return solicitarJson<RespuestaAgendaDocente>(
      `/api/academic/teacher/agenda?${consulta.toString()}`
    );
  },

  obtenerEstadisticasAcademicas: (parametros: {
    id_organizacion: number;
    fecha_desde?: string | null;
    fecha_hasta?: string | null;
    id_carrera?: number | null;
    id_grupo?: number | null;
  }) => {
    const consulta = new URLSearchParams({
      id_organizacion: String(parametros.id_organizacion),
    });
    if (parametros.fecha_desde) consulta.set("fecha_desde", parametros.fecha_desde);
    if (parametros.fecha_hasta) consulta.set("fecha_hasta", parametros.fecha_hasta);
    if (parametros.id_carrera !== undefined && parametros.id_carrera !== null) {
      consulta.set("id_carrera", String(parametros.id_carrera));
    }
    if (parametros.id_grupo !== undefined && parametros.id_grupo !== null) {
      consulta.set("id_grupo", String(parametros.id_grupo));
    }
    return solicitarJson<RespuestaEstadisticasAcademicas>(
      `/api/academic/stats?${consulta.toString()}`
    );
  },

  // --- Turnos Empresariales y Reglas de Jornada ---
  listarTurnosLaborales: (idOrganizacion: number, estaActivo?: boolean) => {
    const consulta = new URLSearchParams({ id_organizacion: String(idOrganizacion) });
    if (estaActivo !== undefined) consulta.set("esta_activo", String(estaActivo));
    return solicitarJson<TurnoLaboral[]>(`/api/enterprise/shifts?${consulta.toString()}`);
  },
  crearTurnoLaboral: (datos: {
    id_organizacion: number;
    nombre: string;
    codigo: string;
    hora_inicio: string;
    hora_fin: string;
    dias_semana: number[];
    minutos_tolerancia_retardo?: number | null;
    minutos_tolerancia_salida_anticipada?: number;
    esta_activo?: boolean;
  }) =>
    solicitarJson<TurnoLaboral>("/api/enterprise/shifts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(datos),
    }),
  actualizarTurnoLaboral: (
    idTurno: number,
    datos: Partial<{
      nombre: string;
      codigo: string;
      hora_inicio: string;
      hora_fin: string;
      dias_semana: number[];
      minutos_tolerancia_retardo: number | null;
      minutos_tolerancia_salida_anticipada: number;
      esta_activo: boolean;
    }>
  ) =>
    solicitarJson<TurnoLaboral>(`/api/enterprise/shifts/${idTurno}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(datos),
    }),
  eliminarTurnoLaboral: (idTurno: number) =>
    solicitarJson<void>(`/api/enterprise/shifts/${idTurno}`, { method: "DELETE" }),
  asignarTurnoAPersonas: (
    idTurno: number,
    datos: { ids_personas?: number[]; id_grupo?: number | null; limpiar_turno?: boolean }
  ) =>
    solicitarJson<RespuestaAsignacionMasivaTurno>(
      `/api/enterprise/shifts/${idTurno}/assign-persons`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(datos),
      }
    ),
  iniciarSesionTurno: (idTurno: number, datos?: { fecha_sesion?: string | null }) =>
    solicitarJson<SesionAsistencia>(`/api/enterprise/shifts/${idTurno}/start-session`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(datos ?? {}),
    }),
  generarSesionesEmpresariales: (datos: {
    id_organizacion: number;
    fecha_objetivo?: string | null;
    id_turno_laboral?: number | null;
  }) =>
    solicitarJson<RespuestaGenerarSesiones>("/api/enterprise/sessions/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(datos),
    }),
  obtenerEstadisticasEmpresariales: (parametros: {
    id_organizacion: number;
    fecha_desde?: string | null;
    fecha_hasta?: string | null;
    id_turno_laboral?: number | null;
    id_grupo?: number | null;
  }) => {
    const consulta = new URLSearchParams({
      id_organizacion: String(parametros.id_organizacion),
    });
    if (parametros.fecha_desde) consulta.set("fecha_desde", parametros.fecha_desde);
    if (parametros.fecha_hasta) consulta.set("fecha_hasta", parametros.fecha_hasta);
    if (parametros.id_turno_laboral !== undefined && parametros.id_turno_laboral !== null) {
      consulta.set("id_turno_laboral", String(parametros.id_turno_laboral));
    }
    if (parametros.id_grupo !== undefined && parametros.id_grupo !== null) {
      consulta.set("id_grupo", String(parametros.id_grupo));
    }
    return solicitarJson<RespuestaEstadisticasEmpresariales>(
      `/api/enterprise/stats?${consulta.toString()}`
    );
  },
};
