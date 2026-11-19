from datetime import date, datetime
import time
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import (
    AttendanceEvent,
    AttendanceSession,
    FaceEmbedding,
    Group,
    Organization,
    Person,
    PersonGroup,
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
from app.services.attendance_service import (
    export_events_csv,
    get_or_create_active_session,
    record_recognized_attendance,
)
from app.vision.engine import bytes_to_embedding, decode_image_bytes, match_embedding
from app.vision.quality import evaluate_face_quality

router = APIRouter(prefix="/api", tags=["attendance"])


def _serialize_event(
    event: AttendanceEvent,
    person: Person,
    session: AttendanceSession,
) -> AttendanceEventRead:
    return AttendanceEventRead(
        id=event.id,
        session_id=event.session_id,
        session_title=session.title,
        person_id=event.person_id,
        person_name=person.full_name,
        person_external_id=person.external_id,
        person_avatar_base64=person.avatar_base64,
        event_type=event.event_type,
        status=event.status,
        confidence_score=event.confidence_score,
        capture_mode=event.capture_mode,
        timestamp=event.timestamp,
        notes=event.notes,
    )


def _serialize_session(
    session: AttendanceSession,
    group_name: str | None,
    events_count: int,
) -> SessionRead:
    return SessionRead(
        id=session.id,
        organization_id=session.organization_id,
        group_id=session.group_id,
        group_name=group_name,
        title=session.title,
        session_date=session.session_date,
        session_type=session.session_type,
        expected_start_time=session.expected_start_time,
        status=session.status,
        created_at=session.created_at,
        closed_at=session.closed_at,
        events_count=events_count,
    )


@router.get("/sessions", response_model=list[SessionRead])
def list_sessions(
    organization_id: int = Query(...),
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
) -> list[SessionRead]:
    stmt = (
        select(AttendanceSession)
        .where(AttendanceSession.organization_id == organization_id)
        .order_by(AttendanceSession.id.desc())
    )
    if status_filter:
        stmt = stmt.where(AttendanceSession.status == status_filter)
    sessions = db.scalars(stmt).all()

    group_names = {
        g.id: g.name
        for g in db.scalars(
            select(Group).where(Group.organization_id == organization_id)
        ).all()
    }
    event_counts = {
        sid: cnt
        for sid, cnt in db.execute(
            select(AttendanceEvent.session_id, func.count(AttendanceEvent.id))
            .group_by(AttendanceEvent.session_id)
        ).all()
    }

    return [
        _serialize_session(
            s,
            group_names.get(s.group_id) if s.group_id else None,
            event_counts.get(s.id, 0),
        )
        for s in sessions
    ]


@router.post("/sessions", response_model=SessionRead, status_code=status.HTTP_201_CREATED)
def create_session(payload: SessionCreate, db: Session = Depends(get_db)) -> SessionRead:
    org = db.get(Organization, payload.organization_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organización no encontrada.")

    group_name: str | None = None
    expected_start = payload.expected_start_time
    if payload.group_id is not None:
        group = db.get(Group, payload.group_id)
        if group is None or group.organization_id != org.id:
            raise HTTPException(status_code=404, detail="Grupo no encontrado en la organización.")
        group_name = group.name
        if expected_start is None:
            expected_start = group.schedule_start

    session_type = payload.session_type or ("class" if org.mode == "education" else "workday")
    session = AttendanceSession(
        organization_id=org.id,
        group_id=payload.group_id,
        title=payload.title.strip(),
        session_date=payload.session_date or date.today(),
        session_type=session_type,
        expected_start_time=expected_start,
        status="open",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return _serialize_session(session, group_name, 0)


@router.post("/sessions/{session_id}/close", response_model=SessionRead)
def close_session(session_id: int, db: Session = Depends(get_db)) -> SessionRead:
    session = db.get(AttendanceSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Sesión no encontrada.")

    if session.status != "closed":
        session.status = "closed"
        session.closed_at = datetime.now()
        db.commit()
        db.refresh(session)

    group = db.get(Group, session.group_id) if session.group_id else None
    count = db.scalar(
        select(func.count(AttendanceEvent.id)).where(AttendanceEvent.session_id == session.id)
    ) or 0
    return _serialize_session(session, group.name if group else None, count)


@router.post("/attendance/recognize-frame", response_model=RecognizeFrameResponse)
async def recognize_frame(
    request: Request,
    image: UploadFile = File(...),
    organization_id: int = Form(...),
    session_id: int | None = Form(default=None),
    group_id: int | None = Form(default=None),
    action_mode: ActionMode = Form(default="auto"),
    db: Session = Depends(get_db),
) -> RecognizeFrameResponse:
    t0 = time.perf_counter()
    settings = get_settings()

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
        if session.status != "open":
            raise HTTPException(status_code=400, detail="La sesión seleccionada ya está cerrada.")
    else:
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
        event=_serialize_event(rec.event, person, session) if rec.event else None,
        worked_minutes=rec.worked_minutes,
        session_id=session.id,
        message=rec.message,
        latency_ms=latency_ms,
    )


@router.get("/attendance/events", response_model=list[AttendanceEventRead])
def list_events(
    organization_id: int = Query(...),
    session_id: int | None = Query(default=None),
    person_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[AttendanceEventRead]:
    stmt = (
        select(AttendanceEvent, Person, AttendanceSession)
        .join(Person, Person.id == AttendanceEvent.person_id)
        .join(AttendanceSession, AttendanceSession.id == AttendanceEvent.session_id)
        .where(AttendanceSession.organization_id == organization_id)
        .order_by(AttendanceEvent.timestamp.desc(), AttendanceEvent.id.desc())
        .limit(limit)
    )
    if session_id is not None:
        stmt = stmt.where(AttendanceEvent.session_id == session_id)
    if person_id is not None:
        stmt = stmt.where(AttendanceEvent.person_id == person_id)

    rows = db.execute(stmt).all()
    return [_serialize_event(ev, per, ses) for ev, per, ses in rows]


@router.post("/attendance/manual", response_model=AttendanceEventRead, status_code=status.HTTP_201_CREATED)
def create_manual_attendance(
    payload: ManualAttendanceRequest,
    db: Session = Depends(get_db),
) -> AttendanceEventRead:
    session = db.get(AttendanceSession, payload.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Sesión no encontrada.")
    person = db.get(Person, payload.person_id)
    if person is None or person.organization_id != session.organization_id:
        raise HTTPException(
            status_code=404,
            detail="Persona no encontrada en la organización de la sesión.",
        )

    event = AttendanceEvent(
        session_id=session.id,
        person_id=person.id,
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
    return _serialize_event(event, person, session)


@router.get("/attendance/export.csv")
def export_attendance_csv(
    organization_id: int = Query(...),
    session_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> Response:
    stmt = (
        select(AttendanceEvent, Person, AttendanceSession)
        .join(Person, Person.id == AttendanceEvent.person_id)
        .join(AttendanceSession, AttendanceSession.id == AttendanceEvent.session_id)
        .where(AttendanceSession.organization_id == organization_id)
        .order_by(AttendanceEvent.timestamp.desc(), AttendanceEvent.id.desc())
    )
    if session_id is not None:
        stmt = stmt.where(AttendanceEvent.session_id == session_id)

    rows = db.execute(stmt).all()
    csv_content = export_events_csv([(ev, per, ses) for ev, per, ses in rows])
    return Response(
        content=csv_content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="asistencia_identia.csv"'},
    )
