from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Career, CourseAssignment, Group, Organization, PersonGroup, User, WorkShift
from app.schemas import (
    GroupCreate,
    GroupRead,
    GroupUpdate,
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
from app.services.academic_service import get_teacher_group_ids
from app.services.security_service import record_audit_log, verify_admin_password

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

    data = payload.model_dump(exclude_unset=True)
    auth_secret = data.pop("authorization_secret", None)

    if (
        "academic_period_type" in data
        and data["academic_period_type"] is not None
        and data["academic_period_type"] != org.academic_period_type
    ):
        auth_admin = verify_admin_password(
            db,
            current_user=current_user,
            organization_id=org.id,
            authorization_secret=auth_secret,
        )
        record_audit_log(
            db,
            organization_id=org.id,
            action="change_org_period_type",
            target_type="organization",
            target_id=org.id,
            target_summary=org.name,
            executed_by_user=current_user,
            authorized_by_user=auth_admin,
            details=f"Periodo general: {org.academic_period_type} -> {data['academic_period_type']}",
        )

    for field, value in data.items():
        setattr(org, field, value)

    db.commit()
    db.refresh(org)
    return org


def _serialize_groups(db: Session, groups: list[Group], organization_id: int) -> list[GroupRead]:
    if not groups:
        return []

    org = db.get(Organization, organization_id)
    org_period_type = org.academic_period_type if org else "semestral"
    career_map = {
        c.id: c
        for c in db.scalars(select(Career).where(Career.organization_id == organization_id)).all()
    }
    shift_map = {
        sh.id: sh
        for sh in db.scalars(select(WorkShift).where(WorkShift.organization_id == organization_id)).all()
    }
    counts_rows = db.execute(
        select(PersonGroup.group_id, func.count(PersonGroup.person_id)).group_by(PersonGroup.group_id)
    ).all()
    counts_map = {gid: cnt for gid, cnt in counts_rows}

    courses_rows = db.execute(
        select(CourseAssignment.group_id, func.count(CourseAssignment.id))
        .where(
            CourseAssignment.organization_id == organization_id,
            CourseAssignment.is_active.is_(True),
        )
        .group_by(CourseAssignment.group_id)
    ).all()
    courses_map = {gid: cnt for gid, cnt in courses_rows}

    result: list[GroupRead] = []
    for g in groups:
        career = career_map.get(g.career_id) if g.career_id else None
        shift = shift_map.get(g.default_work_shift_id) if g.default_work_shift_id else None
        effective_period = (
            g.period_type
            or (career.period_type if career and career.period_type else None)
            or org_period_type
        )
        result.append(
            GroupRead(
                id=g.id,
                organization_id=g.organization_id,
                career_id=g.career_id,
                career_name=career.name if career else None,
                name=g.name,
                code=g.code,
                semester=g.semester,
                default_classroom=g.default_classroom,
                default_work_shift_id=g.default_work_shift_id,
                default_work_shift_name=shift.name if shift else None,
                default_work_shift_code=shift.code if shift else None,
                period_type=effective_period,
                custom_period_type=g.period_type,
                schedule_start=g.schedule_start,
                schedule_end=g.schedule_end,
                created_at=g.created_at,
                members_count=counts_map.get(g.id, 0),
                courses_count=courses_map.get(g.id, 0),
            )
        )
    return result


@router.get("/groups", response_model=list[GroupRead])
def list_groups(
    organization_id: int | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[GroupRead]:
    scoped_org_id = resolve_org_scope(current_user, organization_id)
    stmt = (
        select(Group)
        .where(Group.organization_id == scoped_org_id)
        .order_by(Group.id.asc())
    )
    if current_user.role == "teacher":
        teacher_gids = get_teacher_group_ids(db, current_user.id)
        if not teacher_gids:
            return []
        stmt = stmt.where(Group.id.in_(teacher_gids))

    groups = list(db.scalars(stmt).all())
    return _serialize_groups(db, groups, scoped_org_id)


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

    if payload.career_id is not None:
        career = db.get(Career, payload.career_id)
        if career is None or career.organization_id != org.id:
            raise HTTPException(
                status_code=404,
                detail="Carrera no encontrada en la organización.",
            )

    shift_for_defaults: WorkShift | None = None
    if payload.default_work_shift_id is not None:
        shift_for_defaults = db.get(WorkShift, payload.default_work_shift_id)
        if shift_for_defaults is None or shift_for_defaults.organization_id != org.id:
            raise HTTPException(
                status_code=404,
                detail="Turno laboral no encontrado en la organización.",
            )

    data = payload.model_dump()
    if shift_for_defaults is not None:
        # Mantener las columnas heredadas alineadas con el turno para evitar discrepancias
        data["schedule_start"] = shift_for_defaults.start_time
        data["schedule_end"] = shift_for_defaults.end_time
    if data.get("semester") is not None:
        data["semester"] = data["semester"].strip() or None
    if data.get("default_classroom") is not None:
        data["default_classroom"] = data["default_classroom"].strip() or None

    group = Group(**data)
    db.add(group)
    db.commit()
    db.refresh(group)
    return _serialize_groups(db, [group], org.id)[0]


@router.patch("/groups/{group_id}", response_model=GroupRead)
def update_group(
    group_id: int,
    payload: GroupUpdate,
    current_user: User = Depends(require_roles("superadmin", "org_admin")),
    db: Session = Depends(get_db),
) -> GroupRead:
    group = db.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Grupo no encontrado.")
    assert_org_access(current_user, group.organization_id)

    data = payload.model_dump(exclude_unset=True)
    auth_secret = data.pop("authorization_secret", None)

    if "period_type" in data and data["period_type"] != group.period_type:
        auth_admin = verify_admin_password(
            db,
            current_user=current_user,
            organization_id=group.organization_id,
            authorization_secret=auth_secret,
        )
        record_audit_log(
            db,
            organization_id=group.organization_id,
            action="change_group_period_type",
            target_type="group",
            target_id=group.id,
            target_summary=f"{group.name} ({group.code})",
            executed_by_user=current_user,
            authorized_by_user=auth_admin,
            details=f"Periodo grupo: {group.period_type or 'heredado'} -> {data['period_type'] or 'heredado'}",
        )

    if "career_id" in data and data["career_id"] is not None:
        career = db.get(Career, data["career_id"])
        if career is None or career.organization_id != group.organization_id:
            raise HTTPException(
                status_code=404,
                detail="Carrera no encontrada en la organización.",
            )

    if "default_work_shift_id" in data and data["default_work_shift_id"] is not None:
        shift = db.get(WorkShift, data["default_work_shift_id"])
        if shift is None or shift.organization_id != group.organization_id:
            raise HTTPException(
                status_code=404,
                detail="Turno laboral no encontrado en la organización.",
            )
        # Sincronizar horario base heredado con el turno seleccionado
        data["schedule_start"] = shift.start_time
        data["schedule_end"] = shift.end_time

    for field, value in data.items():
        if field in ("semester", "default_classroom") and isinstance(value, str):
            setattr(group, field, value.strip() or None)
        else:
            setattr(group, field, value)

    db.commit()
    db.refresh(group)
    return _serialize_groups(db, [group], group.organization_id)[0]


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
