"""Enrutador HTTP para turnos laborales empresariales, sesiones de jornada y analítica.

Permite administrar turnos (diurnos y nocturnos con cruce de medianoche),
realizar asignaciones individuales o masivas por departamento, abrir o generar
sesiones laborales y consultar estadísticas de puntualidad y horas trabajadas.
"""

from datetime import date
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import obtener_bd
from app.models import Grupo, Organizacion, Persona, PersonaGrupo, TurnoLaboral, Usuario
from app.schemas import (
    RespuestaAsignacionMasivaTurno,
    RespuestaEstadisticasEmpresariales,
    RespuestaGenerarSesiones,
    SesionLeer,
    SolicitudAsignacionMasivaTurno,
    SolicitudGenerarSesionesTurno,
    SolicitudIniciarSesionTurno,
    TurnoLaboralActualizar,
    TurnoLaboralCrear,
    TurnoLaboralLeer,
)
from app.security import (
    requerir_roles,
    resolver_alcance_organizacion,
    validar_acceso_organizacion,
)
from app.services.academic_service import serializar_sesiones_lote
from app.services.enterprise_service import (
    calcular_estadisticas_empresariales,
    generar_sesiones_turno_para_fecha,
    iniciar_o_obtener_sesion_turno,
    normalizar_dias_semana,
    serializar_turnos_lote,
    validar_horarios_turno_laboral,
)
from app.services.security_service import registrar_auditoria

enrutador = APIRouter(prefix="/api/enterprise", tags=["empresarial"])


@enrutador.get("/shifts", response_model=list[TurnoLaboralLeer])
def listar_turnos_laborales(
    id_organizacion: int | None = Query(default=None),
    esta_activo: bool | None = Query(default=None),
    usuario_actual: Usuario = Depends(
        requerir_roles("superadmin", "org_admin", "supervisor", "operator")
    ),
    sesion_bd: Session = Depends(obtener_bd),
) -> list[TurnoLaboralLeer]:
    """Lista los turnos laborales configurados en la organización empresarial."""
    id_org_alcance = resolver_alcance_organizacion(usuario_actual, id_organizacion)
    consulta = (
        select(TurnoLaboral)
        .where(TurnoLaboral.id_organizacion == id_org_alcance)
        .order_by(TurnoLaboral.hora_inicio.asc(), TurnoLaboral.id.asc())
    )
    if esta_activo is not None:
        consulta = consulta.where(TurnoLaboral.esta_activo.is_(esta_activo))
    turnos = list(sesion_bd.scalars(consulta).all())
    return serializar_turnos_lote(sesion_bd, turnos, id_org_alcance)


@enrutador.post("/shifts", response_model=TurnoLaboralLeer, status_code=status.HTTP_201_CREATED)
def crear_turno_laboral(
    carga: TurnoLaboralCrear,
    usuario_actual: Usuario = Depends(requerir_roles("superadmin", "org_admin")),
    sesion_bd: Session = Depends(obtener_bd),
) -> TurnoLaboralLeer:
    """Crea un turno laboral detectando automáticamente si cruza la medianoche."""
    validar_acceso_organizacion(usuario_actual, carga.id_organizacion)
    organizacion = sesion_bd.get(Organizacion, carga.id_organizacion)
    if organizacion is None:
        raise HTTPException(status_code=404, detail="Organización no encontrada.")

    cruza_medianoche, _ = validar_horarios_turno_laboral(carga.hora_inicio, carga.hora_fin)
    dias_csv = normalizar_dias_semana(carga.dias_semana)

    turno = TurnoLaboral(
        id_organizacion=organizacion.id,
        nombre=carga.nombre.strip(),
        codigo=carga.codigo.strip().upper(),
        hora_inicio=carga.hora_inicio.strip(),
        hora_fin=carga.hora_fin.strip(),
        cruza_medianoche=cruza_medianoche,
        dias_semana=dias_csv,
        minutos_tolerancia_retardo=carga.minutos_tolerancia_retardo,
        minutos_tolerancia_salida_anticipada=carga.minutos_tolerancia_salida_anticipada,
        esta_activo=carga.esta_activo,
    )
    sesion_bd.add(turno)
    try:
        sesion_bd.flush()
    except IntegrityError as excepcion:
        sesion_bd.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe un turno con el código '{turno.codigo}' en esta organización.",
        ) from excepcion

    registrar_auditoria(
        sesion_bd,
        id_organizacion=organizacion.id,
        accion="create_work_shift",
        tipo_objetivo="work_shift",
        id_objetivo=turno.id,
        resumen_objetivo=f"{turno.nombre} ({turno.codigo})",
        usuario_ejecutor=usuario_actual,
        usuario_autorizador=usuario_actual,
        detalles=(
            f"Horario: {turno.hora_inicio}-{turno.hora_fin} | "
            f"Cruza medianoche: {turno.cruza_medianoche}"
        ),
    )
    sesion_bd.commit()
    sesion_bd.refresh(turno)
    return serializar_turnos_lote(sesion_bd, [turno], organizacion.id)[0]


@enrutador.patch("/shifts/{id_turno}", response_model=TurnoLaboralLeer)
def actualizar_turno_laboral(
    id_turno: int,
    carga: TurnoLaboralActualizar,
    usuario_actual: Usuario = Depends(requerir_roles("superadmin", "org_admin")),
    sesion_bd: Session = Depends(obtener_bd),
) -> TurnoLaboralLeer:
    """Modifica horarios, días laborales, tolerancias o estado activo de un turno."""
    turno = sesion_bd.get(TurnoLaboral, id_turno)
    if turno is None:
        raise HTTPException(status_code=404, detail="Turno laboral no encontrado.")
    validar_acceso_organizacion(usuario_actual, turno.id_organizacion)

    datos_parciales = carga.model_dump(exclude_unset=True)
    nuevo_inicio = datos_parciales.get("hora_inicio", turno.hora_inicio)
    nuevo_fin = datos_parciales.get("hora_fin", turno.hora_fin)
    cruza_medianoche, _ = validar_horarios_turno_laboral(nuevo_inicio, nuevo_fin)

    if "dias_semana" in datos_parciales and datos_parciales["dias_semana"] is not None:
        turno.dias_semana = normalizar_dias_semana(datos_parciales["dias_semana"])

    if "nombre" in datos_parciales and datos_parciales["nombre"] is not None:
        turno.nombre = datos_parciales["nombre"].strip()
    if "codigo" in datos_parciales and datos_parciales["codigo"] is not None:
        turno.codigo = datos_parciales["codigo"].strip().upper()
    if "hora_inicio" in datos_parciales and datos_parciales["hora_inicio"] is not None:
        turno.hora_inicio = datos_parciales["hora_inicio"].strip()
    if "hora_fin" in datos_parciales and datos_parciales["hora_fin"] is not None:
        turno.hora_fin = datos_parciales["hora_fin"].strip()
    turno.cruza_medianoche = cruza_medianoche

    if "minutos_tolerancia_retardo" in datos_parciales:
        turno.minutos_tolerancia_retardo = datos_parciales["minutos_tolerancia_retardo"]
    if (
        "minutos_tolerancia_salida_anticipada" in datos_parciales
        and datos_parciales["minutos_tolerancia_salida_anticipada"] is not None
    ):
        turno.minutos_tolerancia_salida_anticipada = datos_parciales[
            "minutos_tolerancia_salida_anticipada"
        ]
    if "esta_activo" in datos_parciales and datos_parciales["esta_activo"] is not None:
        turno.esta_activo = bool(datos_parciales["esta_activo"])

    try:
        sesion_bd.commit()
    except IntegrityError as excepcion:
        sesion_bd.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe un turno con el código '{turno.codigo}' en esta organización.",
        ) from excepcion

    sesion_bd.refresh(turno)
    return serializar_turnos_lote(sesion_bd, [turno], turno.id_organizacion)[0]


@enrutador.delete("/shifts/{id_turno}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_turno_laboral(
    id_turno: int,
    usuario_actual: Usuario = Depends(requerir_roles("superadmin", "org_admin")),
    sesion_bd: Session = Depends(obtener_bd),
) -> None:
    """Elimina un turno laboral dejando en auditoría el registro de la baja."""
    turno = sesion_bd.get(TurnoLaboral, id_turno)
    if turno is None:
        raise HTTPException(status_code=404, detail="Turno laboral no encontrado.")
    validar_acceso_organizacion(usuario_actual, turno.id_organizacion)

    id_organizacion = turno.id_organizacion
    resumen = f"{turno.nombre} ({turno.codigo})"
    registrar_auditoria(
        sesion_bd,
        id_organizacion=id_organizacion,
        accion="delete_work_shift",
        tipo_objetivo="work_shift",
        id_objetivo=turno.id,
        resumen_objetivo=resumen,
        usuario_ejecutor=usuario_actual,
        usuario_autorizador=usuario_actual,
        detalles=f"Turno eliminado: {turno.hora_inicio}-{turno.hora_fin}",
    )
    sesion_bd.delete(turno)
    sesion_bd.commit()


@enrutador.post("/shifts/{id_turno}/assign-persons", response_model=RespuestaAsignacionMasivaTurno)
def asignar_turno_a_personas(
    id_turno: int,
    carga: SolicitudAsignacionMasivaTurno,
    usuario_actual: Usuario = Depends(requerir_roles("superadmin", "org_admin")),
    sesion_bd: Session = Depends(obtener_bd),
) -> RespuestaAsignacionMasivaTurno:
    """Asigna o limpia el turno laboral directo de una lista de empleados o un departamento."""
    turno = sesion_bd.get(TurnoLaboral, id_turno)
    if turno is None:
        raise HTTPException(status_code=404, detail="Turno laboral no encontrado.")
    validar_acceso_organizacion(usuario_actual, turno.id_organizacion)

    ids_unicos = list(dict.fromkeys(carga.ids_personas))
    personas_objetivo: list[Persona] = []
    if ids_unicos:
        personas_objetivo = list(
            sesion_bd.scalars(
                select(Persona).where(
                    Persona.id.in_(ids_unicos),
                    Persona.id_organizacion == turno.id_organizacion,
                )
            ).all()
        )
        if len(personas_objetivo) != len(ids_unicos):
            raise HTTPException(
                status_code=400,
                detail="Uno o más empleados no existen o no pertenecen a la organización.",
            )
    elif carga.id_grupo is not None:
        grupo = sesion_bd.get(Grupo, carga.id_grupo)
        if grupo is None or grupo.id_organizacion != turno.id_organizacion:
            raise HTTPException(status_code=404, detail="Departamento/grupo no encontrado.")
        personas_objetivo = list(
            sesion_bd.scalars(
                select(Persona)
                .join(PersonaGrupo, PersonaGroup_id_persona := PersonaGrupo.id_persona == Persona.id)
                .where(
                    PersonaGrupo.id_grupo == grupo.id,
                    Persona.id_organizacion == turno.id_organizacion,
                )
            ).all()
        )
        del PersonaGroup_id_persona
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debes indicar empleados o un departamento para asignar el turno.",
        )

    for persona in personas_objetivo:
        persona.id_turno_laboral = None if carga.limpiar_turno else turno.id

    registrar_auditoria(
        sesion_bd,
        id_organizacion=turno.id_organizacion,
        accion="clear_work_shift_assignment" if carga.limpiar_turno else "assign_work_shift",
        tipo_objetivo="work_shift",
        id_objetivo=turno.id,
        resumen_objetivo=f"{turno.nombre} ({turno.codigo})",
        usuario_ejecutor=usuario_actual,
        usuario_autorizador=usuario_actual,
        detalles=f"Empleados actualizados: {len(personas_objetivo)}",
    )
    sesion_bd.commit()

    return RespuestaAsignacionMasivaTurno(
        id_turno_laboral=None if carga.limpiar_turno else turno.id,
        nombre_turno_laboral=None if carga.limpiar_turno else turno.nombre,
        cantidad_actualizados=len(personas_objetivo),
    )


@enrutador.post("/shifts/{id_turno}/start-session", response_model=SesionLeer)
def iniciar_sesion_turno(
    id_turno: int,
    carga: SolicitudIniciarSesionTurno | None = Body(default=None),
    usuario_actual: Usuario = Depends(
        requerir_roles("superadmin", "org_admin", "supervisor", "operator")
    ),
    sesion_bd: Session = Depends(obtener_bd),
) -> SesionLeer:
    """Abre o recupera la sesión de jornada del día para un turno laboral."""
    turno = sesion_bd.get(TurnoLaboral, id_turno)
    if turno is None:
        raise HTTPException(status_code=404, detail="Turno laboral no encontrado.")
    validar_acceso_organizacion(usuario_actual, turno.id_organizacion)
    if not turno.esta_activo:
        raise HTTPException(status_code=400, detail="El turno seleccionado está inactivo.")

    fecha_objetivo = carga.fecha_sesion if carga and carga.fecha_sesion else date.today()
    sesion = iniciar_o_obtener_sesion_turno(
        sesion_bd,
        turno=turno,
        fecha_objetivo=fecha_objetivo,
    )
    return serializar_sesiones_lote(sesion_bd, [sesion], turno.id_organizacion)[0]


@enrutador.post("/sessions/generate", response_model=RespuestaGenerarSesiones)
def generar_sesiones_empresariales(
    carga: SolicitudGenerarSesionesTurno,
    usuario_actual: Usuario = Depends(
        requerir_roles("superadmin", "org_admin", "supervisor", "operator")
    ),
    sesion_bd: Session = Depends(obtener_bd),
) -> RespuestaGenerarSesiones:
    """Genera de forma idempotente todas las sesiones laborales activas para una fecha."""
    id_org_alcance = resolver_alcance_organizacion(usuario_actual, carga.id_organizacion)
    organizacion = sesion_bd.get(Organizacion, id_org_alcance)
    if organizacion is None:
        raise HTTPException(status_code=404, detail="Organización no encontrada.")

    fecha_objetivo = carga.fecha_objetivo or date.today()
    cantidad_creadas, cantidad_existentes, sesiones = generar_sesiones_turno_para_fecha(
        sesion_bd,
        id_organizacion=id_org_alcance,
        fecha_objetivo=fecha_objetivo,
        id_turno_laboral=carga.id_turno_laboral,
    )
    return RespuestaGenerarSesiones(
        fecha_objetivo=fecha_objetivo,
        cantidad_creadas=cantidad_creadas,
        cantidad_existentes=cantidad_existentes,
        sesiones=serializar_sesiones_lote(sesion_bd, sesiones, id_org_alcance),
    )


@enrutador.get("/stats", response_model=RespuestaEstadisticasEmpresariales)
def obtener_estadisticas_empresariales(
    id_organizacion: int | None = Query(default=None),
    fecha_desde: date | None = Query(default=None),
    fecha_hasta: date | None = Query(default=None),
    id_turno_laboral: int | None = Query(default=None),
    id_grupo: int | None = Query(default=None),
    usuario_actual: Usuario = Depends(requerir_roles("superadmin", "org_admin", "supervisor")),
    sesion_bd: Session = Depends(obtener_bd),
) -> RespuestaEstadisticasEmpresariales:
    """Calcula métricas empresariales de asistencia, puntualidad, salidas anticipadas y horas."""
    id_org_alcance = resolver_alcance_organizacion(usuario_actual, id_organizacion)
    return calcular_estadisticas_empresariales(
        sesion_bd,
        id_organizacion=id_org_alcance,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        id_turno_laboral=id_turno_laboral,
        id_grupo=id_grupo,
    )
