from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Group, Organization, PersonGroup
from app.schemas import (
    GroupCreate,
    GroupRead,
    OrganizationCreate,
    OrganizationRead,
    OrganizationUpdate,
)

router = APIRouter(prefix="/api", tags=["organizations"])


@router.get("/organizations", response_model=list[OrganizationRead])
def list_organizations(db: Session = Depends(get_db)) -> list[Organization]:
    return list(db.scalars(select(Organization).order_by(Organization.id.asc())).all())


@router.post("/organizations", response_model=OrganizationRead, status_code=status.HTTP_201_CREATED)
def create_organization(
    payload: OrganizationCreate,
    db: Session = Depends(get_db),
) -> Organization:
    org = Organization(**payload.model_dump())
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


@router.patch("/organizations/{org_id}", response_model=OrganizationRead)
def update_organization(
    org_id: int,
    payload: OrganizationUpdate,
    db: Session = Depends(get_db),
) -> Organization:
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
    organization_id: int = Query(...),
    db: Session = Depends(get_db),
) -> list[GroupRead]:
    groups = db.scalars(
        select(Group)
        .where(Group.organization_id == organization_id)
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
    db: Session = Depends(get_db),
) -> GroupRead:
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
def delete_group(group_id: int, db: Session = Depends(get_db)) -> None:
    group = db.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Grupo no encontrado.")
    db.delete(group)
    db.commit()
