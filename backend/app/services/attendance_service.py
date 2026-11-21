"""Servicio de registro de asistencia escolar y empresarial y exportación CSV.

Aplica enfriamiento (cooldown) entre lecturas biométricas consecutivas,
previene duplicados en pase de lista escolar, gestiona secuencias entrada/salida
en empresas (incluyendo turnos nocturnos de la jornada previa) y genera archivos
CSV con BOM UTF-8 listos para abrir en Excel.
"""

import csv
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import io
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EventoAsistencia, Grupo, Organizacion, Persona, SesionAsistencia
from app.services.enterprise_service import (
    buscar_entrada_nocturna_abierta,
    evaluar_entrada_turno,
    evaluar_salida_turno,
    resolver_turno_para_asistencia,
)


@dataclass(frozen=True)
class ResultadoRegistroAsistencia:
    """Resultado de intentar registrar un evento biométrico de asistencia."""

    accion: str  # "recorded" | "cooldown" | "already_present" | "invalid_sequence"
    evento: EventoAsistencia | None
    minutos_trabajados: int | None
    mensaje: str
    nombre_turno: str | None = None
    minutos_retardo: int | None = None
    minutos_salida_anticipada: int | None = None


def _normalizar_fecha_hora(valor: datetime | None) -> datetime:
    """Convierte un `datetime` opcional a hora local ingenua (sin tzinfo)."""
    if valor is None:
        return datetime.now()
    if valor.tzinfo is not None:
        return valor.astimezone().replace(tzinfo=None)
    return valor


def _calcular_puntualidad_sesion(
    sesion: SesionAsistencia,
    organizacion: Organizacion,
    hora_actual: datetime,
) -> str:
    """Determina si una llegada es `'on_time'` o `'late'` respecto a la sesión y tolerancia."""
    if not sesion.hora_inicio_esperada:
        return "on_time"
    try:
        hora_txt, minuto_txt = sesion.hora_inicio_esperada.split(":")
        hora_esperada = time(hour=int(hora_txt), minute=int(minuto_txt))
    except (ValueError, TypeError):
        return "on_time"

    fecha_limite = datetime.combine(sesion.fecha_sesion, hora_esperada) + timedelta(
        minutes=organizacion.minutos_tolerancia_retardo
    )
    return "late" if hora_actual > fecha_limite else "on_time"


def obtener_o_crear_sesion_activa(
    sesion_bd: Session,
    organizacion: Organizacion,
    id_grupo: int | None = None,
    fecha_objetivo: date | None = None,
) -> SesionAsistencia:
    """Obtiene la sesión abierta del día para el kiosco o crea una automáticamente."""
    hoy = fecha_objetivo or date.today()
    consulta = (
        select(SesionAsistencia)
        .where(
            SesionAsistencia.id_organizacion == organizacion.id,
            SesionAsistencia.fecha_sesion == hoy,
            SesionAsistencia.estado == "open",
            SesionAsistencia.id_grupo == id_grupo
            if id_grupo is not None
            else SesionAsistencia.id_grupo.is_(None),
        )
        .order_by(SesionAsistencia.id.desc())
    )
    existente = sesion_bd.scalars(consulta).first()
    if existente is not None:
        return existente

    hora_inicio_esperada: str | None = None
    if id_grupo is not None:
        grupo = sesion_bd.get(Grupo, id_grupo)
        if grupo is None or grupo.id_organizacion != organizacion.id:
            raise ValueError("El grupo indicado no pertenece a la organización.")
        hora_inicio_esperada = grupo.hora_inicio_horario
        titulo = f"{grupo.nombre} ({hoy.isoformat()})"
    else:
        prefijo = "Pase de lista" if organizacion.modo == "education" else "Jornada"
        titulo = f"{prefijo} {hoy.isoformat()}"

    nueva_sesion = SesionAsistencia(
        id_organizacion=organizacion.id,
        id_grupo=id_grupo,
        titulo=titulo,
        fecha_sesion=hoy,
        tipo_sesion="class" if organizacion.modo == "education" else "workday",
        hora_inicio_esperada=hora_inicio_esperada,
        estado="open",
    )
    sesion_bd.add(nueva_sesion)
    sesion_bd.commit()
    sesion_bd.refresh(nueva_sesion)
    return nueva_sesion


def registrar_asistencia_reconocida(
    sesion_bd: Session,
    organizacion: Organizacion,
    sesion: SesionAsistencia,
    persona: Persona,
    puntaje_confianza: float,
    modo_accion: str = "auto",
    modo_captura: str = "kiosk_individual",
    ahora: datetime | None = None,
) -> ResultadoRegistroAsistencia:
    """Registra entrada/salida o asistencia escolar aplicando cooldown y reglas de modo."""
    hora_actual = _normalizar_fecha_hora(ahora)
    es_flujo_educativo = organizacion.modo == "education" or modo_accion == "present"

    ultimo_evento = sesion_bd.scalars(
        select(EventoAsistencia)
        .where(
            EventoAsistencia.id_sesion == sesion.id,
            EventoAsistencia.id_persona == persona.id,
        )
        .order_by(EventoAsistencia.fecha_hora.desc(), EventoAsistencia.id.desc())
    ).first()

    if es_flujo_educativo:
        if ultimo_evento is not None:
            segundos_transcurridos = (hora_actual - ultimo_evento.fecha_hora).total_seconds()
            if 0 <= segundos_transcurridos < organizacion.segundos_enfriamiento:
                restantes = max(1, int(round(organizacion.segundos_enfriamiento - segundos_transcurridos)))
                return ResultadoRegistroAsistencia(
                    accion="cooldown",
                    evento=ultimo_evento,
                    minutos_trabajados=None,
                    mensaje=(
                        f"{persona.nombre_completo} ya registró un movimiento hace poco. "
                        f"Espera {restantes}s."
                    ),
                )

        asistencia_previa = sesion_bd.scalars(
            select(EventoAsistencia).where(
                EventoAsistencia.id_sesion == sesion.id,
                EventoAsistencia.id_persona == persona.id,
                EventoAsistencia.tipo_evento == "present",
            )
        ).first()
        if asistencia_previa is not None:
            return ResultadoRegistroAsistencia(
                accion="already_present",
                evento=asistencia_previa,
                minutos_trabajados=None,
                mensaje=f"{persona.nombre_completo} ya tiene asistencia registrada en esta sesión.",
            )

        estado_puntualidad = _calcular_puntualidad_sesion(sesion, organizacion, hora_actual)
        evento = EventoAsistencia(
            id_sesion=sesion.id,
            id_persona=persona.id,
            tipo_evento="present",
            estado=estado_puntualidad,
            puntaje_confianza=round(puntaje_confianza, 4),
            modo_captura=modo_captura,
            fecha_hora=hora_actual,
        )
        sesion_bd.add(evento)
        sesion_bd.commit()
        sesion_bd.refresh(evento)
        etiqueta = "A tiempo" if estado_puntualidad == "on_time" else "Retardo"
        return ResultadoRegistroAsistencia(
            accion="recorded",
            evento=evento,
            minutos_trabajados=None,
            mensaje=f"Asistencia registrada para {persona.nombre_completo} ({etiqueta}).",
        )

    # Modo empresarial: entrada/salida con turnos laborales y soporte de cruce de medianoche
    turno_efectivo = resolver_turno_para_asistencia(sesion_bd, persona, sesion)
    sesion_objetivo = sesion

    if ultimo_evento is None and modo_accion in ("auto", "check_out"):
        jornada_nocturna = buscar_entrada_nocturna_abierta(
            sesion_bd,
            organizacion.id,
            persona.id,
            hora_actual,
            turno_efectivo,
        )
        if jornada_nocturna is not None:
            evento_origen, sesion_origen, turno_origen = jornada_nocturna
            ultimo_evento = evento_origen
            sesion_objetivo = sesion_origen
            turno_efectivo = turno_origen

    if ultimo_evento is not None:
        segundos_transcurridos = (hora_actual - ultimo_evento.fecha_hora).total_seconds()
        if 0 <= segundos_transcurridos < organizacion.segundos_enfriamiento:
            restantes = max(1, int(round(organizacion.segundos_enfriamiento - segundos_transcurridos)))
            return ResultadoRegistroAsistencia(
                accion="cooldown",
                evento=ultimo_evento,
                minutos_trabajados=None,
                nombre_turno=turno_efectivo.nombre if turno_efectivo else None,
                mensaje=(
                    f"{persona.nombre_completo} ya registró un movimiento hace poco. "
                    f"Espera {restantes}s."
                ),
            )

    if modo_accion == "auto":
        if ultimo_evento is None or ultimo_evento.tipo_evento == "check_out":
            tipo_objetivo = "check_in"
        else:
            tipo_objetivo = "check_out"
    else:
        if (
            modo_accion == "check_in"
            and ultimo_evento is not None
            and ultimo_evento.tipo_evento == "check_in"
        ):
            return ResultadoRegistroAsistencia(
                accion="invalid_sequence",
                evento=ultimo_evento,
                minutos_trabajados=None,
                nombre_turno=turno_efectivo.nombre if turno_efectivo else None,
                mensaje=f"{persona.nombre_completo} ya tiene una entrada activa sin salida.",
            )
        if modo_accion == "check_out" and (
            ultimo_evento is None or ultimo_evento.tipo_evento != "check_in"
        ):
            return ResultadoRegistroAsistencia(
                accion="invalid_sequence",
                evento=ultimo_evento,
                minutos_trabajados=None,
                nombre_turno=turno_efectivo.nombre if turno_efectivo else None,
                mensaje=f"{persona.nombre_completo} no tiene una entrada previa para registrar salida.",
            )
        tipo_objetivo = modo_accion

    minutos_trabajados: int | None = None
    minutos_retardo: int | None = None
    minutos_salida_anticipada: int | None = None

    if tipo_objetivo == "check_in":
        if turno_efectivo is not None:
            estado_evento, minutos_retardo = evaluar_entrada_turno(
                turno_efectivo, organizacion, sesion_objetivo.fecha_sesion, hora_actual
            )
        else:
            estado_evento = _calcular_puntualidad_sesion(sesion_objetivo, organizacion, hora_actual)
    else:
        if ultimo_evento is not None and ultimo_evento.tipo_evento == "check_in":
            minutos_trabajados = max(
                0,
                int((hora_actual - ultimo_evento.fecha_hora).total_seconds() // 60),
            )
        if turno_efectivo is not None:
            estado_evento, minutos_salida_anticipada = evaluar_salida_turno(
                turno_efectivo, sesion_objetivo.fecha_sesion, hora_actual
            )
        else:
            estado_evento = "on_time"

    evento = EventoAsistencia(
        id_sesion=sesion_objetivo.id,
        id_persona=persona.id,
        id_turno_laboral=turno_efectivo.id if turno_efectivo else None,
        tipo_evento=tipo_objetivo,
        estado=estado_evento,
        puntaje_confianza=round(puntaje_confianza, 4),
        minutos_trabajados=minutos_trabajados,
        minutos_retardo=minutos_retardo,
        minutos_salida_anticipada=minutos_salida_anticipada,
        modo_captura=modo_captura,
        fecha_hora=hora_actual,
    )
    sesion_bd.add(evento)
    sesion_bd.commit()
    sesion_bd.refresh(evento)

    nombre_turno = turno_efectivo.nombre if turno_efectivo else None
    if tipo_objetivo == "check_in":
        if turno_efectivo is not None:
            if estado_evento == "late":
                mensaje_resultado = (
                    f"Entrada registrada: {persona.nombre_completo} "
                    f"(Retardo +{minutos_retardo} min · {turno_efectivo.nombre})."
                )
            else:
                mensaje_resultado = (
                    f"Entrada registrada: {persona.nombre_completo} "
                    f"(A tiempo · {turno_efectivo.nombre})."
                )
        else:
            etiqueta = "A tiempo" if estado_evento == "on_time" else "Retardo"
            mensaje_resultado = f"Entrada registrada: {persona.nombre_completo} ({etiqueta})."
    else:
        if turno_efectivo is not None and estado_evento == "early_exit":
            mensaje_resultado = (
                f"Salida anticipada registrada: {persona.nombre_completo} "
                f"(-{minutos_salida_anticipada} min · {turno_efectivo.nombre})."
            )
        elif turno_efectivo is not None:
            mensaje_resultado = (
                f"Salida registrada: {persona.nombre_completo} ({turno_efectivo.nombre})."
            )
        else:
            mensaje_resultado = f"Salida registrada: {persona.nombre_completo}."
        if minutos_trabajados is not None:
            mensaje_resultado += f" Tiempo en jornada: {minutos_trabajados} min."

    return ResultadoRegistroAsistencia(
        accion="recorded",
        evento=evento,
        minutos_trabajados=minutos_trabajados,
        mensaje=mensaje_resultado,
        nombre_turno=nombre_turno,
        minutos_retardo=minutos_retardo,
        minutos_salida_anticipada=minutos_salida_anticipada,
    )


def exportar_eventos_csv(
    filas: list[tuple[EventoAsistencia, Persona, SesionAsistencia]],
    nombres_turnos: dict[int, str] | None = None,
) -> str:
    """Exporta registros de asistencia a CSV con BOM UTF-8 compatible con Excel."""
    bufer = io.StringIO()
    bufer.write("\ufeff")
    escritor = csv.writer(bufer)
    escritor.writerow(
        [
            "ID Evento",
            "Fecha y Hora",
            "Sesión",
            "ID Externo",
            "Nombre Completo",
            "Rol",
            "Tipo de Evento",
            "Estado",
            "Turno",
            "Minutos Trabajados",
            "Minutos Retardo",
            "Minutos Salida Anticipada",
            "Modo de Captura",
            "Confianza (%)",
            "Notas",
        ]
    )
    turnos_resueltos = nombres_turnos or {}
    for evento, persona, sesion in filas:
        porcentaje_confianza = (
            f"{evento.puntaje_confianza * 100:.1f}" if evento.puntaje_confianza is not None else ""
        )
        id_turno = evento.id_turno_laboral or sesion.id_turno_laboral
        nombre_turno = turnos_resueltos.get(id_turno, "") if id_turno is not None else ""
        escritor.writerow(
            [
                evento.id,
                evento.fecha_hora.strftime("%Y-%m-%d %H:%M:%S"),
                sesion.titulo,
                persona.identificador_externo,
                persona.nombre_completo,
                persona.rol,
                evento.tipo_evento,
                evento.estado,
                nombre_turno,
                evento.minutos_trabajados if evento.minutos_trabajados is not None else "",
                (
                    evento.minutos_retardo
                    if evento.minutos_retardo is not None and evento.minutos_retardo > 0
                    else ""
                ),
                (
                    evento.minutos_salida_anticipada
                    if evento.minutos_salida_anticipada is not None
                    and evento.minutos_salida_anticipada > 0
                    else ""
                ),
                evento.modo_captura,
                porcentaje_confianza,
                evento.notas or "",
            ]
        )
    return bufer.getvalue()
