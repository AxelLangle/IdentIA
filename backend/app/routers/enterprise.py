from datetime import date
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Group, Organization, Person, PersonGroup, User, WorkShift
from app.schemas import (
    EnterpriseStatsResponse,
    GenerateSessionsResponse,
    GenerateShiftSessionsRequest,
    SessionRead,
    ShiftBulkAssignRequest,
    ShiftBulkAssignResponse,
    StartShiftSessionRequest,
    WorkShiftCreate,
    WorkShiftRead,
    WorkShiftUpdate,
)
from app.security import assert_org_access, require_roles, resolve_org_scope
from app.services.academic_service import serialize_sessions_batch
from app.services.enterprise_service import (
    compute_enterprise_stats,
    generate_shift_sessions_for_date,
    normalize_days_of_week,
    serialize_work_shifts_batch,
    start_or_get_shift_session,
    validate_work_shift_times,
)
from app.services.security_service import record_audit_log

router = APIRouter(prefix="/api/enterprise", tags=["enterprise"])


@router.get("/shifts", response_model=list[WorkShiftRead])
def list_work_shifts(
    organization_id: int | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    current_user: User = Depends(require_roles("superadmin", "org_admin", "supervisor", "operator")),
    db: Session = Depends(get_db),
) -> list[WorkShiftRead]:
    scoped_org_id = resolve_org_scope(current_user, organization_id)
    stmt = (
        select(WorkShift)
        .where(WorkShift.organization_id == scoped_org_id)
        .order_by(WorkShift.start_time.asc(), WorkShift.id.asc())
    )
    if is_active is not None:
        stmt = stmt.where(WorkShift.is_active.is_(is_active))
    shifts = list(db.scalars(stmt).all())
    return serialize_work_shifts_batch(db, shifts, scoped_org_id)


@router.post("/shifts", response_model=WorkShiftRead, status_code=status.HTTP_201_CREATED)
def create_work_shift(
    payload: WorkShiftCreate,
    current_user: User = Depends(require_roles("superadmin", "org_admin")),
    db: Session = Depends(get_db),
) -> WorkShiftRead:
    assert_org_access(current_user, payload.organization_id)
    org = db.get(Organization, payload.organization_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organización no encontrada.")

    crosses_midnight, _ = validate_work_shift_times(payload.start_time, payload.end_time)
    days_csv = normalize_days_of_week(payload.days_of_week)

    shift = WorkShift(
        organization_id=org.id,
        name=payload.name.strip(),
        code=payload.code.strip().upper(),
        start_time=payload.start_time.strip(),
        end_time=payload.end_time.strip(),
        crosses_midnight=crosses_midnight,
        days_of_week=days_csv,
        late_tolerance_minutes=payload.late_tolerance_minutes,
        early_exit_tolerance_minutes=payload.early_exit_tolerance_minutes,
        is_active=payload.is_active,
    )
    db.add(shift)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe un turno con el código '{shift.code}' en esta organización.",
        ) from exc

    record_audit_log(
        db,
        organization_id=org.id,
        action="create_work_shift",
        target_type="work_shift",
        target_id=shift.id,
        target_summary=f"{shift.name} ({shift.code})",
        executed_by_user=current_user,
        authorized_by_user=current_user,
        details=(
            f"Horario: {shift.start_time}-{shift.end_time} | "
            f"Cruza medianoche: {shift.crosses_midnight}"
        ),
    )
    db.commit()
    db.refresh(shift)
    return serialize_work_shifts_batch(db, [shift], org.id)[0]


@router.patch("/shifts/{shift_id}", response_model=WorkShiftRead)
def update_work_shift(
    shift_id: int,
    payload: WorkShiftUpdate,
    current_user: User = Depends(require_roles("superadmin", "org_admin")),
    db: Session = Depends(get_db),
) -> WorkShiftRead:
    shift = db.get(WorkShift, shift_id)
    if shift is None:
        raise HTTPException(status_code=404, detail="Turno laboral no encontrado.")
    assert_org_access(current_user, shift.organization_id)

    data = payload.model_dump(exclude_unset=True)
    new_start = data.get("start_time", shift.start_time)
    new_end = data.get("end_time", shift.end_time)
    crosses_midnight, _ = validate_work_shift_times(new_start, new_end)

    if "days_of_week" in data and data["days_of_week"] is not None:
        shift.days_of_week = normalize_days_of_week(data["days_of_week"])

    if "name" in data and data["name"] is not None:
        shift.name = data["name"].strip()
    if "code" in data and data["code"] is not None:
        shift.code = data["code"].strip().upper()
    if "start_time" in data and data["start_time"] is not None:
        shift.start_time = data["start_time"].strip()
    if "end_time" in data and data["end_time"] is not None:
        shift.end_time = data["end_time"].strip()
    shift.crosses_midnight = crosses_midnight

    if "late_tolerance_minutes" in data:
        shift.late_tolerance_minutes = data["late_tolerance_minutes"]
    if "early_exit_tolerance_minutes" in data and data["early_exit_tolerance_minutes"] is not None:
        shift.early_exit_tolerance_minutes = data["early_exit_tolerance_minutes"]
    if "is_active" in data and data["is_active"] is not None:
        shift.is_active = bool(data["is_active"])

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe un turno con el código '{shift.code}' en esta organización.",
        ) from exc

    db.refresh(shift)
    return serialize_work_shifts_batch(db, [shift], shift.organization_id)[0]


@router.delete("/shifts/{shift_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_work_shift(
    shift_id: int,
    current_user: User = Depends(require_roles("superadmin", "org_admin")),
    db: Session = Depends(get_db),
) -> None:
    shift = db.get(WorkShift, shift_id)
    if shift is None:
        raise HTTPException(status_code=404, detail="Turno laboral no encontrado.")
    assert_org_access(current_user, shift.organization_id)

    org_id = shift.organization_id
    summary = f"{shift.name} ({shift.code})"
    record_audit_log(
        db,
        organization_id=org_id,
        action="delete_work_shift",
        target_type="work_shift",
        target_id=shift.id,
        target_summary=summary,
        executed_by_user=current_user,
        authorized_by_user=current_user,
        details=f"Turno eliminado: {shift.start_time}-{shift.end_time}",
    )
    db.delete(shift)
    db.commit()


@router.post("/shifts/{shift_id}/assign-persons", response_model=ShiftBulkAssignResponse)
def assign_work_shift_persons(
    shift_id: int,
    payload: ShiftBulkAssignRequest,
    current_user: User = Depends(require_roles("superadmin", "org_admin")),
    db: Session = Depends(get_db),
) -> ShiftBulkAssignResponse:
    shift = db.get(WorkShift, shift_id)
    if shift is None:
        raise HTTPException(status_code=404, detail="Turno laboral no encontrado.")
    assert_org_access(current_user, shift.organization_id)

    unique_ids = list(dict.fromkeys(payload.person_ids))
    target_persons: list[Person] = []
    if unique_ids:
        target_persons = list(
            db.scalars(
                select(Person).where(
                    Person.id.in_(unique_ids),
                    Person.organization_id == shift.organization_id,
                )
            ).all()
        )
        if len(target_persons) != len(unique_ids):
            raise HTTPException(
                status_code=400,
                detail="Uno o más empleados no existen o no pertenecen a la organización.",
            )
    elif payload.group_id is not None:
        group = db.get(Group, payload.group_id)
        if group is None or group.organization_id != shift.organization_id:
            raise HTTPException(status_code=404, detail="Departamento/grupo no encontrado.")
        target_persons = list(
            db.scalars(
                select(Person)
                .join(PersonGroup, PersonGroup.person_id == Person.id)
                .where(
                    PersonGroup.group_id == group.id,
                    Person.organization_id == shift.organization_id,
                )
            ).all()
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debes indicar empleados o un departamento para asignar el turno.",
        )

    for person in target_persons:
        person.work_shift_id = None if payload.clear_shift else shift.id

    record_audit_log(
        db,
        organization_id=shift.organization_id,
        action="clear_work_shift_assignment" if payload.clear_shift else "assign_work_shift",
        target_type="work_shift",
        target_id=shift.id,
        target_summary=f"{shift.name} ({shift.code})",
        executed_by_user=current_user,
        authorized_by_user=current_user,
        details=f"Empleados actualizados: {len(target_persons)}",
    )
    db.commit()

    return ShiftBulkAssignResponse(
        work_shift_id=None if payload.clear_shift else shift.id,
        work_shift_name=None if payload.clear_shift else shift.name,
        updated_count=len(target_persons),
    )


@router.post("/shifts/{shift_id}/start-session", response_model=SessionRead)
def start_shift_session(
    shift_id: int,
    payload: StartShiftSessionRequest | None = Body(default=None),
    current_user: User = Depends(require_roles("superadmin", "org_admin", "supervisor", "operator")),
    db: Session = Depends(get_db),
) -> SessionRead:
    shift = db.get(WorkShift, shift_id)
    if shift is None:
        raise HTTPException(status_code=404, detail="Turno laboral no encontrado.")
    assert_org_access(current_user, shift.organization_id)
    if not shift.is_active:
        raise HTTPException(status_code=400, detail="El turno seleccionado está inactivo.")

    target_date = payload.session_date if payload and payload.session_date else date.today()
    session = start_or_get_shift_session(db, shift=shift, target_date=target_date)
    return serialize_sessions_batch(db, [session], shift.organization_id)[0]


@router.post("/sessions/generate", response_model=GenerateSessionsResponse)
def generate_enterprise_sessions(
    payload: GenerateShiftSessionsRequest,
    current_user: User = Depends(require_roles("superadmin", "org_admin", "supervisor", "operator")),
    db: Session = Depends(get_db),
) -> GenerateSessionsResponse:
    scoped_org_id = resolve_org_scope(current_user, payload.organization_id)
    org = db.get(Organization, scoped_org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organización no encontrada.")

    target_date = payload.target_date or date.today()
    created_count, existing_count, sessions = generate_shift_sessions_for_date(
        db,
        organization_id=scoped_org_id,
        target_date=target_date,
        work_shift_id=payload.work_shift_id,
    )
    return GenerateSessionsResponse(
        target_date=target_date,
        created_count=created_count,
        existing_count=existing_count,
        sessions=serialize_sessions_batch(db, sessions, scoped_org_id),
    )


@router.get("/stats", response_model=EnterpriseStatsResponse)
def get_enterprise_stats(
    organization_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    work_shift_id: int | None = Query(default=None),
    group_id: int | None = Query(default=None),
    current_user: User = Depends(require_roles("superadmin", "org_admin", "supervisor")),
    db: Session = Depends(get_db),
) -> EnterpriseStatsResponse:
    scoped_org_id = resolve_org_scope(current_user, organization_id)
    return compute_enterprise_stats(
        db,
        organization_id=scoped_org_id,
        date_from=date_from,
        date_to=date_to,
        work_shift_id=work_shift_id,
        group_id=group_id,
    )
