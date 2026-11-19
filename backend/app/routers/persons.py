from datetime import datetime
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.db import get_db
from app.models import FaceEmbedding, Group, Organization, Person, PersonGroup
from app.schemas import (
    BiometricsRevokeResponse,
    EnrollFrameResponse,
    FaceBoxSchema,
    PersonCreate,
    PersonRead,
    PersonUpdate,
    PoseLabel,
    QualityReportSchema,
)
from app.vision.engine import (
    bytes_to_embedding,
    cosine_similarity,
    create_avatar_base64,
    decode_image_bytes,
    embedding_to_bytes,
)
from app.vision.quality import FaceBox, evaluate_face_quality

router = APIRouter(prefix="/api", tags=["persons"])


def _to_face_box_schema(box: FaceBox, img_w: int, img_h: int) -> FaceBoxSchema:
    return FaceBoxSchema(
        x=box.x,
        y=box.y,
        w=box.w,
        h=box.h,
        confidence=round(box.confidence, 4),
        image_width=img_w,
        image_height=img_h,
        nx=round(max(0.0, box.x) / max(img_w, 1), 4),
        ny=round(max(0.0, box.y) / max(img_h, 1), 4),
        nw=round(max(0.0, box.w) / max(img_w, 1), 4),
        nh=round(max(0.0, box.h) / max(img_h, 1), 4),
    )


def _serialize_person(person: Person, current_model_version: str) -> PersonRead:
    embeddings = person.embeddings
    current_poses = [
        e.pose_label for e in embeddings if e.model_version == current_model_version
    ]
    needs_reenroll = any(e.model_version != current_model_version for e in embeddings)
    return PersonRead(
        id=person.id,
        organization_id=person.organization_id,
        external_id=person.external_id,
        full_name=person.full_name,
        email=person.email,
        role=person.role,
        avatar_base64=person.avatar_base64,
        biometric_consent=person.biometric_consent,
        biometric_consent_at=person.biometric_consent_at,
        is_active=person.is_active,
        created_at=person.created_at,
        group_ids=[link.group_id for link in person.group_links],
        embeddings_count=len(current_poses),
        poses_completed=current_poses,
        needs_reenroll=needs_reenroll,
    )


def _sync_person_groups(
    db: Session,
    person: Person,
    group_ids: list[int],
) -> None:
    unique_ids = list(dict.fromkeys(group_ids))
    if unique_ids:
        valid_groups = db.scalars(
            select(Group).where(
                Group.id.in_(unique_ids),
                Group.organization_id == person.organization_id,
            )
        ).all()
        if len(valid_groups) != len(unique_ids):
            raise HTTPException(
                status_code=400,
                detail="Uno o más grupos no existen o no pertenecen a la organización.",
            )

    existing_links = db.scalars(
        select(PersonGroup).where(PersonGroup.person_id == person.id)
    ).all()
    for link in existing_links:
        db.delete(link)
    db.flush()

    for gid in unique_ids:
        db.add(PersonGroup(person_id=person.id, group_id=gid))


@router.get("/persons", response_model=list[PersonRead])
def list_persons(
    organization_id: int = Query(...),
    group_id: int | None = Query(default=None),
    search: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[PersonRead]:
    settings = get_settings()
    stmt = (
        select(Person)
        .options(selectinload(Person.embeddings), selectinload(Person.group_links))
        .where(Person.organization_id == organization_id)
        .order_by(Person.id.desc())
    )
    if group_id is not None:
        stmt = stmt.join(PersonGroup, PersonGroup.person_id == Person.id).where(
            PersonGroup.group_id == group_id
        )
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            (Person.full_name.ilike(pattern)) | (Person.external_id.ilike(pattern))
        )

    persons = db.scalars(stmt).all()
    return [_serialize_person(p, settings.model_version) for p in persons]


@router.post("/persons", response_model=PersonRead, status_code=status.HTTP_201_CREATED)
def create_person(
    payload: PersonCreate,
    db: Session = Depends(get_db),
) -> PersonRead:
    settings = get_settings()
    org = db.get(Organization, payload.organization_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organización no encontrada.")

    person = Person(
        organization_id=payload.organization_id,
        external_id=payload.external_id.strip(),
        full_name=payload.full_name.strip(),
        email=payload.email.strip() if payload.email else None,
        role=payload.role,
        biometric_consent=payload.biometric_consent,
        biometric_consent_at=datetime.now() if payload.biometric_consent else None,
    )
    db.add(person)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Ya existe una persona con el ID '{payload.external_id}' en esta organización.",
        ) from exc

    if payload.group_ids:
        _sync_person_groups(db, person, payload.group_ids)

    db.commit()
    loaded = db.scalars(
        select(Person)
        .options(selectinload(Person.embeddings), selectinload(Person.group_links))
        .where(Person.id == person.id)
    ).one()
    return _serialize_person(loaded, settings.model_version)


@router.patch("/persons/{person_id}", response_model=PersonRead)
def update_person(
    person_id: int,
    payload: PersonUpdate,
    db: Session = Depends(get_db),
) -> PersonRead:
    settings = get_settings()
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Persona no encontrada.")

    data = payload.model_dump(exclude_unset=True)
    group_ids = data.pop("group_ids", None)

    if "biometric_consent" in data:
        new_consent = bool(data["biometric_consent"])
        if new_consent and not person.biometric_consent:
            person.biometric_consent_at = datetime.now()
        elif not new_consent:
            person.biometric_consent_at = None

    for field, value in data.items():
        setattr(person, field, value)

    if group_ids is not None:
        _sync_person_groups(db, person, group_ids)

    db.commit()
    loaded = db.scalars(
        select(Person)
        .options(selectinload(Person.embeddings), selectinload(Person.group_links))
        .where(Person.id == person.id)
    ).one()
    return _serialize_person(loaded, settings.model_version)


@router.delete("/persons/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_person(person_id: int, db: Session = Depends(get_db)) -> None:
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Persona no encontrada.")
    db.delete(person)
    db.commit()


@router.post("/persons/{person_id}/enroll-frame", response_model=EnrollFrameResponse)
async def enroll_frame(
    person_id: int,
    request: Request,
    image: UploadFile = File(...),
    pose_label: PoseLabel = Form(...),
    store_avatar: bool | None = Form(default=None),
    db: Session = Depends(get_db),
) -> EnrollFrameResponse:
    settings = get_settings()
    person = db.scalars(
        select(Person)
        .options(selectinload(Person.embeddings))
        .where(Person.id == person_id)
    ).first()
    if person is None:
        raise HTTPException(status_code=404, detail="Persona no encontrada.")
    if not person.biometric_consent:
        raise HTTPException(
            status_code=400,
            detail="Se requiere consentimiento biométrico explícito antes de registrar el rostro.",
        )

    engine = getattr(request.app.state, "biometric_engine", None)
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail="El motor biométrico no está inicializado en el servidor.",
        )

    raw_bytes = await image.read()
    try:
        image_bgr = decode_image_bytes(raw_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    img_h, img_w = image_bgr.shape[:2]
    current_poses = [
        e.pose_label
        for e in person.embeddings
        if e.model_version == settings.model_version
    ]

    detections = engine.detect(image_bgr)
    if len(detections) == 0:
        return EnrollFrameResponse(
            accepted=False,
            pose_label=pose_label,
            message="No se detectó ningún rostro. Colócate frente a la cámara.",
            embeddings_count=len(current_poses),
            poses_completed=current_poses,
        )

    primary_box, primary_row = detections[0]
    face_box_schema = _to_face_box_schema(primary_box, img_w, img_h)

    if len(detections) > 1:
        return EnrollFrameResponse(
            accepted=False,
            pose_label=pose_label,
            message="Se detectaron varios rostros; asegúrate de estar solo frente a la cámara.",
            embeddings_count=len(current_poses),
            poses_completed=current_poses,
            face_box=face_box_schema,
        )

    quality = evaluate_face_quality(
        image_bgr,
        primary_box,
        min_size_px=settings.min_face_size_px,
        min_blur=settings.min_blur_variance,
        min_brightness=settings.min_brightness,
        max_brightness=settings.max_brightness,
    )
    quality_schema = QualityReportSchema(
        ok=quality.ok,
        reason=quality.reason,
        blur_score=round(quality.blur_score, 2),
        brightness=round(quality.brightness, 2),
        face_width=quality.face_width,
        face_height=quality.face_height,
        pose_hint=quality.pose_hint,
    )
    if not quality.ok:
        return EnrollFrameResponse(
            accepted=False,
            pose_label=pose_label,
            message=quality.reason or "Calidad de imagen insuficiente.",
            embeddings_count=len(current_poses),
            poses_completed=current_poses,
            face_box=face_box_schema,
            quality=quality_schema,
        )

    embedding_vec = engine.extract_embedding(image_bgr, primary_row)

    # Verifica que no se mezcle el rostro de otra persona entre poses
    other_same_version = [
        e
        for e in person.embeddings
        if e.model_version == settings.model_version and e.pose_label != pose_label
    ]
    if other_same_version:
        max_self_sim = max(
            cosine_similarity(embedding_vec, bytes_to_embedding(e.vector_bytes))
            for e in other_same_version
        )
        if max_self_sim < settings.self_consistency_threshold:
            return EnrollFrameResponse(
                accepted=False,
                pose_label=pose_label,
                message="El rostro capturado no coincide con las tomas previas de esta persona.",
                embeddings_count=len(current_poses),
                poses_completed=current_poses,
                face_box=face_box_schema,
                quality=quality_schema,
            )

    existing_pose = next((e for e in person.embeddings if e.pose_label == pose_label), None)
    vector_bytes = embedding_to_bytes(embedding_vec)
    if existing_pose is not None:
        existing_pose.vector_bytes = vector_bytes
        existing_pose.model_name = settings.model_name
        existing_pose.model_version = settings.model_version
        existing_pose.quality_score = round(quality.blur_score, 2)
        existing_pose.created_at = datetime.now()
    else:
        db.add(
            FaceEmbedding(
                person_id=person.id,
                pose_label=pose_label,
                vector_bytes=vector_bytes,
                model_name=settings.model_name,
                model_version=settings.model_version,
                quality_score=round(quality.blur_score, 2),
            )
        )

    org = db.get(Organization, person.organization_id)
    should_store_avatar = (
        store_avatar
        if store_avatar is not None
        else (org.store_avatar_by_default if org is not None else True)
    )
    avatar_saved = False
    if pose_label == "frontal" and should_store_avatar:
        person.avatar_base64 = create_avatar_base64(image_bgr, primary_box, size=200)
        avatar_saved = True

    db.commit()

    refreshed = db.scalars(
        select(FaceEmbedding).where(
            FaceEmbedding.person_id == person.id,
            FaceEmbedding.model_version == settings.model_version,
        )
    ).all()
    updated_poses = [e.pose_label for e in refreshed]

    return EnrollFrameResponse(
        accepted=True,
        pose_label=pose_label,
        message=f"Pose '{pose_label}' registrada en memoria y vector almacenado.",
        embeddings_count=len(updated_poses),
        poses_completed=updated_poses,
        face_box=face_box_schema,
        quality=quality_schema,
        avatar_saved=avatar_saved,
    )


@router.delete("/persons/{person_id}/biometrics", response_model=BiometricsRevokeResponse)
def revoke_biometrics(person_id: int, db: Session = Depends(get_db)) -> BiometricsRevokeResponse:
    person = db.scalars(
        select(Person)
        .options(selectinload(Person.embeddings))
        .where(Person.id == person_id)
    ).first()
    if person is None:
        raise HTTPException(status_code=404, detail="Persona no encontrada.")

    deleted_count = len(person.embeddings)
    for emb in list(person.embeddings):
        db.delete(emb)

    had_avatar = person.avatar_base64 is not None
    person.avatar_base64 = None
    db.commit()

    return BiometricsRevokeResponse(
        person_id=person.id,
        deleted_embeddings=deleted_count,
        avatar_cleared=had_avatar,
    )
