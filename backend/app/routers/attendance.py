from datetime import date, datetime
import time
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.db import get_db
from app.models import (
    AttendanceEvent,
    AttendanceSession,
    ClassSchedule,
    CourseAssignment,
    FaceEmbedding,
    Group,
    Organization,
    Person,
    PersonGroup,
    User,
    WorkShift,
)
from app.routers import to_face_box_schema, to_quality_schema
from app.schemas import (
    ActionMode,
    AttendanceEventRead,
    ManualAttendanceRequest,
    PersonSummaryBrief,
    RecognizeFrameResponse,
    SessionCreate,
    SessionRead,
)
from app.security import assert_org_access, get_current_user, resolve_org_scope
from app.services.academic_service import (
    assert_session_teacher_access,
    get_teacher_course_ids,
    serialize_sessions_batch,
)
from app.services.attendance_service import (
    export_events_csv,
    get_or_create_active_session,
    record_recognized_attendance,
)
from app.services.enterprise_service import resolve_attendance_work_shift
from app.vision.engine import bytes_to_embedding, decode_image_bytes, match_embedding
from app.vision.quality import evaluate_face_quality

router = APIRouter(prefix="/api", tags=["attendance"])


def _serialize_event(
    event: AttendanceEvent,
    person: Person,
    session: AttendanceSession,
    shift_names: dict[int, str] | None = None,
) -> AttendanceEventRead:
    resolved_shift_id = event.work_shift_id if event.work_shift_id is not None else session.work_shift_id
    shift_name = (
        shift_names.get(resolved_shift_id)
        if shift_names is not None and resolved_shift_id is not None
        else None
    )
    if shift_name is None and event.work_shift is not None:
        shift_name = event.work_shift.name
    return AttendanceEventRead(
        id=event.id,
        session_id=event.session_id,
        session_title=session.title,
        person_id=event.person_id,
        person_name=person.full_name,
        person_external_id=person.external_id,
        person_avatar_base64=person.avatar_base64,
        work_shift_id=event.work_shift_id,
        work_shift_name=shift_name,
        event_type=event.event_type,
        status=event.status,
        confidence_score=event.confidence_score,
        worked_minutes=event.worked_minutes,
        late_minutes=event.late_minutes,
        early_exit_minutes=event.early_exit_minutes,
        capture_mode=event.capture_mode,
        timestamp=event.timestamp,
        notes=event.notes,
    )


@router.get("/sessions", response_model=list[SessionRead])
def list_sessions(
    organization_id: int | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SessionRead]:
    scoped_org_id = resolve_org_scope(current_user, organization_id)
    stmt = (
        select(AttendanceSession)
        .where(AttendanceSession.organization_id == scoped_org_id)
        .order_by(AttendanceSession.id.desc())
    )
    if current_user.role == "teacher":
        teacher_courses = get_teacher_course_ids(db, current_user.id)
        if not teacher_courses:
            return []
        stmt = stmt.where(AttendanceSession.course_assignment_id.in_(teacher_courses))
    if status_filter:
        stmt = stmt.where(AttendanceSession.status == status_filter)
    sessions = list(db.scalars(stmt).all())
    return serialize_sessions_batch(db, sessions, scoped_org_id)


@router.post("/sessions", response_model=SessionRead, status_code=status.HTTP_201_CREATED)
def create_session(
    payload: SessionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SessionRead:
    assert_org_access(current_user, payload.organization_id)
    org = db.get(Organization, payload.organization_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organización no encontrada.")

    if current_user.role == "teacher" and payload.course_assignment_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Un docente debe abrir sesiones vinculadas a una de sus asignaturas.",
        )

    resolved_group_id = payload.group_id
    expected_start = payload.expected_start_time
    session_type = payload.session_type or ("class" if org.mode == "education" else "workday")

    if payload.course_assignment_id is not None:
        assignment = db.scalars(
            select(CourseAssignment)
            .options(selectinload(CourseAssignment.group))
            .where(CourseAssignment.id == payload.course_assignment_id)
        ).first()
        if assignment is None or assignment.organization_id != org.id:
            raise HTTPException(status_code=404, detail="Asignación de materia no encontrada.")
        if current_user.role == "teacher" and assignment.teacher_user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No puedes crear sesiones para una materia de otro profesor.",
            )
        resolved_group_id = assignment.group_id
        session_type = "class"
        if payload.schedule_id is not None:
            schedule = db.get(ClassSchedule, payload.schedule_id)
            if schedule is None or schedule.course_assignment_id != assignment.id:
                raise HTTPException(status_code=404, detail="Horario no encontrado para la materia.")
            if expected_start is None:
                expected_start = schedule.start_time
        elif expected_start is None and assignment.group is not None:
            expected_start = assignment.group.schedule_start
    elif payload.work_shift_id is not None:
        work_shift = db.get(WorkShift, payload.work_shift_id)
        if work_shift is None or work_shift.organization_id != org.id:
            raise HTTPException(
                status_code=404,
                detail="Turno laboral no encontrado en la organización.",
            )
        session_type = "workday"
        if expected_start is None:
            expected_start = work_shift.start_time
        if resolved_group_id is not None:
            group = db.get(Group, resolved_group_id)
            if group is None or group.organization_id != org.id:
                raise HTTPException(status_code=404, detail="Grupo no encontrado en la organización.")
    elif resolved_group_id is not None:
        group = db.get(Group, resolved_group_id)
        if group is None or group.organization_id != org.id:
            raise HTTPException(status_code=404, detail="Grupo no encontrado en la organización.")
        if expected_start is None:
            expected_start = group.schedule_start

    session = AttendanceSession(
        organization_id=org.id,
        group_id=resolved_group_id,
        course_assignment_id=payload.course_assignment_id,
        schedule_id=payload.schedule_id,
        work_shift_id=payload.work_shift_id,
        title=payload.title.strip(),
        session_date=payload.session_date or date.today(),
        session_type=session_type,
        expected_start_time=expected_start,
        status="open",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return serialize_sessions_batch(db, [session], org.id)[0]


@router.post("/sessions/{session_id}/close", response_model=SessionRead)
def close_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SessionRead:
    session = db.get(AttendanceSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Sesión no encontrada.")
    assert_org_access(current_user, session.organization_id)
    assert_session_teacher_access(db, current_user, session)

    if session.status != "closed":
        session.status = "closed"
        session.closed_at = datetime.now()
        db.commit()
        db.refresh(session)

    return serialize_sessions_batch(db, [session], session.organization_id)[0]


@router.post("/attendance/recognize-frame", response_model=RecognizeFrameResponse)
async def recognize_frame(
    request: Request,
    image: UploadFile = File(...),
    organization_id: int = Form(...),
    session_id: int | None = Form(default=None),
    group_id: int | None = Form(default=None),
    action_mode: ActionMode = Form(default="auto"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecognizeFrameResponse:
    t0 = time.perf_counter()
    settings = get_settings()

    assert_org_access(current_user, organization_id)
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organización no encontrada.")

    engine = getattr(request.app.state, "biometric_engine", None)
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail="El motor biométrico no está inicializado en el servidor.",
        )

    if session_id is not None:
        session = db.get(AttendanceSession, session_id)
        if session is None or session.organization_id != org.id:
            raise HTTPException(status_code=404, detail="Sesión no encontrada en la organización.")
        assert_session_teacher_access(db, current_user, session)
        if session.status != "open":
            raise HTTPException(status_code=400, detail="La sesión seleccionada ya está cerrada.")
    else:
        if current_user.role == "teacher":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Debes seleccionar una sesión de tu asignatura para tomar asistencia.",
            )
        try:
            session = get_or_create_active_session(db, org, group_id=group_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    raw_bytes = await image.read()
    try:
        image_bgr = decode_image_bytes(raw_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    img_h, img_w = image_bgr.shape[:2]
    detections = engine.detect(image_bgr)
    if not detections:
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return RecognizeFrameResponse(
            faces_detected=0,
            match_status="no_face",
            session_id=session.id,
            message="No se detectó ningún rostro frente a la cámara.",
            latency_ms=latency_ms,
        )

    primary_box, primary_row = detections[0]
    face_box_schema = to_face_box_schema(primary_box, img_w, img_h)
    quality = evaluate_face_quality(
        image_bgr,
        primary_box,
        min_size_px=settings.kiosk_min_face_size_px,
        min_blur=settings.kiosk_min_blur_variance,
        min_brightness=settings.kiosk_min_brightness,
        max_brightness=settings.max_brightness,
        max_shadow_asymmetry=settings.kiosk_max_shadow_asymmetry,
        backlight_delta_threshold=settings.backlight_delta_threshold,
        strict_lighting=False,
    )
    quality_schema = to_quality_schema(quality)

    if not quality.ok:
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return RecognizeFrameResponse(
            faces_detected=len(detections),
            match_status="low_quality",
            face_box=face_box_schema,
            quality=quality_schema,
            session_id=session.id,
            message=quality.reason or "Calidad insuficiente para reconocimiento.",
            latency_ms=latency_ms,
        )

    query_vec = engine.extract_embedding(image_bgr, primary_row)

    effective_group_id = session.group_id if session.group_id is not None else group_id
    gallery_stmt = (
        select(Person.id, Person.full_name, FaceEmbedding.vector_bytes)
        .join(FaceEmbedding, FaceEmbedding.person_id == Person.id)
        .where(
            Person.organization_id == org.id,
            Person.is_active.is_(True),
            Person.biometric_consent.is_(True),
            FaceEmbedding.model_version == settings.model_version,
        )
    )
    if effective_group_id is not None:
        gallery_stmt = gallery_stmt.join(
            PersonGroup, PersonGroup.person_id == Person.id
        ).where(PersonGroup.group_id == effective_group_id)

    gallery_rows = db.execute(gallery_stmt).all()
    gallery = [
        (pid, pname, bytes_to_embedding(vec_bytes))
        for pid, pname, vec_bytes in gallery_rows
    ]

    decision = match_embedding(
        query_vec,
        gallery,
        threshold=settings.match_threshold,
        margin=settings.ambiguous_margin,
    )

    if decision.status == "unknown":
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        if not gallery:
            msg = "No hay personas con biometría registrada en este alcance."
        elif quality.backlight_detected:
            msg = (
                "Rostro no reconocido. Se detectó contraluz fuerte; intenta mirar más de frente "
                "o mejorar la luz frontal."
            )
        else:
            msg = "Rostro no reconocido en el padrón activo."
        return RecognizeFrameResponse(
            faces_detected=len(detections),
            match_status="unknown",
            face_box=face_box_schema,
            quality=quality_schema,
            confidence=round(decision.confidence, 4),
            second_best_score=(
                round(decision.second_best_score, 4)
                if decision.second_best_score is not None
                else None
            ),
            session_id=session.id,
            message=msg,
            latency_ms=latency_ms,
        )

    if decision.status == "ambiguous" or decision.person_id is None:
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return RecognizeFrameResponse(
            faces_detected=len(detections),
            match_status="ambiguous",
            face_box=face_box_schema,
            quality=quality_schema,
            confidence=round(decision.confidence, 4),
            second_best_score=(
                round(decision.second_best_score, 4)
                if decision.second_best_score is not None
                else None
            ),
            session_id=session.id,
            message="Coincidencia ambigua entre dos personas. Acércate o mejora la iluminación.",
            latency_ms=latency_ms,
        )

    person = db.get(Person, decision.person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Persona reconocida no encontrada.")

    rec = record_recognized_attendance(
        db=db,
        organization=org,
        session=session,
        person=person,
        confidence_score=decision.confidence,
        action_mode=action_mode,
        capture_mode="kiosk_individual",
    )
    latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    serialized_event = None
    if rec.event is not None:
        event_session = db.get(AttendanceSession, rec.event.session_id) or session
        ev_shift_names = (
            {rec.event.work_shift_id: rec.shift_name}
            if rec.event.work_shift_id is not None and rec.shift_name is not None
            else None
        )
        serialized_event = _serialize_event(rec.event, person, event_session, ev_shift_names)

    return RecognizeFrameResponse(
        faces_detected=len(detections),
        match_status="matched",
        face_box=face_box_schema,
        quality=quality_schema,
        person=PersonSummaryBrief(
            id=person.id,
            external_id=person.external_id,
            full_name=person.full_name,
            role=person.role,
            avatar_base64=person.avatar_base64,
        ),
        confidence=round(decision.confidence, 4),
        second_best_score=(
            round(decision.second_best_score, 4)
            if decision.second_best_score is not None
            else None
        ),
        attendance_action=rec.action,
        event=serialized_event,
        worked_minutes=rec.worked_minutes,
        shift_name=rec.shift_name,
        late_minutes=rec.late_minutes,
        early_exit_minutes=rec.early_exit_minutes,
        session_id=rec.event.session_id if rec.event else session.id,
        message=rec.message,
        latency_ms=latency_ms,
    )


@router.get("/attendance/events", response_model=list[AttendanceEventRead])
def list_events(
    organization_id: int | None = Query(default=None),
    session_id: int | None = Query(default=None),
    person_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AttendanceEventRead]:
    scoped_org_id = resolve_org_scope(current_user, organization_id)
    teacher_courses: set[int] | None = None
    if current_user.role == "teacher":
        if session_id is not None:
            target_sess = db.get(AttendanceSession, session_id)
            if target_sess is None or target_sess.organization_id != scoped_org_id:
                raise HTTPException(status_code=404, detail="Sesión no encontrada.")
            assert_session_teacher_access(db, current_user, target_sess)
        teacher_courses = get_teacher_course_ids(db, current_user.id)
        if not teacher_courses:
            return []

    stmt = (
        select(AttendanceEvent, Person, AttendanceSession)
        .join(Person, Person.id == AttendanceEvent.person_id)
        .join(AttendanceSession, AttendanceSession.id == AttendanceEvent.session_id)
        .where(AttendanceSession.organization_id == scoped_org_id)
        .order_by(AttendanceEvent.timestamp.desc(), AttendanceEvent.id.desc())
        .limit(limit)
    )
    if teacher_courses is not None:
        stmt = stmt.where(AttendanceSession.course_assignment_id.in_(teacher_courses))
    if session_id is not None:
        stmt = stmt.where(AttendanceEvent.session_id == session_id)
    if person_id is not None:
        stmt = stmt.where(AttendanceEvent.person_id == person_id)

    rows = db.execute(stmt).all()
    shift_names = {
        sh.id: sh.name
        for sh in db.scalars(
            select(WorkShift).where(WorkShift.organization_id == scoped_org_id)
        ).all()
    }
    return [_serialize_event(ev, per, ses, shift_names) for ev, per, ses in rows]


@router.post("/attendance/manual", response_model=AttendanceEventRead, status_code=status.HTTP_201_CREATED)
def create_manual_attendance(
    payload: ManualAttendanceRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AttendanceEventRead:
    session = db.get(AttendanceSession, payload.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Sesión no encontrada.")
    assert_org_access(current_user, session.organization_id)
    assert_session_teacher_access(db, current_user, session)

    person = db.get(Person, payload.person_id)
    if person is None or person.organization_id != session.organization_id:
        raise HTTPException(
            status_code=404,
            detail="Persona no encontrada en la organización de la sesión.",
        )

    if current_user.role == "teacher" and session.group_id is not None:
        in_group = db.scalars(
            select(PersonGroup).where(
                PersonGroup.person_id == person.id,
                PersonGroup.group_id == session.group_id,
            )
        ).first()
        if in_group is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="El alumno no pertenece al grupo de esta sesión.",
            )

    resolved_shift = (
        resolve_attendance_work_shift(db, person, session)
        if session.session_type == "workday"
        else None
    )
    event = AttendanceEvent(
        session_id=session.id,
        person_id=person.id,
        work_shift_id=resolved_shift.id if resolved_shift else None,
        event_type=payload.event_type,
        status=payload.status,
        confidence_score=None,
        capture_mode="manual",
        timestamp=datetime.now(),
        notes=payload.notes,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    shift_names = {resolved_shift.id: resolved_shift.name} if resolved_shift else None
    return _serialize_event(event, person, session, shift_names)


@router.get("/attendance/export.csv")
def export_attendance_csv(
    organization_id: int | None = Query(default=None),
    session_id: int | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    scoped_org_id = resolve_org_scope(current_user, organization_id)
    teacher_courses: set[int] | None = None
    if current_user.role == "teacher":
        if session_id is not None:
            target_sess = db.get(AttendanceSession, session_id)
            if target_sess is None or target_sess.organization_id != scoped_org_id:
                raise HTTPException(status_code=404, detail="Sesión no encontrada.")
            assert_session_teacher_access(db, current_user, target_sess)
        teacher_courses = get_teacher_course_ids(db, current_user.id)

    if teacher_courses is not None and not teacher_courses:
        rows = []
    else:
        stmt = (
            select(AttendanceEvent, Person, AttendanceSession)
            .join(Person, Person.id == AttendanceEvent.person_id)
            .join(AttendanceSession, AttendanceSession.id == AttendanceEvent.session_id)
            .where(AttendanceSession.organization_id == scoped_org_id)
            .order_by(AttendanceEvent.timestamp.desc(), AttendanceEvent.id.desc())
        )
        if teacher_courses is not None:
            stmt = stmt.where(AttendanceSession.course_assignment_id.in_(teacher_courses))
        if session_id is not None:
            stmt = stmt.where(AttendanceEvent.session_id == session_id)

        rows = db.execute(stmt).all()

    shift_names = {
        sh.id: sh.name
        for sh in db.scalars(
            select(WorkShift).where(WorkShift.organization_id == scoped_org_id)
        ).all()
    }
    csv_content = export_events_csv(
        [(ev, per, ses) for ev, per, ses in rows],
        shift_names=shift_names,
    )
    return Response(
        content=csv_content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="asistencia_identia.csv"'},
    )
