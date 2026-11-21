"""Enrutador HTTP para padrón de personas, enrolamiento guiado de 6 poses y revocación.

Gestiona el alta y edición de empleados/alumnos, la captura biométrica en memoria
RAM sin almacenar imágenes crudas de entrenamiento (con control estricto de calidad,
iluminación, pose y autoconsistencia) y la revocación individual o por lote protegida
por contraseña administrativa o credencial delegada + bitácora de auditoría.
"""

from datetime import datetime
from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.config import obtener_configuracion
from app.db import obtener_bd
from app.models import (
    Grupo,
    Organizacion,
    Persona,
    PersonaGrupo,
    TurnoLaboral,
    Usuario,
    VectorFacial,
)
from app.routers import convertir_a_esquema_calidad, convertir_a_esquema_cuadro_rostro
from app.schemas import (
    EtiquetaPose,
    OrigenTurno,
    PersonaActualizar,
    PersonaCrear,
    PersonaLeer,
    RespuestaEnrolarFrame,
    RespuestaRevocarBiometria,
    RespuestaRevocarBiometriaLote,
    SolicitudRevocarBiometria,
    SolicitudRevocarBiometriaLote,
)
from app.security import (
    obtener_usuario_actual,
    requerir_roles,
    resolver_alcance_organizacion,
    validar_acceso_organizacion,
)
from app.services.academic_service import obtener_ids_grupos_docente
from app.services.security_service import (
    ResultadoAutorizacion,
    registrar_auditoria,
    verificar_autorizacion_sensible,
)
from app.vision.engine import (
    bytes_a_vector,
    crear_avatar_base64,
    decodificar_bytes_imagen,
    similitud_coseno,
    vector_a_bytes,
)
from app.vision.quality import evaluar_calidad_rostro

enrutador = APIRouter(prefix="/api", tags=["personas"])
CANTIDAD_POSES_REQUERIDAS = 6


def _serializar_personas_lote(
    sesion_bd: Session,
    personas: list[Persona],
    id_organizacion: int,
    version_modelo_actual: str,
) -> list[PersonaLeer]:
    """Serializa personas con progreso biométrico y turno efectivo (directo o heredado)."""
    if not personas:
        return []

    mapa_turnos = {
        turno.id: turno
        for turno in sesion_bd.scalars(
            select(TurnoLaboral).where(TurnoLaboral.id_organizacion == id_organizacion)
        ).all()
    }
    mapa_grupos = {
        grupo.id: grupo
        for grupo in sesion_bd.scalars(
            select(Grupo).where(Grupo.id_organizacion == id_organizacion)
        ).all()
    }

    serializadas: list[PersonaLeer] = []
    for persona in personas:
        vectores = persona.vectores_faciales
        poses_actuales = [
            vector.etiqueta_pose
            for vector in vectores
            if vector.version_modelo == version_modelo_actual
        ]
        requiere_reenrolamiento = any(
            vector.version_modelo != version_modelo_actual for vector in vectores
        )
        ids_grupos = [enlace.id_grupo for enlace in persona.enlaces_grupos]

        turno_directo = (
            mapa_turnos.get(persona.id_turno_laboral) if persona.id_turno_laboral else None
        )
        turno_efectivo = turno_directo
        origen_turno: OrigenTurno = "direct" if turno_directo is not None else "none"
        if turno_efectivo is None:
            for gid in sorted(ids_grupos):
                grupo = mapa_grupos.get(gid)
                if (
                    grupo
                    and grupo.id_turno_laboral_defecto
                    and grupo.id_turno_laboral_defecto in mapa_turnos
                ):
                    turno_efectivo = mapa_turnos[grupo.id_turno_laboral_defecto]
                    origen_turno = "group"
                    break

        serializadas.append(
            PersonaLeer(
                id=persona.id,
                id_organizacion=persona.id_organizacion,
                identificador_externo=persona.identificador_externo,
                nombre_completo=persona.nombre_completo,
                correo=persona.correo,
                rol=persona.rol,
                avatar_base64=persona.avatar_base64,
                consentimiento_biometrico=persona.consentimiento_biometrico,
                fecha_consentimiento_biometrico=persona.fecha_consentimiento_biometrico,
                esta_activo=persona.esta_activo,
                creado_en=persona.creado_en,
                ids_grupos=ids_grupos,
                id_turno_laboral=persona.id_turno_laboral,
                nombre_turno_laboral=turno_directo.nombre if turno_directo else None,
                id_turno_laboral_efectivo=turno_efectivo.id if turno_efectivo else None,
                nombre_turno_laboral_efectivo=turno_efectivo.nombre if turno_efectivo else None,
                codigo_turno_laboral_efectivo=turno_efectivo.codigo if turno_efectivo else None,
                origen_turno=origen_turno,
                cantidad_vectores=len(poses_actuales),
                poses_completadas=poses_actuales,
                requiere_reenrolamiento=requiere_reenrolamiento,
            )
        )
    return serializadas


def _sincronizar_grupos_persona(
    sesion_bd: Session,
    persona: Persona,
    ids_grupos: list[int],
) -> None:
    """Reemplaza los vínculos `PersonaGrupo` validando que pertenezcan a la organización."""
    ids_unicos = list(dict.fromkeys(ids_grupos))
    if ids_unicos:
        grupos_validos = sesion_bd.scalars(
            select(Grupo).where(
                Grupo.id.in_(ids_unicos),
                Grupo.id_organizacion == persona.id_organizacion,
            )
        ).all()
        if len(grupos_validos) != len(ids_unicos):
            raise HTTPException(
                status_code=400,
                detail="Uno o más grupos no existen o no pertenecen a la organización.",
            )

    enlaces_actuales = sesion_bd.scalars(
        select(PersonaGrupo).where(PersonaGrupo.id_persona == persona.id)
    ).all()
    for enlace in enlaces_actuales:
        sesion_bd.delete(enlace)
    sesion_bd.flush()

    for gid in ids_unicos:
        sesion_bd.add(PersonaGrupo(id_persona=persona.id, id_grupo=gid))


@enrutador.get("/persons", response_model=list[PersonaLeer])
def listar_personas(
    id_organizacion: int | None = Query(default=None),
    id_grupo: int | None = Query(default=None),
    id_turno_laboral: int | None = Query(default=None),
    busqueda: str | None = Query(default=None),
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    sesion_bd: Session = Depends(obtener_bd),
) -> list[PersonaLeer]:
    """Lista personas del padrón filtradas por grupo, turno laboral o búsqueda de texto."""
    configuracion = obtener_configuracion()
    id_org_alcance = resolver_alcance_organizacion(usuario_actual, id_organizacion)
    consulta = (
        select(Persona)
        .options(selectinload(Persona.vectores_faciales), selectinload(Persona.enlaces_grupos))
        .where(Persona.id_organizacion == id_org_alcance)
        .order_by(Persona.id.desc())
    )
    if usuario_actual.rol == "teacher":
        ids_grupos_docente = obtener_ids_grupos_docente(sesion_bd, usuario_actual.id)
        if not ids_grupos_docente:
            return []
        consulta = consulta.where(
            Persona.id.in_(
                select(PersonaGrupo.id_persona).where(
                    PersonaGrupo.id_grupo.in_(ids_grupos_docente)
                )
            )
        )
    if id_grupo is not None:
        consulta = consulta.join(PersonaGrupo, PersonaGrupo.id_persona == Persona.id).where(
            PersonaGrupo.id_grupo == id_grupo
        )
    if busqueda:
        patron = f"%{busqueda.strip()}%"
        consulta = consulta.where(
            (Persona.nombre_completo.ilike(patron))
            | (Persona.identificador_externo.ilike(patron))
        )

    personas = list(sesion_bd.scalars(consulta).all())
    serializadas = _serializar_personas_lote(
        sesion_bd, personas, id_org_alcance, configuracion.version_modelo
    )
    if id_turno_laboral is not None:
        serializadas = [
            persona for persona in serializadas if persona.id_turno_laboral_efectivo == id_turno_laboral
        ]
    return serializadas


@enrutador.post("/persons", response_model=PersonaLeer, status_code=status.HTTP_201_CREATED)
def crear_persona(
    carga: PersonaCrear,
    usuario_actual: Usuario = Depends(
        requerir_roles("superadmin", "org_admin", "supervisor", "operator")
    ),
    sesion_bd: Session = Depends(obtener_bd),
) -> PersonaLeer:
    """Registra a una persona en el padrón con su consentimiento biométrico y grupos."""
    configuracion = obtener_configuracion()
    validar_acceso_organizacion(usuario_actual, carga.id_organizacion)
    organizacion = sesion_bd.get(Organizacion, carga.id_organizacion)
    if organizacion is None:
        raise HTTPException(status_code=404, detail="Organización no encontrada.")

    if carga.id_turno_laboral is not None:
        turno = sesion_bd.get(TurnoLaboral, carga.id_turno_laboral)
        if turno is None or turno.id_organizacion != organizacion.id:
            raise HTTPException(
                status_code=404,
                detail="Turno laboral no encontrado en la organización.",
            )

    persona = Persona(
        id_organizacion=carga.id_organizacion,
        id_turno_laboral=carga.id_turno_laboral,
        identificador_externo=carga.identificador_externo.strip(),
        nombre_completo=carga.nombre_completo.strip(),
        correo=carga.correo.strip() if carga.correo else None,
        rol=carga.rol,
        consentimiento_biometrico=carga.consentimiento_biometrico,
        fecha_consentimiento_biometrico=datetime.now() if carga.consentimiento_biometrico else None,
    )
    sesion_bd.add(persona)
    try:
        sesion_bd.flush()
    except IntegrityError as excepcion:
        sesion_bd.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                f"Ya existe una persona con el ID '{carga.identificador_externo}' "
                "en esta organización."
            ),
        ) from excepcion

    if carga.ids_grupos:
        _sincronizar_grupos_persona(sesion_bd, persona, carga.ids_grupos)

    sesion_bd.commit()
    persona_cargada = sesion_bd.scalars(
        select(Persona)
        .options(selectinload(Persona.vectores_faciales), selectinload(Persona.enlaces_grupos))
        .where(Persona.id == persona.id)
    ).one()
    return _serializar_personas_lote(
        sesion_bd,
        [persona_cargada],
        persona_cargada.id_organizacion,
        configuracion.version_modelo,
    )[0]


@enrutador.patch("/persons/{id_persona}", response_model=PersonaLeer)
def actualizar_persona(
    id_persona: int,
    carga: PersonaActualizar,
    usuario_actual: Usuario = Depends(
        requerir_roles("superadmin", "org_admin", "supervisor", "operator")
    ),
    sesion_bd: Session = Depends(obtener_bd),
) -> PersonaLeer:
    """Actualiza datos generales, consentimiento biométrico, grupos o turno de una persona."""
    configuracion = obtener_configuracion()
    persona = sesion_bd.get(Persona, id_persona)
    if persona is None:
        raise HTTPException(status_code=404, detail="Persona no encontrada.")
    validar_acceso_organizacion(usuario_actual, persona.id_organizacion)

    datos_parciales = carga.model_dump(exclude_unset=True)
    ids_grupos = datos_parciales.pop("ids_grupos", None)

    if "id_turno_laboral" in datos_parciales and datos_parciales["id_turno_laboral"] is not None:
        turno = sesion_bd.get(TurnoLaboral, datos_parciales["id_turno_laboral"])
        if turno is None or turno.id_organizacion != persona.id_organizacion:
            raise HTTPException(
                status_code=404,
                detail="Turno laboral no encontrado en la organización.",
            )

    if "consentimiento_biometrico" in datos_parciales:
        nuevo_consentimiento = bool(datos_parciales["consentimiento_biometrico"])
        if nuevo_consentimiento and not persona.consentimiento_biometrico:
            persona.fecha_consentimiento_biometrico = datetime.now()
        elif not nuevo_consentimiento:
            persona.fecha_consentimiento_biometrico = None

    for campo, valor in datos_parciales.items():
        setattr(persona, campo, valor)

    if ids_grupos is not None:
        _sincronizar_grupos_persona(sesion_bd, persona, ids_grupos)

    sesion_bd.commit()
    persona_cargada = sesion_bd.scalars(
        select(Persona)
        .options(selectinload(Persona.vectores_faciales), selectinload(Persona.enlaces_grupos))
        .where(Persona.id == persona.id)
    ).one()
    return _serializar_personas_lote(
        sesion_bd,
        [persona_cargada],
        persona_cargada.id_organizacion,
        configuracion.version_modelo,
    )[0]


@enrutador.delete("/persons/{id_persona}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_persona(
    id_persona: int,
    usuario_actual: Usuario = Depends(requerir_roles("superadmin", "org_admin")),
    sesion_bd: Session = Depends(obtener_bd),
) -> None:
    """Elimina permanentemente a una persona y sus registros asociados en cascada."""
    persona = sesion_bd.get(Persona, id_persona)
    if persona is None:
        raise HTTPException(status_code=404, detail="Persona no encontrada.")
    validar_acceso_organizacion(usuario_actual, persona.id_organizacion)
    sesion_bd.delete(persona)
    sesion_bd.commit()


@enrutador.post("/persons/{id_persona}/enroll-frame", response_model=RespuestaEnrolarFrame)
async def enrolar_frame(
    id_persona: int,
    peticion: Request,
    imagen: UploadFile = File(...),
    etiqueta_pose: EtiquetaPose = Form(...),
    guardar_avatar: bool | None = Form(default=None),
    solo_validacion: bool = Form(default=False),
    usuario_actual: Usuario = Depends(
        requerir_roles("superadmin", "org_admin", "supervisor", "operator")
    ),
    sesion_bd: Session = Depends(obtener_bd),
) -> RespuestaEnrolarFrame:
    """Evalúa o registra una pose facial en memoria RAM descartando la imagen original."""
    configuracion = obtener_configuracion()
    persona = sesion_bd.scalars(
        select(Persona)
        .options(selectinload(Persona.vectores_faciales))
        .where(Persona.id == id_persona)
    ).first()
    if persona is None:
        raise HTTPException(status_code=404, detail="Persona no encontrada.")
    validar_acceso_organizacion(usuario_actual, persona.id_organizacion)
    if not persona.consentimiento_biometrico:
        raise HTTPException(
            status_code=400,
            detail="Se requiere consentimiento biométrico explícito antes de registrar el rostro.",
        )

    motor = getattr(peticion.app.state, "motor_biometrico", None)
    if motor is None:
        raise HTTPException(
            status_code=503,
            detail="El motor biométrico no está inicializado en el servidor.",
        )

    bytes_crudos = await imagen.read()
    try:
        imagen_bgr = decodificar_bytes_imagen(bytes_crudos)
    except ValueError as excepcion:
        raise HTTPException(status_code=400, detail=str(excepcion)) from excepcion

    alto_imagen, ancho_imagen = imagen_bgr.shape[:2]
    poses_actuales = [
        vector.etiqueta_pose
        for vector in persona.vectores_faciales
        if vector.version_modelo == configuracion.version_modelo
    ]
    ya_completo = len(poses_actuales) >= CANTIDAD_POSES_REQUERIDAS

    detecciones = motor.detectar(imagen_bgr)
    if len(detecciones) == 0:
        return RespuestaEnrolarFrame(
            aceptado=False,
            pose_valida=False,
            etiqueta_pose=etiqueta_pose,
            mensaje="No se detectó ningún rostro. Colócate frente a la cámara.",
            cantidad_vectores=len(poses_actuales),
            poses_completadas=poses_actuales,
            enrolamiento_completo=ya_completo,
            cantidad_poses_requeridas=CANTIDAD_POSES_REQUERIDAS,
        )

    cuadro_principal, fila_principal = detecciones[0]
    esquema_cuadro = convertir_a_esquema_cuadro_rostro(cuadro_principal, ancho_imagen, alto_imagen)

    if len(detecciones) > 1:
        return RespuestaEnrolarFrame(
            aceptado=False,
            pose_valida=False,
            etiqueta_pose=etiqueta_pose,
            mensaje="Se detectaron varios rostros; asegúrate de estar solo frente a la cámara.",
            cantidad_vectores=len(poses_actuales),
            poses_completadas=poses_actuales,
            enrolamiento_completo=ya_completo,
            cantidad_poses_requeridas=CANTIDAD_POSES_REQUERIDAS,
            cuadro_rostro=esquema_cuadro,
        )

    vector_frontal = next(
        (
            vector
            for vector in persona.vectores_faciales
            if vector.etiqueta_pose == "frontal"
            and vector.version_modelo == configuracion.version_modelo
        ),
        None,
    )
    relacion_boca_frontal = (
        vector_frontal.relacion_boca if vector_frontal is not None else None
    )
    relacion_inclinacion_frontal = (
        vector_frontal.relacion_inclinacion_vertical
        if vector_frontal is not None
        else None
    )

    calidad = evaluar_calidad_rostro(
        imagen_bgr,
        cuadro_principal,
        tamano_minimo_px=configuracion.tamano_minimo_rostro_px,
        nitidez_minima=configuracion.varianza_minima_nitidez_registro,
        brillo_minimo=configuracion.brillo_minimo_registro,
        brillo_maximo=configuracion.brillo_maximo,
        pose_esperada=etiqueta_pose,
        relacion_boca_frontal=relacion_boca_frontal,
        relacion_inclinacion_frontal=relacion_inclinacion_frontal,
        asimetria_sombra_maxima=configuracion.asimetria_sombra_maxima_registro,
        umbral_delta_contraluz=configuracion.umbral_delta_contraluz,
        iluminacion_estricta=True,
    )
    esquema_calidad = convertir_a_esquema_calidad(calidad)

    if not calidad.es_valida:
        return RespuestaEnrolarFrame(
            aceptado=False,
            pose_valida=False,
            etiqueta_pose=etiqueta_pose,
            mensaje=calidad.motivo or "Calidad de imagen insuficiente.",
            cantidad_vectores=len(poses_actuales),
            poses_completadas=poses_actuales,
            enrolamiento_completo=ya_completo,
            cantidad_poses_requeridas=CANTIDAD_POSES_REQUERIDAS,
            cuadro_rostro=esquema_cuadro,
            calidad=esquema_calidad,
        )

    if not calidad.pose_coincide:
        return RespuestaEnrolarFrame(
            aceptado=False,
            pose_valida=False,
            etiqueta_pose=etiqueta_pose,
            mensaje=(
                calidad.retroalimentacion_pose
                or "La orientación del rostro no coincide con la pose solicitada."
            ),
            cantidad_vectores=len(poses_actuales),
            poses_completadas=poses_actuales,
            enrolamiento_completo=ya_completo,
            cantidad_poses_requeridas=CANTIDAD_POSES_REQUERIDAS,
            cuadro_rostro=esquema_cuadro,
            calidad=esquema_calidad,
        )

    if solo_validacion:
        return RespuestaEnrolarFrame(
            aceptado=False,
            pose_valida=True,
            etiqueta_pose=etiqueta_pose,
            mensaje="Pose validada, mantén firme la posición...",
            cantidad_vectores=len(poses_actuales),
            poses_completadas=poses_actuales,
            enrolamiento_completo=ya_completo,
            cantidad_poses_requeridas=CANTIDAD_POSES_REQUERIDAS,
            cuadro_rostro=esquema_cuadro,
            calidad=esquema_calidad,
        )

    vector_extraido = motor.extraer_vector(imagen_bgr, fila_principal)

    # Verifica autoconsistencia contra poses previas para evitar mezclar dos personas distintas
    otros_vectores_misma_version = [
        vector
        for vector in persona.vectores_faciales
        if vector.version_modelo == configuracion.version_modelo
        and vector.etiqueta_pose != etiqueta_pose
    ]
    if otros_vectores_misma_version:
        similitud_maxima = max(
            similitud_coseno(vector_extraido, bytes_a_vector(vector.bytes_vector))
            for vector in otros_vectores_misma_version
        )
        if similitud_maxima < configuracion.umbral_autoconsistencia:
            return RespuestaEnrolarFrame(
                aceptado=False,
                pose_valida=False,
                etiqueta_pose=etiqueta_pose,
                mensaje="El rostro capturado no coincide con las tomas previas de esta persona.",
                cantidad_vectores=len(poses_actuales),
                poses_completadas=poses_actuales,
                enrolamiento_completo=ya_completo,
                cantidad_poses_requeridas=CANTIDAD_POSES_REQUERIDAS,
                cuadro_rostro=esquema_cuadro,
                calidad=esquema_calidad,
            )

    pose_existente = next(
        (vector for vector in persona.vectores_faciales if vector.etiqueta_pose == etiqueta_pose),
        None,
    )
    bytes_vector = vector_a_bytes(vector_extraido)
    if pose_existente is not None:
        pose_existente.bytes_vector = bytes_vector
        pose_existente.nombre_modelo = configuracion.nombre_modelo
        pose_existente.version_modelo = configuracion.version_modelo
        pose_existente.puntaje_calidad = round(calidad.puntaje_nitidez, 2)
        pose_existente.relacion_boca = round(calidad.relacion_boca, 4)
        pose_existente.relacion_inclinacion_vertical = round(
            calidad.relacion_inclinacion_vertical, 4
        )
        pose_existente.creado_en = datetime.now()
    else:
        sesion_bd.add(
            VectorFacial(
                id_persona=persona.id,
                etiqueta_pose=etiqueta_pose,
                bytes_vector=bytes_vector,
                nombre_modelo=configuracion.nombre_modelo,
                version_modelo=configuracion.version_modelo,
                puntaje_calidad=round(calidad.puntaje_nitidez, 2),
                relacion_boca=round(calidad.relacion_boca, 4),
                relacion_inclinacion_vertical=round(calidad.relacion_inclinacion_vertical, 4),
            )
        )

    organizacion = sesion_bd.get(Organizacion, persona.id_organizacion)
    debe_guardar_avatar = (
        guardar_avatar
        if guardar_avatar is not None
        else (organizacion.guardar_avatar_por_defecto if organizacion is not None else True)
    )
    avatar_guardado = False
    if etiqueta_pose == "frontal" and debe_guardar_avatar:
        persona.avatar_base64 = crear_avatar_base64(imagen_bgr, cuadro_principal, tamano=200)
        avatar_guardado = True

    sesion_bd.commit()

    poses_actualizadas = [
        vector.etiqueta_pose
        for vector in sesion_bd.scalars(
            select(VectorFacial).where(
                VectorFacial.id_persona == persona.id,
                VectorFacial.version_modelo == configuracion.version_modelo,
            )
        ).all()
    ]

    return RespuestaEnrolarFrame(
        aceptado=True,
        pose_valida=True,
        etiqueta_pose=etiqueta_pose,
        mensaje=f"Pose '{etiqueta_pose}' registrada en memoria y vector almacenado.",
        cantidad_vectores=len(poses_actualizadas),
        poses_completadas=poses_actualizadas,
        enrolamiento_completo=len(poses_actualizadas) >= CANTIDAD_POSES_REQUERIDAS,
        cantidad_poses_requeridas=CANTIDAD_POSES_REQUERIDAS,
        cuadro_rostro=esquema_cuadro,
        calidad=esquema_calidad,
        avatar_guardado=avatar_guardado,
    )


def _revocar_biometria_personas(
    sesion_bd: Session,
    *,
    usuario_actual: Usuario,
    personas: list[Persona],
    secreto_autorizacion: str,
    motivo: str | None,
) -> tuple[int, bool, ResultadoAutorizacion]:
    """Ejecuta la revocación biométrica validando autorización sensible y auditando cada baja."""
    ids_organizaciones = {persona.id_organizacion for persona in personas}
    if len(ids_organizaciones) != 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Todas las personas seleccionadas deben pertenecer a la misma organización.",
        )
    id_org_objetivo = next(iter(ids_organizaciones))
    validar_acceso_organizacion(usuario_actual, id_org_objetivo)

    resultado_auth = verificar_autorizacion_sensible(
        sesion_bd,
        usuario_actual=usuario_actual,
        id_organizacion=id_org_objetivo,
        secreto_autorizacion=secreto_autorizacion,
        operacion_requerida="revoke_biometrics",
    )

    total_eliminados = 0
    algun_avatar_limpio = False
    nota_motivo = (
        motivo.strip() if motivo and motivo.strip() else "Revocación de datos biométricos"
    )

    for persona in personas:
        conteo_eliminados = len(persona.vectores_faciales)
        total_eliminados += conteo_eliminados
        for vector in list(persona.vectores_faciales):
            sesion_bd.delete(vector)

        if persona.avatar_base64 is not None:
            algun_avatar_limpio = True
            persona.avatar_base64 = None

        registrar_auditoria(
            sesion_bd,
            id_organizacion=id_org_objetivo,
            accion="revoke_biometrics",
            tipo_objetivo="person",
            id_objetivo=persona.id,
            resumen_objetivo=f"{persona.nombre_completo} ({persona.identificador_externo})",
            usuario_ejecutor=usuario_actual,
            usuario_autorizador=resultado_auth.usuario_autorizador,
            credencial_delegada=resultado_auth.credencial_delegada,
            detalles=(
                f"{nota_motivo} | Vectores eliminados: {conteo_eliminados} | "
                f"Método: {resultado_auth.metodo}"
            ),
        )

    sesion_bd.commit()
    return total_eliminados, algun_avatar_limpio, resultado_auth


@enrutador.post("/persons/biometrics/revoke", response_model=RespuestaRevocarBiometriaLote)
def revocar_biometria_lote(
    carga: SolicitudRevocarBiometriaLote,
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    sesion_bd: Session = Depends(obtener_bd),
) -> RespuestaRevocarBiometriaLote:
    """Revoca simultáneamente los vectores biométricos de un lote de personas."""
    ids_unicos = list(dict.fromkeys(carga.ids_personas))
    personas = list(
        sesion_bd.scalars(
            select(Persona)
            .options(selectinload(Persona.vectores_faciales))
            .where(Persona.id.in_(ids_unicos))
        ).all()
    )
    if len(personas) != len(ids_unicos):
        raise HTTPException(status_code=404, detail="Una o más personas no fueron encontradas.")

    total_eliminados, _, resultado_auth = _revocar_biometria_personas(
        sesion_bd,
        usuario_actual=usuario_actual,
        personas=personas,
        secreto_autorizacion=carga.secreto_autorizacion,
        motivo=carga.motivo,
    )
    return RespuestaRevocarBiometriaLote(
        cantidad_personas_revocadas=len(personas),
        vectores_eliminados=total_eliminados,
        nombre_autorizador=(
            resultado_auth.usuario_autorizador.nombre_completo
            if resultado_auth.usuario_autorizador
            else None
        ),
        metodo_autorizacion=resultado_auth.metodo,
        etiqueta_credencial_delegada=(
            resultado_auth.credencial_delegada.etiqueta
            if resultado_auth.credencial_delegada
            else None
        ),
    )


@enrutador.delete("/persons/{id_persona}/biometrics", response_model=RespuestaRevocarBiometria)
def revocar_biometria_individual(
    id_persona: int,
    carga: SolicitudRevocarBiometria | None = Body(default=None),
    x_secreto_autorizacion: str | None = Header(default=None, alias="X-Secreto-Autorizacion"),
    x_authorization_secret_legado: str | None = Header(
        default=None, alias="X-Authorization-Secret"
    ),
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    sesion_bd: Session = Depends(obtener_bd),
) -> RespuestaRevocarBiometria:
    """Elimina los vectores faciales y avatar de una persona previa autorización validada."""
    persona = sesion_bd.scalars(
        select(Persona)
        .options(selectinload(Persona.vectores_faciales))
        .where(Persona.id == id_persona)
    ).first()
    if persona is None:
        raise HTTPException(status_code=404, detail="Persona no encontrada.")

    secreto = (
        (carga.secreto_autorizacion if carga else None)
        or x_secreto_autorizacion
        or x_authorization_secret_legado
        or ""
    )
    motivo = carga.motivo if carga else None

    conteo_eliminados, tenia_avatar, resultado_auth = _revocar_biometria_personas(
        sesion_bd,
        usuario_actual=usuario_actual,
        personas=[persona],
        secreto_autorizacion=secreto,
        motivo=motivo,
    )
    return RespuestaRevocarBiometria(
        id_persona=persona.id,
        vectores_eliminados=conteo_eliminados,
        avatar_eliminado=tenia_avatar,
        nombre_autorizador=(
            resultado_auth.usuario_autorizador.nombre_completo
            if resultado_auth.usuario_autorizador
            else None
        ),
        metodo_autorizacion=resultado_auth.metodo,
        etiqueta_credencial_delegada=(
            resultado_auth.credencial_delegada.etiqueta
            if resultado_auth.credencial_delegada
            else None
        ),
    )
