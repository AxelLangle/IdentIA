"""Esquemas Pydantic v2 para validación de entradas y serialización JSON de la API.

Todos los campos de petición y respuesta utilizan nombres descriptivos en
español en formato `snake_case`, manteniendo los literales de estado/rol
compatibles con los registros almacenados en la base de datos.
"""

from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


# ==============================================================================
# Tipos literales de dominio (los valores persistidos se mantienen invariantes)
# ==============================================================================
ModoOrganizacion = Literal["enterprise", "education"]
TipoPeriodoAcademico = Literal["bimestral", "trimestral", "cuatrimestral", "semestral", "ciclo"]
RolPersona = Literal["employee", "student", "teacher", "admin"]
RolUsuario = Literal["superadmin", "org_admin", "teacher", "supervisor", "operator"]
EtiquetaPose = Literal["frontal", "left", "right", "up", "down", "smile"]
TipoSesion = Literal["workday", "class"]
EstadoSesion = Literal["open", "closed"]
ModoAccion = Literal["auto", "check_in", "check_out", "present"]
TipoEvento = Literal["check_in", "check_out", "present"]
EstadoEvento = Literal["on_time", "late", "early_exit", "manual"]
ModoCaptura = Literal["kiosk_individual", "group_scan", "manual"]
OrigenTurno = Literal["direct", "group", "none"]


# ==============================================================================
# Organizaciones
# ==============================================================================
class ArranqueAdminOrganizacion(BaseModel):
    """Datos para crear opcionalmente al primer administrador junto con la organización."""

    nombre_completo: str = Field(..., min_length=2, max_length=160)
    correo: str = Field(..., min_length=4, max_length=160)
    contrasena: str = Field(..., min_length=6, max_length=120)


class OrganizacionCrear(BaseModel):
    """Payload para dar de alta una nueva organización escolar o empresarial."""

    nombre: str = Field(..., min_length=2, max_length=120)
    modo: ModoOrganizacion = "enterprise"
    tipo_periodo_academico: TipoPeriodoAcademico = "semestral"
    minutos_tolerancia_retardo: int = Field(default=15, ge=0, le=180)
    segundos_enfriamiento: int = Field(default=60, ge=5, le=3600)
    guardar_avatar_por_defecto: bool = True
    usuario_administrador: ArranqueAdminOrganizacion | None = None


class OrganizacionActualizar(BaseModel):
    """Payload parcial para actualizar reglas o periodo general de una organización."""

    nombre: str | None = Field(default=None, min_length=2, max_length=120)
    modo: ModoOrganizacion | None = None
    tipo_periodo_academico: TipoPeriodoAcademico | None = None
    minutos_tolerancia_retardo: int | None = Field(default=None, ge=0, le=180)
    segundos_enfriamiento: int | None = Field(default=None, ge=5, le=3600)
    guardar_avatar_por_defecto: bool | None = None
    secreto_autorizacion: str | None = Field(default=None, max_length=120)


class OrganizacionLeer(BaseModel):
    """Representación JSON de una organización registrada."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    modo: str
    tipo_periodo_academico: str = "semestral"
    minutos_tolerancia_retardo: int
    segundos_enfriamiento: int
    guardar_avatar_por_defecto: bool
    creado_en: datetime


# ==============================================================================
# Grupos y Departamentos
# ==============================================================================
class GrupoCrear(BaseModel):
    """Payload para registrar un grupo académico o departamento empresarial."""

    id_organizacion: int
    nombre: str = Field(..., min_length=2, max_length=120)
    codigo: str = Field(..., min_length=1, max_length=40)
    hora_inicio_horario: str = Field(default="08:00", pattern=r"^\d{2}:\d{2}$")
    hora_fin_horario: str = Field(default="17:00", pattern=r"^\d{2}:\d{2}$")
    id_carrera: int | None = None
    semestre: str | None = Field(default=None, max_length=40)
    tipo_periodo: TipoPeriodoAcademico | None = None
    aula_defecto: str | None = Field(default=None, max_length=80)
    id_turno_laboral_defecto: int | None = None


class GrupoActualizar(BaseModel):
    """Payload parcial para editar metadatos, aula fija o turno por defecto de un grupo."""

    nombre: str | None = Field(default=None, min_length=2, max_length=120)
    codigo: str | None = Field(default=None, min_length=1, max_length=40)
    hora_inicio_horario: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    hora_fin_horario: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    id_carrera: int | None = None
    semestre: str | None = Field(default=None, max_length=40)
    tipo_periodo: TipoPeriodoAcademico | None = None
    aula_defecto: str | None = Field(default=None, max_length=80)
    id_turno_laboral_defecto: int | None = None
    secreto_autorizacion: str | None = Field(default=None, max_length=120)


class GrupoLeer(BaseModel):
    """Representación JSON enriquecida de un grupo o área con conteos y turno heredado."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    id_organizacion: int
    id_carrera: int | None = None
    nombre_carrera: str | None = None
    nombre: str
    codigo: str
    semestre: str | None = None
    aula_defecto: str | None = None
    id_turno_laboral_defecto: int | None = None
    nombre_turno_laboral_defecto: str | None = None
    codigo_turno_laboral_defecto: str | None = None
    tipo_periodo: str = "semestral"
    tipo_periodo_personalizado: str | None = None
    hora_inicio_horario: str
    hora_fin_horario: str
    creado_en: datetime
    cantidad_integrantes: int = 0
    cantidad_cursos: int = 0


# ==============================================================================
# Personas, Enrolamiento y Revocación Biométrica
# ==============================================================================
class PersonaCrear(BaseModel):
    """Payload para registrar a una persona en el padrón de una organización."""

    id_organizacion: int
    identificador_externo: str = Field(..., min_length=1, max_length=60)
    nombre_completo: str = Field(..., min_length=2, max_length=160)
    correo: str | None = Field(default=None, max_length=160)
    rol: RolPersona = "employee"
    consentimiento_biometrico: bool = False
    ids_grupos: list[int] = Field(default_factory=list)
    id_turno_laboral: int | None = None


class PersonaActualizar(BaseModel):
    """Payload parcial para editar datos de persona, grupos o turno asignado."""

    nombre_completo: str | None = Field(default=None, min_length=2, max_length=160)
    correo: str | None = Field(default=None, max_length=160)
    rol: RolPersona | None = None
    consentimiento_biometrico: bool | None = None
    esta_activo: bool | None = None
    ids_grupos: list[int] | None = None
    id_turno_laboral: int | None = None


class PersonaLeer(BaseModel):
    """Representación JSON de una persona con progreso biométrico y turno efectivo."""

    id: int
    id_organizacion: int
    identificador_externo: str
    nombre_completo: str
    correo: str | None
    rol: str
    avatar_base64: str | None
    consentimiento_biometrico: bool
    fecha_consentimiento_biometrico: datetime | None
    esta_activo: bool
    creado_en: datetime
    ids_grupos: list[int] = Field(default_factory=list)
    id_turno_laboral: int | None = None
    nombre_turno_laboral: str | None = None
    id_turno_laboral_efectivo: int | None = None
    nombre_turno_laboral_efectivo: str | None = None
    codigo_turno_laboral_efectivo: str | None = None
    origen_turno: OrigenTurno = "none"
    cantidad_vectores: int = 0
    poses_completadas: list[str] = Field(default_factory=list)
    requiere_reenrolamiento: bool = False


class EsquemaCuadroRostro(BaseModel):
    """Coordenadas absolutas (px) y normalizadas (0..1) del rostro detectado."""

    coordenada_x: int
    coordenada_y: int
    ancho: int
    alto: int
    confianza: float
    ancho_imagen: int
    alto_imagen: int
    coordenada_x_normalizada: float
    coordenada_y_normalizada: float
    ancho_normalizado: float
    alto_normalizado: float


class EsquemaReporteCalidad(BaseModel):
    """Métricas de nitidez, iluminación, contraluz, sombra lateral y pose facial."""

    es_valida: bool
    motivo: str | None = None
    puntaje_nitidez: float
    brillo: float
    ancho_rostro: int
    alto_rostro: int
    pose_estimada: str
    asimetria_sombra: float = 0.0
    contraluz_detectado: bool = False
    relacion_giro_horizontal: float = 0.0
    relacion_inclinacion_vertical: float = 0.55
    relacion_boca: float = 0.72
    pose_coincide: bool = True
    retroalimentacion_pose: str | None = None


class RespuestaEnrolarFrame(BaseModel):
    """Respuesta al validar o capturar una pose biométrica durante el enrolamiento."""

    aceptado: bool
    pose_valida: bool = False
    etiqueta_pose: str
    mensaje: str
    cantidad_vectores: int
    poses_completadas: list[str]
    enrolamiento_completo: bool = False
    cantidad_poses_requeridas: int = 6
    cuadro_rostro: EsquemaCuadroRostro | None = None
    calidad: EsquemaReporteCalidad | None = None
    avatar_guardado: bool = False


class SolicitudRevocarBiometria(BaseModel):
    """Autorización requerida para borrar los vectores faciales de una persona."""

    secreto_autorizacion: str = Field(..., min_length=1, max_length=120)
    motivo: str | None = Field(default=None, max_length=255)


class RespuestaRevocarBiometria(BaseModel):
    """Resumen de revocación biométrica individual y quién la autorizó."""

    id_persona: int
    vectores_eliminados: int
    avatar_eliminado: bool
    nombre_autorizador: str | None = None
    metodo_autorizacion: str | None = None
    etiqueta_credencial_delegada: str | None = None


class SolicitudRevocarBiometriaLote(BaseModel):
    """Autorización para revocar biometría de múltiples personas en una sola operación."""

    ids_personas: list[int] = Field(..., min_length=1)
    secreto_autorizacion: str = Field(..., min_length=1, max_length=120)
    motivo: str | None = Field(default=None, max_length=255)


class RespuestaRevocarBiometriaLote(BaseModel):
    """Resultado consolidado de revocación biométrica por lote."""

    cantidad_personas_revocadas: int
    vectores_eliminados: int
    nombre_autorizador: str | None = None
    metodo_autorizacion: str
    etiqueta_credencial_delegada: str | None = None


# ==============================================================================
# Sesiones y Eventos de Asistencia
# ==============================================================================
class SesionCrear(BaseModel):
    """Payload para abrir manualmente una sesión de clase o jornada laboral."""

    id_organizacion: int
    id_grupo: int | None = None
    id_asignacion_curso: int | None = None
    id_horario: int | None = None
    id_turno_laboral: int | None = None
    titulo: str = Field(..., min_length=2, max_length=160)
    fecha_sesion: date | None = None
    tipo_sesion: TipoSesion | None = None
    hora_inicio_esperada: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")


class SesionLeer(BaseModel):
    """Representación JSON de una sesión con sus metadatos académicos o de turno."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    id_organizacion: int
    id_grupo: int | None
    nombre_grupo: str | None = None
    id_asignacion_curso: int | None = None
    id_horario: int | None = None
    id_turno_laboral: int | None = None
    nombre_turno_laboral: str | None = None
    codigo_turno_laboral: str | None = None
    turno_cruza_medianoche: bool = False
    nombre_materia: str | None = None
    codigo_materia: str | None = None
    nombre_carrera: str | None = None
    nombre_docente: str | None = None
    titulo: str
    fecha_sesion: date
    tipo_sesion: str
    hora_inicio_esperada: str | None
    estado: str
    creado_en: datetime
    cerrado_en: datetime | None
    cantidad_eventos: int = 0


class EventoAsistenciaLeer(BaseModel):
    """Representación JSON de un evento individual de asistencia."""

    id: int
    id_sesion: int
    titulo_sesion: str | None = None
    id_persona: int
    nombre_persona: str
    identificador_externo_persona: str
    avatar_base64_persona: str | None = None
    id_turno_laboral: int | None = None
    nombre_turno_laboral: str | None = None
    tipo_evento: str
    estado: str
    puntaje_confianza: float | None
    minutos_trabajados: int | None = None
    minutos_retardo: int | None = None
    minutos_salida_anticipada: int | None = None
    modo_captura: str
    fecha_hora: datetime
    notas: str | None = None


class SolicitudAsistenciaManual(BaseModel):
    """Payload para registrar asistencia manual con nota de respaldo."""

    id_sesion: int
    id_persona: int
    tipo_evento: TipoEvento = "present"
    estado: EstadoEvento = "manual"
    notas: str | None = Field(default=None, max_length=255)


class ResumenBrevePersona(BaseModel):
    """Ficha resumida de la persona reconocida devuelta en tiempo real al kiosco."""

    id: int
    identificador_externo: str
    nombre_completo: str
    rol: str
    avatar_base64: str | None = None


class RespuestaReconocerFrame(BaseModel):
    """Resultado completo del pipeline biométrico sobre un frame del kiosco."""

    rostros_detectados: int
    estado_coincidencia: Literal["matched", "unknown", "ambiguous", "no_face", "low_quality"]
    cuadro_rostro: EsquemaCuadroRostro | None = None
    calidad: EsquemaReporteCalidad | None = None
    persona: ResumenBrevePersona | None = None
    confianza: float = 0.0
    puntaje_segundo_candidato: float | None = None
    accion_asistencia: Literal["recorded", "cooldown", "already_present", "invalid_sequence"] | None = None
    evento: EventoAsistenciaLeer | None = None
    minutos_trabajados: int | None = None
    nombre_turno: str | None = None
    minutos_retardo: int | None = None
    minutos_salida_anticipada: int | None = None
    id_sesion: int | None = None
    mensaje: str
    latencia_ms: float


# ==============================================================================
# Salud del Sistema
# ==============================================================================
class RespuestaSalud(BaseModel):
    """Estado de salud del servidor, modelos ONNX y conteos globales básicos."""

    estado: str
    modelos_cargados: bool
    nombre_modelo: str
    version_modelo: str
    cantidad_organizaciones: int
    cantidad_personas: int
    cantidad_vectores: int


# ==============================================================================
# Autenticación, Usuarios, Credenciales Delegadas y Auditoría
# ==============================================================================
class SolicitudInicioSesion(BaseModel):
    """Credenciales de acceso enviadas al endpoint de login."""

    correo: str = Field(..., min_length=3, max_length=160)
    contrasena: str = Field(..., min_length=1, max_length=120)


class UsuarioLeer(BaseModel):
    """Datos públicos de una cuenta de usuario del sistema."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    correo: str
    nombre_completo: str
    rol: str
    id_organizacion: int | None
    nombre_organizacion: str | None = None
    modo_organizacion: str | None = None
    esta_activo: bool
    id_usuario_creador: int | None
    creado_en: datetime


class RespuestaInicioSesion(BaseModel):
    """Token JWT emitido tras autenticación exitosa junto al perfil del usuario."""

    token_acceso: str
    tipo_token: str = "bearer"
    usuario: UsuarioLeer


class UsuarioCrear(BaseModel):
    """Payload para crear un usuario operativo, docente, supervisor o administrador."""

    correo: str = Field(..., min_length=4, max_length=160)
    nombre_completo: str = Field(..., min_length=2, max_length=160)
    contrasena: str = Field(..., min_length=6, max_length=120)
    rol: RolUsuario = "operator"
    id_organizacion: int | None = None


class UsuarioActualizar(BaseModel):
    """Payload parcial para actualizar nombre, rol, contraseña o estado activo."""

    nombre_completo: str | None = Field(default=None, min_length=2, max_length=160)
    contrasena: str | None = Field(default=None, min_length=6, max_length=120)
    rol: RolUsuario | None = None
    esta_activo: bool | None = None


class CredencialDelegadaCrear(BaseModel):
    """Payload para emitir una contraseña delegada temporal o personalizada."""

    id_organizacion: int | None = None
    etiqueta: str = Field(..., min_length=2, max_length=120)
    id_usuario_asignado: int | None = None
    nombre_asignado: str | None = Field(default=None, max_length=160)
    secreto_personalizado: str | None = Field(default=None, min_length=6, max_length=120)
    expira_en_dias: int | None = Field(default=None, ge=1, le=3650)
    operaciones_permitidas: list[str] = Field(default_factory=lambda: ["revoke_biometrics"])


class CredencialDelegadaLeer(BaseModel):
    """Metadatos públicos de una credencial delegada (sin exponer su secreto en claro)."""

    id: int
    id_organizacion: int
    etiqueta: str
    prefijo_secreto: str
    id_usuario_creador: int | None
    nombre_creador: str | None = None
    id_usuario_asignado: int | None
    nombre_asignado: str
    operaciones_permitidas: list[str]
    estado: str
    expira_en: datetime | None
    creado_en: datetime
    revocado_en: datetime | None


class RespuestaCrearCredencialDelegada(BaseModel):
    """Respuesta única al emitir credencial delegada que muestra el secreto plano una sola vez."""

    credencial: CredencialDelegadaLeer
    secreto_plano: str


class RegistroAuditoriaLeer(BaseModel):
    """Entrada legible de la bitácora de auditoría con nombres de actor y autorizador."""

    id: int
    id_organizacion: int | None
    accion: str
    tipo_objetivo: str
    id_objetivo: int | None
    resumen_objetivo: str | None
    id_usuario_ejecutor: int | None
    nombre_ejecutor: str | None = None
    id_usuario_autorizador: int | None
    nombre_autorizador: str | None = None
    id_credencial_delegada: int | None
    prefijo_credencial_delegada: str | None = None
    nombre_asignado_credencial: str | None = None
    detalles: str | None
    creado_en: datetime


# ==============================================================================
# Modelo Educativo Completo
# ==============================================================================
class CarreraCrear(BaseModel):
    """Payload para registrar una carrera en una institución educativa."""

    id_organizacion: int
    nombre: str = Field(..., min_length=2, max_length=140)
    codigo: str = Field(..., min_length=1, max_length=40)
    descripcion: str | None = Field(default=None, max_length=255)
    tipo_periodo: TipoPeriodoAcademico | None = None


class CarreraActualizar(BaseModel):
    """Payload parcial para modificar datos o periodo académico de una carrera."""

    nombre: str | None = Field(default=None, min_length=2, max_length=140)
    codigo: str | None = Field(default=None, min_length=1, max_length=40)
    descripcion: str | None = Field(default=None, max_length=255)
    tipo_periodo: TipoPeriodoAcademico | None = None
    secreto_autorizacion: str | None = Field(default=None, max_length=120)


class CarreraLeer(BaseModel):
    """Representación JSON de una carrera con conteo de grupos y materias."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    id_organizacion: int
    nombre: str
    codigo: str
    descripcion: str | None
    tipo_periodo: str | None = None
    tipo_periodo_efectivo: str = "semestral"
    creado_en: datetime
    cantidad_grupos: int = 0
    cantidad_materias: int = 0


class MateriaCrear(BaseModel):
    """Payload para crear una asignatura en el catálogo escolar."""

    id_organizacion: int
    id_carrera: int | None = None
    nombre: str = Field(..., min_length=2, max_length=140)
    codigo: str = Field(..., min_length=1, max_length=40)


class MateriaLeer(BaseModel):
    """Representación JSON de una materia y su carrera opcional."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    id_organizacion: int
    id_carrera: int | None = None
    nombre_carrera: str | None = None
    nombre: str
    codigo: str
    creado_en: datetime


class HorarioClaseCrear(BaseModel):
    """Definición de un bloque horario semanal para una asignatura."""

    dia_semana: int = Field(..., ge=0, le=6)
    hora_inicio: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    hora_fin: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    aula: str | None = Field(default=None, max_length=80)


class HorarioClaseLeer(BaseModel):
    """Representación JSON de un horario semanal guardado."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    id_asignacion_curso: int
    dia_semana: int
    hora_inicio: str
    hora_fin: str
    aula: str | None = None
    creado_en: datetime


class AsignacionCursoCrear(BaseModel):
    """Payload para asignar una materia y docente a un grupo junto con sus horarios."""

    id_organizacion: int
    id_grupo: int
    id_materia: int
    id_usuario_docente: int | None = None
    periodo_lectivo: str | None = Field(default=None, max_length=60)
    horarios: list[HorarioClaseCrear] = Field(default_factory=list)


class AsignacionCursoActualizar(BaseModel):
    """Payload parcial para reasignar docente, periodo lectivo o estado activo de un curso."""

    id_usuario_docente: int | None = None
    periodo_lectivo: str | None = Field(default=None, max_length=60)
    esta_activo: bool | None = None


class AsignacionCursoLeer(BaseModel):
    """Representación JSON completa de una asignatura asignada a un grupo."""

    id: int
    id_organizacion: int
    id_grupo: int
    nombre_grupo: str
    codigo_grupo: str
    aula_defecto_grupo: str | None = None
    semestre: str | None = None
    tipo_periodo: str = "semestral"
    id_carrera: int | None = None
    nombre_carrera: str | None = None
    id_materia: int
    nombre_materia: str
    codigo_materia: str
    id_usuario_docente: int | None = None
    nombre_docente: str | None = None
    correo_docente: str | None = None
    periodo_lectivo: str | None = None
    esta_activo: bool
    cantidad_estudiantes: int = 0
    horarios: list[HorarioClaseLeer] = Field(default_factory=list)
    creado_en: datetime


class SolicitudGenerarSesiones(BaseModel):
    """Parámetros para generar de forma idempotente las sesiones académicas de una fecha."""

    id_organizacion: int | None = None
    fecha_objetivo: date | None = None
    id_asignacion_curso: int | None = None


class RespuestaGenerarSesiones(BaseModel):
    """Resultado de generación masiva o individual de sesiones del día."""

    fecha_objetivo: date
    cantidad_creadas: int
    cantidad_existentes: int
    sesiones: list[SesionLeer] = Field(default_factory=list)


class SolicitudIniciarSesionCurso(BaseModel):
    """Opciones para iniciar el pase de lista en 1 clic desde una asignatura."""

    id_horario: int | None = None
    fecha_sesion: date | None = None


class BloqueAgendaDocente(BaseModel):
    """Bloque de clase en el horario diario del profesor con su estado temporal."""

    id_horario: int
    id_asignacion_curso: int
    nombre_materia: str
    codigo_materia: str
    id_grupo: int
    nombre_grupo: str
    codigo_grupo: str
    nombre_carrera: str | None = None
    dia_semana: int
    hora_inicio: str
    hora_fin: str
    aula: str | None = None
    estado_bloque: Literal["in_progress", "upcoming", "finished"]
    cantidad_estudiantes: int = 0
    sesion: SesionLeer | None = None


class RespuestaAgendaDocente(BaseModel):
    """Agenda diaria del docente con su clase actual, bloques del día y cursos asignados."""

    fecha_objetivo: date
    hora_actual: str
    bloque_actual: BloqueAgendaDocente | None = None
    bloques_hoy: list[BloqueAgendaDocente] = Field(default_factory=list)
    cursos: list[AsignacionCursoLeer] = Field(default_factory=list)


class EstadisticaAsistenciaMateria(BaseModel):
    """Métricas consolidadas de asistencia por asignatura impartida."""

    id_asignacion_curso: int
    id_materia: int
    nombre_materia: str
    codigo_materia: str
    id_grupo: int
    nombre_grupo: str
    codigo_grupo: str
    id_carrera: int | None = None
    nombre_carrera: str | None = None
    semestre: str | None = None
    tipo_periodo: str = "semestral"
    nombre_docente: str | None = None
    cantidad_sesiones: int
    estudiantes_inscritos: int
    registros_esperados: int
    cantidad_asistencias: int
    cantidad_puntuales: int
    cantidad_retardos: int
    cantidad_manuales: int
    cantidad_faltas: int
    tasa_asistencia: float


class EstadisticaAsistenciaAlumnoGrupo(BaseModel):
    """Desglose individual de asistencias, retardos y faltas de un alumno en su grupo."""

    id_persona: int
    identificador_externo: str
    nombre_completo: str
    registros_esperados: int
    cantidad_asistencias: int
    cantidad_puntuales: int
    cantidad_retardos: int
    cantidad_faltas: int
    tasa_asistencia: float


class EstadisticaAsistenciaGrupo(BaseModel):
    """Resumen de asistencia consolidado para un grupo académico y sus integrantes."""

    id_grupo: int
    nombre_grupo: str
    codigo_grupo: str
    id_carrera: int | None = None
    nombre_carrera: str | None = None
    semestre: str | None = None
    tipo_periodo: str = "semestral"
    cantidad_materias: int
    cantidad_estudiantes: int
    total_sesiones: int
    total_esperados: int
    total_asistencias: int
    total_puntuales: int
    total_retardos: int
    total_faltas: int
    tasa_asistencia_general: float
    desglose_estudiantes: list[EstadisticaAsistenciaAlumnoGrupo] = Field(default_factory=list)


class ResumenEstadisticasAcademicas(BaseModel):
    """Indicadores globales del tablero académico."""

    total_carreras: int
    total_grupos: int
    total_materias: int
    total_cursos: int
    total_sesiones: int
    tasa_asistencia_general: float


class RespuestaEstadisticasAcademicas(BaseModel):
    """Respuesta completa de estadísticas escolares por materia y grupo."""

    id_organizacion: int
    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    resumen: ResumenEstadisticasAcademicas
    por_materia: list[EstadisticaAsistenciaMateria] = Field(default_factory=list)
    por_grupo: list[EstadisticaAsistenciaGrupo] = Field(default_factory=list)


# ==============================================================================
# Turnos Empresariales y Reglas de Jornada
# ==============================================================================
class TurnoLaboralCrear(BaseModel):
    """Payload para crear un turno laboral diurno o nocturno."""

    id_organizacion: int
    nombre: str = Field(..., min_length=2, max_length=120)
    codigo: str = Field(..., min_length=1, max_length=40)
    hora_inicio: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    hora_fin: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    dias_semana: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    minutos_tolerancia_retardo: int | None = Field(default=None, ge=0, le=180)
    minutos_tolerancia_salida_anticipada: int = Field(default=10, ge=0, le=180)
    esta_activo: bool = True


class TurnoLaboralActualizar(BaseModel):
    """Payload parcial para editar horarios, días o tolerancias de un turno laboral."""

    nombre: str | None = Field(default=None, min_length=2, max_length=120)
    codigo: str | None = Field(default=None, min_length=1, max_length=40)
    hora_inicio: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    hora_fin: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    dias_semana: list[int] | None = None
    minutos_tolerancia_retardo: int | None = Field(default=None, ge=0, le=180)
    minutos_tolerancia_salida_anticipada: int | None = Field(default=None, ge=0, le=180)
    esta_activo: bool | None = None


class TurnoLaboralLeer(BaseModel):
    """Representación JSON de un turno con duración calculada y conteo de asignados."""

    id: int
    id_organizacion: int
    nombre: str
    codigo: str
    hora_inicio: str
    hora_fin: str
    cruza_medianoche: bool
    duracion_esperada_minutos: int
    dias_semana: list[int] = Field(default_factory=list)
    minutos_tolerancia_retardo: int | None = None
    minutos_tolerancia_retardo_efectiva: int
    minutos_tolerancia_salida_anticipada: int
    esta_activo: bool
    cantidad_empleados_asignados: int = 0
    cantidad_grupos_por_defecto: int = 0
    creado_en: datetime


class SolicitudAsignacionMasivaTurno(BaseModel):
    """Payload para asignar o limpiar turno en múltiples empleados o por departamento."""

    ids_personas: list[int] = Field(default_factory=list)
    id_grupo: int | None = None
    limpiar_turno: bool = False


class RespuestaAsignacionMasivaTurno(BaseModel):
    """Resumen de empleados actualizados tras una asignación masiva de turno."""

    id_turno_laboral: int | None = None
    nombre_turno_laboral: str | None = None
    cantidad_actualizados: int


class SolicitudGenerarSesionesTurno(BaseModel):
    """Parámetros para generar sesiones de jornada laboral para una fecha dada."""

    id_organizacion: int | None = None
    fecha_objetivo: date | None = None
    id_turno_laboral: int | None = None


class SolicitudIniciarSesionTurno(BaseModel):
    """Fecha opcional para abrir o recuperar la jornada de un turno laboral."""

    fecha_sesion: date | None = None


class EstadisticaAsistenciaTurno(BaseModel):
    """Métricas agregadas de asistencia, puntualidad y horas trabajadas por turno."""

    id_turno_laboral: int | None = None
    nombre_turno: str
    codigo_turno: str | None = None
    hora_inicio: str | None = None
    hora_fin: str | None = None
    cruza_medianoche: bool = False
    dias_semana: list[int] = Field(default_factory=list)
    cantidad_empleados: int
    dias_programados: int
    dias_asistidos: int
    dias_puntuales: int
    dias_con_retardo: int
    dias_salida_anticipada: int
    dias_falta: int
    dias_sin_salida: int
    total_minutos_trabajados: int
    promedio_minutos_trabajados: float
    tasa_asistencia: float
    tasa_puntualidad: float


class EstadisticaAsistenciaEmpleado(BaseModel):
    """Detalle individual de asistencia, retardos, salidas anticipadas y tiempo trabajado."""

    id_persona: int
    identificador_externo: str
    nombre_completo: str
    nombres_grupos: list[str] = Field(default_factory=list)
    id_turno_laboral: int | None = None
    nombre_turno: str | None = None
    codigo_turno: str | None = None
    origen_turno: OrigenTurno = "none"
    dias_programados: int
    dias_asistidos: int
    dias_puntuales: int
    dias_con_retardo: int
    dias_salida_anticipada: int
    dias_falta: int
    dias_sin_salida: int
    total_minutos_retardo: int
    total_minutos_salida_anticipada: int
    total_minutos_trabajados: int
    tasa_asistencia: float
    tasa_puntualidad: float


class ResumenEstadisticasEmpresariales(BaseModel):
    """KPIs globales de operación y puntualidad en modalidad empresarial."""

    total_turnos: int
    turnos_activos: int
    total_empleados: int
    empleados_asignados: int
    empleados_sin_turno: int
    dias_empleado_programados: int
    dias_asistidos: int
    dias_puntuales: int
    dias_con_retardo: int
    dias_salida_anticipada: int
    dias_falta: int
    dias_sin_salida: int
    total_minutos_trabajados: int
    tasa_asistencia: float
    tasa_puntualidad: float


class RespuestaEstadisticasEmpresariales(BaseModel):
    """Respuesta completa de analítica empresarial por turno y por colaborador."""

    id_organizacion: int
    fecha_desde: date
    fecha_hasta: date
    resumen: ResumenEstadisticasEmpresariales
    por_turno: list[EstadisticaAsistenciaTurno] = Field(default_factory=list)
    por_empleado: list[EstadisticaAsistenciaEmpleado] = Field(default_factory=list)
