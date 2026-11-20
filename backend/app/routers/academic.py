from datetime import date, datetime
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import (
    Career,
    ClassSchedule,
    CourseAssignment,
    Group,
    Organization,
    Person,
    Subject,
    User,
)
from app.schemas import (
    AcademicStatsResponse,
    CareerCreate,
    CareerRead,
    CareerUpdate,
    ClassScheduleCreate,
    ClassScheduleRead,
    CourseAssignmentCreate,
    CourseAssignmentRead,
    CourseAssignmentUpdate,
    GenerateSessionsRequest,
    GenerateSessionsResponse,
    SessionRead,
    StartCourseSessionRequest,
    SubjectCreate,
    SubjectRead,
    TeacherAgendaResponse,
)
from app.security import assert_org_access, get_current_user, require_roles, resolve_org_scope
from app.services.academic_service import (
    build_teacher_agenda,
    compute_academic_stats,
    generate_sessions_for_date,
    get_teacher_group_ids,
    serialize_courses_batch,
    serialize_sessions_batch,
    start_or_get_course_session,
    validate_schedule_times,
)
from app.services.security_service import record_audit_log

router = APIRouter(prefix="/api/academic", tags=["academic"])


def _serialize_careers(db: Session, careers: list[Career], organization_id: int) -> list[CareerRead]:
    if not careers:
        return []
    group_counts = {
        cid: int(cnt)
        for cid, cnt in db.execute(
            select(Group.career_id, func.count(Group.id))
            .where(Group.organization_id == organization_id, Group.career_id.is_not(None))
            .group_by(Group.career_id)
        ).all()
    }
    subject_counts = {
        cid: int(cnt)
        for cid, cnt in db.execute(
            select(Subject.career_id, func.count(Subject.id))
            .where(Subject.organization_id == organization_id, Subject.career_id.is_not(None))
            .group_by(Subject.career_id)
        ).all()
    }
    return [
        CareerRead(
            id=c.id,
            organization_id=c.organization_id,
            name=c.name,
            code=c.code,
            description=c.description,
            created_at=c.created_at,
            groups_count=group_counts.get(c.id, 0),
            subjects_count=subject_counts.get(c.id, 0),
        )
        for c in careers
    ]


def _serialize_subjects(db: Session, subjects: list[Subject], organization_id: int) -> list[SubjectRead]:
    if not subjects:
        return []
    career_map = {
        c.id: c.name
        for c in db.scalars(select(Career).where(Career.organization_id == organization_id)).all()
    }
    return [
        SubjectRead(
            id=s.id,
            organization_id=s.organization_id,
            career_id=s.career_id,
            career_name=career_map.get(s.career_id) if s.career_id else None,
            name=s.name,
            code=s.code,
            created_at=s.created_at,
        )
        for s in subjects
    ]


def _load_course_or_404(db: Session, course_id: int) -> CourseAssignment:
    course = db.scalars(
        select(CourseAssignment)
        .options(
            selectinload(CourseAssignment.subject),
            selectinload(CourseAssignment.group),
            selectinload(CourseAssignment.teacher),
            selectinload(CourseAssignment.schedules),
        )
        .where(CourseAssignment.id == course_id)
    ).first()
    if course is None:
        raise HTTPException(status_code=404, detail="Asignación de asignatura no encontrada.")
    return course


def _validate_teacher_user(db: Session, organization_id: int, teacher_user_id: int) -> User:
    teacher = db.get(User, teacher_user_id)
    if teacher is None or not teacher.is_active:
        raise HTTPException(status_code=404, detail="Usuario docente no encontrado o inactivo.")
    if teacher.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El profesor debe pertenecer a la misma organización.",
        )
    if teacher.role not in ("teacher", "org_admin"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El usuario asignado debe tener rol de Profesor o Administrador de organización.",
        )
    return teacher


# --- Carreras ---
@router.get("/careers", response_model=list[CareerRead])
def list_careers(
    organization_id: int | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CareerRead]:
    scoped_org_id = resolve_org_scope(current_user, organization_id)
    careers = list(
        db.scalars(
            select(Career)
            .where(Career.organization_id == scoped_org_id)
            .order_by(Career.name.asc())
        ).all()
    )
    return _serialize_careers(db, careers, scoped_org_id)


@router.post("/careers", response_model=CareerRead, status_code=status.HTTP_201_CREATED)
def create_career(
    payload: CareerCreate,
    current_user: User = Depends(require_roles("superadmin", "org_admin")),
    db: Session = Depends(get_db),
) -> CareerRead:
    assert_org_access(current_user, payload.organization_id)
    org = db.get(Organization, payload.organization_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organización no encontrada.")

    career = Career(
        organization_id=org.id,
        name=payload.name.strip(),
        code=payload.code.strip().upper(),
        description=payload.description.strip() if payload.description else None,
    )
    db.add(career)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe una carrera con el código '{career.code}'.",
        ) from exc

    record_audit_log(
        db,
        organization_id=org.id,
        action="create_career",
        target_type="career",
        target_id=career.id,
        target_summary=f"{career.name} ({career.code})",
        executed_by_user=current_user,
        authorized_by_user=current_user,
    )
    db.commit()
    db.refresh(career)
    return _serialize_careers(db, [career], org.id)[0]


@router.patch("/careers/{career_id}", response_model=CareerRead)
def update_career(
    career_id: int,
    payload: CareerUpdate,
    current_user: User = Depends(require_roles("superadmin", "org_admin")),
    db: Session = Depends(get_db),
) -> CareerRead:
    career = db.get(Career, career_id)
    if career is None:
        raise HTTPException(status_code=404, detail="Carrera no encontrada.")
    assert_org_access(current_user, career.organization_id)

    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        career.name = data["name"].strip()
    if "code" in data and data["code"] is not None:
        career.code = data["code"].strip().upper()
    if "description" in data:
        career.description = data["description"].strip() if data["description"] else None

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe otra carrera con ese código.",
        ) from exc
    db.refresh(career)
    return _serialize_careers(db, [career], career.organization_id)[0]


@router.delete("/careers/{career_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_career(
    career_id: int,
    current_user: User = Depends(require_roles("superadmin", "org_admin")),
    db: Session = Depends(get_db),
) -> None:
    career = db.get(Career, career_id)
    if career is None:
        raise HTTPException(status_code=404, detail="Carrera no encontrada.")
    assert_org_access(current_user, career.organization_id)
    db.delete(career)
    db.commit()


# --- Asignaturas ---
@router.get("/subjects", response_model=list[SubjectRead])
def list_subjects(
    organization_id: int | None = Query(default=None),
    career_id: int | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SubjectRead]:
    scoped_org_id = resolve_org_scope(current_user, organization_id)
    stmt = (
        select(Subject)
        .where(Subject.organization_id == scoped_org_id)
        .order_by(Subject.name.asc())
    )
    if career_id is not None:
        stmt = stmt.where(Subject.career_id == career_id)
    subjects = list(db.scalars(stmt).all())
    return _serialize_subjects(db, subjects, scoped_org_id)


@router.post("/subjects", response_model=SubjectRead, status_code=status.HTTP_201_CREATED)
def create_subject(
    payload: SubjectCreate,
    current_user: User = Depends(require_roles("superadmin", "org_admin")),
    db: Session = Depends(get_db),
) -> SubjectRead:
    assert_org_access(current_user, payload.organization_id)
    org = db.get(Organization, payload.organization_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organización no encontrada.")

    if payload.career_id is not None:
        career = db.get(Career, payload.career_id)
        if career is None or career.organization_id != org.id:
            raise HTTPException(status_code=404, detail="Carrera no encontrada en la organización.")

    subject = Subject(
        organization_id=org.id,
        career_id=payload.career_id,
        name=payload.name.strip(),
        code=payload.code.strip().upper(),
    )
    db.add(subject)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe una asignatura con el código '{subject.code}'.",
        ) from exc
    db.refresh(subject)
    return _serialize_subjects(db, [subject], org.id)[0]


@router.delete("/subjects/{subject_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_subject(
    subject_id: int,
    current_user: User = Depends(require_roles("superadmin", "org_admin")),
    db: Session = Depends(get_db),
) -> None:
    subject = db.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="Asignatura no encontrada.")
    assert_org_access(current_user, subject.organization_id)
    db.delete(subject)
    db.commit()


# --- Asignaciones Grupo-Materia-Profesor y Horarios ---
@router.get("/courses", response_model=list[CourseAssignmentRead])
def list_courses(
    organization_id: int | None = Query(default=None),
    group_id: int | None = Query(default=None),
    teacher_user_id: int | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CourseAssignmentRead]:
    scoped_org_id = resolve_org_scope(current_user, organization_id)

    effective_teacher_id = teacher_user_id
    if current_user.role == "teacher":
        if teacher_user_id is not None and teacher_user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo puedes consultar tus propias asignaciones de materias.",
            )
        effective_teacher_id = current_user.id

    stmt = (
        select(CourseAssignment)
        .options(
            selectinload(CourseAssignment.subject),
            selectinload(CourseAssignment.group),
            selectinload(CourseAssignment.teacher),
            selectinload(CourseAssignment.schedules),
        )
        .where(CourseAssignment.organization_id == scoped_org_id)
        .order_by(CourseAssignment.id.desc())
    )
    if group_id is not None:
        stmt = stmt.where(CourseAssignment.group_id == group_id)
    if effective_teacher_id is not None:
        stmt = stmt.where(CourseAssignment.teacher_user_id == effective_teacher_id)

    courses = list(db.scalars(stmt).all())
    return serialize_courses_batch(db, courses, scoped_org_id)


@router.post("/courses", response_model=CourseAssignmentRead, status_code=status.HTTP_201_CREATED)
def create_course(
    payload: CourseAssignmentCreate,
    current_user: User = Depends(require_roles("superadmin", "org_admin")),
    db: Session = Depends(get_db),
) -> CourseAssignmentRead:
    assert_org_access(current_user, payload.organization_id)
    org = db.get(Organization, payload.organization_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organización no encontrada.")

    group = db.get(Group, payload.group_id)
    if group is None or group.organization_id != org.id:
        raise HTTPException(status_code=404, detail="Grupo no encontrado en la organización.")

    subject = db.get(Subject, payload.subject_id)
    if subject is None or subject.organization_id != org.id:
        raise HTTPException(status_code=404, detail="Asignatura no encontrada en la organización.")

    if payload.teacher_user_id is not None:
        _validate_teacher_user(db, org.id, payload.teacher_user_id)

    for sl in payload.schedules:
        validate_schedule_times(sl.start_time, sl.end_time)

    course = CourseAssignment(
        organization_id=org.id,
        group_id=group.id,
        subject_id=subject.id,
        teacher_user_id=payload.teacher_user_id,
        term=payload.term.strip() if payload.term else None,
        is_active=True,
    )
    db.add(course)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este grupo ya tiene asignada esa asignatura.",
        ) from exc

    for sl in payload.schedules:
        db.add(
            ClassSchedule(
                course_assignment_id=course.id,
                day_of_week=sl.day_of_week,
                start_time=sl.start_time,
                end_time=sl.end_time,
                classroom=sl.classroom.strip() if sl.classroom else None,
            )
        )

    record_audit_log(
        db,
        organization_id=org.id,
        action="create_course_assignment",
        target_type="course_assignment",
        target_id=course.id,
        target_summary=f"{subject.name} -> {group.name}",
        executed_by_user=current_user,
        authorized_by_user=current_user,
    )
    db.commit()
    loaded = _load_course_or_404(db, course.id)
    return serialize_courses_batch(db, [loaded], org.id)[0]


@router.patch("/courses/{course_id}", response_model=CourseAssignmentRead)
def update_course(
    course_id: int,
    payload: CourseAssignmentUpdate,
    current_user: User = Depends(require_roles("superadmin", "org_admin")),
    db: Session = Depends(get_db),
) -> CourseAssignmentRead:
    course = _load_course_or_404(db, course_id)
    assert_org_access(current_user, course.organization_id)

    data = payload.model_dump(exclude_unset=True)
    if "teacher_user_id" in data and data["teacher_user_id"] is not None:
        _validate_teacher_user(db, course.organization_id, data["teacher_user_id"])

    for field, value in data.items():
        if field == "term" and value is not None:
            setattr(course, field, value.strip() or None)
        else:
            setattr(course, field, value)

    db.commit()
    loaded = _load_course_or_404(db, course.id)
    return serialize_courses_batch(db, [loaded], course.organization_id)[0]


@router.delete("/courses/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_course(
    course_id: int,
    current_user: User = Depends(require_roles("superadmin", "org_admin")),
    db: Session = Depends(get_db),
) -> None:
    course = db.get(CourseAssignment, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Asignación de asignatura no encontrada.")
    assert_org_access(current_user, course.organization_id)
    db.delete(course)
    db.commit()


@router.post(
    "/courses/{course_id}/schedules",
    response_model=ClassScheduleRead,
    status_code=status.HTTP_201_CREATED,
)
def add_course_schedule(
    course_id: int,
    payload: ClassScheduleCreate,
    current_user: User = Depends(require_roles("superadmin", "org_admin")),
    db: Session = Depends(get_db),
) -> ClassScheduleRead:
    course = db.get(CourseAssignment, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Asignación de asignatura no encontrada.")
    assert_org_access(current_user, course.organization_id)
    validate_schedule_times(payload.start_time, payload.end_time)

    schedule = ClassSchedule(
        course_assignment_id=course.id,
        day_of_week=payload.day_of_week,
        start_time=payload.start_time,
        end_time=payload.end_time,
        classroom=payload.classroom.strip() if payload.classroom else None,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return ClassScheduleRead.model_validate(schedule)


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule(
    schedule_id: int,
    current_user: User = Depends(require_roles("superadmin", "org_admin")),
    db: Session = Depends(get_db),
) -> None:
    schedule = db.get(ClassSchedule, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Bloque de horario no encontrado.")
    course = db.get(CourseAssignment, schedule.course_assignment_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Curso asociado no encontrado.")
    assert_org_access(current_user, course.organization_id)
    db.delete(schedule)
    db.commit()


# --- Herencia automática de materias para alumnos ---
@router.get("/students/{person_id}/courses", response_model=list[CourseAssignmentRead])
def get_student_inherited_courses(
    person_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CourseAssignmentRead]:
    person = db.scalars(
        select(Person)
        .options(selectinload(Person.group_links))
        .where(Person.id == person_id)
    ).first()
    if person is None:
        raise HTTPException(status_code=404, detail="Alumno no encontrado.")
    assert_org_access(current_user, person.organization_id)

    student_group_ids = {link.group_id for link in person.group_links}
    if current_user.role == "teacher":
        teacher_gids = get_teacher_group_ids(db, current_user.id)
        if not (student_group_ids & teacher_gids):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Este alumno no pertenece a ninguno de tus grupos.",
            )

    if not student_group_ids:
        return []

    stmt = (
        select(CourseAssignment)
        .options(
            selectinload(CourseAssignment.subject),
            selectinload(CourseAssignment.group),
            selectinload(CourseAssignment.teacher),
            selectinload(CourseAssignment.schedules),
        )
        .where(
            CourseAssignment.organization_id == person.organization_id,
            CourseAssignment.group_id.in_(student_group_ids),
            CourseAssignment.is_active.is_(True),
        )
        .order_by(CourseAssignment.id.asc())
    )
    if current_user.role == "teacher":
        stmt = stmt.where(CourseAssignment.teacher_user_id == current_user.id)

    courses = list(db.scalars(stmt).all())
    return serialize_courses_batch(db, courses, person.organization_id)


# --- Generación automática de sesiones y portal docente ---
@router.post("/sessions/generate", response_model=GenerateSessionsResponse)
def generate_academic_sessions(
    payload: GenerateSessionsRequest,
    current_user: User = Depends(require_roles("superadmin", "org_admin", "teacher")),
    db: Session = Depends(get_db),
) -> GenerateSessionsResponse:
    scoped_org_id = resolve_org_scope(current_user, payload.organization_id)
    target_date = payload.target_date or date.today()

    if payload.course_assignment_id is not None:
        assignment = db.get(CourseAssignment, payload.course_assignment_id)
        if assignment is None or assignment.organization_id != scoped_org_id:
            raise HTTPException(status_code=404, detail="Asignación de asignatura no encontrada.")
        if current_user.role == "teacher" and assignment.teacher_user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No puedes generar sesiones para materias de otro docente.",
            )

    created_count, existing_count, sessions = generate_sessions_for_date(
        db,
        organization_id=scoped_org_id,
        target_date=target_date,
        course_assignment_id=payload.course_assignment_id,
        teacher_user_id=current_user.id if current_user.role == "teacher" else None,
    )
    serialized = serialize_sessions_batch(db, sessions, scoped_org_id)
    return GenerateSessionsResponse(
        target_date=target_date,
        created_count=created_count,
        existing_count=existing_count,
        sessions=serialized,
    )


@router.post("/courses/{course_id}/start-session", response_model=SessionRead)
def start_course_session(
    course_id: int,
    payload: StartCourseSessionRequest | None = Body(default=None),
    current_user: User = Depends(require_roles("superadmin", "org_admin", "teacher")),
    db: Session = Depends(get_db),
) -> SessionRead:
    assignment = _load_course_or_404(db, course_id)
    assert_org_access(current_user, assignment.organization_id)

    if current_user.role == "teacher" and assignment.teacher_user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el profesor asignado o un administrador pueden iniciar esta sesión.",
        )

    target_date = (payload.session_date if payload and payload.session_date else None) or date.today()
    schedule_id = payload.schedule_id if payload else None
    session = start_or_get_course_session(
        db,
        assignment=assignment,
        target_date=target_date,
        schedule_id=schedule_id,
    )
    return serialize_sessions_batch(db, [session], assignment.organization_id)[0]


@router.get("/teacher/agenda", response_model=TeacherAgendaResponse)
def get_teacher_agenda(
    organization_id: int | None = Query(default=None),
    target_date: date | None = Query(default=None),
    current_time: str | None = Query(default=None, pattern=r"^\d{2}:\d{2}$"),
    teacher_user_id: int | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TeacherAgendaResponse:
    scoped_org_id = resolve_org_scope(current_user, organization_id)

    if current_user.role == "teacher":
        if teacher_user_id is not None and teacher_user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo puedes consultar tu propia agenda docente.",
            )
        resolved_teacher_id = current_user.id
    else:
        resolved_teacher_id = teacher_user_id if teacher_user_id is not None else current_user.id

    resolved_date = target_date or date.today()
    resolved_time = current_time or datetime.now().strftime("%H:%M")
    return build_teacher_agenda(
        db,
        organization_id=scoped_org_id,
        teacher_user_id=resolved_teacher_id,
        target_date=resolved_date,
        current_time_str=resolved_time,
    )


# --- Estadísticas administrativas (exclusivas para Superadmin / Org Admin) ---
@router.get("/stats", response_model=AcademicStatsResponse)
def get_academic_stats(
    organization_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    career_id: int | None = Query(default=None),
    group_id: int | None = Query(default=None),
    current_user: User = Depends(require_roles("superadmin", "org_admin")),
    db: Session = Depends(get_db),
) -> AcademicStatsResponse:
    scoped_org_id = resolve_org_scope(current_user, organization_id)
    return compute_academic_stats(
        db,
        organization_id=scoped_org_id,
        date_from=date_from,
        date_to=date_to,
        career_id=career_id,
        group_id=group_id,
    )
