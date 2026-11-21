from collections import defaultdict
from datetime import date, datetime, time, timedelta
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AttendanceEvent,
    AttendanceSession,
    Group,
    Organization,
    Person,
    PersonGroup,
    WorkShift,
)
from app.schemas import (
    EmployeeAttendanceStat,
    EnterpriseStatsResponse,
    EnterpriseStatsSummary,
    ShiftAttendanceStat,
    ShiftSource,
    WorkShiftRead,
)

DEFAULT_WORK_DAYS = [0, 1, 2, 3, 4]


def parse_hhmm(value: str) -> time:
    """Convierte una cadena HH:MM en datetime.time validando su rango."""
    try:
        hour_str, minute_str = value.strip().split(":")
        hour = int(hour_str)
        minute = int(minute_str)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato de hora inválido. Usa HH:MM.",
        ) from exc

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Las horas deben estar entre 00:00 y 23:59.",
        )
    return time(hour=hour, minute=minute)


def validate_work_shift_times(start_time: str, end_time: str) -> tuple[bool, int]:
    """Valida inicio/fin del turno y calcula si cruza medianoche y duración esperada (min)."""
    start_t = parse_hhmm(start_time)
    end_t = parse_hhmm(end_time)
    if start_t == end_t:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La hora de entrada y salida del turno no pueden ser iguales.",
        )

    start_min = start_t.hour * 60 + start_t.minute
    end_min = end_t.hour * 60 + end_t.minute
    crosses_midnight = end_t < start_t
    if crosses_midnight:
        expected_duration = (1440 - start_min) + end_min
    else:
        expected_duration = end_min - start_min
    return crosses_midnight, expected_duration


def normalize_days_of_week(days: list[int]) -> str:
    """Valida y serializa los días laborales del turno (0=Lunes .. 6=Domingo)."""
    if not days:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debes seleccionar al menos un día laboral para el turno.",
        )
    cleaned: set[int] = set()
    for d in days:
        if not isinstance(d, int) or d < 0 or d > 6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Los días de la semana deben estar entre 0 (Lunes) y 6 (Domingo).",
            )
        cleaned.add(d)
    return ",".join(str(d) for d in sorted(cleaned))


def parse_days_of_week(raw: str | None) -> list[int]:
    """Convierte la cadena almacenada '0,1,2,3,4' a una lista ordenada de enteros."""
    if not raw:
        return list(DEFAULT_WORK_DAYS)
    result: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            day_num = int(part)
        except ValueError:
            continue
        if 0 <= day_num <= 6:
            result.add(day_num)
    return sorted(result) if result else list(DEFAULT_WORK_DAYS)


def _compute_duration_minutes(start_time: str, end_time: str, crosses_midnight: bool) -> int:
    start_t = parse_hhmm(start_time)
    end_t = parse_hhmm(end_time)
    start_min = start_t.hour * 60 + start_t.minute
    end_min = end_t.hour * 60 + end_t.minute
    if crosses_midnight:
        return (1440 - start_min) + end_min
    return max(0, end_min - start_min)


def resolve_person_work_shift(
    db: Session,
    person: Person,
) -> tuple[WorkShift | None, ShiftSource]:
    """Resuelve el turno propio o heredado por grupo del empleado."""
    if person.work_shift_id is not None:
        direct = db.get(WorkShift, person.work_shift_id)
        if direct is not None and direct.organization_id == person.organization_id:
            return direct, "direct"

    group_row = db.execute(
        select(WorkShift)
        .join(Group, Group.default_work_shift_id == WorkShift.id)
        .join(PersonGroup, PersonGroup.group_id == Group.id)
        .where(
            PersonGroup.person_id == person.id,
            Group.organization_id == person.organization_id,
            WorkShift.organization_id == person.organization_id,
        )
        .order_by(Group.id.asc())
    ).first()
    if group_row is not None:
        return group_row[0], "group"
    return None, "none"


def resolve_attendance_work_shift(
    db: Session,
    person: Person,
    session: AttendanceSession | None = None,
) -> WorkShift | None:
    """Resuelve el turno aplicable al registrar un movimiento en kiosco empresarial."""
    if person.work_shift_id is not None:
        direct = db.get(WorkShift, person.work_shift_id)
        if direct is not None and direct.organization_id == person.organization_id:
            return direct

    if session is not None and session.work_shift_id is not None:
        sess_shift = db.get(WorkShift, session.work_shift_id)
        if sess_shift is not None and sess_shift.organization_id == person.organization_id:
            return sess_shift

    inherited, _ = resolve_person_work_shift(db, person)
    return inherited


def evaluate_shift_check_in(
    shift: WorkShift,
    organization: Organization,
    session_date: date,
    current_time: datetime,
) -> tuple[str, int]:
    """Evalúa puntualidad de entrada respecto al turno asignado y devuelve (status, late_minutes)."""
    expected_start = datetime.combine(session_date, parse_hhmm(shift.start_time))
    tolerance = (
        shift.late_tolerance_minutes
        if shift.late_tolerance_minutes is not None
        else organization.late_tolerance_minutes
    )
    deadline = expected_start + timedelta(minutes=tolerance)
    if current_time > deadline:
        late_mins = max(1, int((current_time - expected_start).total_seconds() // 60))
        return "late", late_mins
    return "on_time", 0


def evaluate_shift_check_out(
    shift: WorkShift,
    session_date: date,
    current_time: datetime,
) -> tuple[str, int]:
    """Evalúa si la salida ocurrió antes del horario esperado del turno (considerando medianoche)."""
    end_date = session_date + timedelta(days=1) if shift.crosses_midnight else session_date
    expected_end = datetime.combine(end_date, parse_hhmm(shift.end_time))
    min_allowed_exit = expected_end - timedelta(minutes=shift.early_exit_tolerance_minutes)
    if current_time < min_allowed_exit:
        early_mins = max(1, int((expected_end - current_time).total_seconds() // 60))
        return "early_exit", early_mins
    return "on_time", 0


def find_open_overnight_checkin(
    db: Session,
    organization_id: int,
    person_id: int,
    current_time: datetime,
    effective_shift: WorkShift | None,
) -> tuple[AttendanceEvent, AttendanceSession, WorkShift] | None:
    """Localiza una entrada abierta de la jornada previa cuando el turno cruza medianoche."""
    row = db.execute(
        select(AttendanceEvent, AttendanceSession)
        .join(AttendanceSession, AttendanceSession.id == AttendanceEvent.session_id)
        .where(
            AttendanceEvent.person_id == person_id,
            AttendanceSession.organization_id == organization_id,
            AttendanceSession.session_type == "workday",
        )
        .order_by(AttendanceEvent.timestamp.desc(), AttendanceEvent.id.desc())
    ).first()
    if row is None:
        return None

    last_ev, origin_session = row
    if last_ev.event_type != "check_in":
        return None
    if origin_session.session_date >= current_time.date():
        return None

    elapsed_sec = (current_time - last_ev.timestamp).total_seconds()
    if elapsed_sec < 0 or elapsed_sec > 18 * 3600:
        return None

    resolved_shift: WorkShift | None = None
    if last_ev.work_shift_id is not None:
        resolved_shift = db.get(WorkShift, last_ev.work_shift_id)
    if resolved_shift is None and origin_session.work_shift_id is not None:
        resolved_shift = db.get(WorkShift, origin_session.work_shift_id)
    if resolved_shift is None:
        resolved_shift = effective_shift

    if resolved_shift is None or not resolved_shift.crosses_midnight:
        return None

    return last_ev, origin_session, resolved_shift


def serialize_work_shifts_batch(
    db: Session,
    shifts: list[WorkShift],
    organization_id: int,
) -> list[WorkShiftRead]:
    """Serializa turnos laborales con conteos de empleados y departamentos sin consultas N+1."""
    if not shifts:
        return []

    org = db.get(Organization, organization_id)
    org_tolerance = org.late_tolerance_minutes if org else 15

    emp_counts = {
        sid: int(cnt)
        for sid, cnt in db.execute(
            select(Person.work_shift_id, func.count(Person.id))
            .where(
                Person.organization_id == organization_id,
                Person.is_active.is_(True),
                Person.work_shift_id.is_not(None),
            )
            .group_by(Person.work_shift_id)
        ).all()
    }
    grp_counts = {
        sid: int(cnt)
        for sid, cnt in db.execute(
            select(Group.default_work_shift_id, func.count(Group.id))
            .where(
                Group.organization_id == organization_id,
                Group.default_work_shift_id.is_not(None),
            )
            .group_by(Group.default_work_shift_id)
        ).all()
    }

    result: list[WorkShiftRead] = []
    for sh in shifts:
        duration = _compute_duration_minutes(sh.start_time, sh.end_time, sh.crosses_midnight)
        eff_tol = (
            sh.late_tolerance_minutes if sh.late_tolerance_minutes is not None else org_tolerance
        )
        result.append(
            WorkShiftRead(
                id=sh.id,
                organization_id=sh.organization_id,
                name=sh.name,
                code=sh.code,
                start_time=sh.start_time,
                end_time=sh.end_time,
                crosses_midnight=sh.crosses_midnight,
                expected_duration_minutes=duration,
                days_of_week=parse_days_of_week(sh.days_of_week),
                late_tolerance_minutes=sh.late_tolerance_minutes,
                effective_late_tolerance_minutes=eff_tol,
                early_exit_tolerance_minutes=sh.early_exit_tolerance_minutes,
                is_active=sh.is_active,
                assigned_employees_count=emp_counts.get(sh.id, 0),
                default_groups_count=grp_counts.get(sh.id, 0),
                created_at=sh.created_at,
            )
        )
    return result


def generate_shift_sessions_for_date(
    db: Session,
    *,
    organization_id: int,
    target_date: date,
    work_shift_id: int | None = None,
) -> tuple[int, int, list[AttendanceSession]]:
    """Genera de forma idempotente sesiones workday para los turnos laborales del día."""
    if work_shift_id is not None:
        target_shift = db.get(WorkShift, work_shift_id)
        if target_shift is None or target_shift.organization_id != organization_id:
            raise HTTPException(status_code=404, detail="Turno laboral no encontrado.")
        if not target_shift.is_active:
            raise HTTPException(status_code=400, detail="El turno seleccionado está inactivo.")
        shifts = [target_shift]
    else:
        weekday = target_date.weekday()
        all_active = list(
            db.scalars(
                select(WorkShift)
                .where(
                    WorkShift.organization_id == organization_id,
                    WorkShift.is_active.is_(True),
                )
                .order_by(WorkShift.start_time.asc(), WorkShift.id.asc())
            ).all()
        )
        shifts = [sh for sh in all_active if weekday in parse_days_of_week(sh.days_of_week)]

    if not shifts:
        return 0, 0, []

    shift_ids = [sh.id for sh in shifts]
    existing_sessions = list(
        db.scalars(
            select(AttendanceSession)
            .where(
                AttendanceSession.organization_id == organization_id,
                AttendanceSession.session_date == target_date,
                AttendanceSession.work_shift_id.in_(shift_ids),
            )
            .order_by(AttendanceSession.id.desc())
        ).all()
    )
    existing_by_shift: dict[int, AttendanceSession] = {}
    for sess in existing_sessions:
        if sess.work_shift_id is not None and sess.work_shift_id not in existing_by_shift:
            existing_by_shift[sess.work_shift_id] = sess

    created_count = 0
    existing_count = 0
    resulting_sessions: list[AttendanceSession] = []

    for sh in shifts:
        if sh.id in existing_by_shift:
            existing_count += 1
            resulting_sessions.append(existing_by_shift[sh.id])
            continue

        new_sess = AttendanceSession(
            organization_id=organization_id,
            work_shift_id=sh.id,
            title=f"{sh.name} ({sh.start_time}-{sh.end_time}) — {target_date.isoformat()}",
            session_date=target_date,
            session_type="workday",
            expected_start_time=sh.start_time,
            status="open",
        )
        db.add(new_sess)
        created_count += 1
        resulting_sessions.append(new_sess)

    if created_count > 0:
        db.commit()
        for sess in resulting_sessions:
            db.refresh(sess)

    return created_count, existing_count, resulting_sessions


def start_or_get_shift_session(
    db: Session,
    *,
    shift: WorkShift,
    target_date: date,
) -> AttendanceSession:
    """Obtiene la sesión abierta hoy para un turno o crea una nueva lista para el kiosco."""
    existing_open = db.scalars(
        select(AttendanceSession)
        .where(
            AttendanceSession.organization_id == shift.organization_id,
            AttendanceSession.work_shift_id == shift.id,
            AttendanceSession.session_date == target_date,
            AttendanceSession.status == "open",
        )
        .order_by(AttendanceSession.id.desc())
    ).first()
    if existing_open is not None:
        return existing_open

    new_sess = AttendanceSession(
        organization_id=shift.organization_id,
        work_shift_id=shift.id,
        title=f"{shift.name} ({shift.start_time}-{shift.end_time}) — {target_date.isoformat()}",
        session_date=target_date,
        session_type="workday",
        expected_start_time=shift.start_time,
        status="open",
    )
    db.add(new_sess)
    db.commit()
    db.refresh(new_sess)
    return new_sess


def compute_enterprise_stats(
    db: Session,
    *,
    organization_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    work_shift_id: int | None = None,
    group_id: int | None = None,
) -> EnterpriseStatsResponse:
    """Calcula estadísticas empresariales de puntualidad, salidas anticipadas, horas e inasistencias."""
    today = date.today()
    effective_to = date_to or today
    effective_from = date_from or effective_to
    if effective_from > effective_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La fecha inicial no puede ser posterior a la fecha final.",
        )

    shifts = list(
        db.scalars(
            select(WorkShift)
            .where(WorkShift.organization_id == organization_id)
            .order_by(WorkShift.start_time.asc(), WorkShift.id.asc())
        ).all()
    )
    shift_map = {sh.id: sh for sh in shifts}
    shift_days_map = {sh.id: set(parse_days_of_week(sh.days_of_week)) for sh in shifts}

    if work_shift_id is not None and work_shift_id not in shift_map:
        raise HTTPException(status_code=404, detail="Turno laboral no encontrado.")

    groups = list(
        db.scalars(
            select(Group)
            .where(Group.organization_id == organization_id)
            .order_by(Group.id.asc())
        ).all()
    )
    group_map = {g.id: g for g in groups}
    if group_id is not None and group_id not in group_map:
        raise HTTPException(status_code=404, detail="Departamento/grupo no encontrado.")

    persons = list(
        db.scalars(
            select(Person)
            .options(selectinload(Person.group_links))
            .where(
                Person.organization_id == organization_id,
                Person.is_active.is_(True),
            )
            .order_by(Person.full_name.asc(), Person.id.asc())
        ).all()
    )
    if group_id is not None:
        persons = [p for p in persons if any(link.group_id == group_id for link in p.group_links)]

    # Resuelve turno efectivo (directo o heredado por primer grupo con turno por defecto)
    resolved_persons: list[tuple[Person, WorkShift | None, ShiftSource, list[str]]] = []
    for p in persons:
        ordered_group_ids = sorted(link.group_id for link in p.group_links)
        grp_names = [group_map[gid].name for gid in ordered_group_ids if gid in group_map]

        eff_shift: WorkShift | None = None
        source: ShiftSource = "none"
        if p.work_shift_id is not None and p.work_shift_id in shift_map:
            eff_shift = shift_map[p.work_shift_id]
            source = "direct"
        else:
            for gid in ordered_group_ids:
                grp = group_map.get(gid)
                if grp and grp.default_work_shift_id and grp.default_work_shift_id in shift_map:
                    eff_shift = shift_map[grp.default_work_shift_id]
                    source = "group"
                    break

        if work_shift_id is not None and (eff_shift is None or eff_shift.id != work_shift_id):
            continue
        resolved_persons.append((p, eff_shift, source, grp_names))

    person_ids = [p.id for p, _, _, _ in resolved_persons]
    events_by_person_date: dict[tuple[int, date], list[AttendanceEvent]] = defaultdict(list)
    if person_ids:
        rows = db.execute(
            select(AttendanceEvent, AttendanceSession.session_date)
            .join(AttendanceSession, AttendanceSession.id == AttendanceEvent.session_id)
            .where(
                AttendanceSession.organization_id == organization_id,
                AttendanceSession.session_type == "workday",
                AttendanceSession.session_date >= effective_from,
                AttendanceSession.session_date <= effective_to,
                AttendanceEvent.person_id.in_(person_ids),
            )
            .order_by(AttendanceEvent.timestamp.asc(), AttendanceEvent.id.asc())
        ).all()
        for ev, sess_date in rows:
            events_by_person_date[(ev.person_id, sess_date)].append(ev)

    # Días calendario exigibles (no posteriores a hoy) dentro del rango
    calendar_days: list[date] = []
    cursor = effective_from
    max_scheduled_date = min(effective_to, today)
    while cursor <= max_scheduled_date:
        calendar_days.append(cursor)
        cursor += timedelta(days=1)

    by_employee: list[EmployeeAttendanceStat] = []
    shift_acc: dict[int | None, dict[str, int]] = defaultdict(
        lambda: {
            "employees": 0,
            "scheduled_days": 0,
            "present_days": 0,
            "on_time_days": 0,
            "late_days": 0,
            "early_exit_days": 0,
            "absent_days": 0,
            "missing_checkout_days": 0,
            "total_worked_minutes": 0,
        }
    )

    for person, eff_shift, source, grp_names in resolved_persons:
        sh_id = eff_shift.id if eff_shift else None
        sh_days = shift_days_map.get(sh_id, set()) if sh_id is not None else set()

        scheduled_days = 0
        present_days = 0
        on_time_days = 0
        late_days = 0
        early_exit_days = 0
        absent_days = 0
        missing_checkout_days = 0
        total_late_minutes = 0
        total_early_exit_minutes = 0
        total_worked_minutes = 0

        # Todas las fechas con eventos en el rango para esta persona
        active_dates_with_events = {
            d for (pid, d) in events_by_person_date.keys() if pid == person.id
        }
        scheduled_dates: set[date] = set()
        if eff_shift is not None:
            for d in calendar_days:
                if d.weekday() in sh_days:
                    scheduled_dates.add(d)
        scheduled_days = len(scheduled_dates)

        dates_to_inspect = sorted(scheduled_dates | active_dates_with_events)
        for d in dates_to_inspect:
            day_events = events_by_person_date.get((person.id, d), [])
            checkins = [e for e in day_events if e.event_type in ("check_in", "present")]
            checkouts = [e for e in day_events if e.event_type == "check_out"]

            if not checkins:
                if d in scheduled_dates:
                    absent_days += 1
                continue

            present_days += 1
            first_in = checkins[0]
            if first_in.status == "late":
                late_days += 1
                total_late_minutes += first_in.late_minutes or 0
            else:
                on_time_days += 1

            if not checkouts:
                missing_checkout_days += 1
            else:
                last_out = checkouts[-1]
                if last_out.status == "early_exit":
                    early_exit_days += 1
                    total_early_exit_minutes += last_out.early_exit_minutes or 0

                day_worked = sum(co.worked_minutes or 0 for co in checkouts)
                if day_worked == 0 and last_out.timestamp >= first_in.timestamp:
                    day_worked = int((last_out.timestamp - first_in.timestamp).total_seconds() // 60)
                total_worked_minutes += max(0, day_worked)

        if scheduled_days > 0:
            att_rate = min(100.0, round((present_days / scheduled_days) * 100.0, 2))
        elif present_days > 0:
            att_rate = 100.0
        else:
            att_rate = 0.0

        punct_rate = round((on_time_days / present_days) * 100.0, 2) if present_days > 0 else 0.0

        by_employee.append(
            EmployeeAttendanceStat(
                person_id=person.id,
                external_id=person.external_id,
                full_name=person.full_name,
                group_names=grp_names,
                work_shift_id=sh_id,
                shift_name=eff_shift.name if eff_shift else None,
                shift_code=eff_shift.code if eff_shift else None,
                shift_source=source,
                scheduled_days=scheduled_days,
                present_days=present_days,
                on_time_days=on_time_days,
                late_days=late_days,
                early_exit_days=early_exit_days,
                absent_days=absent_days,
                missing_checkout_days=missing_checkout_days,
                total_late_minutes=total_late_minutes,
                total_early_exit_minutes=total_early_exit_minutes,
                total_worked_minutes=total_worked_minutes,
                attendance_rate=att_rate,
                punctuality_rate=punct_rate,
            )
        )

        acc = shift_acc[sh_id]
        acc["employees"] += 1
        acc["scheduled_days"] += scheduled_days
        acc["present_days"] += present_days
        acc["on_time_days"] += on_time_days
        acc["late_days"] += late_days
        acc["early_exit_days"] += early_exit_days
        acc["absent_days"] += absent_days
        acc["missing_checkout_days"] += missing_checkout_days
        acc["total_worked_minutes"] += total_worked_minutes

    by_shift: list[ShiftAttendanceStat] = []
    target_shifts = [shift_map[work_shift_id]] if work_shift_id is not None else shifts
    for sh in target_shifts:
        acc = shift_acc.get(
            sh.id,
            {
                "employees": 0,
                "scheduled_days": 0,
                "present_days": 0,
                "on_time_days": 0,
                "late_days": 0,
                "early_exit_days": 0,
                "absent_days": 0,
                "missing_checkout_days": 0,
                "total_worked_minutes": 0,
            },
        )
        sched = acc["scheduled_days"]
        pres = acc["present_days"]
        att_rate = (
            min(100.0, round((pres / sched) * 100.0, 2))
            if sched > 0
            else (100.0 if pres > 0 else 0.0)
        )
        punct_rate = round((acc["on_time_days"] / pres) * 100.0, 2) if pres > 0 else 0.0
        avg_worked = round(acc["total_worked_minutes"] / pres, 1) if pres > 0 else 0.0
        by_shift.append(
            ShiftAttendanceStat(
                work_shift_id=sh.id,
                shift_name=sh.name,
                shift_code=sh.code,
                start_time=sh.start_time,
                end_time=sh.end_time,
                crosses_midnight=sh.crosses_midnight,
                days_of_week=parse_days_of_week(sh.days_of_week),
                employees_count=acc["employees"],
                scheduled_days=sched,
                present_days=pres,
                on_time_days=acc["on_time_days"],
                late_days=acc["late_days"],
                early_exit_days=acc["early_exit_days"],
                absent_days=acc["absent_days"],
                missing_checkout_days=acc["missing_checkout_days"],
                total_worked_minutes=acc["total_worked_minutes"],
                avg_worked_minutes=avg_worked,
                attendance_rate=att_rate,
                punctuality_rate=punct_rate,
            )
        )

    if work_shift_id is None and None in shift_acc:
        acc = shift_acc[None]
        pres = acc["present_days"]
        by_shift.append(
            ShiftAttendanceStat(
                work_shift_id=None,
                shift_name="Sin turno asignado",
                shift_code=None,
                start_time=None,
                end_time=None,
                crosses_midnight=False,
                days_of_week=[],
                employees_count=acc["employees"],
                scheduled_days=0,
                present_days=pres,
                on_time_days=acc["on_time_days"],
                late_days=acc["late_days"],
                early_exit_days=acc["early_exit_days"],
                absent_days=0,
                missing_checkout_days=acc["missing_checkout_days"],
                total_worked_minutes=acc["total_worked_minutes"],
                avg_worked_minutes=round(acc["total_worked_minutes"] / pres, 1) if pres > 0 else 0.0,
                attendance_rate=100.0 if pres > 0 else 0.0,
                punctuality_rate=round((acc["on_time_days"] / pres) * 100.0, 2) if pres > 0 else 0.0,
            )
        )

    total_employees = len(resolved_persons)
    unassigned_employees = sum(1 for _, sh, _, _ in resolved_persons if sh is None)
    assigned_employees = total_employees - unassigned_employees

    tot_sched = sum(e.scheduled_days for e in by_employee)
    tot_pres = sum(e.present_days for e in by_employee)
    tot_on_time = sum(e.on_time_days for e in by_employee)
    tot_late = sum(e.late_days for e in by_employee)
    tot_early = sum(e.early_exit_days for e in by_employee)
    tot_absent = sum(e.absent_days for e in by_employee)
    tot_missing_out = sum(e.missing_checkout_days for e in by_employee)
    tot_worked = sum(e.total_worked_minutes for e in by_employee)

    overall_att = (
        min(100.0, round((tot_pres / tot_sched) * 100.0, 2))
        if tot_sched > 0
        else (100.0 if tot_pres > 0 else 0.0)
    )
    overall_punct = round((tot_on_time / tot_pres) * 100.0, 2) if tot_pres > 0 else 0.0

    summary = EnterpriseStatsSummary(
        total_shifts=len(shifts),
        active_shifts=sum(1 for sh in shifts if sh.is_active),
        total_employees=total_employees,
        assigned_employees=assigned_employees,
        unassigned_employees=unassigned_employees,
        scheduled_employee_days=tot_sched,
        present_days=tot_pres,
        on_time_days=tot_on_time,
        late_days=tot_late,
        early_exit_days=tot_early,
        absent_days=tot_absent,
        missing_checkout_days=tot_missing_out,
        total_worked_minutes=tot_worked,
        attendance_rate=overall_att,
        punctuality_rate=overall_punct,
    )

    return EnterpriseStatsResponse(
        organization_id=organization_id,
        date_from=effective_from,
        date_to=effective_to,
        summary=summary,
        by_shift=by_shift,
        by_employee=by_employee,
    )
