from datetime import datetime
from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.db import get_db
from app.models import FaceEmbedding, Group, Organization, Person, PersonGroup, User
from app.routers import to_face_box_schema, to_quality_schema
from app.schemas import (
    BatchBiometricsRevokeRequest,
    BatchBiometricsRevokeResponse,
    BiometricsRevokeRequest,
    BiometricsRevokeResponse,
    EnrollFrameResponse,
    PersonCreate,
    PersonRead,
    PersonUpdate,
    PoseLabel,
)
from app.security import assert_org_access, get_current_user, require_roles, resolve_org_scope
from app.services.academic_service import get_teacher_group_ids
from app.services.security_service import (
    AuthorizationResult,
    record_audit_log,
    verify_sensitive_authorization,
)
from app.vision.engine import (
    bytes_to_embedding,
    cosine_similarity,
    create_avatar_base64,
    decode_image_bytes,
    embedding_to_bytes,
)
from app.vision.quality import evaluate_face_quality

router = APIRouter(prefix="/api", tags=["persons"])
REQUIRED_POSES_COUNT = 6


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
    organization_id: int | None = Query(default=None),
    group_id: int | None = Query(default=None),
    search: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PersonRead]:
    settings = get_settings()
    scoped_org_id = resolve_org_scope(current_user, organization_id)
    stmt = (
        select(Person)
        .options(selectinload(Person.embeddings), selectinload(Person.group_links))
        .where(Person.organization_id == scoped_org_id)
        .order_by(Person.id.desc())
    )
    if current_user.role == "teacher":
        teacher_gids = get_teacher_group_ids(db, current_user.id)
        if not teacher_gids:
            return []
        stmt = stmt.where(
            Person.id.in_(
                select(PersonGroup.person_id).where(PersonGroup.group_id.in_(teacher_gids))
            )
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
    current_user: User = Depends(require_roles("superadmin", "org_admin", "operator")),
    db: Session = Depends(get_db),
) -> PersonRead:
    settings = get_settings()
    assert_org_access(current_user, payload.organization_id)
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
    current_user: User = Depends(require_roles("superadmin", "org_admin", "operator")),
    db: Session = Depends(get_db),
) -> PersonRead:
    settings = get_settings()
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Persona no encontrada.")
    assert_org_access(current_user, person.organization_id)

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
def delete_person(
    person_id: int,
    current_user: User = Depends(require_roles("superadmin", "org_admin")),
    db: Session = Depends(get_db),
) -> None:
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Persona no encontrada.")
    assert_org_access(current_user, person.organization_id)
    db.delete(person)
    db.commit()


@router.post("/persons/{person_id}/enroll-frame", response_model=EnrollFrameResponse)
async def enroll_frame(
    person_id: int,
    request: Request,
    image: UploadFile = File(...),
    pose_label: PoseLabel = Form(...),
    store_avatar: bool | None = Form(default=None),
    dry_run: bool = Form(default=False),
    current_user: User = Depends(require_roles("superadmin", "org_admin", "operator")),
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
    assert_org_access(current_user, person.organization_id)
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
    already_complete = len(current_poses) >= REQUIRED_POSES_COUNT

    detections = engine.detect(image_bgr)
    if len(detections) == 0:
        return EnrollFrameResponse(
            accepted=False,
            pose_valid=False,
            pose_label=pose_label,
            message="No se detectó ningún rostro. Colócate frente a la cámara.",
            embeddings_count=len(current_poses),
            poses_completed=current_poses,
            is_complete=already_complete,
            required_poses_count=REQUIRED_POSES_COUNT,
        )

    primary_box, primary_row = detections[0]
    face_box_schema = to_face_box_schema(primary_box, img_w, img_h)

    if len(detections) > 1:
        return EnrollFrameResponse(
            accepted=False,
            pose_valid=False,
            pose_label=pose_label,
            message="Se detectaron varios rostros; asegúrate de estar solo frente a la cámara.",
            embeddings_count=len(current_poses),
            poses_completed=current_poses,
            is_complete=already_complete,
            required_poses_count=REQUIRED_POSES_COUNT,
            face_box=face_box_schema,
        )

    frontal_emb = next(
        (
            e
            for e in person.embeddings
            if e.pose_label == "frontal" and e.model_version == settings.model_version
        ),
        None,
    )
    frontal_mouth_ratio = frontal_emb.mouth_ratio if frontal_emb is not None else None
    frontal_pitch_ratio = frontal_emb.pitch_ratio if frontal_emb is not None else None

    quality = evaluate_face_quality(
        image_bgr,
        primary_box,
        min_size_px=settings.min_face_size_px,
        min_blur=settings.enroll_min_blur_variance,
        min_brightness=settings.enroll_min_brightness,
        max_brightness=settings.max_brightness,
        expected_pose=pose_label,
        frontal_mouth_ratio=frontal_mouth_ratio,
        frontal_pitch_ratio=frontal_pitch_ratio,
        max_shadow_asymmetry=settings.enroll_max_shadow_asymmetry,
        backlight_delta_threshold=settings.backlight_delta_threshold,
        strict_lighting=True,
    )
    quality_schema = to_quality_schema(quality)

    if not quality.ok:
        return EnrollFrameResponse(
            accepted=False,
            pose_valid=False,
            pose_label=pose_label,
            message=quality.reason or "Calidad de imagen insuficiente.",
            embeddings_count=len(current_poses),
            poses_completed=current_poses,
            is_complete=already_complete,
            required_poses_count=REQUIRED_POSES_COUNT,
            face_box=face_box_schema,
            quality=quality_schema,
        )

    if not quality.pose_matches:
        return EnrollFrameResponse(
            accepted=False,
            pose_valid=False,
            pose_label=pose_label,
            message=quality.pose_feedback or "La orientación del rostro no coincide con la pose solicitada.",
            embeddings_count=len(current_poses),
            poses_completed=current_poses,
            is_complete=already_complete,
            required_poses_count=REQUIRED_POSES_COUNT,
            face_box=face_box_schema,
            quality=quality_schema,
        )

    if dry_run:
        return EnrollFrameResponse(
            accepted=False,
            pose_valid=True,
            pose_label=pose_label,
            message="Pose validada, mantén firme la posición...",
            embeddings_count=len(current_poses),
            poses_completed=current_poses,
            is_complete=already_complete,
            required_poses_count=REQUIRED_POSES_COUNT,
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
                pose_valid=False,
                pose_label=pose_label,
                message="El rostro capturado no coincide con las tomas previas de esta persona.",
                embeddings_count=len(current_poses),
                poses_completed=current_poses,
                is_complete=already_complete,
                required_poses_count=REQUIRED_POSES_COUNT,
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
        existing_pose.mouth_ratio = round(quality.mouth_ratio, 4)
        existing_pose.pitch_ratio = round(quality.pitch_ratio, 4)
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
                mouth_ratio=round(quality.mouth_ratio, 4),
                pitch_ratio=round(quality.pitch_ratio, 4),
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
        pose_valid=True,
        pose_label=pose_label,
        message=f"Pose '{pose_label}' registrada en memoria y vector almacenado.",
        embeddings_count=len(updated_poses),
        poses_completed=updated_poses,
        is_complete=len(updated_poses) >= REQUIRED_POSES_COUNT,
        required_poses_count=REQUIRED_POSES_COUNT,
        face_box=face_box_schema,
        quality=quality_schema,
        avatar_saved=avatar_saved,
    )


def _revoke_persons_biometrics(
    db: Session,
    *,
    current_user: User,
    persons: list[Person],
    authorization_secret: str,
    reason: str | None,
) -> tuple[int, bool, AuthorizationResult]:
    org_ids = {p.organization_id for p in persons}
    if len(org_ids) != 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Todas las personas seleccionadas deben pertenecer a la misma organización.",
        )
    target_org_id = next(iter(org_ids))
    assert_org_access(current_user, target_org_id)

    auth_res = verify_sensitive_authorization(
        db,
        current_user=current_user,
        organization_id=target_org_id,
        authorization_secret=authorization_secret,
        required_operation="revoke_biometrics",
    )

    total_deleted = 0
    any_avatar_cleared = False
    reason_note = reason.strip() if reason and reason.strip() else "Revocación de datos biométricos"

    for person in persons:
        deleted_count = len(person.embeddings)
        total_deleted += deleted_count
        for emb in list(person.embeddings):
            db.delete(emb)

        if person.avatar_base64 is not None:
            any_avatar_cleared = True
            person.avatar_base64 = None

        record_audit_log(
            db,
            organization_id=target_org_id,
            action="revoke_biometrics",
            target_type="person",
            target_id=person.id,
            target_summary=f"{person.full_name} ({person.external_id})",
            executed_by_user=current_user,
            authorized_by_user=auth_res.authorized_by_user,
            delegated_credential=auth_res.delegated_credential,
            details=f"{reason_note} | Vectores eliminados: {deleted_count} | Método: {auth_res.method}",
        )

    db.commit()
    return total_deleted, any_avatar_cleared, auth_res


@router.post("/persons/biometrics/revoke", response_model=BatchBiometricsRevokeResponse)
def revoke_biometrics_batch(
    payload: BatchBiometricsRevokeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BatchBiometricsRevokeResponse:
    unique_ids = list(dict.fromkeys(payload.person_ids))
    persons = list(
        db.scalars(
            select(Person)
            .options(selectinload(Person.embeddings))
            .where(Person.id.in_(unique_ids))
        ).all()
    )
    if len(persons) != len(unique_ids):
        raise HTTPException(status_code=404, detail="Una o más personas no fueron encontradas.")

    total_deleted, _, auth_res = _revoke_persons_biometrics(
        db,
        current_user=current_user,
        persons=persons,
        authorization_secret=payload.authorization_secret,
        reason=payload.reason,
    )
    return BatchBiometricsRevokeResponse(
        revoked_persons_count=len(persons),
        deleted_embeddings=total_deleted,
        authorized_by_name=auth_res.authorized_by_user.full_name if auth_res.authorized_by_user else None,
        authorization_method=auth_res.method,
        delegated_credential_label=(
            auth_res.delegated_credential.label if auth_res.delegated_credential else None
        ),
    )


@router.delete("/persons/{person_id}/biometrics", response_model=BiometricsRevokeResponse)
def revoke_biometrics(
    person_id: int,
    payload: BiometricsRevokeRequest | None = Body(default=None),
    x_authorization_secret: str | None = Header(default=None, alias="X-Authorization-Secret"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BiometricsRevokeResponse:
    person = db.scalars(
        select(Person)
        .options(selectinload(Person.embeddings))
        .where(Person.id == person_id)
    ).first()
    if person is None:
        raise HTTPException(status_code=404, detail="Persona no encontrada.")

    secret = (payload.authorization_secret if payload else None) or x_authorization_secret or ""
    reason = payload.reason if payload else None

    deleted_count, had_avatar, auth_res = _revoke_persons_biometrics(
        db,
        current_user=current_user,
        persons=[person],
        authorization_secret=secret,
        reason=reason,
    )
    return BiometricsRevokeResponse(
        person_id=person.id,
        deleted_embeddings=deleted_count,
        avatar_cleared=had_avatar,
        authorized_by_name=auth_res.authorized_by_user.full_name if auth_res.authorized_by_user else None,
        authorization_method=auth_res.method,
        delegated_credential_label=(
            auth_res.delegated_credential.label if auth_res.delegated_credential else None
        ),
    )
