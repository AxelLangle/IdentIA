"""Servicio de lógica académica para el dominio educativo de IdentIA.

Implementa el aislamiento estricto por docente, validación de horarios semanales,
serialización por lotes libre de N+1, generación idempotente de sesiones de clase,
construcción de la agenda diaria ("Tu clase ahora") y cálculo de estadísticas por
asignatura, grupo y alumno.
"""

from collections import defaultdict
from datetime import date, datetime
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AsignacionCurso,
    Carrera,
    EventoAsistencia,
    Grupo,
    HorarioClase,
    Organizacion,
    Persona,
    PersonaGrupo,
    SesionAsistencia,
    TurnoLaboral,
    Usuario,
)
from app.schemas import (
    AsignacionCursoLeer,
    BloqueAgendaDocente,
    EstadisticaAsistenciaAlumnoGrupo,
    EstadisticaAsistenciaGrupo,
    EstadisticaAsistenciaMateria,
    HorarioClaseLeer,
    RespuestaAgendaDocente,
    RespuestaEstadisticasAcademicas,
    ResumenEstadisticasAcademicas,
    SesionLeer,
)


def obtener_ids_cursos_docente(sesion_bd: Session, id_usuario_docente: int) -> set[int]:
    """Devuelve el conjunto de IDs de asignaciones activas que imparte un docente."""
    filas = sesion_bd.scalars(
        select(AsignacionCurso.id).where(
            AsignacionCurso.id_usuario_docente == id_usuario_docente,
            AsignacionCurso.esta_activo.is_(True),
        )
    ).all()
    return set(filas)


def obtener_ids_grupos_docente(sesion_bd: Session, id_usuario_docente: int) -> set[int]:
    """Devuelve los IDs de grupos donde el docente imparte al menos una asignatura activa."""
    filas = sesion_bd.scalars(
        select(AsignacionCurso.id_grupo)
        .where(
            AsignacionCurso.id_usuario_docente == id_usuario_docente,
            AsignacionCurso.esta_activo.is_(True),
        )
        .distinct()
    ).all()
    return set(filas)


def validar_acceso_docente_sesion(
    sesion_bd: Session,
    usuario_actual: Usuario,
    sesion: SesionAsistencia,
) -> None:
    """Impide que un docente consulte o modifique sesiones de asignaturas ajenas."""
    if usuario_actual.rol != "teacher":
        return
    cursos_docente = obtener_ids_cursos_docente(sesion_bd, usuario_actual.id)
    if sesion.id_asignacion_curso is None or sesion.id_asignacion_curso not in cursos_docente:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo puedes operar sesiones de tus materias asignadas.",
        )


def validar_horarios_clase(hora_inicio: str, hora_fin: str) -> None:
    """Valida formato HH:MM y verifica que la hora de inicio sea anterior a la de fin."""
    try:
        hora_ini, min_ini = (int(parte) for parte in hora_inicio.split(":"))
        hora_ter, min_ter = (int(parte) for parte in hora_fin.split(":"))
    except ValueError as excepcion:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato de horario inválido. Usa HH:MM.",
        ) from excepcion

    if not (0 <= hora_ini <= 23 and 0 <= min_ini <= 59 and 0 <= hora_ter <= 23 and 0 <= min_ter <= 59):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Las horas deben estar entre 00:00 y 23:59.",
        )
    if (hora_ini, min_ini) >= (hora_ter, min_ter):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La hora de inicio de clase debe ser anterior a la hora de fin.",
        )


def _contar_alumnos_por_grupo(sesion_bd: Session, id_organizacion: int) -> dict[int, int]:
    """Cuenta alumnos activos (excluyendo docentes) inscritos en cada grupo."""
    filas = sesion_bd.execute(
        select(PersonaGrupo.id_grupo, func.count(PersonaGrupo.id_persona))
        .join(Persona, Persona.id == PersonaGrupo.id_persona)
        .where(
            Persona.id_organizacion == id_organizacion,
            Persona.esta_activo.is_(True),
            Persona.rol != "teacher",
        )
        .group_by(PersonaGrupo.id_grupo)
    ).all()
    return {id_grupo: int(conteo) for id_grupo, conteo in filas}


def serializar_cursos_lote(
    sesion_bd: Session,
    cursos: list[AsignacionCurso],
    id_organizacion: int,
) -> list[AsignacionCursoLeer]:
    """Serializa una lista de asignaciones de curso evitando consultas N+1."""
    if not cursos:
        return []

    conteo_estudiantes = _contar_alumnos_por_grupo(sesion_bd, id_organizacion)
    organizacion = sesion_bd.get(Organizacion, id_organizacion)
    tipo_periodo_org = organizacion.tipo_periodo_academico if organizacion else "semestral"
    mapa_carreras = {
        carrera.id: carrera
        for carrera in sesion_bd.scalars(
            select(Carrera).where(Carrera.id_organizacion == id_organizacion)
        ).all()
    }

    resultado: list[AsignacionCursoLeer] = []
    for curso in cursos:
        horarios_ordenados = sorted(
            curso.horarios,
            key=lambda horario: (horario.dia_semana, horario.hora_inicio, horario.id),
        )
        id_carrera = curso.grupo.id_carrera if curso.grupo else None
        carrera = mapa_carreras.get(id_carrera) if id_carrera else None
        # Herencia de tipo de periodo: grupo -> carrera -> organización
        tipo_periodo_efectivo = (
            (curso.grupo.tipo_periodo if curso.grupo else None)
            or (carrera.tipo_periodo if carrera and carrera.tipo_periodo else None)
            or tipo_periodo_org
        )
        resultado.append(
            AsignacionCursoLeer(
                id=curso.id,
                id_organizacion=curso.id_organizacion,
                id_grupo=curso.id_grupo,
                nombre_grupo=curso.grupo.nombre if curso.grupo else "",
                codigo_grupo=curso.grupo.codigo if curso.grupo else "",
                aula_defecto_grupo=curso.grupo.aula_defecto if curso.grupo else None,
                semestre=curso.grupo.semestre if curso.grupo else None,
                tipo_periodo=tipo_periodo_efectivo,
                id_carrera=id_carrera,
                nombre_carrera=carrera.nombre if carrera else None,
                id_materia=curso.id_materia,
                nombre_materia=curso.materia.nombre if curso.materia else "",
                codigo_materia=curso.materia.codigo if curso.materia else "",
                id_usuario_docente=curso.id_usuario_docente,
                nombre_docente=curso.docente.nombre_completo if curso.docente else None,
                correo_docente=curso.docente.correo if curso.docente else None,
                periodo_lectivo=curso.periodo_lectivo,
                esta_activo=curso.esta_activo,
                cantidad_estudiantes=conteo_estudiantes.get(curso.id_grupo, 0),
                horarios=[
                    HorarioClaseLeer(
                        id=horario.id,
                        id_asignacion_curso=horario.id_asignacion_curso,
                        dia_semana=horario.dia_semana,
                        hora_inicio=horario.hora_inicio,
                        hora_fin=horario.hora_fin,
                        aula=horario.aula,
                        creado_en=horario.creado_en,
                    )
                    for horario in horarios_ordenados
                ],
                creado_en=curso.creado_en,
            )
        )
    return resultado


def serializar_sesiones_lote(
    sesion_bd: Session,
    sesiones: list[SesionAsistencia],
    id_organizacion: int,
) -> list[SesionLeer]:
    """Serializa sesiones con metadatos de grupo, asignatura, carrera, profesor y turno."""
    if not sesiones:
        return []

    ids_sesiones = [sesion.id for sesion in sesiones]
    conteo_eventos = {
        id_sesion: int(conteo)
        for id_sesion, conteo in sesion_bd.execute(
            select(EventoAsistencia.id_sesion, func.count(EventoAsistencia.id))
            .where(EventoAsistencia.id_sesion.in_(ids_sesiones))
            .group_by(EventoAsistencia.id_sesion)
        ).all()
    }
    mapa_grupos = {
        grupo.id: grupo
        for grupo in sesion_bd.scalars(
            select(Grupo).where(Grupo.id_organizacion == id_organizacion)
        ).all()
    }
    mapa_carreras = {
        carrera.id: carrera.nombre
        for carrera in sesion_bd.scalars(
            select(Carrera).where(Carrera.id_organizacion == id_organizacion)
        ).all()
    }
    mapa_turnos = {
        turno.id: turno
        for turno in sesion_bd.scalars(
            select(TurnoLaboral).where(TurnoLaboral.id_organizacion == id_organizacion)
        ).all()
    }

    ids_cursos = [
        sesion.id_asignacion_curso
        for sesion in sesiones
        if sesion.id_asignacion_curso is not None
    ]
    mapa_cursos: dict[int, AsignacionCurso] = {}
    if ids_cursos:
        cursos_cargados = sesion_bd.scalars(
            select(AsignacionCurso)
            .options(
                selectinload(AsignacionCurso.materia),
                selectinload(AsignacionCurso.grupo),
                selectinload(AsignacionCurso.docente),
            )
            .where(AsignacionCurso.id.in_(ids_cursos))
        ).all()
        mapa_cursos = {curso.id: curso for curso in cursos_cargados}

    resultado: list[SesionLeer] = []
    for sesion in sesiones:
        grupo = mapa_grupos.get(sesion.id_grupo) if sesion.id_grupo else None
        curso = mapa_cursos.get(sesion.id_asignacion_curso) if sesion.id_asignacion_curso else None
        turno = mapa_turnos.get(sesion.id_turno_laboral) if sesion.id_turno_laboral else None

        id_carrera = (
            grupo.id_carrera
            if grupo
            else (curso.grupo.id_carrera if curso and curso.grupo else None)
        )
        if id_carrera is None and curso and curso.materia:
            id_carrera = curso.materia.id_carrera

        resultado.append(
            SesionLeer(
                id=sesion.id,
                id_organizacion=sesion.id_organizacion,
                id_grupo=sesion.id_grupo,
                nombre_grupo=(
                    grupo.nombre
                    if grupo
                    else (curso.grupo.nombre if curso and curso.grupo else None)
                ),
                id_asignacion_curso=sesion.id_asignacion_curso,
                id_horario=sesion.id_horario,
                id_turno_laboral=sesion.id_turno_laboral,
                nombre_turno_laboral=turno.nombre if turno else None,
                codigo_turno_laboral=turno.codigo if turno else None,
                turno_cruza_medianoche=turno.cruza_medianoche if turno else False,
                nombre_materia=curso.materia.nombre if curso and curso.materia else None,
                codigo_materia=curso.materia.codigo if curso and curso.materia else None,
                nombre_carrera=mapa_carreras.get(id_carrera) if id_carrera else None,
                nombre_docente=curso.docente.nombre_completo if curso and curso.docente else None,
                titulo=sesion.titulo,
                fecha_sesion=sesion.fecha_sesion,
                tipo_sesion=sesion.tipo_sesion,
                hora_inicio_esperada=sesion.hora_inicio_esperada,
                estado=sesion.estado,
                creado_en=sesion.creado_en,
                cerrado_en=sesion.cerrado_en,
                cantidad_eventos=conteo_eventos.get(sesion.id, 0),
            )
        )
    return resultado


def generar_sesiones_para_fecha(
    sesion_bd: Session,
    *,
    id_organizacion: int,
    fecha_objetivo: date,
    id_asignacion_curso: int | None = None,
    id_usuario_docente: int | None = None,
) -> tuple[int, int, list[SesionAsistencia]]:
    """Genera de forma idempotente sesiones académicas para los horarios del día indicado."""
    dia_semana = fecha_objetivo.weekday()
    consulta = (
        select(AsignacionCurso)
        .options(
            selectinload(AsignacionCurso.materia),
            selectinload(AsignacionCurso.grupo),
            selectinload(AsignacionCurso.horarios),
        )
        .where(
            AsignacionCurso.id_organizacion == id_organizacion,
            AsignacionCurso.esta_activo.is_(True),
        )
    )
    if id_asignacion_curso is not None:
        consulta = consulta.where(AsignacionCurso.id == id_asignacion_curso)
    if id_usuario_docente is not None:
        consulta = consulta.where(AsignacionCurso.id_usuario_docente == id_usuario_docente)

    cursos = list(sesion_bd.scalars(consulta).all())
    if not cursos:
        return 0, 0, []

    ids_cursos = [curso.id for curso in cursos]
    sesiones_existentes = list(
        sesion_bd.scalars(
            select(SesionAsistencia).where(
                SesionAsistencia.id_organizacion == id_organizacion,
                SesionAsistencia.fecha_sesion == fecha_objetivo,
                SesionAsistencia.id_asignacion_curso.in_(ids_cursos),
            )
        ).all()
    )
    existentes_por_bloque: dict[tuple[int, int], SesionAsistencia] = {
        (sesion.id_asignacion_curso, sesion.id_horario): sesion
        for sesion in sesiones_existentes
        if sesion.id_asignacion_curso is not None and sesion.id_horario is not None
    }

    cantidad_creadas = 0
    cantidad_existentes = 0
    sesiones_resultantes: list[SesionAsistencia] = []

    for curso in cursos:
        bloques_del_dia = sorted(
            [horario for horario in curso.horarios if horario.dia_semana == dia_semana],
            key=lambda horario: (horario.hora_inicio, horario.id),
        )
        for bloque in bloques_del_dia:
            clave = (curso.id, bloque.id)
            if clave in existentes_por_bloque:
                cantidad_existentes += 1
                sesiones_resultantes.append(existentes_por_bloque[clave])
                continue

            etiqueta_materia = curso.materia.nombre if curso.materia else "Clase"
            etiqueta_grupo = curso.grupo.nombre if curso.grupo else "Grupo"
            nueva_sesion = SesionAsistencia(
                id_organizacion=id_organizacion,
                id_grupo=curso.id_grupo,
                id_asignacion_curso=curso.id,
                id_horario=bloque.id,
                titulo=f"{etiqueta_materia} — {etiqueta_grupo} ({bloque.hora_inicio}-{bloque.hora_fin})",
                fecha_sesion=fecha_objetivo,
                tipo_sesion="class",
                hora_inicio_esperada=bloque.hora_inicio,
                estado="open",
            )
            sesion_bd.add(nueva_sesion)
            cantidad_creadas += 1
            sesiones_resultantes.append(nueva_sesion)

    if cantidad_creadas > 0:
        sesion_bd.commit()
        for sesion in sesiones_resultantes:
            sesion_bd.refresh(sesion)

    return cantidad_creadas, cantidad_existentes, sesiones_resultantes


def iniciar_o_obtener_sesion_curso(
    sesion_bd: Session,
    *,
    asignacion: AsignacionCurso,
    fecha_objetivo: date,
    id_horario: int | None = None,
) -> SesionAsistencia:
    """Obtiene la sesión abierta del curso para hoy o crea una lista para el kiosco."""
    horario_seleccionado: HorarioClase | None = None
    if id_horario is not None:
        horario_seleccionado = sesion_bd.get(HorarioClase, id_horario)
        if (
            horario_seleccionado is None
            or horario_seleccionado.id_asignacion_curso != asignacion.id
        ):
            raise HTTPException(
                status_code=404,
                detail="Horario no encontrado para la asignatura seleccionada.",
            )
        sesion_bloque_abierta = sesion_bd.scalars(
            select(SesionAsistencia)
            .where(
                SesionAsistencia.id_asignacion_curso == asignacion.id,
                SesionAsistencia.id_horario == horario_seleccionado.id,
                SesionAsistencia.fecha_sesion == fecha_objetivo,
                SesionAsistencia.estado == "open",
            )
            .order_by(SesionAsistencia.id.desc())
        ).first()
        if sesion_bloque_abierta is not None:
            return sesion_bloque_abierta
    else:
        sesion_abierta = sesion_bd.scalars(
            select(SesionAsistencia)
            .where(
                SesionAsistencia.id_asignacion_curso == asignacion.id,
                SesionAsistencia.fecha_sesion == fecha_objetivo,
                SesionAsistencia.estado == "open",
            )
            .order_by(SesionAsistencia.id.desc())
        ).first()
        if sesion_abierta is not None:
            return sesion_abierta

        dia_semana = fecha_objetivo.weekday()
        bloques_del_dia = sorted(
            [horario for horario in asignacion.horarios if horario.dia_semana == dia_semana],
            key=lambda horario: horario.hora_inicio,
        )
        if bloques_del_dia:
            horario_seleccionado = bloques_del_dia[0]

    etiqueta_materia = asignacion.materia.nombre if asignacion.materia else "Materia"
    etiqueta_grupo = asignacion.grupo.nombre if asignacion.grupo else "Grupo"
    if horario_seleccionado is not None:
        titulo = (
            f"{etiqueta_materia} — {etiqueta_grupo} "
            f"({horario_seleccionado.hora_inicio}-{horario_seleccionado.hora_fin})"
        )
        inicio_esperado = horario_seleccionado.hora_inicio
        id_horario_resuelto = horario_seleccionado.id
    else:
        titulo = f"{etiqueta_materia} — {etiqueta_grupo} ({fecha_objetivo.isoformat()})"
        inicio_esperado = asignacion.grupo.hora_inicio_horario if asignacion.grupo else None
        id_horario_resuelto = None

    nueva_sesion = SesionAsistencia(
        id_organizacion=asignacion.id_organizacion,
        id_grupo=asignacion.id_grupo,
        id_asignacion_curso=asignacion.id,
        id_horario=id_horario_resuelto,
        titulo=titulo,
        fecha_sesion=fecha_objetivo,
        tipo_sesion="class",
        hora_inicio_esperada=inicio_esperado,
        estado="open",
    )
    sesion_bd.add(nueva_sesion)
    sesion_bd.commit()
    sesion_bd.refresh(nueva_sesion)
    return nueva_sesion


def construir_agenda_docente(
    sesion_bd: Session,
    *,
    id_organizacion: int,
    id_usuario_docente: int,
    fecha_objetivo: date,
    hora_actual_texto: str,
) -> RespuestaAgendaDocente:
    """Construye la agenda diaria y lista de asignaturas del profesor para la jornada actual."""
    cursos = list(
        sesion_bd.scalars(
            select(AsignacionCurso)
            .options(
                selectinload(AsignacionCurso.materia),
                selectinload(AsignacionCurso.grupo),
                selectinload(AsignacionCurso.docente),
                selectinload(AsignacionCurso.horarios),
            )
            .where(
                AsignacionCurso.id_organizacion == id_organizacion,
                AsignacionCurso.id_usuario_docente == id_usuario_docente,
                AsignacionCurso.esta_activo.is_(True),
            )
            .order_by(AsignacionCurso.id.asc())
        ).all()
    )
    cursos_serializados = serializar_cursos_lote(sesion_bd, cursos, id_organizacion)
    mapa_cursos_leidos = {curso.id: curso for curso in cursos_serializados}

    ids_cursos = [curso.id for curso in cursos]
    sesiones_dia: list[SesionAsistencia] = []
    if ids_cursos:
        sesiones_dia = list(
            sesion_bd.scalars(
                select(SesionAsistencia)
                .where(
                    SesionAsistencia.id_organizacion == id_organizacion,
                    SesionAsistencia.fecha_sesion == fecha_objetivo,
                    SesionAsistencia.id_asignacion_curso.in_(ids_cursos),
                )
                .order_by(SesionAsistencia.id.desc())
            ).all()
        )
    sesiones_serializadas = serializar_sesiones_lote(sesion_bd, sesiones_dia, id_organizacion)

    sesion_por_horario: dict[int, SesionLeer] = {}
    sesion_por_curso: dict[int, SesionLeer] = {}
    for sesion in sesiones_serializadas:
        if sesion.id_horario is not None:
            previa = sesion_por_horario.get(sesion.id_horario)
            if previa is None or (previa.estado != "open" and sesion.estado == "open"):
                sesion_por_horario[sesion.id_horario] = sesion
        if sesion.id_asignacion_curso is not None:
            previa_curso = sesion_por_curso.get(sesion.id_asignacion_curso)
            if previa_curso is None or (previa_curso.estado != "open" and sesion.estado == "open"):
                sesion_por_curso[sesion.id_asignacion_curso] = sesion

    dia_semana = fecha_objetivo.weekday()
    bloques_hoy: list[BloqueAgendaDocente] = []
    for curso in cursos:
        curso_leido = mapa_cursos_leidos[curso.id]
        for horario in curso.horarios:
            if horario.dia_semana != dia_semana:
                continue
            if horario.hora_inicio <= hora_actual_texto <= horario.hora_fin:
                estado_bloque = "in_progress"
            elif hora_actual_texto < horario.hora_inicio:
                estado_bloque = "upcoming"
            else:
                estado_bloque = "finished"

            sesion_vinculada = (
                sesion_por_horario.get(horario.id) or sesion_por_curso.get(curso.id)
            )
            bloques_hoy.append(
                BloqueAgendaDocente(
                    id_horario=horario.id,
                    id_asignacion_curso=curso.id,
                    nombre_materia=curso_leido.nombre_materia,
                    codigo_materia=curso_leido.codigo_materia,
                    id_grupo=curso_leido.id_grupo,
                    nombre_grupo=curso_leido.nombre_grupo,
                    codigo_grupo=curso_leido.codigo_grupo,
                    nombre_carrera=curso_leido.nombre_carrera,
                    dia_semana=horario.dia_semana,
                    hora_inicio=horario.hora_inicio,
                    hora_fin=horario.hora_fin,
                    aula=horario.aula,
                    estado_bloque=estado_bloque,
                    cantidad_estudiantes=curso_leido.cantidad_estudiantes,
                    sesion=sesion_vinculada,
                )
            )

    bloques_hoy.sort(key=lambda bloque: (bloque.hora_inicio, bloque.hora_fin, bloque.id_horario))

    # Selecciona primero la clase en curso; si no hay ninguna, la próxima clase del día
    bloque_actual = next(
        (bloque for bloque in bloques_hoy if bloque.estado_bloque == "in_progress"),
        None,
    )
    if bloque_actual is None:
        bloque_actual = next(
            (bloque for bloque in bloques_hoy if bloque.estado_bloque == "upcoming"),
            None,
        )

    return RespuestaAgendaDocente(
        fecha_objetivo=fecha_objetivo,
        hora_actual=hora_actual_texto,
        bloque_actual=bloque_actual,
        bloques_hoy=bloques_hoy,
        cursos=cursos_serializados,
    )


def calcular_estadisticas_academicas(
    sesion_bd: Session,
    *,
    id_organizacion: int,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    id_carrera: int | None = None,
    id_grupo: int | None = None,
) -> RespuestaEstadisticasAcademicas:
    """Calcula estadísticas académicas por asignatura y consolidadas por grupo y alumno."""
    organizacion = sesion_bd.get(Organizacion, id_organizacion)
    tipo_periodo_org = organizacion.tipo_periodo_academico if organizacion else "semestral"

    from app.models import Materia  # import local para mantener encabezado limpio

    carreras = list(
        sesion_bd.scalars(
            select(Carrera).where(Carrera.id_organizacion == id_organizacion)
        ).all()
    )
    mapa_objetos_carrera = {carrera.id: carrera for carrera in carreras}
    mapa_nombres_carrera = {carrera.id: carrera.nombre for carrera in carreras}

    consulta_grupos = (
        select(Grupo)
        .where(Grupo.id_organizacion == id_organizacion)
        .order_by(Grupo.nombre.asc())
    )
    if id_carrera is not None:
        consulta_grupos = consulta_grupos.where(Grupo.id_carrera == id_carrera)
    if id_grupo is not None:
        consulta_grupos = consulta_grupos.where(Grupo.id == id_grupo)
    grupos = list(sesion_bd.scalars(consulta_grupos).all())
    mapa_grupos = {grupo.id: grupo for grupo in grupos}
    ids_grupos_filtrados = set(mapa_grupos.keys())

    materias = list(
        sesion_bd.scalars(
            select(Materia).where(Materia.id_organizacion == id_organizacion)
        ).all()
    )

    cursos = list(
        sesion_bd.scalars(
            select(AsignacionCurso)
            .options(
                selectinload(AsignacionCurso.materia),
                selectinload(AsignacionCurso.grupo),
                selectinload(AsignacionCurso.docente),
            )
            .where(AsignacionCurso.id_organizacion == id_organizacion)
            .order_by(AsignacionCurso.id.asc())
        ).all()
    )
    if ids_grupos_filtrados or id_carrera is not None or id_grupo is not None:
        cursos = [curso for curso in cursos if curso.id_grupo in ids_grupos_filtrados]

    # Alumnos activos agrupados por grupo escolar
    alumnos_por_grupo: dict[int, list[Persona]] = defaultdict(list)
    if ids_grupos_filtrados:
        filas_alumnos = sesion_bd.execute(
            select(PersonaGrupo.id_grupo, Persona)
            .join(Persona, Persona.id == PersonaGrupo.id_persona)
            .where(
                PersonaGrupo.id_grupo.in_(ids_grupos_filtrados),
                Persona.id_organizacion == id_organizacion,
                Persona.esta_activo.is_(True),
                Persona.rol != "teacher",
            )
            .order_by(Persona.nombre_completo.asc())
        ).all()
        for gid, alumno in filas_alumnos:
            alumnos_por_grupo[gid].append(alumno)

    ids_cursos = [curso.id for curso in cursos]
    sesiones_por_curso: dict[int, list[SesionAsistencia]] = defaultdict(list)
    ids_sesiones: list[int] = []
    if ids_cursos:
        consulta_sesiones = select(SesionAsistencia).where(
            SesionAsistencia.id_organizacion == id_organizacion,
            SesionAsistencia.id_asignacion_curso.in_(ids_cursos),
        )
        if fecha_desde is not None:
            consulta_sesiones = consulta_sesiones.where(
                SesionAsistencia.fecha_sesion >= fecha_desde
            )
        if fecha_hasta is not None:
            consulta_sesiones = consulta_sesiones.where(
                SesionAsistencia.fecha_sesion <= fecha_hasta
            )
        sesiones = list(sesion_bd.scalars(consulta_sesiones).all())
        for sesion in sesiones:
            if sesion.id_asignacion_curso is not None:
                sesiones_por_curso[sesion.id_asignacion_curso].append(sesion)
                ids_sesiones.append(sesion.id)

    # Mapeo único `(id_sesion, id_persona) -> estado` conservando el primer evento de la sesión
    mapa_estado_evento: dict[tuple[int, int], str] = {}
    if ids_sesiones:
        eventos = list(
            sesion_bd.scalars(
                select(EventoAsistencia)
                .where(EventoAsistencia.id_sesion.in_(ids_sesiones))
                .order_by(EventoAsistencia.id.asc())
            ).all()
        )
        for evento in eventos:
            clave = (evento.id_sesion, evento.id_persona)
            if clave not in mapa_estado_evento:
                mapa_estado_evento[clave] = evento.estado

    por_materia: list[EstadisticaAsistenciaMateria] = []
    cursos_por_grupo: dict[int, list[AsignacionCurso]] = defaultdict(list)

    for curso in cursos:
        cursos_por_grupo[curso.id_grupo].append(curso)
        alumnos_grupo = alumnos_por_grupo.get(curso.id_grupo, [])
        ids_alumnos = [alumno.id for alumno in alumnos_grupo]
        sesiones_curso = sesiones_por_curso.get(curso.id, [])

        cantidad_sesiones = len(sesiones_curso)
        inscritos = len(ids_alumnos)
        esperados = cantidad_sesiones * inscritos

        asistencias = 0
        puntuales = 0
        retardos = 0
        manuales = 0
        for sesion in sesiones_curso:
            for id_alumno in ids_alumnos:
                estado_ev = mapa_estado_evento.get((sesion.id, id_alumno))
                if estado_ev is not None:
                    asistencias += 1
                    if estado_ev == "on_time":
                        puntuales += 1
                    elif estado_ev == "late":
                        retardos += 1
                    elif estado_ev == "manual":
                        manuales += 1

        faltas = max(0, esperados - asistencias)
        tasa = round((asistencias / esperados) * 100.0, 2) if esperados > 0 else 0.0
        cid = curso.grupo.id_carrera if curso.grupo else None
        carrera_obj = mapa_objetos_carrera.get(cid) if cid else None
        tipo_periodo_materia = (
            (curso.grupo.tipo_periodo if curso.grupo else None)
            or (carrera_obj.tipo_periodo if carrera_obj and carrera_obj.tipo_periodo else None)
            or tipo_periodo_org
        )

        por_materia.append(
            EstadisticaAsistenciaMateria(
                id_asignacion_curso=curso.id,
                id_materia=curso.id_materia,
                nombre_materia=curso.materia.nombre if curso.materia else "",
                codigo_materia=curso.materia.codigo if curso.materia else "",
                id_grupo=curso.id_grupo,
                nombre_grupo=curso.grupo.nombre if curso.grupo else "",
                codigo_grupo=curso.grupo.codigo if curso.grupo else "",
                id_carrera=cid,
                nombre_carrera=mapa_nombres_carrera.get(cid) if cid else None,
                semestre=curso.grupo.semestre if curso.grupo else None,
                tipo_periodo=tipo_periodo_materia,
                nombre_docente=curso.docente.nombre_completo if curso.docente else None,
                cantidad_sesiones=cantidad_sesiones,
                estudiantes_inscritos=inscritos,
                registros_esperados=esperados,
                cantidad_asistencias=asistencias,
                cantidad_puntuales=puntuales,
                cantidad_retardos=retardos,
                cantidad_manuales=manuales,
                cantidad_faltas=faltas,
                tasa_asistencia=tasa,
            )
        )

    por_grupo: list[EstadisticaAsistenciaGrupo] = []
    gran_total_esperados = 0
    gran_total_asistencias = 0
    gran_total_sesiones = 0

    for grupo in grupos:
        cursos_grupo = cursos_por_grupo.get(grupo.id, [])
        alumnos_grupo = alumnos_por_grupo.get(grupo.id, [])
        todas_sesiones_grupo: list[SesionAsistencia] = []
        for curso in cursos_grupo:
            todas_sesiones_grupo.extend(sesiones_por_curso.get(curso.id, []))

        total_sesiones = len(todas_sesiones_grupo)
        total_esperados = total_sesiones * len(alumnos_grupo)
        total_asistencias = 0
        total_puntuales = 0
        total_retardos = 0
        desglose_estudiantes: list[EstadisticaAsistenciaAlumnoGrupo] = []

        for alumno in alumnos_grupo:
            al_asistencias = 0
            al_puntuales = 0
            al_retardos = 0
            for sesion in todas_sesiones_grupo:
                estado_ev = mapa_estado_evento.get((sesion.id, alumno.id))
                if estado_ev is not None:
                    al_asistencias += 1
                    if estado_ev == "on_time":
                        al_puntuales += 1
                    elif estado_ev == "late":
                        al_retardos += 1
            al_faltas = max(0, total_sesiones - al_asistencias)
            al_tasa = (
                round((al_asistencias / total_sesiones) * 100.0, 2)
                if total_sesiones > 0
                else 0.0
            )
            total_asistencias += al_asistencias
            total_puntuales += al_puntuales
            total_retardos += al_retardos
            desglose_estudiantes.append(
                EstadisticaAsistenciaAlumnoGrupo(
                    id_persona=alumno.id,
                    identificador_externo=alumno.identificador_externo,
                    nombre_completo=alumno.nombre_completo,
                    registros_esperados=total_sesiones,
                    cantidad_asistencias=al_asistencias,
                    cantidad_puntuales=al_puntuales,
                    cantidad_retardos=al_retardos,
                    cantidad_faltas=al_faltas,
                    tasa_asistencia=al_tasa,
                )
            )

        total_faltas = max(0, total_esperados - total_asistencias)
        tasa_grupo = (
            round((total_asistencias / total_esperados) * 100.0, 2)
            if total_esperados > 0
            else 0.0
        )
        gran_total_esperados += total_esperados
        gran_total_asistencias += total_asistencias
        gran_total_sesiones += total_sesiones

        carrera_grupo = mapa_objetos_carrera.get(grupo.id_carrera) if grupo.id_carrera else None
        tipo_periodo_grupo = (
            grupo.tipo_periodo
            or (
                carrera_grupo.tipo_periodo
                if carrera_grupo and carrera_grupo.tipo_periodo
                else None
            )
            or tipo_periodo_org
        )
        por_grupo.append(
            EstadisticaAsistenciaGrupo(
                id_grupo=grupo.id,
                nombre_grupo=grupo.nombre,
                codigo_grupo=grupo.codigo,
                id_carrera=grupo.id_carrera,
                nombre_carrera=(
                    mapa_nombres_carrera.get(grupo.id_carrera) if grupo.id_carrera else None
                ),
                semestre=grupo.semestre,
                tipo_periodo=tipo_periodo_grupo,
                cantidad_materias=len(cursos_grupo),
                cantidad_estudiantes=len(alumnos_grupo),
                total_sesiones=total_sesiones,
                total_esperados=total_esperados,
                total_asistencias=total_asistencias,
                total_puntuales=total_puntuales,
                total_retardos=total_retardos,
                total_faltas=total_faltas,
                tasa_asistencia_general=tasa_grupo,
                desglose_estudiantes=desglose_estudiantes,
            )
        )

    tasa_global = (
        round((gran_total_asistencias / gran_total_esperados) * 100.0, 2)
        if gran_total_esperados > 0
        else 0.0
    )

    return RespuestaEstadisticasAcademicas(
        id_organizacion=id_organizacion,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        resumen=ResumenEstadisticasAcademicas(
            total_carreras=len(carreras),
            total_grupos=len(grupos),
            total_materias=len(materias),
            total_cursos=len(cursos),
            total_sesiones=gran_total_sesiones,
            tasa_asistencia_general=tasa_global,
        ),
        por_materia=por_materia,
        por_grupo=por_grupo,
    )
