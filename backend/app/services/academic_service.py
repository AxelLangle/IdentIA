from collections import defaultdict
from datetime import date, datetime
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AttendanceEvent,
    AttendanceSession,
    Career,
    ClassSchedule,
    CourseAssignment,
    Group,
    Organization,
    Person,
    PersonGroup,
    Subject,
    User,
    WorkShift,
)
from app.schemas import (
    AcademicStatsResponse,
    AcademicStatsSummary,
    ClassScheduleRead,
    CourseAssignmentRead,
    GroupAttendanceStat,
    SessionRead,
    StudentGroupAttendanceStat,
    SubjectAttendanceStat,
    TeacherAgendaResponse,
    TeacherAgendaSlot,
)


def get_teacher_course_ids(db: Session, teacher_user_id: int) -> set[int]:
    """Devuelve los IDs de cursos activos asignados al docente."""
    rows = db.scalars(
        select(CourseAssignment.id).where(
            CourseAssignment.teacher_user_id == teacher_user_id,
            CourseAssignment.is_active.is_(True),
        )
    ).all()
    return set(rows)


def get_teacher_group_ids(db: Session, teacher_user_id: int) -> set[int]:
    """Devuelve los IDs de grupos donde el docente imparte al menos una materia activa."""
    rows = db.scalars(
        select(CourseAssignment.group_id)
        .where(
            CourseAssignment.teacher_user_id == teacher_user_id,
            CourseAssignment.is_active.is_(True),
        )
        .distinct()
    ).all()
    return set(rows)


def assert_session_teacher_access(
    db: Session,
    current_user: User,
    session: AttendanceSession,
) -> None:
    """Impide que un docente opere sesiones que no pertenecen a sus asignaturas."""
    if current_user.role != "teacher":
        return
    teacher_courses = get_teacher_course_ids(db, current_user.id)
    if session.course_assignment_id is None or session.course_assignment_id not in teacher_courses:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo puedes operar sesiones de tus materias asignadas.",
        )


def validate_schedule_times(start_time: str, end_time: str) -> None:
    """Valida formato HH:MM y que la hora de inicio sea anterior al fin."""
    try:
        sh, sm = (int(p) for p in start_time.split(":"))
        eh, em = (int(p) for p in end_time.split(":"))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato de horario inválido. Usa HH:MM.",
        ) from exc

    if not (0 <= sh <= 23 and 0 <= sm <= 59 and 0 <= eh <= 23 and 0 <= em <= 59):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Las horas deben estar entre 00:00 y 23:59.",
        )
    if (sh, sm) >= (eh, em):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La hora de inicio de clase debe ser anterior a la hora de fin.",
        )


def _group_student_counts(db: Session, organization_id: int) -> dict[int, int]:
    rows = db.execute(
        select(PersonGroup.group_id, func.count(PersonGroup.person_id))
        .join(Person, Person.id == PersonGroup.person_id)
        .where(
            Person.organization_id == organization_id,
            Person.is_active.is_(True),
            Person.role != "teacher",
        )
        .group_by(PersonGroup.group_id)
    ).all()
    return {gid: int(cnt) for gid, cnt in rows}


def serialize_courses_batch(
    db: Session,
    courses: list[CourseAssignment],
    organization_id: int,
) -> list[CourseAssignmentRead]:
    """Serializa una lista de asignaciones de curso evitando consultas N+1."""
    if not courses:
        return []

    student_counts = _group_student_counts(db, organization_id)
    org = db.get(Organization, organization_id)
    org_period_type = org.academic_period_type if org else "semestral"
    career_map = {
        c.id: c
        for c in db.scalars(select(Career).where(Career.organization_id == organization_id)).all()
    }

    result: list[CourseAssignmentRead] = []
    for c in courses:
        sorted_schedules = sorted(
            c.schedules,
            key=lambda s: (s.day_of_week, s.start_time, s.id),
        )
        career_id = c.group.career_id if c.group else None
        career = career_map.get(career_id) if career_id else None
        effective_period = (
            (c.group.period_type if c.group else None)
            or (career.period_type if career and career.period_type else None)
            or org_period_type
        )
        result.append(
            CourseAssignmentRead(
                id=c.id,
                organization_id=c.organization_id,
                group_id=c.group_id,
                group_name=c.group.name if c.group else "",
                group_code=c.group.code if c.group else "",
                group_default_classroom=c.group.default_classroom if c.group else None,
                semester=c.group.semester if c.group else None,
                period_type=effective_period,
                career_id=career_id,
                career_name=career.name if career else None,
                subject_id=c.subject_id,
                subject_name=c.subject.name if c.subject else "",
                subject_code=c.subject.code if c.subject else "",
                teacher_user_id=c.teacher_user_id,
                teacher_name=c.teacher.full_name if c.teacher else None,
                teacher_email=c.teacher.email if c.teacher else None,
                term=c.term,
                is_active=c.is_active,
                students_count=student_counts.get(c.group_id, 0),
                schedules=[
                    ClassScheduleRead(
                        id=s.id,
                        course_assignment_id=s.course_assignment_id,
                        day_of_week=s.day_of_week,
                        start_time=s.start_time,
                        end_time=s.end_time,
                        classroom=s.classroom,
                        created_at=s.created_at,
                    )
                    for s in sorted_schedules
                ],
                created_at=c.created_at,
            )
        )
    return result


def serialize_sessions_batch(
    db: Session,
    sessions: list[AttendanceSession],
    organization_id: int,
) -> list[SessionRead]:
    """Serializa sesiones incluyendo metadatos académicos (materia, carrera, profesor)."""
    if not sessions:
        return []

    session_ids = [s.id for s in sessions]
    event_counts = {
        sid: int(cnt)
        for sid, cnt in db.execute(
            select(AttendanceEvent.session_id, func.count(AttendanceEvent.id))
            .where(AttendanceEvent.session_id.in_(session_ids))
            .group_by(AttendanceEvent.session_id)
        ).all()
    }
    group_map = {
        g.id: g
        for g in db.scalars(select(Group).where(Group.organization_id == organization_id)).all()
    }
    career_map = {
        c.id: c.name
        for c in db.scalars(select(Career).where(Career.organization_id == organization_id)).all()
    }
    shift_map = {
        sh.id: sh
        for sh in db.scalars(select(WorkShift).where(WorkShift.organization_id == organization_id)).all()
    }

    course_ids = [s.course_assignment_id for s in sessions if s.course_assignment_id is not None]
    course_map: dict[int, CourseAssignment] = {}
    if course_ids:
        loaded_courses = db.scalars(
            select(CourseAssignment)
            .options(
                selectinload(CourseAssignment.subject),
                selectinload(CourseAssignment.group),
                selectinload(CourseAssignment.teacher),
            )
            .where(CourseAssignment.id.in_(course_ids))
        ).all()
        course_map = {c.id: c for c in loaded_courses}

    result: list[SessionRead] = []
    for s in sessions:
        group = group_map.get(s.group_id) if s.group_id else None
        course = course_map.get(s.course_assignment_id) if s.course_assignment_id else None
        shift = shift_map.get(s.work_shift_id) if s.work_shift_id else None
        career_id = group.career_id if group else (course.group.career_id if course and course.group else None)
        if career_id is None and course and course.subject:
            career_id = course.subject.career_id

        result.append(
            SessionRead(
                id=s.id,
                organization_id=s.organization_id,
                group_id=s.group_id,
                group_name=group.name if group else (course.group.name if course and course.group else None),
                course_assignment_id=s.course_assignment_id,
                schedule_id=s.schedule_id,
                work_shift_id=s.work_shift_id,
                work_shift_name=shift.name if shift else None,
                work_shift_code=shift.code if shift else None,
                work_shift_crosses_midnight=shift.crosses_midnight if shift else False,
                subject_name=course.subject.name if course and course.subject else None,
                subject_code=course.subject.code if course and course.subject else None,
                career_name=career_map.get(career_id) if career_id else None,
                teacher_name=course.teacher.full_name if course and course.teacher else None,
                title=s.title,
                session_date=s.session_date,
                session_type=s.session_type,
                expected_start_time=s.expected_start_time,
                status=s.status,
                created_at=s.created_at,
                closed_at=s.closed_at,
                events_count=event_counts.get(s.id, 0),
            )
        )
    return result


def generate_sessions_for_date(
    db: Session,
    *,
    organization_id: int,
    target_date: date,
    course_assignment_id: int | None = None,
    teacher_user_id: int | None = None,
) -> tuple[int, int, list[AttendanceSession]]:
    """Genera de forma idempotente sesiones académicas para los horarios del día indicado."""
    weekday = target_date.weekday()
    stmt = (
        select(CourseAssignment)
        .options(
            selectinload(CourseAssignment.subject),
            selectinload(CourseAssignment.group),
            selectinload(CourseAssignment.schedules),
        )
        .where(
            CourseAssignment.organization_id == organization_id,
            CourseAssignment.is_active.is_(True),
        )
    )
    if course_assignment_id is not None:
        stmt = stmt.where(CourseAssignment.id == course_assignment_id)
    if teacher_user_id is not None:
        stmt = stmt.where(CourseAssignment.teacher_user_id == teacher_user_id)

    courses = list(db.scalars(stmt).all())
    if not courses:
        return 0, 0, []

    course_ids = [c.id for c in courses]
    existing_sessions = list(
        db.scalars(
            select(AttendanceSession).where(
                AttendanceSession.organization_id == organization_id,
                AttendanceSession.session_date == target_date,
                AttendanceSession.course_assignment_id.in_(course_ids),
            )
        ).all()
    )
    existing_by_slot: dict[tuple[int, int], AttendanceSession] = {
        (s.course_assignment_id, s.schedule_id): s
        for s in existing_sessions
        if s.course_assignment_id is not None and s.schedule_id is not None
    }

    created_count = 0
    existing_count = 0
    resulting_sessions: list[AttendanceSession] = []

    for course in courses:
        day_slots = sorted(
            [sl for sl in course.schedules if sl.day_of_week == weekday],
            key=lambda sl: (sl.start_time, sl.id),
        )
        for slot in day_slots:
            key = (course.id, slot.id)
            if key in existing_by_slot:
                existing_count += 1
                resulting_sessions.append(existing_by_slot[key])
                continue

            subject_label = course.subject.name if course.subject else "Clase"
            group_label = course.group.name if course.group else "Grupo"
            session = AttendanceSession(
                organization_id=organization_id,
                group_id=course.group_id,
                course_assignment_id=course.id,
                schedule_id=slot.id,
                title=f"{subject_label} — {group_label} ({slot.start_time}-{slot.end_time})",
                session_date=target_date,
                session_type="class",
                expected_start_time=slot.start_time,
                status="open",
            )
            db.add(session)
            created_count += 1
            resulting_sessions.append(session)

    if created_count > 0:
        db.commit()
        for sess in resulting_sessions:
            db.refresh(sess)

    return created_count, existing_count, resulting_sessions


def start_or_get_course_session(
    db: Session,
    *,
    assignment: CourseAssignment,
    target_date: date,
    schedule_id: int | None = None,
) -> AttendanceSession:
    """Obtiene la sesión abierta del curso para hoy o crea una nueva lista para el kiosco."""
    schedule: ClassSchedule | None = None
    if schedule_id is not None:
        schedule = db.get(ClassSchedule, schedule_id)
        if schedule is None or schedule.course_assignment_id != assignment.id:
            raise HTTPException(
                status_code=404,
                detail="Horario no encontrado para la asignatura seleccionada.",
            )
        existing_slot = db.scalars(
            select(AttendanceSession)
            .where(
                AttendanceSession.course_assignment_id == assignment.id,
                AttendanceSession.schedule_id == schedule.id,
                AttendanceSession.session_date == target_date,
                AttendanceSession.status == "open",
            )
            .order_by(AttendanceSession.id.desc())
        ).first()
        if existing_slot is not None:
            return existing_slot
    else:
        existing_open = db.scalars(
            select(AttendanceSession)
            .where(
                AttendanceSession.course_assignment_id == assignment.id,
                AttendanceSession.session_date == target_date,
                AttendanceSession.status == "open",
            )
            .order_by(AttendanceSession.id.desc())
        ).first()
        if existing_open is not None:
            return existing_open

        weekday = target_date.weekday()
        day_slots = sorted(
            [sl for sl in assignment.schedules if sl.day_of_week == weekday],
            key=lambda sl: sl.start_time,
        )
        if day_slots:
            schedule = day_slots[0]

    subject_label = assignment.subject.name if assignment.subject else "Materia"
    group_label = assignment.group.name if assignment.group else "Grupo"
    if schedule is not None:
        title = f"{subject_label} — {group_label} ({schedule.start_time}-{schedule.end_time})"
        expected_start = schedule.start_time
        resolved_schedule_id = schedule.id
    else:
        title = f"{subject_label} — {group_label} ({target_date.isoformat()})"
        expected_start = assignment.group.schedule_start if assignment.group else None
        resolved_schedule_id = None

    session = AttendanceSession(
        organization_id=assignment.organization_id,
        group_id=assignment.group_id,
        course_assignment_id=assignment.id,
        schedule_id=resolved_schedule_id,
        title=title,
        session_date=target_date,
        session_type="class",
        expected_start_time=expected_start,
        status="open",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def build_teacher_agenda(
    db: Session,
    *,
    organization_id: int,
    teacher_user_id: int,
    target_date: date,
    current_time_str: str,
) -> TeacherAgendaResponse:
    """Construye la agenda diaria y lista de cursos del profesor en su jornada actual."""
    courses = list(
        db.scalars(
            select(CourseAssignment)
            .options(
                selectinload(CourseAssignment.subject),
                selectinload(CourseAssignment.group),
                selectinload(CourseAssignment.teacher),
                selectinload(CourseAssignment.schedules),
            )
            .where(
                CourseAssignment.organization_id == organization_id,
                CourseAssignment.teacher_user_id == teacher_user_id,
                CourseAssignment.is_active.is_(True),
            )
            .order_by(CourseAssignment.id.asc())
        ).all()
    )
    serialized_courses = serialize_courses_batch(db, courses, organization_id)
    course_read_map = {c.id: c for c in serialized_courses}

    course_ids = [c.id for c in courses]
    day_sessions: list[AttendanceSession] = []
    if course_ids:
        day_sessions = list(
            db.scalars(
                select(AttendanceSession)
                .where(
                    AttendanceSession.organization_id == organization_id,
                    AttendanceSession.session_date == target_date,
                    AttendanceSession.course_assignment_id.in_(course_ids),
                )
                .order_by(AttendanceSession.id.desc())
            ).all()
        )
    serialized_sessions = serialize_sessions_batch(db, day_sessions, organization_id)
    session_by_slot: dict[int, SessionRead] = {}
    session_by_course: dict[int, SessionRead] = {}
    for sess in serialized_sessions:
        if sess.schedule_id is not None:
            prev = session_by_slot.get(sess.schedule_id)
            if prev is None or (prev.status != "open" and sess.status == "open"):
                session_by_slot[sess.schedule_id] = sess
        if sess.course_assignment_id is not None:
            prev_c = session_by_course.get(sess.course_assignment_id)
            if prev_c is None or (prev_c.status != "open" and sess.status == "open"):
                session_by_course[sess.course_assignment_id] = sess

    weekday = target_date.weekday()
    today_slots: list[TeacherAgendaSlot] = []
    for course in courses:
        c_read = course_read_map[course.id]
        for sl in course.schedules:
            if sl.day_of_week != weekday:
                continue
            if sl.start_time <= current_time_str <= sl.end_time:
                slot_status = "in_progress"
            elif current_time_str < sl.start_time:
                slot_status = "upcoming"
            else:
                slot_status = "finished"

            matched_session = session_by_slot.get(sl.id) or session_by_course.get(course.id)
            today_slots.append(
                TeacherAgendaSlot(
                    schedule_id=sl.id,
                    course_assignment_id=course.id,
                    subject_name=c_read.subject_name,
                    subject_code=c_read.subject_code,
                    group_id=c_read.group_id,
                    group_name=c_read.group_name,
                    group_code=c_read.group_code,
                    career_name=c_read.career_name,
                    day_of_week=sl.day_of_week,
                    start_time=sl.start_time,
                    end_time=sl.end_time,
                    classroom=sl.classroom,
                    slot_status=slot_status,
                    students_count=c_read.students_count,
                    session=matched_session,
                )
            )

    today_slots.sort(key=lambda item: (item.start_time, item.end_time, item.schedule_id))

    current_slot = next((s for s in today_slots if s.slot_status == "in_progress"), None)
    if current_slot is None:
        current_slot = next((s for s in today_slots if s.slot_status == "upcoming"), None)

    return TeacherAgendaResponse(
        target_date=target_date,
        current_time=current_time_str,
        current_slot=current_slot,
        today_slots=today_slots,
        courses=serialized_courses,
    )


def compute_academic_stats(
    db: Session,
    *,
    organization_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    career_id: int | None = None,
    group_id: int | None = None,
) -> AcademicStatsResponse:
    """Calcula estadísticas por asignatura y consolidadas por grupo/alumno."""
    org = db.get(Organization, organization_id)
    org_period_type = org.academic_period_type if org else "semestral"
    careers = list(
        db.scalars(select(Career).where(Career.organization_id == organization_id)).all()
    )
    career_obj_map = {c.id: c for c in careers}
    career_map = {c.id: c.name for c in careers}

    groups_stmt = select(Group).where(Group.organization_id == organization_id).order_by(Group.name.asc())
    if career_id is not None:
        groups_stmt = groups_stmt.where(Group.career_id == career_id)
    if group_id is not None:
        groups_stmt = groups_stmt.where(Group.id == group_id)
    groups = list(db.scalars(groups_stmt).all())
    group_map = {g.id: g for g in groups}
    filtered_group_ids = set(group_map.keys())

    subjects = list(
        db.scalars(select(Subject).where(Subject.organization_id == organization_id)).all()
    )

    courses = list(
        db.scalars(
            select(CourseAssignment)
            .options(
                selectinload(CourseAssignment.subject),
                selectinload(CourseAssignment.group),
                selectinload(CourseAssignment.teacher),
            )
            .where(CourseAssignment.organization_id == organization_id)
            .order_by(CourseAssignment.id.asc())
        ).all()
    )
    if filtered_group_ids or career_id is not None or group_id is not None:
        courses = [c for c in courses if c.group_id in filtered_group_ids]

    # Alumnos activos por grupo
    group_students_map: dict[int, list[Person]] = defaultdict(list)
    if filtered_group_ids:
        pg_rows = db.execute(
            select(PersonGroup.group_id, Person)
            .join(Person, Person.id == PersonGroup.person_id)
            .where(
                PersonGroup.group_id.in_(filtered_group_ids),
                Person.organization_id == organization_id,
                Person.is_active.is_(True),
                Person.role != "teacher",
            )
            .order_by(Person.full_name.asc())
        ).all()
        for gid, person in pg_rows:
            group_students_map[gid].append(person)

    course_ids = [c.id for c in courses]
    sessions_by_course: dict[int, list[AttendanceSession]] = defaultdict(list)
    session_ids: list[int] = []
    if course_ids:
        sess_stmt = select(AttendanceSession).where(
            AttendanceSession.organization_id == organization_id,
            AttendanceSession.course_assignment_id.in_(course_ids),
        )
        if date_from is not None:
            sess_stmt = sess_stmt.where(AttendanceSession.session_date >= date_from)
        if date_to is not None:
            sess_stmt = sess_stmt.where(AttendanceSession.session_date <= date_to)
        sessions = list(db.scalars(sess_stmt).all())
        for sess in sessions:
            if sess.course_assignment_id is not None:
                sessions_by_course[sess.course_assignment_id].append(sess)
                session_ids.append(sess.id)

    # Mapeo único (session_id, person_id) -> status
    event_status_map: dict[tuple[int, int], str] = {}
    if session_ids:
        events = list(
            db.scalars(
                select(AttendanceEvent)
                .where(AttendanceEvent.session_id.in_(session_ids))
                .order_by(AttendanceEvent.id.asc())
            ).all()
        )
        for ev in events:
            key = (ev.session_id, ev.person_id)
            if key not in event_status_map:
                event_status_map[key] = ev.status

    by_subject: list[SubjectAttendanceStat] = []
    courses_by_group: dict[int, list[CourseAssignment]] = defaultdict(list)

    for course in courses:
        courses_by_group[course.group_id].append(course)
        group_students = group_students_map.get(course.group_id, [])
        student_ids = [p.id for p in group_students]
        course_sessions = sessions_by_course.get(course.id, [])

        sessions_count = len(course_sessions)
        enrolled_count = len(student_ids)
        expected = sessions_count * enrolled_count

        present = 0
        on_time = 0
        late = 0
        manual = 0
        for sess in course_sessions:
            for sid in student_ids:
                st = event_status_map.get((sess.id, sid))
                if st is not None:
                    present += 1
                    if st == "on_time":
                        on_time += 1
                    elif st == "late":
                        late += 1
                    elif st == "manual":
                        manual += 1

        absent = max(0, expected - present)
        rate = round((present / expected) * 100.0, 2) if expected > 0 else 0.0
        cid = course.group.career_id if course.group else None
        career_obj = career_obj_map.get(cid) if cid else None
        subj_period_type = (
            (course.group.period_type if course.group else None)
            or (career_obj.period_type if career_obj and career_obj.period_type else None)
            or org_period_type
        )

        by_subject.append(
            SubjectAttendanceStat(
                course_assignment_id=course.id,
                subject_id=course.subject_id,
                subject_name=course.subject.name if course.subject else "",
                subject_code=course.subject.code if course.subject else "",
                group_id=course.group_id,
                group_name=course.group.name if course.group else "",
                group_code=course.group.code if course.group else "",
                career_id=cid,
                career_name=career_map.get(cid) if cid else None,
                semester=course.group.semester if course.group else None,
                period_type=subj_period_type,
                teacher_name=course.teacher.full_name if course.teacher else None,
                sessions_count=sessions_count,
                enrolled_students=enrolled_count,
                expected_records=expected,
                present_count=present,
                on_time_count=on_time,
                late_count=late,
                manual_count=manual,
                absent_count=absent,
                attendance_rate=rate,
            )
        )

    by_group: list[GroupAttendanceStat] = []
    grand_expected = 0
    grand_present = 0
    grand_sessions = 0

    for g in groups:
        group_courses = courses_by_group.get(g.id, [])
        group_students = group_students_map.get(g.id, [])
        all_group_sessions: list[AttendanceSession] = []
        for c in group_courses:
            all_group_sessions.extend(sessions_by_course.get(c.id, []))

        total_sessions = len(all_group_sessions)
        total_expected = total_sessions * len(group_students)
        total_present = 0
        total_on_time = 0
        total_late = 0
        students_breakdown: list[StudentGroupAttendanceStat] = []

        for person in group_students:
            s_present = 0
            s_on_time = 0
            s_late = 0
            for sess in all_group_sessions:
                st = event_status_map.get((sess.id, person.id))
                if st is not None:
                    s_present += 1
                    if st == "on_time":
                        s_on_time += 1
                    elif st == "late":
                        s_late += 1
            s_absent = max(0, total_sessions - s_present)
            s_rate = round((s_present / total_sessions) * 100.0, 2) if total_sessions > 0 else 0.0
            total_present += s_present
            total_on_time += s_on_time
            total_late += s_late
            students_breakdown.append(
                StudentGroupAttendanceStat(
                    person_id=person.id,
                    external_id=person.external_id,
                    full_name=person.full_name,
                    expected_records=total_sessions,
                    present_count=s_present,
                    on_time_count=s_on_time,
                    late_count=s_late,
                    absent_count=s_absent,
                    attendance_rate=s_rate,
                )
            )

        total_absent = max(0, total_expected - total_present)
        g_rate = round((total_present / total_expected) * 100.0, 2) if total_expected > 0 else 0.0
        grand_expected += total_expected
        grand_present += total_present
        grand_sessions += total_sessions

        grp_career = career_obj_map.get(g.career_id) if g.career_id else None
        grp_period_type = (
            g.period_type
            or (grp_career.period_type if grp_career and grp_career.period_type else None)
            or org_period_type
        )
        by_group.append(
            GroupAttendanceStat(
                group_id=g.id,
                group_name=g.name,
                group_code=g.code,
                career_id=g.career_id,
                career_name=career_map.get(g.career_id) if g.career_id else None,
                semester=g.semester,
                period_type=grp_period_type,
                subjects_count=len(group_courses),
                students_count=len(group_students),
                total_sessions=total_sessions,
                total_expected=total_expected,
                total_present=total_present,
                total_on_time=total_on_time,
                total_late=total_late,
                total_absent=total_absent,
                overall_attendance_rate=g_rate,
                students_breakdown=students_breakdown,
            )
        )

    overall_rate = round((grand_present / grand_expected) * 100.0, 2) if grand_expected > 0 else 0.0

    return AcademicStatsResponse(
        organization_id=organization_id,
        date_from=date_from,
        date_to=date_to,
        summary=AcademicStatsSummary(
            total_careers=len(careers),
            total_groups=len(groups),
            total_subjects=len(subjects),
            total_courses=len(courses),
            total_sessions=grand_sessions,
            overall_attendance_rate=overall_rate,
        ),
        by_subject=by_subject,
        by_group=by_group,
    )
