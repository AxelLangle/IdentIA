import csv
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import io
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AttendanceEvent, AttendanceSession, Group, Organization, Person
from app.services.enterprise_service import (
    evaluate_shift_check_in,
    evaluate_shift_check_out,
    find_open_overnight_checkin,
    resolve_attendance_work_shift,
)


@dataclass(frozen=True)
class AttendanceRecordResult:
    """Resultado de intentar registrar un evento de asistencia."""

    action: str  # "recorded" | "cooldown" | "already_present" | "invalid_sequence"
    event: AttendanceEvent | None
    worked_minutes: int | None
    message: str
    shift_name: str | None = None
    late_minutes: int | None = None
    early_exit_minutes: int | None = None


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
    is_education_flow = organization.mode == "education" or action_mode == "present"

    last_event = db.scalars(
        select(AttendanceEvent)
        .where(
            AttendanceEvent.session_id == session.id,
            AttendanceEvent.person_id == person.id,
        )
        .order_by(AttendanceEvent.timestamp.desc(), AttendanceEvent.id.desc())
    ).first()

    if is_education_flow:
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

    # Modo empresarial (check_in / check_out con soporte de turnos y cruce de medianoche)
    effective_shift = resolve_attendance_work_shift(db, person, session)
    target_session = session

    if last_event is None and action_mode in ("auto", "check_out"):
        overnight = find_open_overnight_checkin(
            db,
            organization.id,
            person.id,
            current_time,
            effective_shift,
        )
        if overnight is not None:
            origin_event, origin_session, origin_shift = overnight
            last_event = origin_event
            target_session = origin_session
            effective_shift = origin_shift

    if last_event is not None:
        elapsed = (current_time - last_event.timestamp).total_seconds()
        if 0 <= elapsed < organization.cooldown_seconds:
            remaining = max(1, int(round(organization.cooldown_seconds - elapsed)))
            return AttendanceRecordResult(
                action="cooldown",
                event=last_event,
                worked_minutes=None,
                shift_name=effective_shift.name if effective_shift else None,
                message=(
                    f"{person.full_name} ya registró un movimiento hace poco. "
                    f"Espera {remaining}s."
                ),
            )

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
                shift_name=effective_shift.name if effective_shift else None,
                message=f"{person.full_name} ya tiene una entrada activa sin salida.",
            )
        if action_mode == "check_out" and (last_event is None or last_event.event_type != "check_in"):
            return AttendanceRecordResult(
                action="invalid_sequence",
                event=last_event,
                worked_minutes=None,
                shift_name=effective_shift.name if effective_shift else None,
                message=f"{person.full_name} no tiene una entrada previa para registrar salida.",
            )
        target_type = action_mode

    worked_minutes: int | None = None
    late_minutes: int | None = None
    early_exit_minutes: int | None = None

    if target_type == "check_in":
        if effective_shift is not None:
            status, late_minutes = evaluate_shift_check_in(
                effective_shift, organization, target_session.session_date, current_time
            )
        else:
            status = _compute_punctuality(target_session, organization, current_time)
    else:
        if last_event is not None and last_event.event_type == "check_in":
            worked_minutes = max(0, int((current_time - last_event.timestamp).total_seconds() // 60))
        if effective_shift is not None:
            status, early_exit_minutes = evaluate_shift_check_out(
                effective_shift, target_session.session_date, current_time
            )
        else:
            status = "on_time"

    event = AttendanceEvent(
        session_id=target_session.id,
        person_id=person.id,
        work_shift_id=effective_shift.id if effective_shift else None,
        event_type=target_type,
        status=status,
        confidence_score=round(confidence_score, 4),
        worked_minutes=worked_minutes,
        late_minutes=late_minutes,
        early_exit_minutes=early_exit_minutes,
        capture_mode=capture_mode,
        timestamp=current_time,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    shift_label = effective_shift.name if effective_shift else None
    if target_type == "check_in":
        if effective_shift is not None:
            if status == "late":
                msg = f"Entrada registrada: {person.full_name} (Retardo +{late_minutes} min · {effective_shift.name})."
            else:
                msg = f"Entrada registrada: {person.full_name} (A tiempo · {effective_shift.name})."
        else:
            label = "A tiempo" if status == "on_time" else "Retardo"
            msg = f"Entrada registrada: {person.full_name} ({label})."
    else:
        if effective_shift is not None and status == "early_exit":
            msg = f"Salida anticipada registrada: {person.full_name} (-{early_exit_minutes} min · {effective_shift.name})."
        elif effective_shift is not None:
            msg = f"Salida registrada: {person.full_name} ({effective_shift.name})."
        else:
            msg = f"Salida registrada: {person.full_name}."
        if worked_minutes is not None:
            msg += f" Tiempo en jornada: {worked_minutes} min."

    return AttendanceRecordResult(
        action="recorded",
        event=event,
        worked_minutes=worked_minutes,
        message=msg,
        shift_name=shift_label,
        late_minutes=late_minutes,
        early_exit_minutes=early_exit_minutes,
    )


def export_events_csv(
    rows: list[tuple[AttendanceEvent, Person, AttendanceSession]],
    shift_names: dict[int, str] | None = None,
) -> str:
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
            "Turno",
            "Minutos Trabajados",
            "Minutos Retardo",
            "Minutos Salida Anticipada",
            "Modo de Captura",
            "Confianza (%)",
            "Notas",
        ]
    )
    resolved_shifts = shift_names or {}
    for event, person, session in rows:
        conf_pct = f"{event.confidence_score * 100:.1f}" if event.confidence_score is not None else ""
        shift_id = event.work_shift_id or session.work_shift_id
        shift_name = resolved_shifts.get(shift_id, "") if shift_id is not None else ""
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
                shift_name,
                event.worked_minutes if event.worked_minutes is not None else "",
                event.late_minutes if event.late_minutes is not None and event.late_minutes > 0 else "",
                event.early_exit_minutes if event.early_exit_minutes is not None and event.early_exit_minutes > 0 else "",
                event.capture_mode,
                conf_pct,
                event.notes or "",
            ]
        )
    return buffer.getvalue()
