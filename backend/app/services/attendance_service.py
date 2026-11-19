import csv
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import io
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AttendanceEvent, AttendanceSession, Group, Organization, Person


@dataclass(frozen=True)
class AttendanceRecordResult:
    """Resultado de intentar registrar un evento de asistencia."""

    action: str  # "recorded" | "cooldown" | "already_present" | "invalid_sequence"
    event: AttendanceEvent | None
    worked_minutes: int | None
    message: str


def _normalize_dt(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now()
    if value.tzinfo is not None:
        return value.astimezone().replace(tzinfo=None)
    return value


def _compute_punctuality(
    session: AttendanceSession,
    organization: Organization,
    current_time: datetime,
) -> str:
    if not session.expected_start_time:
        return "on_time"
    try:
        hour_str, minute_str = session.expected_start_time.split(":")
        expected_t = time(hour=int(hour_str), minute=int(minute_str))
    except (ValueError, TypeError):
        return "on_time"

    deadline = datetime.combine(session.session_date, expected_t) + timedelta(
        minutes=organization.late_tolerance_minutes
    )
    return "late" if current_time > deadline else "on_time"


def get_or_create_active_session(
    db: Session,
    organization: Organization,
    group_id: int | None = None,
    target_date: date | None = None,
) -> AttendanceSession:
    """Obtiene la sesión abierta del día o crea una automáticamente para el kiosco."""
    today = target_date or date.today()
    stmt = (
        select(AttendanceSession)
        .where(
            AttendanceSession.organization_id == organization.id,
            AttendanceSession.session_date == today,
            AttendanceSession.status == "open",
            AttendanceSession.group_id == group_id
            if group_id is not None
            else AttendanceSession.group_id.is_(None),
        )
        .order_by(AttendanceSession.id.desc())
    )
    existing = db.scalars(stmt).first()
    if existing is not None:
        return existing

    expected_start_time: str | None = None
    if group_id is not None:
        group = db.get(Group, group_id)
        if group is None or group.organization_id != organization.id:
            raise ValueError("El grupo indicado no pertenece a la organización.")
        expected_start_time = group.schedule_start
        title = f"{group.name} ({today.isoformat()})"
    else:
        prefix = "Pase de lista" if organization.mode == "education" else "Jornada"
        title = f"{prefix} {today.isoformat()}"

    session = AttendanceSession(
        organization_id=organization.id,
        group_id=group_id,
        title=title,
        session_date=today,
        session_type="class" if organization.mode == "education" else "workday",
        expected_start_time=expected_start_time,
        status="open",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def record_recognized_attendance(
    db: Session,
    organization: Organization,
    session: AttendanceSession,
    person: Person,
    confidence_score: float,
    action_mode: str = "auto",
    capture_mode: str = "kiosk_individual",
    now: datetime | None = None,
) -> AttendanceRecordResult:
    """Registra entrada/salida o asistencia escolar aplicando cooldown y reglas de modo."""
    current_time = _normalize_dt(now)

    last_event = db.scalars(
        select(AttendanceEvent)
        .where(
            AttendanceEvent.session_id == session.id,
            AttendanceEvent.person_id == person.id,
        )
        .order_by(AttendanceEvent.timestamp.desc(), AttendanceEvent.id.desc())
    ).first()

    if last_event is not None:
        elapsed = (current_time - last_event.timestamp).total_seconds()
        if 0 <= elapsed < organization.cooldown_seconds:
            remaining = max(1, int(round(organization.cooldown_seconds - elapsed)))
            return AttendanceRecordResult(
                action="cooldown",
                event=last_event,
                worked_minutes=None,
                message=(
                    f"{person.full_name} ya registró un movimiento hace poco. "
                    f"Espera {remaining}s."
                ),
            )

    is_education_flow = organization.mode == "education" or action_mode == "present"
    if is_education_flow:
        existing_present = db.scalars(
            select(AttendanceEvent).where(
                AttendanceEvent.session_id == session.id,
                AttendanceEvent.person_id == person.id,
                AttendanceEvent.event_type == "present",
            )
        ).first()
        if existing_present is not None:
            return AttendanceRecordResult(
                action="already_present",
                event=existing_present,
                worked_minutes=None,
                message=f"{person.full_name} ya tiene asistencia registrada en esta sesión.",
            )

        status = _compute_punctuality(session, organization, current_time)
        event = AttendanceEvent(
            session_id=session.id,
            person_id=person.id,
            event_type="present",
            status=status,
            confidence_score=round(confidence_score, 4),
            capture_mode=capture_mode,
            timestamp=current_time,
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        label = "A tiempo" if status == "on_time" else "Retardo"
        return AttendanceRecordResult(
            action="recorded",
            event=event,
            worked_minutes=None,
            message=f"Asistencia registrada para {person.full_name} ({label}).",
        )

    # Modo empresarial (check_in / check_out)
    if action_mode == "auto":
        if last_event is None or last_event.event_type == "check_out":
            target_type = "check_in"
        else:
            target_type = "check_out"
    else:
        if action_mode == "check_in" and last_event is not None and last_event.event_type == "check_in":
            return AttendanceRecordResult(
                action="invalid_sequence",
                event=last_event,
                worked_minutes=None,
                message=f"{person.full_name} ya tiene una entrada activa sin salida.",
            )
        if action_mode == "check_out" and (last_event is None or last_event.event_type != "check_in"):
            return AttendanceRecordResult(
                action="invalid_sequence",
                event=last_event,
                worked_minutes=None,
                message=f"{person.full_name} no tiene una entrada previa para registrar salida.",
            )
        target_type = action_mode

    worked_minutes: int | None = None
    if target_type == "check_in":
        status = _compute_punctuality(session, organization, current_time)
    else:
        status = "on_time"
        if last_event is not None and last_event.event_type == "check_in":
            worked_minutes = max(0, int((current_time - last_event.timestamp).total_seconds() // 60))

    event = AttendanceEvent(
        session_id=session.id,
        person_id=person.id,
        event_type=target_type,
        status=status,
        confidence_score=round(confidence_score, 4),
        capture_mode=capture_mode,
        timestamp=current_time,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    if target_type == "check_in":
        label = "A tiempo" if status == "on_time" else "Retardo"
        msg = f"Entrada registrada: {person.full_name} ({label})."
    else:
        msg = f"Salida registrada: {person.full_name}."
        if worked_minutes is not None:
            msg += f" Tiempo en jornada: {worked_minutes} min."

    return AttendanceRecordResult(
        action="recorded",
        event=event,
        worked_minutes=worked_minutes,
        message=msg,
    )


def export_events_csv(rows: list[tuple[AttendanceEvent, Person, AttendanceSession]]) -> str:
    """Exporta registros de asistencia a CSV con BOM UTF-8 compatible con Excel."""
    buffer = io.StringIO()
    buffer.write("\ufeff")
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "ID Evento",
            "Fecha y Hora",
            "Sesión",
            "ID Externo",
            "Nombre Completo",
            "Rol",
            "Tipo de Evento",
            "Estado",
            "Modo de Captura",
            "Confianza (%)",
            "Notas",
        ]
    )
    for event, person, session in rows:
        conf_pct = f"{event.confidence_score * 100:.1f}" if event.confidence_score is not None else ""
        writer.writerow(
            [
                event.id,
                event.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                session.title,
                person.external_id,
                person.full_name,
                person.role,
                event.event_type,
                event.status,
                event.capture_mode,
                conf_pct,
                event.notes or "",
            ]
        )
    return buffer.getvalue()
