from dataclasses import dataclass
from datetime import datetime
from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import AuditLog, DelegatedCredential, User
from app.security import verify_secret


@dataclass(frozen=True)
class AuthorizationResult:
    """Resultado de validar una autorización sensible (admin o credencial delegada)."""

    authorized_by_user: User | None
    delegated_credential: DelegatedCredential | None
    method: str  # "admin_password" | "delegated_credential"


def record_audit_log(
    db: Session,
    *,
    organization_id: int | None,
    action: str,
    target_type: str,
    target_id: int | None,
    target_summary: str | None,
    executed_by_user: User | None,
    authorized_by_user: User | None = None,
    delegated_credential: DelegatedCredential | None = None,
    details: str | None = None,
) -> AuditLog:
    """Registra una entrada en la bitácora de auditoría sin confirmar transacción."""
    entry = AuditLog(
        organization_id=organization_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        target_summary=target_summary,
        executed_by_user_id=executed_by_user.id if executed_by_user else None,
        authorized_by_user_id=authorized_by_user.id if authorized_by_user else None,
        delegated_credential_id=delegated_credential.id if delegated_credential else None,
        details=details,
    )
    db.add(entry)
    return entry


def verify_sensitive_authorization(
    db: Session,
    *,
    current_user: User,
    organization_id: int,
    authorization_secret: str,
    required_operation: str = "revoke_biometrics",
) -> AuthorizationResult:
    """Valida contraseña de Superadmin, Org Admin de la organización o credencial delegada."""
    secret = authorization_secret.strip()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Se requiere la contraseña de autorización.",
        )

    admin_candidates = list(
        db.scalars(
            select(User).where(
                User.is_active.is_(True),
                or_(
                    User.role == "superadmin",
                    (User.role == "org_admin") & (User.organization_id == organization_id),
                ),
            )
        ).all()
    )

    # Prioriza al propio usuario actual si es admin autorizado
    admin_candidates.sort(key=lambda u: 0 if u.id == current_user.id else 1)

    for admin in admin_candidates:
        if verify_secret(secret, admin.password_hash):
            return AuthorizationResult(
                authorized_by_user=admin,
                delegated_credential=None,
                method="admin_password",
            )

    # Verifica credenciales delegadas activas de la organización
    credentials = list(
        db.scalars(
            select(DelegatedCredential).where(
                DelegatedCredential.organization_id == organization_id,
                DelegatedCredential.status == "active",
            )
        ).all()
    )
    now = datetime.now()
    for cred in credentials:
        if cred.expires_at is not None and cred.expires_at < now:
            cred.status = "expired"
            db.flush()
            continue

        allowed = {op.strip() for op in cred.allowed_operations.split(",") if op.strip()}
        if required_operation not in allowed:
            continue

        if verify_secret(secret, cred.secret_hash):
            if (
                cred.assigned_to_user_id is not None
                and current_user.role not in ("superadmin", "org_admin")
                and cred.assigned_to_user_id != current_user.id
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Esta credencial delegada está asignada a otro usuario.",
                )

            creator = (
                db.get(User, cred.created_by_user_id)
                if cred.created_by_user_id is not None
                else None
            )
            return AuthorizationResult(
                authorized_by_user=creator,
                delegated_credential=cred,
                method="delegated_credential",
            )

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Contraseña de autorización inválida o sin permisos para esta operación.",
    )


def verify_admin_password(
    db: Session,
    *,
    current_user: User,
    organization_id: int,
    authorization_secret: str | None,
) -> User:
    """Valida exclusivamente la contraseña de un Superadmin o Admin de la organización."""
    secret = (authorization_secret or "").strip()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Se requiere la contraseña de administrador para cambiar el tipo de periodo.",
        )

    admin_candidates = list(
        db.scalars(
            select(User).where(
                User.is_active.is_(True),
                or_(
                    User.role == "superadmin",
                    (User.role == "org_admin") & (User.organization_id == organization_id),
                ),
            )
        ).all()
    )
    admin_candidates.sort(key=lambda u: 0 if u.id == current_user.id else 1)

    for admin in admin_candidates:
        if verify_secret(secret, admin.password_hash):
            return admin

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Contraseña de administrador inválida.",
    )
