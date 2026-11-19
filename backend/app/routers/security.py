from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AuditLog, DelegatedCredential, Organization, User
from app.schemas import (
    AuditLogRead,
    DelegatedCredentialCreate,
    DelegatedCredentialCreateResponse,
    DelegatedCredentialRead,
)
from app.security import (
    assert_org_access,
    generate_delegated_secret,
    hash_secret,
    require_roles,
    resolve_org_scope,
)
from app.services.security_service import record_audit_log

router = APIRouter(prefix="/api/security", tags=["security"])


def _serialize_credential(
    cred: DelegatedCredential,
    users_map: dict[int, User],
) -> DelegatedCredentialRead:
    creator = users_map.get(cred.created_by_user_id) if cred.created_by_user_id else None
    ops = [op.strip() for op in cred.allowed_operations.split(",") if op.strip()]
    return DelegatedCredentialRead(
        id=cred.id,
        organization_id=cred.organization_id,
        label=cred.label,
        secret_prefix=cred.secret_prefix,
        created_by_user_id=cred.created_by_user_id,
        created_by_name=creator.full_name if creator else None,
        assigned_to_user_id=cred.assigned_to_user_id,
        assigned_to_name=cred.assigned_to_name,
        allowed_operations=ops,
        status=cred.status,
        expires_at=cred.expires_at,
        created_at=cred.created_at,
        revoked_at=cred.revoked_at,
    )


@router.get("/delegated-credentials", response_model=list[DelegatedCredentialRead])
def list_delegated_credentials(
    organization_id: int | None = Query(default=None),
    current_user: User = Depends(require_roles("superadmin", "org_admin")),
    db: Session = Depends(get_db),
) -> list[DelegatedCredentialRead]:
    scoped_org_id = resolve_org_scope(current_user, organization_id)
    creds = list(
        db.scalars(
            select(DelegatedCredential)
            .where(DelegatedCredential.organization_id == scoped_org_id)
            .order_by(DelegatedCredential.id.desc())
        ).all()
    )

    now = datetime.now()
    dirty = False
    for cred in creds:
        if cred.status == "active" and cred.expires_at is not None and cred.expires_at < now:
            cred.status = "expired"
            dirty = True
    if dirty:
        db.commit()

    users_map = {u.id: u for u in db.scalars(select(User)).all()}
    return [_serialize_credential(c, users_map) for c in creds]


@router.post(
    "/delegated-credentials",
    response_model=DelegatedCredentialCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_delegated_credential(
    payload: DelegatedCredentialCreate,
    current_user: User = Depends(require_roles("superadmin", "org_admin")),
    db: Session = Depends(get_db),
) -> DelegatedCredentialCreateResponse:
    scoped_org_id = resolve_org_scope(current_user, payload.organization_id)
    org = db.get(Organization, scoped_org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organización no encontrada.")

    assigned_name = payload.assigned_to_name.strip() if payload.assigned_to_name else ""
    if payload.assigned_to_user_id is not None:
        assigned_user = db.get(User, payload.assigned_to_user_id)
        if assigned_user is None or not assigned_user.is_active:
            raise HTTPException(status_code=404, detail="Usuario subordinado no encontrado.")
        if assigned_user.organization_id not in (scoped_org_id, None):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="El usuario asignado no pertenece a esta organización.",
            )
        if not assigned_name:
            assigned_name = assigned_user.full_name

    if not assigned_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debes indicar el usuario o el nombre de la persona que utilizará la contraseña.",
        )

    if payload.custom_secret:
        plain_secret = payload.custom_secret.strip()
        prefix = f"CUS-{plain_secret[:4].upper()}"
    else:
        plain_secret, prefix = generate_delegated_secret()

    expires_at = (
        datetime.now() + timedelta(days=payload.expires_in_days)
        if payload.expires_in_days is not None
        else None
    )
    allowed_ops = [op.strip() for op in payload.allowed_operations if op.strip()] or [
        "revoke_biometrics"
    ]

    cred = DelegatedCredential(
        organization_id=scoped_org_id,
        label=payload.label.strip(),
        secret_prefix=prefix,
        secret_hash=hash_secret(plain_secret),
        created_by_user_id=current_user.id,
        assigned_to_user_id=payload.assigned_to_user_id,
        assigned_to_name=assigned_name,
        allowed_operations=",".join(allowed_ops),
        status="active",
        expires_at=expires_at,
    )
    db.add(cred)
    db.flush()

    record_audit_log(
        db,
        organization_id=scoped_org_id,
        action="create_delegated_credential",
        target_type="delegated_credential",
        target_id=cred.id,
        target_summary=f"{cred.label} ({cred.secret_prefix})",
        executed_by_user=current_user,
        authorized_by_user=current_user,
        delegated_credential=cred,
        details=f"Asignada a: {assigned_name} | Permisos: {', '.join(allowed_ops)}",
    )

    db.commit()
    db.refresh(cred)
    users_map = {current_user.id: current_user}
    return DelegatedCredentialCreateResponse(
        credential=_serialize_credential(cred, users_map),
        plain_secret=plain_secret,
    )


@router.post("/delegated-credentials/{cred_id}/revoke", response_model=DelegatedCredentialRead)
def revoke_delegated_credential(
    cred_id: int,
    current_user: User = Depends(require_roles("superadmin", "org_admin")),
    db: Session = Depends(get_db),
) -> DelegatedCredentialRead:
    cred = db.get(DelegatedCredential, cred_id)
    if cred is None:
        raise HTTPException(status_code=404, detail="Credencial delegada no encontrada.")
    assert_org_access(current_user, cred.organization_id)

    if cred.status != "revoked":
        cred.status = "revoked"
        cred.revoked_at = datetime.now()
        record_audit_log(
            db,
            organization_id=cred.organization_id,
            action="revoke_delegated_credential",
            target_type="delegated_credential",
            target_id=cred.id,
            target_summary=f"{cred.label} ({cred.secret_prefix})",
            executed_by_user=current_user,
            authorized_by_user=current_user,
            delegated_credential=cred,
            details=f"Revocada credencial asignada a {cred.assigned_to_name}",
        )
        db.commit()
        db.refresh(cred)

    users_map = {u.id: u for u in db.scalars(select(User)).all()}
    return _serialize_credential(cred, users_map)


@router.get("/audit-logs", response_model=list[AuditLogRead])
def list_audit_logs(
    organization_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(require_roles("superadmin", "org_admin")),
    db: Session = Depends(get_db),
) -> list[AuditLogRead]:
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit)
    if current_user.role == "superadmin":
        if organization_id is not None:
            stmt = stmt.where(AuditLog.organization_id == organization_id)
    else:
        scoped_org_id = resolve_org_scope(current_user, organization_id)
        stmt = stmt.where(AuditLog.organization_id == scoped_org_id)

    logs = list(db.scalars(stmt).all())
    users_map = {u.id: u for u in db.scalars(select(User)).all()}
    creds_map = {c.id: c for c in db.scalars(select(DelegatedCredential)).all()}

    results: list[AuditLogRead] = []
    for entry in logs:
        exec_user = users_map.get(entry.executed_by_user_id) if entry.executed_by_user_id else None
        auth_user = users_map.get(entry.authorized_by_user_id) if entry.authorized_by_user_id else None
        cred = creds_map.get(entry.delegated_credential_id) if entry.delegated_credential_id else None
        results.append(
            AuditLogRead(
                id=entry.id,
                organization_id=entry.organization_id,
                action=entry.action,
                target_type=entry.target_type,
                target_id=entry.target_id,
                target_summary=entry.target_summary,
                executed_by_user_id=entry.executed_by_user_id,
                executed_by_name=exec_user.full_name if exec_user else None,
                authorized_by_user_id=entry.authorized_by_user_id,
                authorized_by_name=auth_user.full_name if auth_user else None,
                delegated_credential_id=entry.delegated_credential_id,
                delegated_credential_prefix=cred.secret_prefix if cred else None,
                delegated_assigned_to_name=cred.assigned_to_name if cred else None,
                details=entry.details,
                created_at=entry.created_at,
            )
        )
    return results
