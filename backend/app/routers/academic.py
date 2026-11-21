"""Enrutador HTTP del dominio educativo (carreras, materias, cursos, agenda y estadísticas).

Implementa la estructura académica completa con herencia automática de asignaturas
hacia los alumnos inscritos en grupos, horarios semanales multi-bloque, portal
docente con aislamiento estricto y analítica administrativa consolidada.
"""

from datetime import date, datetime
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db import obtener_bd
from app.models import (
    AsignacionCurso,
    Carrera,
    Grupo,
    HorarioClase,
    Materia,
    Organizacion,
    Persona,
    Usuario,
)
from app.schemas import (
    AsignacionCursoActualizar,
    AsignacionCursoCrear,
    AsignacionCursoLeer,
    CarreraActualizar,
    CarreraCrear,
    CarreraLeer,
    HorarioClaseCrear,
    HorarioClaseLeer,
    MateriaCrear,
    MateriaLeer,
    RespuestaAgendaDocente,
    RespuestaEstadisticasAcademicas,
    RespuestaGenerarSesiones,
    SesionLeer,
    SolicitudGenerarSesiones,
    SolicitudIniciarSesionCurso,
)
from app.security import (
    obtener_usuario_actual,
    requerir_roles,
    resolver_alcance_organizacion,
    validar_acceso_organizacion,
)
from app.services.academic_service import (
    calcular_estadisticas_academicas,
    construir_agenda_docente,
    generar_sesiones_para_fecha,
    iniciar_o_obtener_sesion_curso,
    obtener_ids_grupos_docente,
    serializar_cursos_lote,
    serializar_sesiones_lote,
    validar_horarios_clase,
)
from app.services.security_service import registrar_auditoria, verificar_contrasena_admin

enrutador = APIRouter(prefix="/api/academic", tags=["academico"])


def _serializar_carreras(
    sesion_bd: Session,
    carreras: list[Carrera],
    id_organizacion: int,
) -> list[CarreraLeer]:
    """Serializa carreras junto con su periodo efectivo y conteos de grupos y materias."""
    if not carreras:
        return []
    organizacion = sesion_bd.get(Organizacion, id_organizacion)
    tipo_periodo_org = organizacion.tipo_periodo_academico if organizacion else "semestral"

    conteo_grupos = {
        id_carrera: int(conteo)
        for id_carrera, conteo in sesion_bd.execute(
            select(Grupo.id_carrera, func.count(Grupo.id))
            .where(Grupo.id_organizacion == id_organizacion, Grupo.id_carrera.is_not(None))
            .group_by(Grupo.id_carrera)
        ).all()
    }
    conteo_materias = {
        id_carrera: int(conteo)
        for id_carrera, conteo in sesion_bd.execute(
            select(Materia.id_carrera, func.count(Materia.id))
            .where(Materia.id_organizacion == id_organizacion, Materia.id_carrera.is_not(None))
            .group_by(Materia.id_carrera)
        ).all()
    }
    return [
        CarreraLeer(
            id=carrera.id,
            id_organizacion=carrera.id_organizacion,
            nombre=carrera.nombre,
            codigo=carrera.codigo,
            descripcion=carrera.descripcion,
            tipo_periodo=carrera.tipo_periodo,
            tipo_periodo_efectivo=carrera.tipo_periodo or tipo_periodo_org,
            creado_en=carrera.creado_en,
            cantidad_grupos=conteo_grupos.get(carrera.id, 0),
            cantidad_materias=conteo_materias.get(carrera.id, 0),
        )
        for carrera in carreras
    ]


def _serializar_materias(
    sesion_bd: Session,
    materias: list[Materia],
    id_organizacion: int,
) -> list[MateriaLeer]:
    """Serializa asignaturas resolviendo el nombre de su carrera asociada."""
    if not materias:
        return []
    mapa_carreras = {
        carrera.id: carrera.nombre
        for carrera in sesion_bd.scalars(
            select(Carrera).where(Carrera.id_organizacion == id_organizacion)
        ).all()
    }
    return [
        MateriaLeer(
            id=materia.id,
            id_organizacion=materia.id_organizacion,
            id_carrera=materia.id_carrera,
            nombre_carrera=mapa_carreras.get(materia.id_carrera) if materia.id_carrera else None,
            nombre=materia.nombre,
            codigo=materia.codigo,
            creado_en=materia.creado_en,
        )
        for materia in materias
    ]


def _cargar_curso_o_404(sesion_bd: Session, id_curso: int) -> AsignacionCurso:
    """Obtiene una asignación de curso con sus relaciones cargadas o lanza HTTP 404."""
    curso = sesion_bd.scalars(
        select(AsignacionCurso)
        .options(
            selectinload(AsignacionCurso.materia),
            selectinload(AsignacionCurso.grupo),
            selectinload(AsignacionCurso.docente),
            selectinload(AsignacionCurso.horarios),
        )
        .where(AsignacionCurso.id == id_curso)
    ).first()
    if curso is None:
        raise HTTPException(status_code=404, detail="Asignación de asignatura no encontrada.")
    return curso


def _validar_usuario_docente(
    sesion_bd: Session,
    id_organizacion: int,
    id_usuario_docente: int,
) -> Usuario:
    """Verifica que el usuario asignado como docente esté activo, pertenezca a la escuela y tenga rol válido."""
    docente = sesion_bd.get(Usuario, id_usuario_docente)
    if docente is None or not docente.esta_activo:
        raise HTTPException(status_code=404, detail="Usuario docente no encontrado o inactivo.")
    if docente.id_organizacion != id_organizacion:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El profesor debe pertenecer a la misma organización.",
        )
    if docente.rol not in ("teacher", "org_admin"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El usuario asignado debe tener rol de Profesor o Administrador de organización.",
        )
    return docente


# ==============================================================================
# Carreras
# ==============================================================================
@enrutador.get("/careers", response_model=list[CarreraLeer])
def listar_carreras(
    id_organizacion: int | None = Query(default=None),
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    sesion_bd: Session = Depends(obtener_bd),
) -> list[CarreraLeer]:
    """Lista todas las carreras registradas en la institución."""
    id_org_alcance = resolver_alcance_organizacion(usuario_actual, id_organizacion)
    carreras = list(
        sesion_bd.scalars(
            select(Carrera)
            .where(Carrera.id_organizacion == id_org_alcance)
            .order_by(Carrera.nombre.asc())
        ).all()
    )
    return _serializar_carreras(sesion_bd, carreras, id_org_alcance)


@enrutador.post("/careers", response_model=CarreraLeer, status_code=status.HTTP_201_CREATED)
def crear_carrera(
    carga: CarreraCrear,
    usuario_actual: Usuario = Depends(requerir_roles("superadmin", "org_admin")),
    sesion_bd: Session = Depends(obtener_bd),
) -> CarreraLeer:
    """Da de alta una nueva carrera o programa académico."""
    validar_acceso_organizacion(usuario_actual, carga.id_organizacion)
    organizacion = sesion_bd.get(Organizacion, carga.id_organizacion)
    if organizacion is None:
        raise HTTPException(status_code=404, detail="Organización no encontrada.")

    carrera = Carrera(
        id_organizacion=organizacion.id,
        nombre=carga.nombre.strip(),
        codigo=carga.codigo.strip().upper(),
        descripcion=carga.descripcion.strip() if carga.descripcion else None,
        tipo_periodo=carga.tipo_periodo,
    )
    sesion_bd.add(carrera)
    try:
        sesion_bd.flush()
    except IntegrityError as excepcion:
        sesion_bd.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe una carrera con el código '{carrera.codigo}'.",
        ) from excepcion

    registrar_auditoria(
        sesion_bd,
        id_organizacion=organizacion.id,
        accion="create_career",
        tipo_objetivo="career",
        id_objetivo=carrera.id,
        resumen_objetivo=f"{carrera.nombre} ({carrera.codigo})",
        usuario_ejecutor=usuario_actual,
        usuario_autorizador=usuario_actual,
    )
    sesion_bd.commit()
    sesion_bd.refresh(carrera)
    return _serializar_carreras(sesion_bd, [carrera], organizacion.id)[0]


@enrutador.patch("/careers/{id_carrera}", response_model=CarreraLeer)
def actualizar_carrera(
    id_carrera: int,
    carga: CarreraActualizar,
    usuario_actual: Usuario = Depends(requerir_roles("superadmin", "org_admin")),
    sesion_bd: Session = Depends(obtener_bd),
) -> CarreraLeer:
    """Actualiza una carrera (cambiar su periodo académico exige contraseña administrativa)."""
    carrera = sesion_bd.get(Carrera, id_carrera)
    if carrera is None:
        raise HTTPException(status_code=404, detail="Carrera no encontrada.")
    validar_acceso_organizacion(usuario_actual, carrera.id_organizacion)

    datos_parciales = carga.model_dump(exclude_unset=True)
    secreto_autorizacion = datos_parciales.pop("secreto_autorizacion", None)

    if "tipo_periodo" in datos_parciales and datos_parciales["tipo_periodo"] != carrera.tipo_periodo:
        admin_autorizador = verificar_contrasena_admin(
            sesion_bd,
            usuario_actual=usuario_actual,
            id_organizacion=carrera.id_organizacion,
            secreto_autorizacion=secreto_autorizacion,
        )
        registrar_auditoria(
            sesion_bd,
            id_organizacion=carrera.id_organizacion,
            accion="change_career_period_type",
            tipo_objetivo="career",
            id_objetivo=carrera.id,
            resumen_objetivo=f"{carrera.nombre} ({carrera.codigo})",
            usuario_ejecutor=usuario_actual,
            usuario_autorizador=admin_autorizador,
            detalles=(
                f"Periodo carrera: {carrera.tipo_periodo or 'general'} -> "
                f"{datos_parciales['tipo_periodo'] or 'general'}"
            ),
        )

    if "nombre" in datos_parciales and datos_parciales["nombre"] is not None:
        carrera.nombre = datos_parciales["nombre"].strip()
    if "codigo" in datos_parciales and datos_parciales["codigo"] is not None:
        carrera.codigo = datos_parciales["codigo"].strip().upper()
    if "descripcion" in datos_parciales:
        carrera.descripcion = (
            datos_parciales["descripcion"].strip() if datos_parciales["descripcion"] else None
        )
    if "tipo_periodo" in datos_parciales:
        carrera.tipo_periodo = datos_parciales["tipo_periodo"]

    try:
        sesion_bd.commit()
    except IntegrityError as excepcion:
        sesion_bd.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe otra carrera con ese código.",
        ) from excepcion
    sesion_bd.refresh(carrera)
    return _serializar_carreras(sesion_bd, [carrera], carrera.id_organizacion)[0]


@enrutador.delete("/careers/{id_carrera}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_carrera(
    id_carrera: int,
    usuario_actual: Usuario = Depends(requerir_roles("superadmin", "org_admin")),
    sesion_bd: Session = Depends(obtener_bd),
) -> None:
    """Elimina una carrera existente (los grupos asociados quedan con `id_carrera=None`)."""
    carrera = sesion_bd.get(Carrera, id_carrera)
    if carrera is None:
        raise HTTPException(status_code=404, detail="Carrera no encontrada.")
    validar_acceso_organizacion(usuario_actual, carrera.id_organizacion)
    sesion_bd.delete(carrera)
    sesion_bd.commit()


# ==============================================================================
# Asignaturas
# ==============================================================================
@enrutador.get("/subjects", response_model=list[MateriaLeer])
def listar_materias(
    id_organizacion: int | None = Query(default=None),
    id_carrera: int | None = Query(default=None),
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    sesion_bd: Session = Depends(obtener_bd),
) -> list[MateriaLeer]:
    """Lista las materias del catálogo institucional filtradas opcionalmente por carrera."""
    id_org_alcance = resolver_alcance_organizacion(usuario_actual, id_organizacion)
    consulta = (
        select(Materia)
        .where(Materia.id_organizacion == id_org_alcance)
        .order_by(Materia.nombre.asc())
    )
    if id_carrera is not None:
        consulta = consulta.where(Materia.id_carrera == id_carrera)
    materias = list(sesion_bd.scalars(consulta).all())
    return _serializar_materias(sesion_bd, materias, id_org_alcance)


@enrutador.post("/subjects", response_model=MateriaLeer, status_code=status.HTTP_201_CREATED)
def crear_materia(
    carga: MateriaCrear,
    usuario_actual: Usuario = Depends(requerir_roles("superadmin", "org_admin")),
    sesion_bd: Session = Depends(obtener_bd),
) -> MateriaLeer:
    """Crea una asignatura dentro del catálogo de la escuela."""
    validar_acceso_organizacion(usuario_actual, carga.id_organizacion)
    organizacion = sesion_bd.get(Organizacion, carga.id_organizacion)
    if organizacion is None:
        raise HTTPException(status_code=404, detail="Organización no encontrada.")

    if carga.id_carrera is not None:
        carrera = sesion_bd.get(Carrera, carga.id_carrera)
        if carrera is None or carrera.id_organizacion != organizacion.id:
            raise HTTPException(status_code=404, detail="Carrera no encontrada en la organización.")

    materia = Materia(
        id_organizacion=organizacion.id,
        id_carrera=carga.id_carrera,
        nombre=carga.nombre.strip(),
        codigo=carga.codigo.strip().upper(),
    )
    sesion_bd.add(materia)
    try:
        sesion_bd.commit()
    except IntegrityError as excepcion:
        sesion_bd.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe una asignatura con el código '{materia.codigo}'.",
        ) from excepcion
    sesion_bd.refresh(materia)
    return _serializar_materias(sesion_bd, [materia], organizacion.id)[0]


@enrutador.delete("/subjects/{id_materia}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_materia(
    id_materia: int,
    usuario_actual: Usuario = Depends(requerir_roles("superadmin", "org_admin")),
    sesion_bd: Session = Depends(obtener_bd),
) -> None:
    """Elimina una materia del catálogo escolar."""
    materia = sesion_bd.get(Materia, id_materia)
    if materia is None:
        raise HTTPException(status_code=404, detail="Asignatura no encontrada.")
    validar_acceso_organizacion(usuario_actual, materia.id_organizacion)
    sesion_bd.delete(materia)
    sesion_bd.commit()


# ==============================================================================
# Asignaciones Grupo-Materia-Profesor y Horarios
# ==============================================================================
@enrutador.get("/courses", response_model=list[AsignacionCursoLeer])
def listar_cursos(
    id_organizacion: int | None = Query(default=None),
    id_grupo: int | None = Query(default=None),
    id_usuario_docente: int | None = Query(default=None),
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    sesion_bd: Session = Depends(obtener_bd),
) -> list[AsignacionCursoLeer]:
    """Lista cursos asignados a grupos; un docente solo puede consultar sus propios cursos."""
    id_org_alcance = resolver_alcance_organizacion(usuario_actual, id_organizacion)

    id_docente_efectivo = id_usuario_docente
    if usuario_actual.rol == "teacher":
        if id_usuario_docente is not None and id_usuario_docente != usuario_actual.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo puedes consultar tus propias asignaciones de materias.",
            )
        id_docente_efectivo = usuario_actual.id

    consulta = (
        select(AsignacionCurso)
        .options(
            selectinload(AsignacionCurso.materia),
            selectinload(AsignacionCurso.grupo),
            selectinload(AsignacionCurso.docente),
            selectinload(AsignacionCurso.horarios),
        )
        .where(AsignacionCurso.id_organizacion == id_org_alcance)
        .order_by(AsignacionCurso.id.desc())
    )
    if id_grupo is not None:
        consulta = consulta.where(AsignacionCurso.id_grupo == id_grupo)
    if id_docente_efectivo is not None:
        consulta = consulta.where(AsignacionCurso.id_usuario_docente == id_docente_efectivo)

    cursos = list(sesion_bd.scalars(consulta).all())
    return serializar_cursos_lote(sesion_bd, cursos, id_org_alcance)


@enrutador.post("/courses", response_model=AsignacionCursoLeer, status_code=status.HTTP_201_CREATED)
def crear_curso(
    carga: AsignacionCursoCrear,
    usuario_actual: Usuario = Depends(requerir_roles("superadmin", "org_admin")),
    sesion_bd: Session = Depends(obtener_bd),
) -> AsignacionCursoLeer:
    """Asigna una asignatura y profesor a un grupo junto con sus bloques horarios iniciales."""
    validar_acceso_organizacion(usuario_actual, carga.id_organizacion)
    organizacion = sesion_bd.get(Organizacion, carga.id_organizacion)
    if organizacion is None:
        raise HTTPException(status_code=404, detail="Organización no encontrada.")

    grupo = sesion_bd.get(Grupo, carga.id_grupo)
    if grupo is None or grupo.id_organizacion != organizacion.id:
        raise HTTPException(status_code=404, detail="Grupo no encontrado en la organización.")

    materia = sesion_bd.get(Materia, carga.id_materia)
    if materia is None or materia.id_organizacion != organizacion.id:
        raise HTTPException(status_code=404, detail="Asignatura no encontrada en la organización.")

    if carga.id_usuario_docente is not None:
        _validar_usuario_docente(sesion_bd, organizacion.id, carga.id_usuario_docente)

    for horario in carga.horarios:
        validar_horarios_clase(horario.hora_inicio, horario.hora_fin)

    curso = AsignacionCurso(
        id_organizacion=organizacion.id,
        id_grupo=grupo.id,
        id_materia=materia.id,
        id_usuario_docente=carga.id_usuario_docente,
        periodo_lectivo=carga.periodo_lectivo.strip() if carga.periodo_lectivo else None,
        esta_activo=True,
    )
    sesion_bd.add(curso)
    try:
        sesion_bd.flush()
    except IntegrityError as excepcion:
        sesion_bd.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este grupo ya tiene asignada esa asignatura.",
        ) from excepcion

    for horario in carga.horarios:
        sesion_bd.add(
            HorarioClase(
                id_asignacion_curso=curso.id,
                dia_semana=horario.dia_semana,
                hora_inicio=horario.hora_inicio,
                hora_fin=horario.hora_fin,
                aula=horario.aula.strip() if horario.aula else None,
            )
        )

    registrar_auditoria(
        sesion_bd,
        id_organizacion=organizacion.id,
        accion="create_course_assignment",
        tipo_objetivo="course_assignment",
        id_objetivo=curso.id,
        resumen_objetivo=f"{materia.nombre} -> {grupo.nombre}",
        usuario_ejecutor=usuario_actual,
        usuario_autorizador=usuario_actual,
    )
    sesion_bd.commit()
    curso_cargado = _cargar_curso_o_404(sesion_bd, curso.id)
    return serializar_cursos_lote(sesion_bd, [curso_cargado], organizacion.id)[0]


@enrutador.patch("/courses/{id_curso}", response_model=AsignacionCursoLeer)
def actualizar_curso(
    id_curso: int,
    carga: AsignacionCursoActualizar,
    usuario_actual: Usuario = Depends(requerir_roles("superadmin", "org_admin")),
    sesion_bd: Session = Depends(obtener_bd),
) -> AsignacionCursoLeer:
    """Reasigna docente, periodo lectivo o estado activo de una asignatura en un grupo."""
    curso = _cargar_curso_o_404(sesion_bd, id_curso)
    validar_acceso_organizacion(usuario_actual, curso.id_organizacion)

    datos_parciales = carga.model_dump(exclude_unset=True)
    if (
        "id_usuario_docente" in datos_parciales
        and datos_parciales["id_usuario_docente"] is not None
    ):
        _validar_usuario_docente(
            sesion_bd, curso.id_organizacion, datos_parciales["id_usuario_docente"]
        )

    for campo, valor in datos_parciales.items():
        if campo == "periodo_lectivo" and valor is not None:
            setattr(curso, campo, valor.strip() or None)
        else:
            setattr(curso, campo, valor)

    sesion_bd.commit()
    curso_cargado = _cargar_curso_o_404(sesion_bd, curso.id)
    return serializar_cursos_lote(sesion_bd, [curso_cargado], curso.id_organizacion)[0]


@enrutador.delete("/courses/{id_curso}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_curso(
    id_curso: int,
    usuario_actual: Usuario = Depends(requerir_roles("superadmin", "org_admin")),
    sesion_bd: Session = Depends(obtener_bd),
) -> None:
    """Elimina la asignación de una asignatura en un grupo junto con sus horarios."""
    curso = sesion_bd.get(AsignacionCurso, id_curso)
    if curso is None:
        raise HTTPException(status_code=404, detail="Asignación de asignatura no encontrada.")
    validar_acceso_organizacion(usuario_actual, curso.id_organizacion)
    sesion_bd.delete(curso)
    sesion_bd.commit()


@enrutador.post(
    "/courses/{id_curso}/schedules",
    response_model=HorarioClaseLeer,
    status_code=status.HTTP_201_CREATED,
)
def agregar_horario_curso(
    id_curso: int,
    carga: HorarioClaseCrear,
    usuario_actual: Usuario = Depends(requerir_roles("superadmin", "org_admin")),
    sesion_bd: Session = Depends(obtener_bd),
) -> HorarioClaseLeer:
    """Agrega un bloque semanal (día, hora inicio/fin y aula) a una asignatura asignada."""
    curso = sesion_bd.get(AsignacionCurso, id_curso)
    if curso is None:
        raise HTTPException(status_code=404, detail="Asignación de asignatura no encontrada.")
    validar_acceso_organizacion(usuario_actual, curso.id_organizacion)
    validar_horarios_clase(carga.hora_inicio, carga.hora_fin)

    horario = HorarioClase(
        id_asignacion_curso=curso.id,
        dia_semana=carga.dia_semana,
        hora_inicio=carga.hora_inicio,
        hora_fin=carga.hora_fin,
        aula=carga.aula.strip() if carga.aula else None,
    )
    sesion_bd.add(horario)
    sesion_bd.commit()
    sesion_bd.refresh(horario)
    return HorarioClaseLeer.model_validate(horario)


@enrutador.delete("/schedules/{id_horario}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_horario(
    id_horario: int,
    usuario_actual: Usuario = Depends(requerir_roles("superadmin", "org_admin")),
    sesion_bd: Session = Depends(obtener_bd),
) -> None:
    """Elimina un bloque semanal específico de horario."""
    horario = sesion_bd.get(HorarioClase, id_horario)
    if horario is None:
        raise HTTPException(status_code=404, detail="Bloque de horario no encontrado.")
    curso = sesion_bd.get(AsignacionCurso, horario.id_asignacion_curso)
    if curso is None:
        raise HTTPException(status_code=404, detail="Curso asociado no encontrado.")
    validar_acceso_organizacion(usuario_actual, curso.id_organizacion)
    sesion_bd.delete(horario)
    sesion_bd.commit()


# ==============================================================================
# Herencia automática de materias para alumnos
# ==============================================================================
@enrutador.get("/students/{id_persona}/courses", response_model=list[AsignacionCursoLeer])
def obtener_cursos_heredados_alumno(
    id_persona: int,
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    sesion_bd: Session = Depends(obtener_bd),
) -> list[AsignacionCursoLeer]:
    """Devuelve las materias que hereda automáticamente un alumno según sus grupos."""
    persona = sesion_bd.scalars(
        select(Persona)
        .options(selectinload(Persona.enlaces_grupos))
        .where(Persona.id == id_persona)
    ).first()
    if persona is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado.")
    validar_acceso_organizacion(usuario_actual, persona.id_organizacion)

    ids_grupos_alumno = {enlace.id_grupo for enlace in persona.enlaces_grupos}
    if usuario_actual.rol == "teacher":
        ids_grupos_docente = obtener_ids_grupos_docente(sesion_bd, usuario_actual.id)
        if not (ids_grupos_alumno & ids_grupos_docente):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Este alumno no pertenece a ninguno de tus grupos.",
            )

    if not ids_grupos_alumno:
        return []

    consulta = (
        select(AsignacionCurso)
        .options(
            selectinload(AsignacionCurso.materia),
            selectinload(AsignacionCurso.grupo),
            selectinload(AsignacionCurso.docente),
            selectinload(AsignacionCurso.horarios),
        )
        .where(
            AsignacionCurso.id_organizacion == persona.id_organizacion,
            AsignacionCurso.id_grupo.in_(ids_grupos_alumno),
            AsignacionCurso.esta_activo.is_(True),
        )
        .order_by(AsignacionCurso.id.asc())
    )
    if usuario_actual.rol == "teacher":
        consulta = consulta.where(AsignacionCurso.id_usuario_docente == usuario_actual.id)

    cursos = list(sesion_bd.scalars(consulta).all())
    return serializar_cursos_lote(sesion_bd, cursos, persona.id_organizacion)


# ==============================================================================
# Generación automática de sesiones y portal docente
# ==============================================================================
@enrutador.post("/sessions/generate", response_model=RespuestaGenerarSesiones)
def generar_sesiones_academicas(
    carga: SolicitudGenerarSesiones,
    usuario_actual: Usuario = Depends(requerir_roles("superadmin", "org_admin", "teacher")),
    sesion_bd: Session = Depends(obtener_bd),
) -> RespuestaGenerarSesiones:
    """Genera de forma idempotente todas las sesiones de clase programadas para una fecha."""
    id_org_alcance = resolver_alcance_organizacion(usuario_actual, carga.id_organizacion)
    fecha_objetivo = carga.fecha_objetivo or date.today()

    if carga.id_asignacion_curso is not None:
        asignacion = sesion_bd.get(AsignacionCurso, carga.id_asignacion_curso)
        if asignacion is None or asignacion.id_organizacion != id_org_alcance:
            raise HTTPException(status_code=404, detail="Asignación de asignatura no encontrada.")
        if usuario_actual.rol == "teacher" and asignacion.id_usuario_docente != usuario_actual.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No puedes generar sesiones para materias de otro docente.",
            )

    cantidad_creadas, cantidad_existentes, sesiones = generar_sesiones_para_fecha(
        sesion_bd,
        id_organizacion=id_org_alcance,
        fecha_objetivo=fecha_objetivo,
        id_asignacion_curso=carga.id_asignacion_curso,
        id_usuario_docente=usuario_actual.id if usuario_actual.rol == "teacher" else None,
    )
    sesiones_serializadas = serializar_sesiones_lote(sesion_bd, sesiones, id_org_alcance)
    return RespuestaGenerarSesiones(
        fecha_objetivo=fecha_objetivo,
        cantidad_creadas=cantidad_creadas,
        cantidad_existentes=cantidad_existentes,
        sesiones=sesiones_serializadas,
    )


@enrutador.post("/courses/{id_curso}/start-session", response_model=SesionLeer)
def iniciar_sesion_curso(
    id_curso: int,
    carga: SolicitudIniciarSesionCurso | None = Body(default=None),
    usuario_actual: Usuario = Depends(requerir_roles("superadmin", "org_admin", "teacher")),
    sesion_bd: Session = Depends(obtener_bd),
) -> SesionLeer:
    """Inicia en 1 clic (o recupera si ya está abierta) la sesión de pase de lista de un curso."""
    asignacion = _cargar_curso_o_404(sesion_bd, id_curso)
    validar_acceso_organizacion(usuario_actual, asignacion.id_organizacion)

    if usuario_actual.rol == "teacher" and asignacion.id_usuario_docente != usuario_actual.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el profesor asignado o un administrador pueden iniciar esta sesión.",
        )

    fecha_objetivo = (carga.fecha_sesion if carga and carga.fecha_sesion else None) or date.today()
    id_horario = carga.id_horario if carga else None
    sesion = iniciar_o_obtener_sesion_curso(
        sesion_bd,
        asignacion=asignacion,
        fecha_objetivo=fecha_objetivo,
        id_horario=id_horario,
    )
    return serializar_sesiones_lote(sesion_bd, [sesion], asignacion.id_organizacion)[0]


@enrutador.get("/teacher/agenda", response_model=RespuestaAgendaDocente)
def obtener_agenda_docente(
    id_organizacion: int | None = Query(default=None),
    fecha_objetivo: date | None = Query(default=None),
    hora_actual: str | None = Query(default=None, pattern=r"^\d{2}:\d{2}$"),
    id_usuario_docente: int | None = Query(default=None),
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    sesion_bd: Session = Depends(obtener_bd),
) -> RespuestaAgendaDocente:
    """Devuelve la agenda diaria del profesor ('Tu clase ahora') con aislamiento estricto."""
    id_org_alcance = resolver_alcance_organizacion(usuario_actual, id_organizacion)

    if usuario_actual.rol == "teacher":
        if id_usuario_docente is not None and id_usuario_docente != usuario_actual.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo puedes consultar tu propia agenda docente.",
            )
        id_docente_resuelto = usuario_actual.id
    else:
        id_docente_resuelto = (
            id_usuario_docente if id_usuario_docente is not None else usuario_actual.id
        )

    fecha_resuelta = fecha_objetivo or date.today()
    hora_resuelta = hora_actual or datetime.now().strftime("%H:%M")
    return construir_agenda_docente(
        sesion_bd,
        id_organizacion=id_org_alcance,
        id_usuario_docente=id_docente_resuelto,
        fecha_objetivo=fecha_resuelta,
        hora_actual_texto=hora_resuelta,
    )


# ==============================================================================
# Estadísticas administrativas (exclusivas para Superadmin / Org Admin)
# ==============================================================================
@enrutador.get("/stats", response_model=RespuestaEstadisticasAcademicas)
def obtener_estadisticas_academicas(
    id_organizacion: int | None = Query(default=None),
    fecha_desde: date | None = Query(default=None),
    fecha_hasta: date | None = Query(default=None),
    id_carrera: int | None = Query(default=None),
    id_grupo: int | None = Query(default=None),
    usuario_actual: Usuario = Depends(requerir_roles("superadmin", "org_admin")),
    sesion_bd: Session = Depends(obtener_bd),
) -> RespuestaEstadisticasAcademicas:
    """Consolida métricas escolares por asignatura, grupo y alumno en un rango de fechas."""
    id_org_alcance = resolver_alcance_organizacion(usuario_actual, id_organizacion)
    return calcular_estadisticas_academicas(
        sesion_bd,
        id_organizacion=id_org_alcance,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        id_carrera=id_carrera,
        id_grupo=id_grupo,
    )
