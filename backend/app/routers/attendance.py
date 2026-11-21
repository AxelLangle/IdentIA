"""Enrutador HTTP para sesiones de asistencia, reconocimiento en kiosco y exportación CSV.

Orquesta la apertura y cierre de sesiones, el pipeline de reconocimiento en
memoria RAM (`decode -> detect -> quality -> extract -> 1:N match -> cooldown/reglas`),
el registro manual de respaldo y la descarga de reportes CSV.
"""

from datetime import date, datetime
import time
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import obtener_configuracion
from app.db import obtener_bd
from app.models import (
    AsignacionCurso,
    EventoAsistencia,
    Grupo,
    HorarioClase,
    Organizacion,
    Persona,
    PersonaGrupo,
    SesionAsistencia,
    TurnoLaboral,
    Usuario,
    VectorFacial,
)
from app.routers import convertir_a_esquema_calidad, convertir_a_esquema_cuadro_rostro
from app.schemas import (
    EventoAsistenciaLeer,
    ModoAccion,
    RespuestaReconocerFrame,
    ResumenBrevePersona,
    SesionCrear,
    SesionLeer,
    SolicitudAsistenciaManual,
)
from app.security import (
    obtener_usuario_actual,
    resolver_alcance_organizacion,
    validar_acceso_organizacion,
)
from app.services.academic_service import (
    obtener_ids_cursos_docente,
    serializar_sesiones_lote,
    validar_acceso_docente_sesion,
)
from app.services.attendance_service import (
    exportar_eventos_csv,
    obtener_o_crear_sesion_activa,
    registrar_asistencia_reconocida,
)
from app.services.enterprise_service import resolver_turno_para_asistencia
from app.vision.engine import bytes_a_vector, coincidir_vector, decodificar_bytes_imagen
from app.vision.quality import evaluar_calidad_rostro

enrutador = APIRouter(prefix="/api", tags=["asistencia"])


def _serializar_evento(
    evento: EventoAsistencia,
    persona: Persona,
    sesion: SesionAsistencia,
    nombres_turnos: dict[int, str] | None = None,
) -> EventoAsistenciaLeer:
    """Construye el esquema JSON público de un evento de asistencia."""
    id_turno_resuelto = (
        evento.id_turno_laboral if evento.id_turno_laboral is not None else sesion.id_turno_laboral
    )
    nombre_turno = (
        nombres_turnos.get(id_turno_resuelto)
        if nombres_turnos is not None and id_turno_resuelto is not None
        else None
    )
    if nombre_turno is None and evento.turno_laboral is not None:
        nombre_turno = evento.turno_laboral.nombre
    return EventoAsistenciaLeer(
        id=evento.id,
        id_sesion=evento.id_sesion,
        titulo_sesion=sesion.titulo,
        id_persona=evento.id_persona,
        nombre_persona=persona.nombre_completo,
        identificador_externo_persona=persona.identificador_externo,
        avatar_base64_persona=persona.avatar_base64,
        id_turno_laboral=evento.id_turno_laboral,
        nombre_turno_laboral=nombre_turno,
        tipo_evento=evento.tipo_evento,
        estado=evento.estado,
        puntaje_confianza=evento.puntaje_confianza,
        minutos_trabajados=evento.minutos_trabajados,
        minutos_retardo=evento.minutos_retardo,
        minutos_salida_anticipada=evento.minutos_salida_anticipada,
        modo_captura=evento.modo_captura,
        fecha_hora=evento.fecha_hora,
        notas=evento.notas,
    )


@enrutador.get("/sessions", response_model=list[SesionLeer])
def listar_sesiones(
    id_organizacion: int | None = Query(default=None),
    filtro_estado: str | None = Query(default=None, alias="estado"),
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    sesion_bd: Session = Depends(obtener_bd),
) -> list[SesionLeer]:
    """Lista las sesiones de asistencia de la organización (para docentes, solo sus clases)."""
    id_org_alcance = resolver_alcance_organizacion(usuario_actual, id_organizacion)
    consulta = (
        select(SesionAsistencia)
        .where(SesionAsistencia.id_organizacion == id_org_alcance)
        .order_by(SesionAsistencia.id.desc())
    )
    if usuario_actual.rol == "teacher":
        cursos_docente = obtener_ids_cursos_docente(sesion_bd, usuario_actual.id)
        if not cursos_docente:
            return []
        consulta = consulta.where(SesionAsistencia.id_asignacion_curso.in_(cursos_docente))
    if filtro_estado:
        consulta = consulta.where(SesionAsistencia.estado == filtro_estado)
    sesiones = list(sesion_bd.scalars(consulta).all())
    return serializar_sesiones_lote(sesion_bd, sesiones, id_org_alcance)


@enrutador.post("/sessions", response_model=SesionLeer, status_code=status.HTTP_201_CREATED)
def crear_sesion(
    carga: SesionCrear,
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    sesion_bd: Session = Depends(obtener_bd),
) -> SesionLeer:
    """Crea una sesión de asistencia vinculada a grupo, curso académico o turno laboral."""
    validar_acceso_organizacion(usuario_actual, carga.id_organizacion)
    organizacion = sesion_bd.get(Organizacion, carga.id_organizacion)
    if organizacion is None:
        raise HTTPException(status_code=404, detail="Organización no encontrada.")

    if usuario_actual.rol == "teacher" and carga.id_asignacion_curso is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Un docente debe abrir sesiones vinculadas a una de sus asignaturas.",
        )

    id_grupo_resuelto = carga.id_grupo
    inicio_esperado = carga.hora_inicio_esperada
    tipo_sesion = carga.tipo_sesion or (
        "class" if organizacion.modo == "education" else "workday"
    )

    if carga.id_asignacion_curso is not None:
        asignacion = sesion_bd.scalars(
            select(AsignacionCurso)
            .options(selectinload(AsignacionCurso.grupo))
            .where(AsignacionCurso.id == carga.id_asignacion_curso)
        ).first()
        if asignacion is None or asignacion.id_organizacion != organizacion.id:
            raise HTTPException(status_code=404, detail="Asignación de materia no encontrada.")
        if usuario_actual.rol == "teacher" and asignacion.id_usuario_docente != usuario_actual.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No puedes crear sesiones para una materia de otro profesor.",
            )
        id_grupo_resuelto = asignacion.id_grupo
        tipo_sesion = "class"
        if carga.id_horario is not None:
            horario = sesion_bd.get(HorarioClase, carga.id_horario)
            if horario is None or horario.id_asignacion_curso != asignacion.id:
                raise HTTPException(status_code=404, detail="Horario no encontrado para la materia.")
            if inicio_esperado is None:
                inicio_esperado = horario.hora_inicio
        elif inicio_esperado is None and asignacion.grupo is not None:
            inicio_esperado = asignacion.grupo.hora_inicio_horario
    elif carga.id_turno_laboral is not None:
        turno_laboral = sesion_bd.get(TurnoLaboral, carga.id_turno_laboral)
        if turno_laboral is None or turno_laboral.id_organizacion != organizacion.id:
            raise HTTPException(
                status_code=404,
                detail="Turno laboral no encontrado en la organización.",
            )
        tipo_sesion = "workday"
        if inicio_esperado is None:
            inicio_esperado = turno_laboral.hora_inicio
        if id_grupo_resuelto is not None:
            grupo = sesion_bd.get(Grupo, id_grupo_resuelto)
            if grupo is None or grupo.id_organizacion != organizacion.id:
                raise HTTPException(status_code=404, detail="Grupo no encontrado en la organización.")
    elif id_grupo_resuelto is not None:
        grupo = sesion_bd.get(Grupo, id_grupo_resuelto)
        if grupo is None or grupo.id_organizacion != organizacion.id:
            raise HTTPException(status_code=404, detail="Grupo no encontrado en la organización.")
        if inicio_esperado is None:
            inicio_esperado = grupo.hora_inicio_horario

    sesion = SesionAsistencia(
        id_organizacion=organizacion.id,
        id_grupo=id_grupo_resuelto,
        id_asignacion_curso=carga.id_asignacion_curso,
        id_horario=carga.id_horario,
        id_turno_laboral=carga.id_turno_laboral,
        titulo=carga.titulo.strip(),
        fecha_sesion=carga.fecha_sesion or date.today(),
        tipo_sesion=tipo_sesion,
        hora_inicio_esperada=inicio_esperado,
        estado="open",
    )
    sesion_bd.add(sesion)
    sesion_bd.commit()
    sesion_bd.refresh(sesion)
    return serializar_sesiones_lote(sesion_bd, [sesion], organizacion.id)[0]


@enrutador.post("/sessions/{id_sesion}/close", response_model=SesionLeer)
def cerrar_sesion(
    id_sesion: int,
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    sesion_bd: Session = Depends(obtener_bd),
) -> SesionLeer:
    """Cierra una sesión de asistencia abierta registrando su marca temporal."""
    sesion = sesion_bd.get(SesionAsistencia, id_sesion)
    if sesion is None:
        raise HTTPException(status_code=404, detail="Sesión no encontrada.")
    validar_acceso_organizacion(usuario_actual, sesion.id_organizacion)
    validar_acceso_docente_sesion(sesion_bd, usuario_actual, sesion)

    if sesion.estado != "closed":
        sesion.estado = "closed"
        sesion.cerrado_en = datetime.now()
        sesion_bd.commit()
        sesion_bd.refresh(sesion)

    return serializar_sesiones_lote(sesion_bd, [sesion], sesion.id_organizacion)[0]


@enrutador.post("/attendance/recognize-frame", response_model=RespuestaReconocerFrame)
async def reconocer_frame(
    peticion: Request,
    imagen: UploadFile = File(...),
    id_organizacion: int = Form(...),
    id_sesion: int | None = Form(default=None),
    id_grupo: int | None = Form(default=None),
    modo_accion: ModoAccion = Form(default="auto"),
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    sesion_bd: Session = Depends(obtener_bd),
) -> RespuestaReconocerFrame:
    """Procesa un frame de cámara del kiosco, identifica al sujeto y registra asistencia."""
    tiempo_inicio = time.perf_counter()
    configuracion = obtener_configuracion()

    validar_acceso_organizacion(usuario_actual, id_organizacion)
    organizacion = sesion_bd.get(Organizacion, id_organizacion)
    if organizacion is None:
        raise HTTPException(status_code=404, detail="Organización no encontrada.")

    motor = getattr(peticion.app.state, "motor_biometrico", None)
    if motor is None:
        raise HTTPException(
            status_code=503,
            detail="El motor biométrico no está inicializado en el servidor.",
        )

    if id_sesion is not None:
        sesion = sesion_bd.get(SesionAsistencia, id_sesion)
        if sesion is None or sesion.id_organizacion != organizacion.id:
            raise HTTPException(status_code=404, detail="Sesión no encontrada en la organización.")
        validar_acceso_docente_sesion(sesion_bd, usuario_actual, sesion)
        if sesion.estado != "open":
            raise HTTPException(status_code=400, detail="La sesión seleccionada ya está cerrada.")
    else:
        if usuario_actual.rol == "teacher":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Debes seleccionar una sesión de tu asignatura para tomar asistencia.",
            )
        try:
            sesion = obtener_o_crear_sesion_activa(sesion_bd, organizacion, id_grupo=id_grupo)
        except ValueError as excepcion:
            raise HTTPException(status_code=400, detail=str(excepcion)) from excepcion

    bytes_crudos = await imagen.read()
    try:
        imagen_bgr = decodificar_bytes_imagen(bytes_crudos)
    except ValueError as excepcion:
        raise HTTPException(status_code=400, detail=str(excepcion)) from excepcion

    alto_imagen, ancho_imagen = imagen_bgr.shape[:2]
    detecciones = motor.detectar(imagen_bgr)
    if not detecciones:
        latencia_ms = round((time.perf_counter() - tiempo_inicio) * 1000.0, 2)
        return RespuestaReconocerFrame(
            rostros_detectados=0,
            estado_coincidencia="no_face",
            id_sesion=sesion.id,
            mensaje="No se detectó ningún rostro frente a la cámara.",
            latencia_ms=latencia_ms,
        )

    cuadro_principal, fila_principal = detecciones[0]
    esquema_cuadro = convertir_a_esquema_cuadro_rostro(cuadro_principal, ancho_imagen, alto_imagen)
    calidad = evaluar_calidad_rostro(
        imagen_bgr,
        cuadro_principal,
        tamano_minimo_px=configuracion.tamano_minimo_rostro_kiosco_px,
        nitidez_minima=configuracion.varianza_minima_nitidez_kiosco,
        brillo_minimo=configuracion.brillo_minimo_kiosco,
        brillo_maximo=configuracion.brillo_maximo,
        asimetria_sombra_maxima=configuracion.asimetria_sombra_maxima_kiosco,
        umbral_delta_contraluz=configuracion.umbral_delta_contraluz,
        iluminacion_estricta=False,
    )
    esquema_calidad = convertir_a_esquema_calidad(calidad)

    if not calidad.es_valida:
        latencia_ms = round((time.perf_counter() - tiempo_inicio) * 1000.0, 2)
        return RespuestaReconocerFrame(
            rostros_detectados=len(detecciones),
            estado_coincidencia="low_quality",
            cuadro_rostro=esquema_cuadro,
            calidad=esquema_calidad,
            id_sesion=sesion.id,
            mensaje=calidad.motivo or "Calidad insuficiente para reconocimiento.",
            latencia_ms=latencia_ms,
        )

    vector_consulta = motor.extraer_vector(imagen_bgr, fila_principal)

    id_grupo_efectivo = sesion.id_grupo if sesion.id_grupo is not None else id_grupo
    consulta_galeria = (
        select(Persona.id, Persona.nombre_completo, VectorFacial.bytes_vector)
        .join(VectorFacial, VectorFacial.id_persona == Persona.id)
        .where(
            Persona.id_organizacion == organizacion.id,
            Persona.esta_activo.is_(True),
            Persona.consentimiento_biometrico.is_(True),
            VectorFacial.version_modelo == configuracion.version_modelo,
        )
    )
    if id_grupo_efectivo is not None:
        consulta_galeria = consulta_galeria.join(
            PersonaGrupo, PersonaGrupo.id_persona == Persona.id
        ).where(PersonaGrupo.id_grupo == id_grupo_efectivo)

    filas_galeria = sesion_bd.execute(consulta_galeria).all()
    galeria = [
        (id_per, nombre_per, bytes_a_vector(bytes_vec))
        for id_per, nombre_per, bytes_vec in filas_galeria
    ]

    decision = coincidir_vector(
        vector_consulta,
        galeria,
        umbral=configuracion.umbral_coincidencia,
        margen=configuracion.margen_ambiguedad,
    )

    if decision.estado == "unknown":
        latencia_ms = round((time.perf_counter() - tiempo_inicio) * 1000.0, 2)
        if not galeria:
            mensaje = "No hay personas con biometría registrada en este alcance."
        elif calidad.contraluz_detectado:
            mensaje = (
                "Rostro no reconocido. Se detectó contraluz fuerte; intenta mirar más de frente "
                "o mejorar la luz frontal."
            )
        else:
            mensaje = "Rostro no reconocido en el padrón activo."
        return RespuestaReconocerFrame(
            rostros_detectados=len(detecciones),
            estado_coincidencia="unknown",
            cuadro_rostro=esquema_cuadro,
            calidad=esquema_calidad,
            confianza=round(decision.confianza, 4),
            puntaje_segundo_candidato=(
                round(decision.puntaje_segundo_candidato, 4)
                if decision.puntaje_segundo_candidato is not None
                else None
            ),
            id_sesion=sesion.id,
            mensaje=mensaje,
            latencia_ms=latencia_ms,
        )

    if decision.estado == "ambiguous" or decision.id_persona is None:
        latencia_ms = round((time.perf_counter() - tiempo_inicio) * 1000.0, 2)
        return RespuestaReconocerFrame(
            rostros_detectados=len(detecciones),
            estado_coincidencia="ambiguous",
            cuadro_rostro=esquema_cuadro,
            calidad=esquema_calidad,
            confianza=round(decision.confianza, 4),
            puntaje_segundo_candidato=(
                round(decision.puntaje_segundo_candidato, 4)
                if decision.puntaje_segundo_candidato is not None
                else None
            ),
            id_sesion=sesion.id,
            mensaje="Coincidencia ambigua entre dos personas. Acércate o mejora la iluminación.",
            latencia_ms=latencia_ms,
        )

    persona = sesion_bd.get(Persona, decision.id_persona)
    if persona is None:
        raise HTTPException(status_code=404, detail="Persona reconocida no encontrada.")

    registro = registrar_asistencia_reconocida(
        sesion_bd=sesion_bd,
        organizacion=organizacion,
        sesion=sesion,
        persona=persona,
        puntaje_confianza=decision.confianza,
        modo_accion=modo_accion,
        modo_captura="kiosk_individual",
    )
    latencia_ms = round((time.perf_counter() - tiempo_inicio) * 1000.0, 2)

    evento_serializado = None
    if registro.evento is not None:
        sesion_del_evento = sesion_bd.get(SesionAsistencia, registro.evento.id_sesion) or sesion
        nombres_turnos_ev = (
            {registro.evento.id_turno_laboral: registro.nombre_turno}
            if registro.evento.id_turno_laboral is not None and registro.nombre_turno is not None
            else None
        )
        evento_serializado = _serializar_evento(
            registro.evento, persona, sesion_del_evento, nombres_turnos_ev
        )

    return RespuestaReconocerFrame(
        rostros_detectados=len(detecciones),
        estado_coincidencia="matched",
        cuadro_rostro=esquema_cuadro,
        calidad=esquema_calidad,
        persona=ResumenBrevePersona(
            id=persona.id,
            identificador_externo=persona.identificador_externo,
            nombre_completo=persona.nombre_completo,
            rol=persona.rol,
            avatar_base64=persona.avatar_base64,
        ),
        confianza=round(decision.confianza, 4),
        puntaje_segundo_candidato=(
            round(decision.puntaje_segundo_candidato, 4)
            if decision.puntaje_segundo_candidato is not None
            else None
        ),
        accion_asistencia=registro.accion,
        evento=evento_serializado,
        minutos_trabajados=registro.minutos_trabajados,
        nombre_turno=registro.nombre_turno,
        minutos_retardo=registro.minutos_retardo,
        minutos_salida_anticipada=registro.minutos_salida_anticipada,
        id_sesion=registro.evento.id_sesion if registro.evento else sesion.id,
        mensaje=registro.mensaje,
        latencia_ms=latencia_ms,
    )


@enrutador.get("/attendance/events", response_model=list[EventoAsistenciaLeer])
def listar_eventos_asistencia(
    id_organizacion: int | None = Query(default=None),
    id_sesion: int | None = Query(default=None),
    id_persona: int | None = Query(default=None),
    limite: int = Query(default=100, ge=1, le=500),
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    sesion_bd: Session = Depends(obtener_bd),
) -> list[EventoAsistenciaLeer]:
    """Consulta eventos recientes de asistencia con filtros por sesión, persona o docente."""
    id_org_alcance = resolver_alcance_organizacion(usuario_actual, id_organizacion)
    cursos_docente: set[int] | None = None
    if usuario_actual.rol == "teacher":
        if id_sesion is not None:
            sesion_objetivo = sesion_bd.get(SesionAsistencia, id_sesion)
            if sesion_objetivo is None or sesion_objetivo.id_organizacion != id_org_alcance:
                raise HTTPException(status_code=404, detail="Sesión no encontrada.")
            validar_acceso_docente_sesion(sesion_bd, usuario_actual, sesion_objetivo)
        cursos_docente = obtener_ids_cursos_docente(sesion_bd, usuario_actual.id)
        if not cursos_docente:
            return []

    consulta = (
        select(EventoAsistencia, Persona, SesionAsistencia)
        .join(Persona, Persona.id == EventoAsistencia.id_persona)
        .join(SesionAsistencia, SesionAsistencia.id == EventoAsistencia.id_sesion)
        .where(SesionAsistencia.id_organizacion == id_org_alcance)
        .order_by(EventoAsistencia.fecha_hora.desc(), EventoAsistencia.id.desc())
        .limit(limite)
    )
    if cursos_docente is not None:
        consulta = consulta.where(SesionAsistencia.id_asignacion_curso.in_(cursos_docente))
    if id_sesion is not None:
        consulta = consulta.where(EventoAsistencia.id_sesion == id_sesion)
    if id_persona is not None:
        consulta = consulta.where(EventoAsistencia.id_persona == id_persona)

    filas = sesion_bd.execute(consulta).all()
    nombres_turnos = {
        turno.id: turno.nombre
        for turno in sesion_bd.scalars(
            select(TurnoLaboral).where(TurnoLaboral.id_organizacion == id_org_alcance)
        ).all()
    }
    return [
        _serializar_evento(evento, persona, sesion, nombres_turnos)
        for evento, persona, sesion in filas
    ]


@enrutador.post(
    "/attendance/manual",
    response_model=EventoAsistenciaLeer,
    status_code=status.HTTP_201_CREATED,
)
def crear_asistencia_manual(
    carga: SolicitudAsistenciaManual,
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    sesion_bd: Session = Depends(obtener_bd),
) -> EventoAsistenciaLeer:
    """Registra una asistencia manual de contingencia (con nota obligatoria u opcional)."""
    sesion = sesion_bd.get(SesionAsistencia, carga.id_sesion)
    if sesion is None:
        raise HTTPException(status_code=404, detail="Sesión no encontrada.")
    validar_acceso_organizacion(usuario_actual, sesion.id_organizacion)
    validar_acceso_docente_sesion(sesion_bd, usuario_actual, sesion)

    persona = sesion_bd.get(Persona, carga.id_persona)
    if persona is None or persona.id_organizacion != sesion.id_organizacion:
        raise HTTPException(
            status_code=404,
            detail="Persona no encontrada en la organización de la sesión.",
        )

    if usuario_actual.rol == "teacher" and sesion.id_grupo is not None:
        en_grupo = sesion_bd.scalars(
            select(PersonaGrupo).where(
                PersonaGrupo.id_persona == persona.id,
                PersonaGrupo.id_grupo == sesion.id_grupo,
            )
        ).first()
        if en_grupo is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="El alumno no pertenece al grupo de esta sesión.",
            )

    turno_resuelto = (
        resolver_turno_para_asistencia(sesion_bd, persona, sesion)
        if sesion.tipo_sesion == "workday"
        else None
    )
    evento = EventoAsistencia(
        id_sesion=sesion.id,
        id_persona=persona.id,
        id_turno_laboral=turno_resuelto.id if turno_resuelto else None,
        tipo_evento=carga.tipo_evento,
        estado=carga.estado,
        puntaje_confianza=None,
        modo_captura="manual",
        fecha_hora=datetime.now(),
        notas=carga.notas,
    )
    sesion_bd.add(evento)
    sesion_bd.commit()
    sesion_bd.refresh(evento)
    nombres_turnos = {turno_resuelto.id: turno_resuelto.nombre} if turno_resuelto else None
    return _serializar_evento(evento, persona, sesion, nombres_turnos)


@enrutador.get("/attendance/export.csv")
def exportar_asistencia_csv(
    id_organizacion: int | None = Query(default=None),
    id_sesion: int | None = Query(default=None),
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    sesion_bd: Session = Depends(obtener_bd),
) -> Response:
    """Genera y descarga un archivo CSV compatible con Excel para la organización o sesión."""
    id_org_alcance = resolver_alcance_organizacion(usuario_actual, id_organizacion)
    cursos_docente: set[int] | None = None
    if usuario_actual.rol == "teacher":
        if id_sesion is not None:
            sesion_objetivo = sesion_bd.get(SesionAsistencia, id_sesion)
            if sesion_objetivo is None or sesion_objetivo.id_organizacion != id_org_alcance:
                raise HTTPException(status_code=404, detail="Sesión no encontrada.")
            validar_acceso_docente_sesion(sesion_bd, usuario_actual, sesion_objetivo)
        cursos_docente = obtener_ids_cursos_docente(sesion_bd, usuario_actual.id)

    if cursos_docente is not None and not cursos_docente:
        filas = []
    else:
        consulta = (
            select(EventoAsistencia, Persona, SesionAsistencia)
            .join(Persona, Persona.id == EventoAsistencia.id_persona)
            .join(SesionAsistencia, SesionAsistencia.id == EventoAsistencia.id_sesion)
            .where(SesionAsistencia.id_organizacion == id_org_alcance)
            .order_by(EventoAsistencia.fecha_hora.desc(), EventoAsistencia.id.desc())
        )
        if cursos_docente is not None:
            consulta = consulta.where(SesionAsistencia.id_asignacion_curso.in_(cursos_docente))
        if id_sesion is not None:
            consulta = consulta.where(EventoAsistencia.id_sesion == id_sesion)

        filas = sesion_bd.execute(consulta).all()

    nombres_turnos = {
        turno.id: turno.nombre
        for turno in sesion_bd.scalars(
            select(TurnoLaboral).where(TurnoLaboral.id_organizacion == id_org_alcance)
        ).all()
    }
    contenido_csv = exportar_eventos_csv(
        [(evento, persona, sesion) for evento, persona, sesion in filas],
        nombres_turnos=nombres_turnos,
    )
    return Response(
        content=contenido_csv.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="asistencia_identia.csv"'},
    )
