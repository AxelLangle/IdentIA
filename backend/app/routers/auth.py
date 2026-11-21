from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Organization, User
from app.schemas import LoginRequest, LoginResponse, UserCreate, UserRead, UserUpdate
from app.security import (
    create_access_token,
    get_current_user,
    hash_secret,
    require_roles,
    resolve_org_scope,
    verify_secret,
)
from app.services.security_service import record_audit_log

router = APIRouter(prefix="/api", tags=["auth"])


def _validate_role_for_org_mode(role: str, org: Organization | None) -> None:
    """Impide asignar roles docentes en empresa o supervisores en escuela."""
    if org is None:
        return
    if org.mode == "enterprise" and role == "teacher":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El rol 'Profesor' solo está disponible en organizaciones escolares. En modo empresa utiliza 'Supervisor'.",
        )
    if org.mode == "education" and role == "supervisor":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El rol 'Supervisor' solo está disponible en organizaciones empresariales. En modo escolar utiliza 'Profesor'.",
        )


def _serialize_user(user: User, org_map: dict[int, Organization] | None = None) -> UserRead:
    org = None
    if user.organization_id is not None:
        org = org_map.get(user.organization_id) if org_map is not None else user.organization
    return UserRead(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        organization_id=user.organization_id,
        organization_name=org.name if org else None,
        organization_mode=org.mode if org else None,
        is_active=user.is_active,
        created_by_user_id=user.created_by_user_id,
        created_at=user.created_at,
    )


@router.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    email_norm = payload.email.strip().lower()
    user = db.scalars(select(User).where(User.email == email_norm)).first()
    if user is None or not user.is_active or not verify_secret(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Correo o contraseña incorrectos.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(user)
    return LoginResponse(access_token=token, user=_serialize_user(user))


@router.get("/auth/me", response_model=UserRead)
def get_me(current_user: User = Depends(get_current_user)) -> UserRead:
    return _serialize_user(current_user)


@router.get("/users", response_model=list[UserRead])
def list_users(
    organization_id: int | None = Query(default=None),
    current_user: User = Depends(require_roles("superadmin", "org_admin")),
    db: Session = Depends(get_db),
) -> list[UserRead]:
    stmt = select(User).order_by(User.id.asc())
    if current_user.role == "superadmin":
        if organization_id is not None:
            stmt = stmt.where(User.organization_id == organization_id)
    else:
        scoped_org_id = resolve_org_scope(current_user, organization_id)
        stmt = stmt.where(User.organization_id == scoped_org_id)

    users = list(db.scalars(stmt).all())
    org_map = {org.id: org for org in db.scalars(select(Organization)).all()}
    return [_serialize_user(u, org_map) for u in users]


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    current_user: User = Depends(require_roles("superadmin", "org_admin")),
    db: Session = Depends(get_db),
) -> UserRead:
    if current_user.role == "org_admin":
        if payload.role == "superadmin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Un administrador de organización no puede crear usuarios Superadmin.",
            )
        target_org_id: int | None = resolve_org_scope(current_user, payload.organization_id)
        target_org = db.get(Organization, target_org_id)
    else:
        if payload.role == "superadmin":
            target_org_id = None
            target_org = None
        else:
            if payload.organization_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Debes indicar organization_id para este rol.",
                )
            org = db.get(Organization, payload.organization_id)
            if org is None:
                raise HTTPException(status_code=404, detail="Organización no encontrada.")
            target_org_id = org.id
            target_org = org

    _validate_role_for_org_mode(payload.role, target_org)

    email_norm = payload.email.strip().lower()
    existing = db.scalars(select(User).where(User.email == email_norm)).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe una cuenta registrada con el correo '{email_norm}'.",
        )

    user = User(
        email=email_norm,
        full_name=payload.full_name.strip(),
        password_hash=hash_secret(payload.password),
        role=payload.role,
        organization_id=target_org_id,
        created_by_user_id=current_user.id,
    )
    db.add(user)
    db.flush()

    record_audit_log(
        db,
        organization_id=target_org_id,
        action="create_user",
        target_type="user",
        target_id=user.id,
        target_summary=f"{user.full_name} ({user.email})",
        executed_by_user=current_user,
        authorized_by_user=current_user,
        details=f"Rol asignado: {user.role}",
    )

    db.commit()
    db.refresh(user)
    return _serialize_user(user)


@router.patch("/users/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    payload: UserUpdate,
    current_user: User = Depends(require_roles("superadmin", "org_admin")),
    db: Session = Depends(get_db),
) -> UserRead:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")

    if current_user.role == "org_admin":
        if target.role == "superadmin" or target.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Acceso denegado a usuarios fuera de tu organización.",
            )
        if payload.role == "superadmin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No puedes asignar el rol Superadmin.",
            )

    if target.id == current_user.id and payload.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No puedes desactivar tu propia cuenta activa.",
        )

    changes: list[str] = []
    if payload.full_name is not None:
        target.full_name = payload.full_name.strip()
        changes.append("nombre")
    if payload.role is not None and payload.role != target.role:
        if payload.role == "superadmin" and target.organization_id is not None:
            target.organization_id = None
        elif payload.role != "superadmin" and target.organization_id is not None:
            target_org = db.get(Organization, target.organization_id)
            _validate_role_for_org_mode(payload.role, target_org)
        target.role = payload.role
        changes.append(f"rol={payload.role}")
    if payload.is_active is not None:
        target.is_active = payload.is_active
        changes.append(f"activo={payload.is_active}")
    if payload.password is not None:
        target.password_hash = hash_secret(payload.password)
        changes.append("contraseña")

    record_audit_log(
        db,
        organization_id=target.organization_id,
        action="update_user",
        target_type="user",
        target_id=target.id,
        target_summary=f"{target.full_name} ({target.email})",
        executed_by_user=current_user,
        authorized_by_user=current_user,
        details=", ".join(changes) if changes else "actualización",
    )

    db.commit()
    db.refresh(target)
    return _serialize_user(target)
