"""Servicio de lógica empresarial: turnos laborales, jornadas nocturnas y estadísticas.

Gestiona la validación de turnos diurnos y con cruce de medianoche, herencia de
turnos desde el departamento hacia el colaborador, reglas de puntualidad y salida
anticipada, búsqueda de entradas nocturnas abiertas de la jornada previa,
generación idempotente de sesiones laborales y cálculo de métricas por turno y empleado.
"""

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    EventoAsistencia,
    Grupo,
    Organizacion,
    Persona,
    PersonaGrupo,
    SesionAsistencia,
    TurnoLaboral,
)
from app.schemas import (
    EstadisticaAsistenciaEmpleado,
    EstadisticaAsistenciaTurno,
    OrigenTurno,
    RespuestaEstadisticasEmpresariales,
    ResumenEstadisticasEmpresariales,
    TurnoLaboralLeer,
)

DIAS_LABORALES_POR_DEFECTO = [0, 1, 2, 3, 4]


def analizar_hora_hhmm(valor_hora: str) -> time:
    """Convierte una cadena `'HH:MM'` en un objeto `datetime.time` validando rango 24h."""
    try:
        hora_txt, minuto_txt = valor_hora.strip().split(":")
        hora = int(hora_txt)
        minuto = int(minuto_txt)
    except (ValueError, AttributeError) as excepcion:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato de hora inválido. Usa HH:MM.",
        ) from excepcion

    if not (0 <= hora <= 23 and 0 <= minuto <= 59):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Las horas deben estar entre 00:00 y 23:59.",
        )
    return time(hour=hora, minute=minuto)


def validar_horarios_turno_laboral(hora_inicio: str, hora_fin: str) -> tuple[bool, int]:
    """Valida entrada/salida del turno e informa si cruza medianoche y su duración (min)."""
    tiempo_inicio = analizar_hora_hhmm(hora_inicio)
    tiempo_fin = analizar_hora_hhmm(hora_fin)
    if tiempo_inicio == tiempo_fin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La hora de entrada y salida del turno no pueden ser iguales.",
        )

    minutos_inicio = tiempo_inicio.hour * 60 + tiempo_inicio.minute
    minutos_fin = tiempo_fin.hour * 60 + tiempo_fin.minute
    cruza_medianoche = tiempo_fin < tiempo_inicio
    if cruza_medianoche:
        duracion_esperada = (1440 - minutos_inicio) + minutos_fin
    else:
        duracion_esperada = minutos_fin - minutos_inicio
    return cruza_medianoche, duracion_esperada


def normalizar_dias_semana(dias: list[int]) -> str:
    """Valida y serializa a CSV los días laborales del turno (`0=Lunes .. 6=Domingo`)."""
    if not dias:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debes seleccionar al menos un día laboral para el turno.",
        )
    dias_validos: set[int] = set()
    for dia in dias:
        if not isinstance(dia, int) or dia < 0 or dia > 6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Los días de la semana deben estar entre 0 (Lunes) y 6 (Domingo).",
            )
        dias_validos.add(dia)
    return ",".join(str(dia) for dia in sorted(dias_validos))


def analizar_dias_semana(texto_crudo: str | None) -> list[int]:
    """Convierte el texto CSV `'0,1,2,3,4'` almacenado en BD a lista ordenada de enteros."""
    if not texto_crudo:
        return list(DIAS_LABORALES_POR_DEFECTO)
    dias_limpios: set[int] = set()
    for fragmento in texto_crudo.split(","):
        fragmento = fragmento.strip()
        if not fragmento:
            continue
        try:
            numero_dia = int(fragmento)
        except ValueError:
            continue
        if 0 <= numero_dia <= 6:
            dias_limpios.add(numero_dia)
    return sorted(dias_limpios) if dias_limpios else list(DIAS_LABORALES_POR_DEFECTO)


def _calcular_duracion_minutos(
    hora_inicio: str,
    hora_fin: str,
    cruza_medianoche: bool,
) -> int:
    """Calcula la duración esperada en minutos entre entrada y salida del turno."""
    tiempo_inicio = analizar_hora_hhmm(hora_inicio)
    tiempo_fin = analizar_hora_hhmm(hora_fin)
    minutos_inicio = tiempo_inicio.hour * 60 + tiempo_inicio.minute
    minutos_fin = tiempo_fin.hour * 60 + tiempo_fin.minute
    if cruza_medianoche:
        return (1440 - minutos_inicio) + minutos_fin
    return max(0, minutos_fin - minutos_inicio)


def resolver_turno_persona(
    sesion_bd: Session,
    persona: Persona,
) -> tuple[TurnoLaboral | None, OrigenTurno]:
    """Resuelve el turno laboral efectivo del colaborador (asignación directa o heredada)."""
    if persona.id_turno_laboral is not None:
        turno_directo = sesion_bd.get(TurnoLaboral, persona.id_turno_laboral)
        if turno_directo is not None and turno_directo.id_organizacion == persona.id_organizacion:
            return turno_directo, "direct"

    fila_grupo = sesion_bd.execute(
        select(TurnoLaboral)
        .join(Grupo, Grupo.id_turno_laboral_defecto == TurnoLaboral.id)
        .join(PersonaGrupo, PersonaGrupo.id_grupo == Grupo.id)
        .where(
            PersonaGrupo.id_persona == persona.id,
            Grupo.id_organizacion == persona.id_organizacion,
            TurnoLaboral.id_organizacion == persona.id_organizacion,
        )
        .order_by(Grupo.id.asc())
    ).first()
    if fila_grupo is not None:
        return fila_grupo[0], "group"
    return None, "none"


def resolver_turno_para_asistencia(
    sesion_bd: Session,
    persona: Persona,
    sesion: SesionAsistencia | None = None,
) -> TurnoLaboral | None:
    """Determina el turno aplicable al registrar un movimiento en el kiosco empresarial.

    Orden de precedencia: turno directo del colaborador -> turno de la sesión abierta ->
    turno heredado del departamento al que pertenece el colaborador.
    """
    if persona.id_turno_laboral is not None:
        turno_directo = sesion_bd.get(TurnoLaboral, persona.id_turno_laboral)
        if turno_directo is not None and turno_directo.id_organizacion == persona.id_organizacion:
            return turno_directo

    if sesion is not None and sesion.id_turno_laboral is not None:
        turno_sesion = sesion_bd.get(TurnoLaboral, sesion.id_turno_laboral)
        if turno_sesion is not None and turno_sesion.id_organizacion == persona.id_organizacion:
            return turno_sesion

    turno_heredado, _ = resolver_turno_persona(sesion_bd, persona)
    return turno_heredado


def evaluar_entrada_turno(
    turno: TurnoLaboral,
    organizacion: Organizacion,
    fecha_sesion: date,
    hora_actual: datetime,
) -> tuple[str, int]:
    """Evalúa puntualidad de check-in contra el turno y retorna `(estado, minutos_retardo)`."""
    inicio_esperado = datetime.combine(fecha_sesion, analizar_hora_hhmm(turno.hora_inicio))
    tolerancia = (
        turno.minutos_tolerancia_retardo
        if turno.minutos_tolerancia_retardo is not None
        else organizacion.minutos_tolerancia_retardo
    )
    hora_limite = inicio_esperado + timedelta(minutes=tolerancia)
    if hora_actual > hora_limite:
        minutos_retardo = max(1, int((hora_actual - inicio_esperado).total_seconds() // 60))
        return "late", minutos_retardo
    return "on_time", 0


def evaluar_salida_turno(
    turno: TurnoLaboral,
    fecha_sesion: date,
    hora_actual: datetime,
) -> tuple[str, int]:
    """Evalúa si el check-out ocurrió antes del fin del turno (soportando cruce de medianoche)."""
    fecha_fin = fecha_sesion + timedelta(days=1) if turno.cruza_medianoche else fecha_sesion
    fin_esperado = datetime.combine(fecha_fin, analizar_hora_hhmm(turno.hora_fin))
    salida_minima_permitida = fin_esperado - timedelta(
        minutes=turno.minutos_tolerancia_salida_anticipada
    )
    if hora_actual < salida_minima_permitida:
        minutos_anticipados = max(1, int((fin_esperado - hora_actual).total_seconds() // 60))
        return "early_exit", minutos_anticipados
    return "on_time", 0


def buscar_entrada_nocturna_abierta(
    sesion_bd: Session,
    id_organizacion: int,
    id_persona: int,
    hora_actual: datetime,
    turno_efectivo: TurnoLaboral | None,
) -> tuple[EventoAsistencia, SesionAsistencia, TurnoLaboral] | None:
    """Localiza un check-in abierto del día previo cuando la persona labora turno nocturno."""
    fila = sesion_bd.execute(
        select(EventoAsistencia, SesionAsistencia)
        .join(SesionAsistencia, SesionAsistencia.id == EventoAsistencia.id_sesion)
        .where(
            EventoAsistencia.id_persona == id_persona,
            SesionAsistencia.id_organizacion == id_organizacion,
            SesionAsistencia.tipo_sesion == "workday",
        )
        .order_by(EventoAsistencia.fecha_hora.desc(), EventoAsistencia.id.desc())
    ).first()
    if fila is None:
        return None

    ultimo_evento, sesion_origen = fila
    if ultimo_evento.tipo_evento != "check_in":
        return None
    if sesion_origen.fecha_sesion >= hora_actual.date():
        return None

    # Evita asociar entradas viejas olvidadas más allá de 18 horas continuas
    segundos_transcurridos = (hora_actual - ultimo_evento.fecha_hora).total_seconds()
    if segundos_transcurridos < 0 or segundos_transcurridos > 18 * 3600:
        return None

    turno_resuelto: TurnoLaboral | None = None
    if ultimo_evento.id_turno_laboral is not None:
        turno_resuelto = sesion_bd.get(TurnoLaboral, ultimo_evento.id_turno_laboral)
    if turno_resuelto is None and sesion_origen.id_turno_laboral is not None:
        turno_resuelto = sesion_bd.get(TurnoLaboral, sesion_origen.id_turno_laboral)
    if turno_resuelto is None:
        turno_resuelto = turno_efectivo

    if turno_resuelto is None or not turno_resuelto.cruza_medianoche:
        return None

    return ultimo_evento, sesion_origen, turno_resuelto


def serializar_turnos_lote(
    sesion_bd: Session,
    turnos: list[TurnoLaboral],
    id_organizacion: int,
) -> list[TurnoLaboralLeer]:
    """Serializa turnos laborales con conteos de empleados y departamentos en una sola pasada."""
    if not turnos:
        return []

    organizacion = sesion_bd.get(Organizacion, id_organizacion)
    tolerancia_org = organizacion.minutos_tolerancia_retardo if organizacion else 15

    conteo_empleados = {
        id_turno: int(conteo)
        for id_turno, conteo in sesion_bd.execute(
            select(Persona.id_turno_laboral, func.count(Persona.id))
            .where(
                Persona.id_organizacion == id_organizacion,
                Persona.esta_activo.is_(True),
                Persona.id_turno_laboral.is_not(None),
            )
            .group_by(Persona.id_turno_laboral)
        ).all()
    }
    conteo_grupos = {
        id_turno: int(conteo)
        for id_turno, conteo in sesion_bd.execute(
            select(Grupo.id_turno_laboral_defecto, func.count(Grupo.id))
            .where(
                Grupo.id_organizacion == id_organizacion,
                Grupo.id_turno_laboral_defecto.is_not(None),
            )
            .group_by(Grupo.id_turno_laboral_defecto)
        ).all()
    }

    resultado: list[TurnoLaboralLeer] = []
    for turno in turnos:
        duracion_min = _calcular_duracion_minutos(
            turno.hora_inicio,
            turno.hora_fin,
            turno.cruza_medianoche,
        )
        tolerancia_efectiva = (
            turno.minutos_tolerancia_retardo
            if turno.minutos_tolerancia_retardo is not None
            else tolerancia_org
        )
        resultado.append(
            TurnoLaboralLeer(
                id=turno.id,
                id_organizacion=turno.id_organizacion,
                nombre=turno.nombre,
                codigo=turno.codigo,
                hora_inicio=turno.hora_inicio,
                hora_fin=turno.hora_fin,
                cruza_medianoche=turno.cruza_medianoche,
                duracion_esperada_minutos=duracion_min,
                dias_semana=analizar_dias_semana(turno.dias_semana),
                minutos_tolerancia_retardo=turno.minutos_tolerancia_retardo,
                minutos_tolerancia_retardo_efectiva=tolerancia_efectiva,
                minutos_tolerancia_salida_anticipada=turno.minutos_tolerancia_salida_anticipada,
                esta_activo=turno.esta_activo,
                cantidad_empleados_asignados=conteo_empleados.get(turno.id, 0),
                cantidad_grupos_por_defecto=conteo_grupos.get(turno.id, 0),
                creado_en=turno.creado_en,
            )
        )
    return resultado


def generar_sesiones_turno_para_fecha(
    sesion_bd: Session,
    *,
    id_organizacion: int,
    fecha_objetivo: date,
    id_turno_laboral: int | None = None,
) -> tuple[int, int, list[SesionAsistencia]]:
    """Genera de forma idempotente sesiones `workday` para los turnos del día."""
    if id_turno_laboral is not None:
        turno_objetivo = sesion_bd.get(TurnoLaboral, id_turno_laboral)
        if turno_objetivo is None or turno_objetivo.id_organizacion != id_organizacion:
            raise HTTPException(status_code=404, detail="Turno laboral no encontrado.")
        if not turno_objetivo.esta_activo:
            raise HTTPException(status_code=400, detail="El turno seleccionado está inactivo.")
        turnos = [turno_objetivo]
    else:
        dia_semana = fecha_objetivo.weekday()
        todos_activos = list(
            sesion_bd.scalars(
                select(TurnoLaboral)
                .where(
                    TurnoLaboral.id_organizacion == id_organizacion,
                    TurnoLaboral.esta_activo.is_(True),
                )
                .order_by(TurnoLaboral.hora_inicio.asc(), TurnoLaboral.id.asc())
            ).all()
        )
        turnos = [
            turno for turno in todos_activos if dia_semana in analizar_dias_semana(turno.dias_semana)
        ]

    if not turnos:
        return 0, 0, []

    ids_turnos = [turno.id for turno in turnos]
    sesiones_existentes = list(
        sesion_bd.scalars(
            select(SesionAsistencia)
            .where(
                SesionAsistencia.id_organizacion == id_organizacion,
                SesionAsistencia.fecha_sesion == fecha_objetivo,
                SesionAsistencia.id_turno_laboral.in_(ids_turnos),
            )
            .order_by(SesionAsistencia.id.desc())
        ).all()
    )
    existentes_por_turno: dict[int, SesionAsistencia] = {}
    for sesion in sesiones_existentes:
        if sesion.id_turno_laboral is not None and sesion.id_turno_laboral not in existentes_por_turno:
            existentes_por_turno[sesion.id_turno_laboral] = sesion

    cantidad_creadas = 0
    cantidad_existentes = 0
    sesiones_resultantes: list[SesionAsistencia] = []

    for turno in turnos:
        if turno.id in existentes_por_turno:
            cantidad_existentes += 1
            sesiones_resultantes.append(existentes_por_turno[turno.id])
            continue

        nueva_sesion = SesionAsistencia(
            id_organizacion=id_organizacion,
            id_turno_laboral=turno.id,
            titulo=f"{turno.nombre} ({turno.hora_inicio}-{turno.hora_fin}) — {fecha_objetivo.isoformat()}",
            fecha_sesion=fecha_objetivo,
            tipo_sesion="workday",
            hora_inicio_esperada=turno.hora_inicio,
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


def iniciar_o_obtener_sesion_turno(
    sesion_bd: Session,
    *,
    turno: TurnoLaboral,
    fecha_objetivo: date,
) -> SesionAsistencia:
    """Obtiene la sesión abierta hoy para un turno laboral o crea una nueva lista para kiosco."""
    sesion_abierta = sesion_bd.scalars(
        select(SesionAsistencia)
        .where(
            SesionAsistencia.id_organizacion == turno.id_organizacion,
            SesionAsistencia.id_turno_laboral == turno.id,
            SesionAsistencia.fecha_sesion == fecha_objetivo,
            SesionAsistencia.estado == "open",
        )
        .order_by(SesionAsistencia.id.desc())
    ).first()
    if sesion_abierta is not None:
        return sesion_abierta

    nueva_sesion = SesionAsistencia(
        id_organizacion=turno.id_organizacion,
        id_turno_laboral=turno.id,
        titulo=f"{turno.nombre} ({turno.hora_inicio}-{turno.hora_fin}) — {fecha_objetivo.isoformat()}",
        fecha_sesion=fecha_objetivo,
        tipo_sesion="workday",
        hora_inicio_esperada=turno.hora_inicio,
        estado="open",
    )
    sesion_bd.add(nueva_sesion)
    sesion_bd.commit()
    sesion_bd.refresh(nueva_sesion)
    return nueva_sesion


def calcular_estadisticas_empresariales(
    sesion_bd: Session,
    *,
    id_organizacion: int,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    id_turno_laboral: int | None = None,
    id_grupo: int | None = None,
) -> RespuestaEstadisticasEmpresariales:
    """Calcula estadísticas empresariales de puntualidad, salidas anticipadas, horas y faltas."""
    hoy = date.today()
    hasta_efectiva = fecha_hasta or hoy
    desde_efectiva = fecha_desde or hasta_efectiva
    if desde_efectiva > hasta_efectiva:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La fecha inicial no puede ser posterior a la fecha final.",
        )

    turnos = list(
        sesion_bd.scalars(
            select(TurnoLaboral)
            .where(TurnoLaboral.id_organizacion == id_organizacion)
            .order_by(TurnoLaboral.hora_inicio.asc(), TurnoLaboral.id.asc())
        ).all()
    )
    mapa_turnos = {turno.id: turno for turno in turnos}
    mapa_dias_turno = {turno.id: set(analizar_dias_semana(turno.dias_semana)) for turno in turnos}

    if id_turno_laboral is not None and id_turno_laboral not in mapa_turnos:
        raise HTTPException(status_code=404, detail="Turno laboral no encontrado.")

    grupos = list(
        sesion_bd.scalars(
            select(Grupo)
            .where(Grupo.id_organizacion == id_organizacion)
            .order_by(Grupo.id.asc())
        ).all()
    )
    mapa_grupos = {grupo.id: grupo for grupo in grupos}
    if id_grupo is not None and id_grupo not in mapa_grupos:
        raise HTTPException(status_code=404, detail="Departamento/grupo no encontrado.")

    personas = list(
        sesion_bd.scalars(
            select(Persona)
            .options(selectinload(Persona.enlaces_grupos))
            .where(
                Persona.id_organizacion == id_organizacion,
                Persona.esta_activo.is_(True),
            )
            .order_by(Persona.nombre_completo.asc(), Persona.id.asc())
        ).all()
    )
    if id_grupo is not None:
        personas = [
            persona
            for persona in personas
            if any(enlace.id_grupo == id_grupo for enlace in persona.enlaces_grupos)
        ]

    # Resuelve el turno efectivo por cada empleado (directo o heredado del primer departamento)
    personas_resueltas: list[tuple[Persona, TurnoLaboral | None, OrigenTurno, list[str]]] = []
    for persona in personas:
        ids_grupos_ordenados = sorted(enlace.id_grupo for enlace in persona.enlaces_grupos)
        nombres_grupos = [
            mapa_grupos[gid].nombre for gid in ids_grupos_ordenados if gid in mapa_grupos
        ]

        turno_efectivo: TurnoLaboral | None = None
        origen: OrigenTurno = "none"
        if persona.id_turno_laboral is not None and persona.id_turno_laboral in mapa_turnos:
            turno_efectivo = mapa_turnos[persona.id_turno_laboral]
            origen = "direct"
        else:
            for gid in ids_grupos_ordenados:
                grupo = mapa_grupos.get(gid)
                if (
                    grupo
                    and grupo.id_turno_laboral_defecto
                    and grupo.id_turno_laboral_defecto in mapa_turnos
                ):
                    turno_efectivo = mapa_turnos[grupo.id_turno_laboral_defecto]
                    origen = "group"
                    break

        if id_turno_laboral is not None and (
            turno_efectivo is None or turno_efectivo.id != id_turno_laboral
        ):
            continue
        personas_resueltas.append((persona, turno_efectivo, origen, nombres_grupos))

    ids_personas = [persona.id for persona, _, _, _ in personas_resueltas]
    eventos_por_persona_fecha: dict[tuple[int, date], list[EventoAsistencia]] = defaultdict(list)
    if ids_personas:
        filas = sesion_bd.execute(
            select(EventoAsistencia, SesionAsistencia.fecha_sesion)
            .join(SesionAsistencia, SesionAsistencia.id == EventoAsistencia.id_sesion)
            .where(
                SesionAsistencia.id_organizacion == id_organizacion,
                SesionAsistencia.tipo_sesion == "workday",
                SesionAsistencia.fecha_sesion >= desde_efectiva,
                SesionAsistencia.fecha_sesion <= hasta_efectiva,
                EventoAsistencia.id_persona.in_(ids_personas),
            )
            .order_by(EventoAsistencia.fecha_hora.asc(), EventoAsistencia.id.asc())
        ).all()
        for evento, fecha_sesion in filas:
            eventos_por_persona_fecha[(evento.id_persona, fecha_sesion)].append(evento)

    # Días calendario exigibles (sin exigir días futuros respecto a hoy) dentro del rango
    dias_calendario: list[date] = []
    cursor_fecha = desde_efectiva
    fecha_maxima_exigible = min(hasta_efectiva, hoy)
    while cursor_fecha <= fecha_maxima_exigible:
        dias_calendario.append(cursor_fecha)
        cursor_fecha += timedelta(days=1)

    por_empleado: list[EstadisticaAsistenciaEmpleado] = []
    acumulado_turno: dict[int | None, dict[str, int]] = defaultdict(
        lambda: {
            "empleados": 0,
            "dias_programados": 0,
            "dias_asistidos": 0,
            "dias_puntuales": 0,
            "dias_con_retardo": 0,
            "dias_salida_anticipada": 0,
            "dias_falta": 0,
            "dias_sin_salida": 0,
            "total_minutos_trabajados": 0,
        }
    )

    for persona, turno_efectivo, origen, nombres_grupos in personas_resueltas:
        id_turno = turno_efectivo.id if turno_efectivo else None
        dias_turno = mapa_dias_turno.get(id_turno, set()) if id_turno is not None else set()

        dias_programados = 0
        dias_asistidos = 0
        dias_puntuales = 0
        dias_con_retardo = 0
        dias_salida_anticipada = 0
        dias_falta = 0
        dias_sin_salida = 0
        total_minutos_retardo = 0
        total_minutos_salida_anticipada = 0
        total_minutos_trabajados = 0

        fechas_con_eventos = {
            fecha_ev
            for (pid, fecha_ev) in eventos_por_persona_fecha.keys()
            if pid == persona.id
        }
        fechas_programadas: set[date] = set()
        if turno_efectivo is not None:
            for dia_cal in dias_calendario:
                if dia_cal.weekday() in dias_turno:
                    fechas_programadas.add(dia_cal)
        dias_programados = len(fechas_programadas)

        fechas_a_revisar = sorted(fechas_programadas | fechas_con_eventos)
        for fecha_dia in fechas_a_revisar:
            eventos_dia = eventos_por_persona_fecha.get((persona.id, fecha_dia), [])
            entradas = [ev for ev in eventos_dia if ev.tipo_evento in ("check_in", "present")]
            salidas = [ev for ev in eventos_dia if ev.tipo_evento == "check_out"]

            if not entradas:
                if fecha_dia in fechas_programadas:
                    dias_falta += 1
                continue

            dias_asistidos += 1
            primera_entrada = entradas[0]
            if primera_entrada.estado == "late":
                dias_con_retardo += 1
                total_minutos_retardo += primera_entrada.minutos_retardo or 0
            else:
                dias_puntuales += 1

            if not salidas:
                dias_sin_salida += 1
            else:
                ultima_salida = salidas[-1]
                if ultima_salida.estado == "early_exit":
                    dias_salida_anticipada += 1
                    total_minutos_salida_anticipada += (
                        ultima_salida.minutos_salida_anticipada or 0
                    )

                trabajado_dia = sum(salida.minutos_trabajados or 0 for salida in salidas)
                if trabajado_dia == 0 and ultima_salida.fecha_hora >= primera_entrada.fecha_hora:
                    trabajado_dia = int(
                        (ultima_salida.fecha_hora - primera_entrada.fecha_hora).total_seconds()
                        // 60
                    )
                total_minutos_trabajados += max(0, trabajado_dia)

        if dias_programados > 0:
            tasa_asistencia = min(100.0, round((dias_asistidos / dias_programados) * 100.0, 2))
        elif dias_asistidos > 0:
            tasa_asistencia = 100.0
        else:
            tasa_asistencia = 0.0

        tasa_puntualidad = (
            round((dias_puntuales / dias_asistidos) * 100.0, 2) if dias_asistidos > 0 else 0.0
        )

        por_empleado.append(
            EstadisticaAsistenciaEmpleado(
                id_persona=persona.id,
                identificador_externo=persona.identificador_externo,
                nombre_completo=persona.nombre_completo,
                nombres_grupos=nombres_grupos,
                id_turno_laboral=id_turno,
                nombre_turno=turno_efectivo.nombre if turno_efectivo else None,
                codigo_turno=turno_efectivo.codigo if turno_efectivo else None,
                origen_turno=origen,
                dias_programados=dias_programados,
                dias_asistidos=dias_asistidos,
                dias_puntuales=dias_puntuales,
                dias_con_retardo=dias_con_retardo,
                dias_salida_anticipada=dias_salida_anticipada,
                dias_falta=dias_falta,
                dias_sin_salida=dias_sin_salida,
                total_minutos_retardo=total_minutos_retardo,
                total_minutos_salida_anticipada=total_minutos_salida_anticipada,
                total_minutos_trabajados=total_minutos_trabajados,
                tasa_asistencia=tasa_asistencia,
                tasa_puntualidad=tasa_puntualidad,
            )
        )

        acumulador = acumulado_turno[id_turno]
        acumulador["empleados"] += 1
        acumulador["dias_programados"] += dias_programados
        acumulador["dias_asistidos"] += dias_asistidos
        acumulador["dias_puntuales"] += dias_puntuales
        acumulador["dias_con_retardo"] += dias_con_retardo
        acumulador["dias_salida_anticipada"] += dias_salida_anticipada
        acumulador["dias_falta"] += dias_falta
        acumulador["dias_sin_salida"] += dias_sin_salida
        acumulador["total_minutos_trabajados"] += total_minutos_trabajados

    por_turno: list[EstadisticaAsistenciaTurno] = []
    turnos_objetivo = [mapa_turnos[id_turno_laboral]] if id_turno_laboral is not None else turnos
    for turno in turnos_objetivo:
        acumulador = acumulado_turno.get(
            turno.id,
            {
                "empleados": 0,
                "dias_programados": 0,
                "dias_asistidos": 0,
                "dias_puntuales": 0,
                "dias_con_retardo": 0,
                "dias_salida_anticipada": 0,
                "dias_falta": 0,
                "dias_sin_salida": 0,
                "total_minutos_trabajados": 0,
            },
        )
        programados = acumulador["dias_programados"]
        asistidos = acumulador["dias_asistidos"]
        tasa_asist_turno = (
            min(100.0, round((asistidos / programados) * 100.0, 2))
            if programados > 0
            else (100.0 if asistidos > 0 else 0.0)
        )
        tasa_punt_turno = (
            round((acumulador["dias_puntuales"] / asistidos) * 100.0, 2)
            if asistidos > 0
            else 0.0
        )
        promedio_trabajado = (
            round(acumulador["total_minutos_trabajados"] / asistidos, 1)
            if asistidos > 0
            else 0.0
        )
        por_turno.append(
            EstadisticaAsistenciaTurno(
                id_turno_laboral=turno.id,
                nombre_turno=turno.nombre,
                codigo_turno=turno.codigo,
                hora_inicio=turno.hora_inicio,
                hora_fin=turno.hora_fin,
                cruza_medianoche=turno.cruza_medianoche,
                dias_semana=analizar_dias_semana(turno.dias_semana),
                cantidad_empleados=acumulador["empleados"],
                dias_programados=programados,
                dias_asistidos=asistidos,
                dias_puntuales=acumulador["dias_puntuales"],
                dias_con_retardo=acumulador["dias_con_retardo"],
                dias_salida_anticipada=acumulador["dias_salida_anticipada"],
                dias_falta=acumulador["dias_falta"],
                dias_sin_salida=acumulador["dias_sin_salida"],
                total_minutos_trabajados=acumulador["total_minutos_trabajados"],
                promedio_minutos_trabajados=promedio_trabajado,
                tasa_asistencia=tasa_asist_turno,
                tasa_puntualidad=tasa_punt_turno,
            )
        )

    if id_turno_laboral is None and None in acumulado_turno:
        acumulador = acumulado_turno[None]
        asistidos = acumulador["dias_asistidos"]
        por_turno.append(
            EstadisticaAsistenciaTurno(
                id_turno_laboral=None,
                nombre_turno="Sin turno asignado",
                codigo_turno=None,
                hora_inicio=None,
                hora_fin=None,
                cruza_medianoche=False,
                dias_semana=[],
                cantidad_empleados=acumulador["empleados"],
                dias_programados=0,
                dias_asistidos=asistidos,
                dias_puntuales=acumulador["dias_puntuales"],
                dias_con_retardo=acumulador["dias_con_retardo"],
                dias_salida_anticipada=acumulador["dias_salida_anticipada"],
                dias_falta=0,
                dias_sin_salida=acumulador["dias_sin_salida"],
                total_minutos_trabajados=acumulador["total_minutos_trabajados"],
                promedio_minutos_trabajados=(
                    round(acumulador["total_minutos_trabajados"] / asistidos, 1)
                    if asistidos > 0
                    else 0.0
                ),
                tasa_asistencia=100.0 if asistidos > 0 else 0.0,
                tasa_puntualidad=(
                    round((acumulador["dias_puntuales"] / asistidos) * 100.0, 2)
                    if asistidos > 0
                    else 0.0
                ),
            )
        )

    total_empleados = len(personas_resueltas)
    empleados_sin_turno = sum(1 for _, turno_ef, _, _ in personas_resueltas if turno_ef is None)
    empleados_asignados = total_empleados - empleados_sin_turno

    total_programados = sum(emp.dias_programados for emp in por_empleado)
    total_asistidos = sum(emp.dias_asistidos for emp in por_empleado)
    total_puntuales = sum(emp.dias_puntuales for emp in por_empleado)
    total_retardos = sum(emp.dias_con_retardo for emp in por_empleado)
    total_salidas_anticipadas = sum(emp.dias_salida_anticipada for emp in por_empleado)
    total_faltas = sum(emp.dias_falta for emp in por_empleado)
    total_sin_salida = sum(emp.dias_sin_salida for emp in por_empleado)
    total_trabajados = sum(emp.total_minutos_trabajados for emp in por_empleado)

    tasa_asistencia_global = (
        min(100.0, round((total_asistidos / total_programados) * 100.0, 2))
        if total_programados > 0
        else (100.0 if total_asistidos > 0 else 0.0)
    )
    tasa_puntualidad_global = (
        round((total_puntuales / total_asistidos) * 100.0, 2) if total_asistidos > 0 else 0.0
    )

    resumen = ResumenEstadisticasEmpresariales(
        total_turnos=len(turnos),
        turnos_activos=sum(1 for turno in turnos if turno.esta_activo),
        total_empleados=total_empleados,
        empleados_asignados=empleados_asignados,
        empleados_sin_turno=empleados_sin_turno,
        dias_empleado_programados=total_programados,
        dias_asistidos=total_asistidos,
        dias_puntuales=total_puntuales,
        dias_con_retardo=total_retardos,
        dias_salida_anticipada=total_salidas_anticipadas,
        dias_falta=total_faltas,
        dias_sin_salida=total_sin_salida,
        total_minutos_trabajados=total_trabajados,
        tasa_asistencia=tasa_asistencia_global,
        tasa_puntualidad=tasa_puntualidad_global,
    )

    return RespuestaEstadisticasEmpresariales(
        id_organizacion=id_organizacion,
        fecha_desde=desde_efectiva,
        fecha_hasta=hasta_efectiva,
        resumen=resumen,
        por_turno=por_turno,
        por_empleado=por_empleado,
    )
