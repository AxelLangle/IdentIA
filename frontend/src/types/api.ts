/**
 * Definiciones de tipos TypeScript para todos los contratos JSON de la API IdentIA v1.1.0.
 *
 * Cada interfaz refleja de forma exacta la estructura serializada por los esquemas
 * Pydantic del backend (`backend/app/schemas.py`).
 */

// ==============================================================================
// Tipos literales de dominio
// ==============================================================================
export type ModoOrganizacion = "enterprise" | "education";
export type TipoPeriodoAcademico =
  | "bimestral"
  | "trimestral"
  | "cuatrimestral"
  | "semestral"
  | "ciclo";
export type RolPersona = "employee" | "student" | "teacher" | "admin";
export type RolUsuario = "superadmin" | "org_admin" | "teacher" | "supervisor" | "operator";
export type EtiquetaPose = "frontal" | "left" | "right" | "up" | "down" | "smile";
export type ModoAccion = "auto" | "check_in" | "check_out" | "present";
export type EstadoSesion = "open" | "closed";
export type OrigenTurno = "direct" | "group" | "none";

// ==============================================================================
// Organizaciones y Grupos / Departamentos
// ==============================================================================
/** Organización registrada (empresa o institución educativa). */
export interface Organizacion {
  id: number;
  nombre: string;
  modo: ModoOrganizacion;
  tipo_periodo_academico: TipoPeriodoAcademico;
  minutos_tolerancia_retardo: number;
  segundos_enfriamiento: number;
  guardar_avatar_por_defecto: boolean;
  creado_en: string;
}

/** Grupo académico o departamento operativo perteneciente a una organización. */
export interface Grupo {
  id: number;
  id_organizacion: number;
  id_carrera: number | null;
  nombre_carrera: string | null;
  nombre: string;
  codigo: string;
  semestre: string | null;
  aula_defecto: string | null;
  id_turno_laboral_defecto: number | null;
  nombre_turno_laboral_defecto: string | null;
  codigo_turno_laboral_defecto: string | null;
  tipo_periodo: string;
  tipo_periodo_personalizado: TipoPeriodoAcademico | null;
  hora_inicio_horario: string;
  hora_fin_horario: string;
  creado_en: string;
  cantidad_integrantes: number;
  cantidad_cursos: number;
}

// ==============================================================================
// Personas, Visión y Enrolamiento Biométrico
// ==============================================================================
/** Registro de persona en el padrón con su avance de poses y turno efectivo. */
export interface Persona {
  id: number;
  id_organizacion: number;
  identificador_externo: string;
  nombre_completo: string;
  correo: string | null;
  rol: RolPersona;
  avatar_base64: string | null;
  consentimiento_biometrico: boolean;
  fecha_consentimiento_biometrico: string | null;
  esta_activo: boolean;
  creado_en: string;
  ids_grupos: number[];
  id_turno_laboral: number | null;
  nombre_turno_laboral: string | null;
  id_turno_laboral_efectivo: number | null;
  nombre_turno_laboral_efectivo: string | null;
  codigo_turno_laboral_efectivo: string | null;
  origen_turno: OrigenTurno;
  cantidad_vectores: number;
  poses_completadas: EtiquetaPose[];
  requiere_reenrolamiento: boolean;
}

/** Coordenadas absolutas y normalizadas de la detección facial en pantalla. */
export interface CuadroRostro {
  coordenada_x: number;
  coordenada_y: number;
  ancho: number;
  alto: number;
  confianza: number;
  ancho_imagen: number;
  alto_imagen: number;
  coordenada_x_normalizada: number;
  coordenada_y_normalizada: number;
  ancho_normalizado: number;
  alto_normalizado: number;
}

/** Métricas de nitidez, exposición, contraluz, sombra lateral y geometría de pose. */
export interface ReporteCalidad {
  es_valida: boolean;
  motivo: string | null;
  puntaje_nitidez: number;
  brillo: number;
  ancho_rostro: number;
  alto_rostro: number;
  pose_estimada: string;
  asimetria_sombra: number;
  contraluz_detectado: boolean;
  relacion_giro_horizontal: number;
  relacion_inclinacion_vertical: number;
  relacion_boca: number;
  pose_coincide: boolean;
  retroalimentacion_pose: string | null;
}

/** Respuesta del servidor tras validar o capturar una pose biométrica. */
export interface RespuestaEnrolarFrame {
  aceptado: boolean;
  pose_valida: boolean;
  etiqueta_pose: EtiquetaPose;
  mensaje: string;
  cantidad_vectores: number;
  poses_completadas: EtiquetaPose[];
  enrolamiento_completo: boolean;
  cantidad_poses_requeridas: number;
  cuadro_rostro: CuadroRostro | null;
  calidad: ReporteCalidad | null;
  avatar_guardado: boolean;
}

// ==============================================================================
// Sesiones y Eventos de Asistencia
// ==============================================================================
/** Sesión de pase de lista escolar o jornada laboral empresarial. */
export interface SesionAsistencia {
  id: number;
  id_organizacion: number;
  id_grupo: number | null;
  nombre_grupo: string | null;
  id_asignacion_curso: number | null;
  id_horario: number | null;
  id_turno_laboral: number | null;
  nombre_turno_laboral: string | null;
  codigo_turno_laboral: string | null;
  turno_cruza_medianoche: boolean;
  nombre_materia: string | null;
  codigo_materia: string | null;
  nombre_carrera: string | null;
  nombre_docente: string | null;
  titulo: string;
  fecha_sesion: string;
  tipo_sesion: "workday" | "class";
  hora_inicio_esperada: string | null;
  estado: EstadoSesion;
  creado_en: string;
  cerrado_en: string | null;
  cantidad_eventos: number;
}

/** Registro individual de entrada, salida o asistencia en clase. */
export interface EventoAsistencia {
  id: number;
  id_sesion: number;
  titulo_sesion: string | null;
  id_persona: number;
  nombre_persona: string;
  identificador_externo_persona: string;
  avatar_base64_persona: string | null;
  id_turno_laboral: number | null;
  nombre_turno_laboral: string | null;
  tipo_evento: "check_in" | "check_out" | "present";
  estado: "on_time" | "late" | "early_exit" | "manual";
  puntaje_confianza: number | null;
  minutos_trabajados: number | null;
  minutos_retardo: number | null;
  minutos_salida_anticipada: number | null;
  modo_captura: "kiosk_individual" | "group_scan" | "manual";
  fecha_hora: string;
  notas: string | null;
}

/** Ficha breve de persona devuelta al instante en el kiosco tras un reconocimiento. */
export interface ResumenBrevePersona {
  id: number;
  identificador_externo: string;
  nombre_completo: string;
  rol: string;
  avatar_base64: string | null;
}

/** Respuesta del pipeline biométrico sobre un frame capturado por el kiosco. */
export interface RespuestaReconocerFrame {
  rostros_detectados: number;
  estado_coincidencia: "matched" | "unknown" | "ambiguous" | "no_face" | "low_quality";
  cuadro_rostro: CuadroRostro | null;
  calidad: ReporteCalidad | null;
  persona: ResumenBrevePersona | null;
  confianza: number;
  puntaje_segundo_candidato: number | null;
  accion_asistencia: "recorded" | "cooldown" | "already_present" | "invalid_sequence" | null;
  evento: EventoAsistencia | null;
  minutos_trabajados: number | null;
  nombre_turno: string | null;
  minutos_retardo: number | null;
  minutos_salida_anticipada: number | null;
  id_sesion: number | null;
  mensaje: string;
  latencia_ms: number;
}

/** Estado de salud y carga de modelos del backend. */
export interface RespuestaSalud {
  estado: string;
  modelos_cargados: boolean;
  nombre_modelo: string;
  version_modelo: string;
  cantidad_organizaciones: number;
  cantidad_personas: number;
  cantidad_vectores: number;
}

// ==============================================================================
// Autenticación, Usuarios, Credenciales Delegadas y Auditoría
// ==============================================================================
/** Usuario autenticado y sus metadatos de rol y organización. */
export interface UsuarioAutenticado {
  id: number;
  correo: string;
  nombre_completo: string;
  rol: RolUsuario;
  id_organizacion: number | null;
  nombre_organizacion: string | null;
  modo_organizacion: ModoOrganizacion | null;
  esta_activo: boolean;
  id_usuario_creador: number | null;
  creado_en: string;
}

/** Respuesta emitida al iniciar sesión con token JWT. */
export interface RespuestaInicioSesion {
  token_acceso: string;
  tipo_token: string;
  usuario: UsuarioAutenticado;
}

/** Credencial delegada para autorizar revocaciones biométricas sin compartir clave admin. */
export interface CredencialDelegada {
  id: number;
  id_organizacion: number;
  etiqueta: string;
  prefijo_secreto: string;
  id_usuario_creador: number | null;
  nombre_creador: string | null;
  id_usuario_asignado: number | null;
  nombre_asignado: string;
  operaciones_permitidas: string[];
  estado: "active" | "revoked" | "expired";
  expira_en: string | null;
  creado_en: string;
  revocado_en: string | null;
}

/** Respuesta única al generar credencial delegada que incluye el secreto en texto plano. */
export interface CredencialDelegadaCreada {
  credencial: CredencialDelegada;
  secreto_plano: string;
}

/** Registro de bitácora de auditoría para acciones críticas del sistema. */
export interface EntradaBitacoraAuditoria {
  id: number;
  id_organizacion: number | null;
  accion: string;
  tipo_objetivo: string;
  id_objetivo: number | null;
  resumen_objetivo: string | null;
  id_usuario_ejecutor: number | null;
  nombre_ejecutor: string | null;
  id_usuario_autorizador: number | null;
  nombre_autorizador: string | null;
  id_credencial_delegada: number | null;
  prefijo_credencial_delegada: string | null;
  nombre_asignado_credencial: string | null;
  detalles: string | null;
  creado_en: string;
}

/** Resumen de revocación biométrica masiva. */
export interface RespuestaRevocarBiometriaLote {
  cantidad_personas_revocadas: number;
  vectores_eliminados: number;
  nombre_autorizador: string | null;
  metodo_autorizacion: string;
  etiqueta_credencial_delegada: string | null;
}

// ==============================================================================
// Modelo Educativo Completo
// ==============================================================================
/** Carrera o programa académico de una escuela. */
export interface Carrera {
  id: number;
  id_organizacion: number;
  nombre: string;
  codigo: string;
  descripcion: string | null;
  tipo_periodo: TipoPeriodoAcademico | null;
  tipo_periodo_efectivo: TipoPeriodoAcademico;
  creado_en: string;
  cantidad_grupos: number;
  cantidad_materias: number;
}

/** Asignatura perteneciente al catálogo institucional. */
export interface Materia {
  id: number;
  id_organizacion: number;
  id_carrera: number | null;
  nombre_carrera: string | null;
  nombre: string;
  codigo: string;
  creado_en: string;
}

/** Bloque semanal de clase asociado a una asignación de curso. */
export interface HorarioClase {
  id: number;
  id_asignacion_curso: number;
  dia_semana: number;
  hora_inicio: string;
  hora_fin: string;
  aula: string | null;
  creado_en: string;
}

/** Asignación única Grupo + Materia + Docente junto con sus bloques de horario. */
export interface AsignacionCurso {
  id: number;
  id_organizacion: number;
  id_grupo: number;
  nombre_grupo: string;
  codigo_grupo: string;
  aula_defecto_grupo: string | null;
  semestre: string | null;
  tipo_periodo: string;
  id_carrera: number | null;
  nombre_carrera: string | null;
  id_materia: number;
  nombre_materia: string;
  codigo_materia: string;
  id_usuario_docente: number | null;
  nombre_docente: string | null;
  correo_docente: string | null;
  periodo_lectivo: string | null;
  esta_activo: boolean;
  cantidad_estudiantes: number;
  horarios: HorarioClase[];
  creado_en: string;
}

/** Resultado al generar automáticamente sesiones del día (académicas o de turnos). */
export interface RespuestaGenerarSesiones {
  fecha_objetivo: string;
  cantidad_creadas: number;
  cantidad_existentes: number;
  sesiones: SesionAsistencia[];
}

/** Bloque horario en la agenda diaria del docente. */
export interface BloqueAgendaDocente {
  id_horario: number;
  id_asignacion_curso: number;
  nombre_materia: string;
  codigo_materia: string;
  id_grupo: number;
  nombre_grupo: string;
  codigo_grupo: string;
  nombre_carrera: string | null;
  dia_semana: number;
  hora_inicio: string;
  hora_fin: string;
  aula: string | null;
  estado_bloque: "in_progress" | "upcoming" | "finished";
  cantidad_estudiantes: number;
  sesion: SesionAsistencia | null;
}

/** Respuesta del portal docente con su clase activa, agenda del día y cursos asignados. */
export interface RespuestaAgendaDocente {
  fecha_objetivo: string;
  hora_actual: string;
  bloque_actual: BloqueAgendaDocente | null;
  bloques_hoy: BloqueAgendaDocente[];
  cursos: AsignacionCurso[];
}

/** Métricas de asistencia por asignatura impartida. */
export interface EstadisticaAsistenciaMateria {
  id_asignacion_curso: number;
  id_materia: number;
  nombre_materia: string;
  codigo_materia: string;
  id_grupo: number;
  nombre_grupo: string;
  codigo_grupo: string;
  id_carrera: number | null;
  nombre_carrera: string | null;
  semestre: string | null;
  tipo_periodo: string;
  nombre_docente: string | null;
  cantidad_sesiones: number;
  estudiantes_inscritos: number;
  registros_esperados: number;
  cantidad_asistencias: number;
  cantidad_puntuales: number;
  cantidad_retardos: number;
  cantidad_manuales: number;
  cantidad_faltas: number;
  tasa_asistencia: number;
}

/** Desglose de asistencia individual de un alumno en su grupo. */
export interface EstadisticaAsistenciaAlumnoGrupo {
  id_persona: number;
  identificador_externo: string;
  nombre_completo: string;
  registros_esperados: number;
  cantidad_asistencias: number;
  cantidad_puntuales: number;
  cantidad_retardos: number;
  cantidad_faltas: number;
  tasa_asistencia: number;
}

/** Estadísticas consolidadas de un grupo académico. */
export interface EstadisticaAsistenciaGrupo {
  id_grupo: number;
  nombre_grupo: string;
  codigo_grupo: string;
  id_carrera: number | null;
  nombre_carrera: string | null;
  semestre: string | null;
  tipo_periodo: string;
  cantidad_materias: number;
  cantidad_estudiantes: number;
  total_sesiones: number;
  total_esperados: number;
  total_asistencias: number;
  total_puntuales: number;
  total_retardos: number;
  total_faltas: number;
  tasa_asistencia_general: number;
  desglose_estudiantes: EstadisticaAsistenciaAlumnoGrupo[];
}

/** Indicadores globales del tablero académico administrativo. */
export interface ResumenEstadisticasAcademicas {
  total_carreras: number;
  total_grupos: number;
  total_materias: number;
  total_cursos: number;
  total_sesiones: number;
  tasa_asistencia_general: number;
}

/** Respuesta completa de analítica académica por asignatura y grupo. */
export interface RespuestaEstadisticasAcademicas {
  id_organizacion: number;
  fecha_desde: string | null;
  fecha_hasta: string | null;
  resumen: ResumenEstadisticasAcademicas;
  por_materia: EstadisticaAsistenciaMateria[];
  por_grupo: EstadisticaAsistenciaGrupo[];
}

// ==============================================================================
// Turnos Empresariales y Reglas de Jornada
// ==============================================================================
/** Turno laboral diurno o nocturno configurado en una empresa. */
export interface TurnoLaboral {
  id: number;
  id_organizacion: number;
  nombre: string;
  codigo: string;
  hora_inicio: string;
  hora_fin: string;
  cruza_medianoche: boolean;
  duracion_esperada_minutos: number;
  dias_semana: number[];
  minutos_tolerancia_retardo: number | null;
  minutos_tolerancia_retardo_efectiva: number;
  minutos_tolerancia_salida_anticipada: number;
  esta_activo: boolean;
  cantidad_empleados_asignados: number;
  cantidad_grupos_por_defecto: number;
  creado_en: string;
}

/** Resultado de asignación o limpieza de turno en lote. */
export interface RespuestaAsignacionMasivaTurno {
  id_turno_laboral: number | null;
  nombre_turno_laboral: string | null;
  cantidad_actualizados: number;
}

/** Métricas agregadas por turno laboral empresarial. */
export interface EstadisticaAsistenciaTurno {
  id_turno_laboral: number | null;
  nombre_turno: string;
  codigo_turno: string | null;
  hora_inicio: string | null;
  hora_fin: string | null;
  cruza_medianoche: boolean;
  dias_semana: number[];
  cantidad_empleados: number;
  dias_programados: number;
  dias_asistidos: number;
  dias_puntuales: number;
  dias_con_retardo: number;
  dias_salida_anticipada: number;
  dias_falta: number;
  dias_sin_salida: number;
  total_minutos_trabajados: number;
  promedio_minutos_trabajados: number;
  tasa_asistencia: number;
  tasa_puntualidad: number;
}

/** Métricas de asistencia, puntualidad y tiempo trabajado de cada colaborador. */
export interface EstadisticaAsistenciaEmpleado {
  id_persona: number;
  identificador_externo: string;
  nombre_completo: string;
  nombres_grupos: string[];
  id_turno_laboral: number | null;
  nombre_turno: string | null;
  codigo_turno: string | null;
  origen_turno: OrigenTurno;
  dias_programados: number;
  dias_asistidos: number;
  dias_puntuales: number;
  dias_con_retardo: number;
  dias_salida_anticipada: number;
  dias_falta: number;
  dias_sin_salida: number;
  total_minutos_retardo: number;
  total_minutos_salida_anticipada: number;
  total_minutos_trabajados: number;
  tasa_asistencia: number;
  tasa_puntualidad: number;
}

/** Indicadores globales del módulo de turnos empresariales. */
export interface ResumenEstadisticasEmpresariales {
  total_turnos: number;
  turnos_activos: number;
  total_empleados: number;
  empleados_asignados: number;
  empleados_sin_turno: number;
  dias_empleado_programados: number;
  dias_asistidos: number;
  dias_puntuales: number;
  dias_con_retardo: number;
  dias_salida_anticipada: number;
  dias_falta: number;
  dias_sin_salida: number;
  total_minutos_trabajados: number;
  tasa_asistencia: number;
  tasa_puntualidad: number;
}

/** Respuesta consolidada de estadísticas empresariales por turno y empleado. */
export interface RespuestaEstadisticasEmpresariales {
  id_organizacion: number;
  fecha_desde: string;
  fecha_hasta: string;
  resumen: ResumenEstadisticasEmpresariales;
  por_turno: EstadisticaAsistenciaTurno[];
  por_empleado: EstadisticaAsistenciaEmpleado[];
}
