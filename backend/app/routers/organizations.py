from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Group, Organization, PersonGroup, User
from app.schemas import (
    GroupCreate,
    GroupRead,
    OrganizationCreate,
    OrganizationRead,
    OrganizationUpdate,
)
from app.security import (
    assert_org_access,
    get_current_user,
    hash_secret,
    require_roles,
    resolve_org_scope,
)
from app.services.security_service import record_audit_log

router = APIRouter(prefix="/api", tags=["organizations"])


@router.get("/organizations", response_model=list[OrganizationRead])
def list_organizations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Organization]:
    if current_user.role == "superadmin":
        return list(db.scalars(select(Organization).order_by(Organization.id.asc())).all())
    if current_user.organization_id is None:
        return []
    return list(
        db.scalars(
            select(Organization)
            .where(Organization.id == current_user.organization_id)
            .order_by(Organization.id.asc())
        ).all()
    )


@router.post("/organizations", response_model=OrganizationRead, status_code=status.HTTP_201_CREATED)
def create_organization(
    payload: OrganizationCreate,
    current_user: User = Depends(require_roles("superadmin")),
    db: Session = Depends(get_db),
) -> Organization:
    org_data = payload.model_dump(exclude={"admin_user"})
    org = Organization(**org_data)
    db.add(org)
    db.flush()

    db.add(
        Group(
            organization_id=org.id,
            name="General",
            code="GEN-01",
            schedule_start="09:00",
            schedule_end="18:00",
        )
    )

    admin_summary = "sin admin inicial"
    if payload.admin_user is not None:
        email_norm = payload.admin_user.email.strip().lower()
        dup = db.scalars(select(User).where(User.email == email_norm)).first()
        if dup is not None:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Ya existe un usuario con el correo '{email_norm}'.",
            )
        org_admin = User(
            email=email_norm,
            full_name=payload.admin_user.full_name.strip(),
            password_hash=hash_secret(payload.admin_user.password),
            role="org_admin",
            organization_id=org.id,
            created_by_user_id=current_user.id,
        )
        db.add(org_admin)
        admin_summary = f"admin inicial: {email_norm}"

    record_audit_log(
        db,
        organization_id=org.id,
        action="create_organization",
        target_type="organization",
        target_id=org.id,
        target_summary=org.name,
        executed_by_user=current_user,
        authorized_by_user=current_user,
        details=f"Modo: {org.mode} | {admin_summary}",
    )

    db.commit()
    db.refresh(org)
    return org


@router.patch("/organizations/{org_id}", response_model=OrganizationRead)
def update_organization(
    org_id: int,
    payload: OrganizationUpdate,
    current_user: User = Depends(require_roles("superadmin", "org_admin")),
    db: Session = Depends(get_db),
) -> Organization:
    assert_org_access(current_user, org_id)
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organización no encontrada.")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(org, field, value)

    db.commit()
    db.refresh(org)
    return org


@router.get("/groups", response_model=list[GroupRead])
def list_groups(
    organization_id: int | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[GroupRead]:
    scoped_org_id = resolve_org_scope(current_user, organization_id)
    groups = db.scalars(
        select(Group)
        .where(Group.organization_id == scoped_org_id)
        .order_by(Group.id.asc())
    ).all()

    counts_rows = db.execute(
        select(PersonGroup.group_id, func.count(PersonGroup.person_id))
        .group_by(PersonGroup.group_id)
    ).all()
    counts_map = {gid: cnt for gid, cnt in counts_rows}

    result: list[GroupRead] = []
    for g in groups:
        result.append(
            GroupRead(
                id=g.id,
                organization_id=g.organization_id,
                name=g.name,
                code=g.code,
                schedule_start=g.schedule_start,
                schedule_end=g.schedule_end,
                created_at=g.created_at,
                members_count=counts_map.get(g.id, 0),
            )
        )
    return result


@router.post("/groups", response_model=GroupRead, status_code=status.HTTP_201_CREATED)
def create_group(
    payload: GroupCreate,
    current_user: User = Depends(require_roles("superadmin", "org_admin")),
    db: Session = Depends(get_db),
) -> GroupRead:
    assert_org_access(current_user, payload.organization_id)
    org = db.get(Organization, payload.organization_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organización no encontrada.")

    group = Group(**payload.model_dump())
    db.add(group)
    db.commit()
    db.refresh(group)
    return GroupRead(
        id=group.id,
        organization_id=group.organization_id,
        name=group.name,
        code=group.code,
        schedule_start=group.schedule_start,
        schedule_end=group.schedule_end,
        created_at=group.created_at,
        members_count=0,
    )


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(
    group_id: int,
    current_user: User = Depends(require_roles("superadmin", "org_admin")),
    db: Session = Depends(get_db),
) -> None:
    group = db.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Grupo no encontrado.")
    assert_org_access(current_user, group.organization_id)
    db.delete(group)
    db.commit()
