"""Modelos ORM de SQLAlchemy 2.0 para el dominio unificado de IdentIA.

Todos los atributos Python están nombrados en español descriptivo, mientras que
las tablas físicas (`__tablename__`) y los nombres físicos de columnas en SQLite
(`mapped_column("nombre_sql", ...)`) se mantienen sin cambios para preservar la
compatibilidad total con las bases de datos y migraciones Alembic `0001`–`0005`.
"""

from datetime import date, datetime, timezone
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import BaseDeclarativa


def fecha_utc_ingenua() -> datetime:
    """Devuelve la fecha y hora UTC actual sin tzinfo para almacenamiento homogéneo en SQLite."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Organizacion(BaseDeclarativa):
    """Entidad raíz multi-tenant que representa una escuela o empresa en IdentIA."""

    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column("id", Integer, primary_key=True, index=True)
    nombre: Mapped[str] = mapped_column("name", String(120), nullable=False)
    modo: Mapped[str] = mapped_column("mode", String(20), nullable=False, default="enterprise")
    tipo_periodo_academico: Mapped[str] = mapped_column(
        "academic_period_type", String(20), nullable=False, default="semestral"
    )
    minutos_tolerancia_retardo: Mapped[int] = mapped_column(
        "late_tolerance_minutes", Integer, nullable=False, default=15
    )
    segundos_enfriamiento: Mapped[int] = mapped_column(
        "cooldown_seconds", Integer, nullable=False, default=60
    )
    guardar_avatar_por_defecto: Mapped[bool] = mapped_column(
        "store_avatar_by_default", Boolean, nullable=False, default=True
    )
    creado_en: Mapped[datetime] = mapped_column(
        "created_at", DateTime, nullable=False, default=fecha_utc_ingenua
    )

    # Relaciones inversas en cascada para aislar y limpiar recursos al borrar una organización
    grupos: Mapped[list["Grupo"]] = relationship(
        back_populates="organizacion", cascade="all, delete-orphan"
    )
    carreras: Mapped[list["Carrera"]] = relationship(
        back_populates="organizacion", cascade="all, delete-orphan"
    )
    materias: Mapped[list["Materia"]] = relationship(
        back_populates="organizacion", cascade="all, delete-orphan"
    )
    asignaciones_curso: Mapped[list["AsignacionCurso"]] = relationship(
        back_populates="organizacion", cascade="all, delete-orphan"
    )
    turnos_laborales: Mapped[list["TurnoLaboral"]] = relationship(
        back_populates="organizacion", cascade="all, delete-orphan"
    )
    usuarios: Mapped[list["Usuario"]] = relationship(
        back_populates="organizacion", cascade="all, delete-orphan"
    )
    personas: Mapped[list["Persona"]] = relationship(
        back_populates="organizacion", cascade="all, delete-orphan"
    )
    sesiones: Mapped[list["SesionAsistencia"]] = relationship(
        back_populates="organizacion", cascade="all, delete-orphan"
    )
    credenciales_delegadas: Mapped[list["CredencialDelegada"]] = relationship(
        cascade="all, delete-orphan"
    )
    registros_auditoria: Mapped[list["RegistroAuditoria"]] = relationship(
        cascade="all, delete-orphan"
    )


class Carrera(BaseDeclarativa):
    """Programa educativo o licenciatura dentro de una organización escolar."""

    __tablename__ = "careers"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_career_org_code"),
    )

    id: Mapped[int] = mapped_column("id", Integer, primary_key=True, index=True)
    id_organizacion: Mapped[int] = mapped_column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    nombre: Mapped[str] = mapped_column("name", String(140), nullable=False)
    codigo: Mapped[str] = mapped_column("code", String(40), nullable=False)
    descripcion: Mapped[str | None] = mapped_column("description", String(255), nullable=True)
    tipo_periodo: Mapped[str | None] = mapped_column("period_type", String(20), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(
        "created_at", DateTime, nullable=False, default=fecha_utc_ingenua
    )

    organizacion: Mapped["Organizacion"] = relationship(back_populates="carreras")
    grupos: Mapped[list["Grupo"]] = relationship(back_populates="carrera")
    materias: Mapped[list["Materia"]] = relationship(back_populates="carrera")


class Grupo(BaseDeclarativa):
    """Grupo académico (escuela) o departamento/área operativa (empresa)."""

    __tablename__ = "groups"

    id: Mapped[int] = mapped_column("id", Integer, primary_key=True, index=True)
    id_organizacion: Mapped[int] = mapped_column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    id_carrera: Mapped[int | None] = mapped_column(
        "career_id",
        ForeignKey("careers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    id_turno_laboral_defecto: Mapped[int | None] = mapped_column(
        "default_work_shift_id",
        ForeignKey("work_shifts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    nombre: Mapped[str] = mapped_column("name", String(120), nullable=False)
    codigo: Mapped[str] = mapped_column("code", String(40), nullable=False)
    semestre: Mapped[str | None] = mapped_column("semester", String(40), nullable=True)
    tipo_periodo: Mapped[str | None] = mapped_column("period_type", String(20), nullable=True)
    aula_defecto: Mapped[str | None] = mapped_column("default_classroom", String(80), nullable=True)
    hora_inicio_horario: Mapped[str] = mapped_column(
        "schedule_start", String(5), nullable=False, default="08:00"
    )
    hora_fin_horario: Mapped[str] = mapped_column(
        "schedule_end", String(5), nullable=False, default="17:00"
    )
    creado_en: Mapped[datetime] = mapped_column(
        "created_at", DateTime, nullable=False, default=fecha_utc_ingenua
    )

    organizacion: Mapped["Organizacion"] = relationship(back_populates="grupos")
    carrera: Mapped["Carrera | None"] = relationship(back_populates="grupos")
    turno_laboral_defecto: Mapped["TurnoLaboral | None"] = relationship(
        foreign_keys=[id_turno_laboral_defecto]
    )
    enlaces_personas: Mapped[list["PersonaGrupo"]] = relationship(
        back_populates="grupo", cascade="all, delete-orphan"
    )
    asignaciones_curso: Mapped[list["AsignacionCurso"]] = relationship(
        back_populates="grupo", cascade="all, delete-orphan"
    )
    sesiones: Mapped[list["SesionAsistencia"]] = relationship(back_populates="grupo")


class Materia(BaseDeclarativa):
    """Catálogo de asignaturas académicas pertenecientes a una escuela o carrera."""

    __tablename__ = "subjects"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_subject_org_code"),
    )

    id: Mapped[int] = mapped_column("id", Integer, primary_key=True, index=True)
    id_organizacion: Mapped[int] = mapped_column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    id_carrera: Mapped[int | None] = mapped_column(
        "career_id",
        ForeignKey("careers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    nombre: Mapped[str] = mapped_column("name", String(140), nullable=False)
    codigo: Mapped[str] = mapped_column("code", String(40), nullable=False)
    creado_en: Mapped[datetime] = mapped_column(
        "created_at", DateTime, nullable=False, default=fecha_utc_ingenua
    )

    organizacion: Mapped["Organizacion"] = relationship(back_populates="materias")
    carrera: Mapped["Carrera | None"] = relationship(back_populates="materias")
    asignaciones_curso: Mapped[list["AsignacionCurso"]] = relationship(
        back_populates="materia", cascade="all, delete-orphan"
    )


class AsignacionCurso(BaseDeclarativa):
    """Vinculación única Grupo + Materia + Docente responsable en un periodo escolar."""

    __tablename__ = "course_assignments"
    __table_args__ = (
        UniqueConstraint("group_id", "subject_id", name="uq_course_group_subject"),
    )

    id: Mapped[int] = mapped_column("id", Integer, primary_key=True, index=True)
    id_organizacion: Mapped[int] = mapped_column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    id_grupo: Mapped[int] = mapped_column(
        "group_id",
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    id_materia: Mapped[int] = mapped_column(
        "subject_id",
        ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    id_usuario_docente: Mapped[int | None] = mapped_column(
        "teacher_user_id",
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    periodo_lectivo: Mapped[str | None] = mapped_column("term", String(60), nullable=True)
    esta_activo: Mapped[bool] = mapped_column("is_active", Boolean, nullable=False, default=True)
    creado_en: Mapped[datetime] = mapped_column(
        "created_at", DateTime, nullable=False, default=fecha_utc_ingenua
    )

    organizacion: Mapped["Organizacion"] = relationship(back_populates="asignaciones_curso")
    grupo: Mapped["Grupo"] = relationship(back_populates="asignaciones_curso")
    materia: Mapped["Materia"] = relationship(back_populates="asignaciones_curso")
    docente: Mapped["Usuario | None"] = relationship(foreign_keys=[id_usuario_docente])
    horarios: Mapped[list["HorarioClase"]] = relationship(
        back_populates="asignacion_curso", cascade="all, delete-orphan"
    )


class HorarioClase(BaseDeclarativa):
    """Bloque semanal específico (día, hora inicio/fin y aula) de una asignación de curso."""

    __tablename__ = "class_schedules"

    id: Mapped[int] = mapped_column("id", Integer, primary_key=True, index=True)
    id_asignacion_curso: Mapped[int] = mapped_column(
        "course_assignment_id",
        ForeignKey("course_assignments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 0=Lunes .. 6=Domingo según `datetime.weekday()`
    dia_semana: Mapped[int] = mapped_column("day_of_week", Integer, nullable=False)
    hora_inicio: Mapped[str] = mapped_column("start_time", String(5), nullable=False)
    hora_fin: Mapped[str] = mapped_column("end_time", String(5), nullable=False)
    aula: Mapped[str | None] = mapped_column("classroom", String(80), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(
        "created_at", DateTime, nullable=False, default=fecha_utc_ingenua
    )

    asignacion_curso: Mapped["AsignacionCurso"] = relationship(back_populates="horarios")


class TurnoLaboral(BaseDeclarativa):
    """Turno empresarial configurable con soporte para jornadas nocturnas (cruce de medianoche)."""

    __tablename__ = "work_shifts"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_work_shift_org_code"),
    )

    id: Mapped[int] = mapped_column("id", Integer, primary_key=True, index=True)
    id_organizacion: Mapped[int] = mapped_column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    nombre: Mapped[str] = mapped_column("name", String(120), nullable=False)
    codigo: Mapped[str] = mapped_column("code", String(40), nullable=False)
    hora_inicio: Mapped[str] = mapped_column("start_time", String(5), nullable=False)
    hora_fin: Mapped[str] = mapped_column("end_time", String(5), nullable=False)
    cruza_medianoche: Mapped[bool] = mapped_column(
        "crosses_midnight", Boolean, nullable=False, default=False
    )
    dias_semana: Mapped[str] = mapped_column(
        "days_of_week", String(30), nullable=False, default="0,1,2,3,4"
    )
    minutos_tolerancia_retardo: Mapped[int | None] = mapped_column(
        "late_tolerance_minutes", Integer, nullable=True
    )
    minutos_tolerancia_salida_anticipada: Mapped[int] = mapped_column(
        "early_exit_tolerance_minutes", Integer, nullable=False, default=10
    )
    esta_activo: Mapped[bool] = mapped_column("is_active", Boolean, nullable=False, default=True)
    creado_en: Mapped[datetime] = mapped_column(
        "created_at", DateTime, nullable=False, default=fecha_utc_ingenua
    )

    organizacion: Mapped["Organizacion"] = relationship(back_populates="turnos_laborales")


class Persona(BaseDeclarativa):
    """Sujeto enrolable en el padrón biométrico (empleado, estudiante, docente o administrativo)."""

    __tablename__ = "persons"
    __table_args__ = (
        UniqueConstraint("organization_id", "external_id", name="uq_org_external_id"),
    )

    id: Mapped[int] = mapped_column("id", Integer, primary_key=True, index=True)
    id_organizacion: Mapped[int] = mapped_column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    id_turno_laboral: Mapped[int | None] = mapped_column(
        "work_shift_id",
        ForeignKey("work_shifts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    identificador_externo: Mapped[str] = mapped_column(
        "external_id", String(60), nullable=False, index=True
    )
    nombre_completo: Mapped[str] = mapped_column("full_name", String(160), nullable=False)
    correo: Mapped[str | None] = mapped_column("email", String(160), nullable=True)
    rol: Mapped[str] = mapped_column("role", String(30), nullable=False, default="employee")
    avatar_base64: Mapped[str | None] = mapped_column("avatar_base64", Text, nullable=True)
    consentimiento_biometrico: Mapped[bool] = mapped_column(
        "biometric_consent", Boolean, nullable=False, default=False
    )
    fecha_consentimiento_biometrico: Mapped[datetime | None] = mapped_column(
        "biometric_consent_at", DateTime, nullable=True
    )
    esta_activo: Mapped[bool] = mapped_column("is_active", Boolean, nullable=False, default=True)
    creado_en: Mapped[datetime] = mapped_column(
        "created_at", DateTime, nullable=False, default=fecha_utc_ingenua
    )

    organizacion: Mapped["Organizacion"] = relationship(back_populates="personas")
    turno_laboral: Mapped["TurnoLaboral | None"] = relationship(foreign_keys=[id_turno_laboral])
    enlaces_grupos: Mapped[list["PersonaGrupo"]] = relationship(
        back_populates="persona", cascade="all, delete-orphan"
    )
    vectores_faciales: Mapped[list["VectorFacial"]] = relationship(
        back_populates="persona", cascade="all, delete-orphan"
    )
    eventos_asistencia: Mapped[list["EventoAsistencia"]] = relationship(
        back_populates="persona", cascade="all, delete-orphan"
    )


class PersonaGrupo(BaseDeclarativa):
    """Tabla puente N:M que asocia personas con grupos escolares o departamentos."""

    __tablename__ = "person_groups"

    id_persona: Mapped[int] = mapped_column(
        "person_id", ForeignKey("persons.id", ondelete="CASCADE"), primary_key=True
    )
    id_grupo: Mapped[int] = mapped_column(
        "group_id", ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )

    persona: Mapped["Persona"] = relationship(back_populates="enlaces_grupos")
    grupo: Mapped["Grupo"] = relationship(back_populates="enlaces_personas")


class VectorFacial(BaseDeclarativa):
    """Embedding biométrico normalizado L2 (128-D float32) vinculado a una pose."""

    __tablename__ = "face_embeddings"
    __table_args__ = (
        UniqueConstraint("person_id", "pose_label", name="uq_person_pose"),
    )

    id: Mapped[int] = mapped_column("id", Integer, primary_key=True, index=True)
    id_persona: Mapped[int] = mapped_column(
        "person_id",
        ForeignKey("persons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    etiqueta_pose: Mapped[str] = mapped_column("pose_label", String(30), nullable=False)
    bytes_vector: Mapped[bytes] = mapped_column("vector_bytes", LargeBinary, nullable=False)
    nombre_modelo: Mapped[str] = mapped_column("model_name", String(40), nullable=False)
    version_modelo: Mapped[str] = mapped_column("model_version", String(60), nullable=False)
    puntaje_calidad: Mapped[float] = mapped_column(
        "quality_score", Float, nullable=False, default=0.0
    )
    relacion_boca: Mapped[float | None] = mapped_column("mouth_ratio", Float, nullable=True)
    relacion_inclinacion_vertical: Mapped[float | None] = mapped_column(
        "pitch_ratio", Float, nullable=True
    )
    creado_en: Mapped[datetime] = mapped_column(
        "created_at", DateTime, nullable=False, default=fecha_utc_ingenua
    )

    persona: Mapped["Persona"] = relationship(back_populates="vectores_faciales")


class SesionAsistencia(BaseDeclarativa):
    """Sesión de pase de lista (clase académica) o jornada laboral empresarial."""

    __tablename__ = "attendance_sessions"

    id: Mapped[int] = mapped_column("id", Integer, primary_key=True, index=True)
    id_organizacion: Mapped[int] = mapped_column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    id_grupo: Mapped[int | None] = mapped_column(
        "group_id",
        ForeignKey("groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    id_asignacion_curso: Mapped[int | None] = mapped_column(
        "course_assignment_id",
        ForeignKey("course_assignments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    id_horario: Mapped[int | None] = mapped_column(
        "schedule_id",
        ForeignKey("class_schedules.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    id_turno_laboral: Mapped[int | None] = mapped_column(
        "work_shift_id",
        ForeignKey("work_shifts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    titulo: Mapped[str] = mapped_column("title", String(160), nullable=False)
    fecha_sesion: Mapped[date] = mapped_column("session_date", Date, nullable=False)
    tipo_sesion: Mapped[str] = mapped_column(
        "session_type", String(20), nullable=False, default="workday"
    )
    hora_inicio_esperada: Mapped[str | None] = mapped_column(
        "expected_start_time", String(5), nullable=True
    )
    estado: Mapped[str] = mapped_column("status", String(20), nullable=False, default="open")
    creado_en: Mapped[datetime] = mapped_column(
        "created_at", DateTime, nullable=False, default=fecha_utc_ingenua
    )
    cerrado_en: Mapped[datetime | None] = mapped_column("closed_at", DateTime, nullable=True)

    organizacion: Mapped["Organizacion"] = relationship(back_populates="sesiones")
    grupo: Mapped["Grupo | None"] = relationship(back_populates="sesiones")
    asignacion_curso: Mapped["AsignacionCurso | None"] = relationship()
    horario: Mapped["HorarioClase | None"] = relationship()
    turno_laboral: Mapped["TurnoLaboral | None"] = relationship(foreign_keys=[id_turno_laboral])
    eventos: Mapped[list["EventoAsistencia"]] = relationship(
        back_populates="sesion", cascade="all, delete-orphan"
    )


class EventoAsistencia(BaseDeclarativa):
    """Registro individual de asistencia (entrada, salida o asistencia escolar)."""

    __tablename__ = "attendance_events"

    id: Mapped[int] = mapped_column("id", Integer, primary_key=True, index=True)
    id_sesion: Mapped[int] = mapped_column(
        "session_id",
        ForeignKey("attendance_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    id_persona: Mapped[int] = mapped_column(
        "person_id",
        ForeignKey("persons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    id_turno_laboral: Mapped[int | None] = mapped_column(
        "work_shift_id",
        ForeignKey("work_shifts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    tipo_evento: Mapped[str] = mapped_column("event_type", String(20), nullable=False)
    estado: Mapped[str] = mapped_column("status", String(20), nullable=False, default="on_time")
    puntaje_confianza: Mapped[float | None] = mapped_column(
        "confidence_score", Float, nullable=True
    )
    minutos_trabajados: Mapped[int | None] = mapped_column(
        "worked_minutes", Integer, nullable=True
    )
    minutos_retardo: Mapped[int | None] = mapped_column("late_minutes", Integer, nullable=True)
    minutos_salida_anticipada: Mapped[int | None] = mapped_column(
        "early_exit_minutes", Integer, nullable=True
    )
    modo_captura: Mapped[str] = mapped_column(
        "capture_mode", String(30), nullable=False, default="kiosk_individual"
    )
    fecha_hora: Mapped[datetime] = mapped_column(
        "timestamp", DateTime, nullable=False, default=fecha_utc_ingenua, index=True
    )
    notas: Mapped[str | None] = mapped_column("notes", String(255), nullable=True)

    sesion: Mapped["SesionAsistencia"] = relationship(back_populates="eventos")
    persona: Mapped["Persona"] = relationship(back_populates="eventos_asistencia")
    turno_laboral: Mapped["TurnoLaboral | None"] = relationship(foreign_keys=[id_turno_laboral])


class Usuario(BaseDeclarativa):
    """Cuenta autenticada del sistema con rol RBAC y alcance multi-organización."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column("id", Integer, primary_key=True, index=True)
    correo: Mapped[str] = mapped_column("email", String(160), unique=True, nullable=False, index=True)
    nombre_completo: Mapped[str] = mapped_column("full_name", String(160), nullable=False)
    hash_contrasena: Mapped[str] = mapped_column("password_hash", String(255), nullable=False)
    rol: Mapped[str] = mapped_column("role", String(30), nullable=False, default="operator")
    id_organizacion: Mapped[int | None] = mapped_column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    esta_activo: Mapped[bool] = mapped_column("is_active", Boolean, nullable=False, default=True)
    id_usuario_creador: Mapped[int | None] = mapped_column(
        "created_by_user_id",
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    creado_en: Mapped[datetime] = mapped_column(
        "created_at", DateTime, nullable=False, default=fecha_utc_ingenua
    )

    organizacion: Mapped["Organizacion | None"] = relationship(back_populates="usuarios")


class CredencialDelegada(BaseDeclarativa):
    """Contraseña delegada temporal hasheada con scrypt para operaciones biométricas sensibles."""

    __tablename__ = "delegated_credentials"

    id: Mapped[int] = mapped_column("id", Integer, primary_key=True, index=True)
    id_organizacion: Mapped[int] = mapped_column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    etiqueta: Mapped[str] = mapped_column("label", String(120), nullable=False)
    prefijo_secreto: Mapped[str] = mapped_column("secret_prefix", String(20), nullable=False)
    hash_secreto: Mapped[str] = mapped_column("secret_hash", String(255), nullable=False)
    id_usuario_creador: Mapped[int | None] = mapped_column(
        "created_by_user_id",
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    id_usuario_asignado: Mapped[int | None] = mapped_column(
        "assigned_to_user_id",
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    nombre_asignado: Mapped[str] = mapped_column("assigned_to_name", String(160), nullable=False)
    operaciones_permitidas: Mapped[str] = mapped_column(
        "allowed_operations", String(255), nullable=False, default="revoke_biometrics"
    )
    estado: Mapped[str] = mapped_column("status", String(20), nullable=False, default="active")
    expira_en: Mapped[datetime | None] = mapped_column("expires_at", DateTime, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(
        "created_at", DateTime, nullable=False, default=fecha_utc_ingenua
    )
    revocado_en: Mapped[datetime | None] = mapped_column("revoked_at", DateTime, nullable=True)


class RegistroAuditoria(BaseDeclarativa):
    """Bitácora inmutable de acciones críticas, revocaciones biométricas y autorizaciones."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column("id", Integer, primary_key=True, index=True)
    id_organizacion: Mapped[int | None] = mapped_column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    accion: Mapped[str] = mapped_column("action", String(80), nullable=False)
    tipo_objetivo: Mapped[str] = mapped_column("target_type", String(40), nullable=False)
    id_objetivo: Mapped[int | None] = mapped_column("target_id", Integer, nullable=True)
    resumen_objetivo: Mapped[str | None] = mapped_column(
        "target_summary", String(255), nullable=True
    )
    id_usuario_ejecutor: Mapped[int | None] = mapped_column(
        "executed_by_user_id",
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    id_usuario_autorizador: Mapped[int | None] = mapped_column(
        "authorized_by_user_id",
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    id_credencial_delegada: Mapped[int | None] = mapped_column(
        "delegated_credential_id",
        ForeignKey("delegated_credentials.id", ondelete="SET NULL"),
        nullable=True,
    )
    detalles: Mapped[str | None] = mapped_column("details", Text, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(
        "created_at", DateTime, nullable=False, default=fecha_utc_ingenua, index=True
    )
