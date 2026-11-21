from datetime import date, datetime
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.config import BACKEND_DIR, get_settings
from app.db import create_db_engine
from app.models import AttendanceSession, Organization, Person, WorkShift
from app.services.attendance_service import record_recognized_attendance
from app.services.enterprise_service import generate_shift_sessions_for_date


def _auth_header(client, email: str, password: str) -> dict[str, str]:
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _create_enterprise_org(
    client,
    sa_headers: dict[str, str],
    *,
    name: str,
    admin_email: str,
    admin_password: str = "EmpresaPass123!",
    late_tolerance_minutes: int = 15,
) -> tuple[int, dict[str, str]]:
    res = client.post(
        "/api/organizations",
        headers=sa_headers,
        json={
            "name": name,
            "mode": "enterprise",
            "late_tolerance_minutes": late_tolerance_minutes,
            "cooldown_seconds": 30,
            "admin_user": {
                "full_name": f"Admin {name}",
                "email": admin_email,
                "password": admin_password,
            },
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["id"], _auth_header(client, admin_email, admin_password)


def test_work_shift_crud_validations_and_multi_tenant_rbac(raw_api_client) -> None:
    """Valida alta, edición, borrado, cruce medianoche, validaciones y aislamiento RBAC."""
    client, _, _, _ = raw_api_client
    settings = get_settings()
    sa_headers = _auth_header(
        client,
        settings.bootstrap_superadmin_email,
        settings.bootstrap_superadmin_password,
    )

    org_a, admin_a = _create_enterprise_org(
        client, sa_headers, name="Planta Alfa", admin_email="admin.alfa@corp.com"
    )
    org_b, admin_b = _create_enterprise_org(
        client, sa_headers, name="Planta Beta", admin_email="admin.beta@corp.com"
    )

    op_res = client.post(
        "/api/users",
        headers=admin_a,
        json={
            "email": "kiosco.alfa@corp.com",
            "full_name": "Operador Kiosco",
            "password": "OperPass123!",
            "role": "operator",
            "organization_id": org_a,
        },
    )
    assert op_res.status_code == 201, op_res.text
    op_headers = _auth_header(client, "kiosco.alfa@corp.com", "OperPass123!")

    # Turno diurno
    day_res = client.post(
        "/api/enterprise/shifts",
        headers=admin_a,
        json={
            "organization_id": org_a,
            "name": "Matutino",
            "code": "mat-01",
            "start_time": "08:00",
            "end_time": "17:00",
            "days_of_week": [0, 1, 2, 3, 4],
            "late_tolerance_minutes": None,
            "early_exit_tolerance_minutes": 10,
        },
    )
    assert day_res.status_code == 201, day_res.text
    day_shift = day_res.json()
    assert day_shift["code"] == "MAT-01"
    assert day_shift["crosses_midnight"] is False
    assert day_shift["expected_duration_minutes"] == 540
    assert day_shift["effective_late_tolerance_minutes"] == 15

    # Turno nocturno con cruce de medianoche
    night_res = client.post(
        "/api/enterprise/shifts",
        headers=admin_a,
        json={
            "organization_id": org_a,
            "name": "Nocturno Logística",
            "code": "NOC-01",
            "start_time": "22:00",
            "end_time": "06:00",
            "days_of_week": [0, 1, 2, 3, 4],
            "late_tolerance_minutes": 10,
            "early_exit_tolerance_minutes": 15,
        },
    )
    assert night_res.status_code == 201, night_res.text
    night_shift = night_res.json()
    assert night_shift["crosses_midnight"] is True
    assert night_shift["expected_duration_minutes"] == 480

    # Validaciones de error
    same_hours = client.post(
        "/api/enterprise/shifts",
        headers=admin_a,
        json={
            "organization_id": org_a,
            "name": "Inválido",
            "code": "INV-1",
            "start_time": "09:00",
            "end_time": "09:00",
            "days_of_week": [0, 1],
        },
    )
    assert same_hours.status_code == 400

    empty_days = client.post(
        "/api/enterprise/shifts",
        headers=admin_a,
        json={
            "organization_id": org_a,
            "name": "Sin días",
            "code": "INV-2",
            "start_time": "09:00",
            "end_time": "17:00",
            "days_of_week": [],
        },
    )
    assert empty_days.status_code == 400

    dup_code = client.post(
        "/api/enterprise/shifts",
        headers=admin_a,
        json={
            "organization_id": org_a,
            "name": "Matutino Duplicado",
            "code": "MAT-01",
            "start_time": "07:00",
            "end_time": "15:00",
            "days_of_week": [0],
        },
    )
    assert dup_code.status_code == 409

    # Aislamiento multi-tenant (Admin B no accede a Org A)
    assert client.get(f"/api/enterprise/shifts?organization_id={org_a}", headers=admin_b).status_code == 403
    assert (
        client.patch(
            f"/api/enterprise/shifts/{day_shift['id']}",
            headers=admin_b,
            json={"name": "Hack"},
        ).status_code
        == 403
    )
    assert client.delete(f"/api/enterprise/shifts/{day_shift['id']}", headers=admin_b).status_code == 403
    assert client.get(f"/api/enterprise/stats?organization_id={org_a}", headers=admin_b).status_code == 403

    # RBAC de operador: no administra catálogo ni ve stats, pero sí lista y abre kiosco
    assert (
        client.post(
            "/api/enterprise/shifts",
            headers=op_headers,
            json={
                "organization_id": org_a,
                "name": "Operador No Puede",
                "code": "OP-NO",
                "start_time": "10:00",
                "end_time": "18:00",
            },
        ).status_code
        == 403
    )
    assert client.delete(f"/api/enterprise/shifts/{day_shift['id']}", headers=op_headers).status_code == 403
    assert client.get(f"/api/enterprise/stats?organization_id={org_a}", headers=op_headers).status_code == 403
    assert client.get(f"/api/enterprise/shifts?organization_id={org_a}", headers=op_headers).status_code == 200
    start_sess = client.post(
        f"/api/enterprise/shifts/{day_shift['id']}/start-session",
        headers=op_headers,
        json={"session_date": "2026-11-16"},
    )
    assert start_sess.status_code == 200, start_sess.text
    assert start_sess.json()["work_shift_id"] == day_shift["id"]

    # Eliminar turno vinculado a empleado limpia FK sin error
    emp = client.post(
        "/api/persons",
        headers=admin_a,
        json={
            "organization_id": org_a,
            "external_id": "EMP-DEL-1",
            "full_name": "Carlos Ruiz",
            "role": "employee",
            "biometric_consent": True,
            "work_shift_id": night_shift["id"],
        },
    )
    assert emp.status_code == 201, emp.text
    assert emp.json()["shift_source"] == "direct"

    assert client.delete(f"/api/enterprise/shifts/{night_shift['id']}", headers=admin_a).status_code == 204
    persons_after = client.get(f"/api/persons?organization_id={org_a}", headers=admin_a).json()
    emp_after = next(p for p in persons_after if p["id"] == emp.json()["id"])
    assert emp_after["work_shift_id"] is None
    assert emp_after["effective_work_shift_id"] is None
    assert emp_after["shift_source"] == "none"


def test_shift_punctuality_late_early_exit_and_group_inheritance(raw_api_client) -> None:
    """Valida puntualidad, retardo, salida anticipada y herencia de turno desde departamento."""
    client, SessionLocal, _, _ = raw_api_client
    settings = get_settings()
    sa_headers = _auth_header(
        client,
        settings.bootstrap_superadmin_email,
        settings.bootstrap_superadmin_password,
    )

    org_id, admin_headers = _create_enterprise_org(
        client,
        sa_headers,
        name="Fábrica Central",
        admin_email="admin@fabrica.com",
        late_tolerance_minutes=15,
    )

    shift = client.post(
        "/api/enterprise/shifts",
        headers=admin_headers,
        json={
            "organization_id": org_id,
            "name": "Oficina 9-6",
            "code": "OF-0918",
            "start_time": "09:00",
            "end_time": "18:00",
            "days_of_week": [0, 1, 2, 3, 4],
            "late_tolerance_minutes": 10,
            "early_exit_tolerance_minutes": 15,
        },
    ).json()

    dept = client.post(
        "/api/groups",
        headers=admin_headers,
        json={
            "organization_id": org_id,
            "name": "Producción",
            "code": "PROD",
            "schedule_start": "09:00",
            "schedule_end": "18:00",
            "default_work_shift_id": shift["id"],
        },
    )
    assert dept.status_code == 201, dept.text
    assert dept.json()["default_work_shift_name"] == "Oficina 9-6"

    emp_direct = client.post(
        "/api/persons",
        headers=admin_headers,
        json={
            "organization_id": org_id,
            "external_id": "EMP-D1",
            "full_name": "Ana López",
            "role": "employee",
            "biometric_consent": True,
            "work_shift_id": shift["id"],
        },
    ).json()
    assert emp_direct["shift_source"] == "direct"

    emp_group = client.post(
        "/api/persons",
        headers=admin_headers,
        json={
            "organization_id": org_id,
            "external_id": "EMP-G2",
            "full_name": "Luis García",
            "role": "employee",
            "biometric_consent": True,
            "group_ids": [dept.json()["id"]],
        },
    ).json()
    assert emp_group["work_shift_id"] is None
    assert emp_group["effective_work_shift_id"] == shift["id"]
    assert emp_group["shift_source"] == "group"

    sess_res = client.post(
        "/api/sessions",
        headers=admin_headers,
        json={
            "organization_id": org_id,
            "title": "Jornada Lunes 2026-11-16",
            "session_date": "2026-11-16",
        },
    )
    assert sess_res.status_code == 201, sess_res.text
    sess_id = sess_res.json()["id"]

    with SessionLocal() as db:
        org_obj = db.get(Organization, org_id)
        sess_obj = db.get(AttendanceSession, sess_id)
        p1 = db.get(Person, emp_direct["id"])
        p2 = db.get(Person, emp_group["id"])
        assert org_obj and sess_obj and p1 and p2

        # Emp 1: llega dentro de tolerancia (09:08 <= 09:10) pero sale temprano (17:20 < 17:45)
        r1_in = record_recognized_attendance(
            db, org_obj, sess_obj, p1, 0.92, action_mode="auto", now=datetime(2026, 11, 16, 9, 8)
        )
        assert r1_in.event is not None
        assert r1_in.event.event_type == "check_in"
        assert r1_in.event.status == "on_time"
        assert r1_in.late_minutes == 0

        r1_out = record_recognized_attendance(
            db, org_obj, sess_obj, p1, 0.93, action_mode="auto", now=datetime(2026, 11, 16, 17, 20)
        )
        assert r1_out.event is not None
        assert r1_out.event.event_type == "check_out"
        assert r1_out.event.status == "early_exit"
        assert r1_out.early_exit_minutes == 40
        assert r1_out.worked_minutes == 492

        # Emp 2 (turno heredado del grupo): llega con retardo (09:22) y sale a tiempo (17:50 >= 17:45)
        r2_in = record_recognized_attendance(
            db, org_obj, sess_obj, p2, 0.91, action_mode="auto", now=datetime(2026, 11, 16, 9, 22)
        )
        assert r2_in.event is not None
        assert r2_in.event.event_type == "check_in"
        assert r2_in.event.status == "late"
        assert r2_in.late_minutes == 22

        r2_out = record_recognized_attendance(
            db, org_obj, sess_obj, p2, 0.94, action_mode="auto", now=datetime(2026, 11, 16, 17, 50)
        )
        assert r2_out.event is not None
        assert r2_out.event.event_type == "check_out"
        assert r2_out.event.status == "on_time"
        assert r2_out.early_exit_minutes == 0
        assert r2_out.worked_minutes == 508


def test_overnight_shift_crosses_midnight_checkout_and_early_exit(raw_api_client) -> None:
    """Valida que un turno nocturno 22:00-06:00 cierre al día siguiente sobre la sesión origen."""
    client, SessionLocal, _, _ = raw_api_client
    settings = get_settings()
    sa_headers = _auth_header(
        client,
        settings.bootstrap_superadmin_email,
        settings.bootstrap_superadmin_password,
    )

    org_id, admin_headers = _create_enterprise_org(
        client, sa_headers, name="Logística 24/7", admin_email="admin@log247.com"
    )

    night = client.post(
        "/api/enterprise/shifts",
        headers=admin_headers,
        json={
            "organization_id": org_id,
            "name": "Nocturno",
            "code": "NOC-2206",
            "start_time": "22:00",
            "end_time": "06:00",
            "days_of_week": [0, 1, 2, 3, 4],
            "late_tolerance_minutes": 15,
            "early_exit_tolerance_minutes": 10,
        },
    ).json()

    emp_a = client.post(
        "/api/persons",
        headers=admin_headers,
        json={
            "organization_id": org_id,
            "external_id": "NOC-A",
            "full_name": "Elena Torres",
            "biometric_consent": True,
            "work_shift_id": night["id"],
        },
    ).json()
    emp_b = client.post(
        "/api/persons",
        headers=admin_headers,
        json={
            "organization_id": org_id,
            "external_id": "NOC-B",
            "full_name": "Mateo Vega",
            "biometric_consent": True,
            "work_shift_id": night["id"],
        },
    ).json()

    s_day1 = client.post(
        f"/api/enterprise/shifts/{night['id']}/start-session",
        headers=admin_headers,
        json={"session_date": "2026-11-16"},
    ).json()
    s_day2 = client.post(
        f"/api/enterprise/shifts/{night['id']}/start-session",
        headers=admin_headers,
        json={"session_date": "2026-11-17"},
    ).json()

    with SessionLocal() as db:
        org_obj = db.get(Organization, org_id)
        sess1 = db.get(AttendanceSession, s_day1["id"])
        sess2 = db.get(AttendanceSession, s_day2["id"])
        pa = db.get(Person, emp_a["id"])
        pb = db.get(Person, emp_b["id"])
        assert org_obj and sess1 and sess2 and pa and pb

        in_a = record_recognized_attendance(
            db, org_obj, sess1, pa, 0.90, action_mode="auto", now=datetime(2026, 11, 16, 22, 5)
        )
        assert in_a.event and in_a.event.status == "on_time"

        in_b = record_recognized_attendance(
            db, org_obj, sess1, pb, 0.91, action_mode="auto", now=datetime(2026, 11, 16, 22, 0)
        )
        assert in_b.event and in_b.event.status == "on_time"

        # Al día siguiente (2026-11-17) marcan en la sesión del día 2; debe cerrar la sesión del día 1
        out_a = record_recognized_attendance(
            db, org_obj, sess2, pa, 0.92, action_mode="auto", now=datetime(2026, 11, 17, 5, 30)
        )
        assert out_a.action == "recorded"
        assert out_a.event is not None
        assert out_a.event.session_id == sess1.id
        assert out_a.event.event_type == "check_out"
        assert out_a.event.status == "early_exit"
        assert out_a.early_exit_minutes == 30
        assert out_a.worked_minutes == 445

        out_b = record_recognized_attendance(
            db, org_obj, sess2, pb, 0.95, action_mode="auto", now=datetime(2026, 11, 17, 5, 55)
        )
        assert out_b.action == "recorded"
        assert out_b.event is not None
        assert out_b.event.session_id == sess1.id
        assert out_b.event.event_type == "check_out"
        assert out_b.event.status == "on_time"
        assert out_b.early_exit_minutes == 0
        assert out_b.worked_minutes == 475


def test_bulk_assign_generate_sessions_enterprise_stats_and_csv(raw_api_client) -> None:
    """Valida asignación en lote, generación idempotente, estadísticas y CSV empresarial."""
    client, SessionLocal, _, _ = raw_api_client
    settings = get_settings()
    sa_headers = _auth_header(
        client,
        settings.bootstrap_superadmin_email,
        settings.bootstrap_superadmin_password,
    )

    org_id, admin_headers = _create_enterprise_org(
        client,
        sa_headers,
        name="Corporativo Norte",
        admin_email="admin@norte.com",
        late_tolerance_minutes=10,
    )

    m1 = client.post(
        "/api/enterprise/shifts",
        headers=admin_headers,
        json={
            "organization_id": org_id,
            "name": "Matutino Corto",
            "code": "M1",
            "start_time": "08:00",
            "end_time": "16:00",
            "days_of_week": [0, 1, 2],
            "late_tolerance_minutes": 10,
            "early_exit_tolerance_minutes": 10,
        },
    ).json()

    v1 = client.post(
        "/api/enterprise/shifts",
        headers=admin_headers,
        json={
            "organization_id": org_id,
            "name": "Vespertino",
            "code": "V1",
            "start_time": "14:00",
            "end_time": "22:00",
            "days_of_week": [0, 1, 2, 3, 4],
        },
    ).json()

    emp1 = client.post(
        "/api/persons",
        headers=admin_headers,
        json={
            "organization_id": org_id,
            "external_id": "N-01",
            "full_name": "Sofía Salas",
            "biometric_consent": True,
        },
    ).json()
    emp2 = client.post(
        "/api/persons",
        headers=admin_headers,
        json={
            "organization_id": org_id,
            "external_id": "N-02",
            "full_name": "Jorge Méndez",
            "biometric_consent": True,
        },
    ).json()
    emp3 = client.post(
        "/api/persons",
        headers=admin_headers,
        json={
            "organization_id": org_id,
            "external_id": "N-03",
            "full_name": "Lucía Pardo",
            "biometric_consent": True,
        },
    ).json()

    bulk_assign = client.post(
        f"/api/enterprise/shifts/{m1['id']}/assign-persons",
        headers=admin_headers,
        json={"person_ids": [emp1["id"], emp2["id"], emp3["id"]]},
    )
    assert bulk_assign.status_code == 200, bulk_assign.text
    assert bulk_assign.json()["updated_count"] == 3

    bulk_clear = client.post(
        f"/api/enterprise/shifts/{m1['id']}/assign-persons",
        headers=admin_headers,
        json={"person_ids": [emp3["id"]], "clear_shift": True},
    )
    assert bulk_clear.status_code == 200
    assert bulk_clear.json()["updated_count"] == 1

    # Generación idempotente de jornadas para el lunes 2026-11-09
    gen1 = client.post(
        "/api/enterprise/sessions/generate",
        headers=admin_headers,
        json={"organization_id": org_id, "target_date": "2026-11-09"},
    )
    assert gen1.status_code == 200, gen1.text
    assert gen1.json()["created_count"] == 2
    assert gen1.json()["existing_count"] == 0

    gen2 = client.post(
        "/api/enterprise/sessions/generate",
        headers=admin_headers,
        json={"organization_id": org_id, "target_date": "2026-11-09"},
    )
    assert gen2.status_code == 200
    assert gen2.json()["created_count"] == 0
    assert gen2.json()["existing_count"] == 2

    with SessionLocal() as db:
        _, _, sess_mon_list = generate_shift_sessions_for_date(
            db, organization_id=org_id, target_date=date(2026, 11, 9), work_shift_id=m1["id"]
        )
        _, _, sess_tue_list = generate_shift_sessions_for_date(
            db, organization_id=org_id, target_date=date(2026, 11, 10), work_shift_id=m1["id"]
        )
        _, _, _ = generate_shift_sessions_for_date(
            db, organization_id=org_id, target_date=date(2026, 11, 11), work_shift_id=m1["id"]
        )

        org_obj = db.get(Organization, org_id)
        p1 = db.get(Person, emp1["id"])
        p2 = db.get(Person, emp2["id"])
        assert org_obj and p1 and p2
        s_mon = sess_mon_list[0]
        s_tue = sess_tue_list[0]

        # Emp 1: Lunes a tiempo + salida a tiempo (483m), Martes retardo (+25m) + salida ant. (-30m, 425m), Miércoles falta
        record_recognized_attendance(
            db, org_obj, s_mon, p1, 0.90, action_mode="auto", now=datetime(2026, 11, 9, 8, 2)
        )
        record_recognized_attendance(
            db, org_obj, s_mon, p1, 0.91, action_mode="auto", now=datetime(2026, 11, 9, 16, 5)
        )
        record_recognized_attendance(
            db, org_obj, s_tue, p1, 0.92, action_mode="auto", now=datetime(2026, 11, 10, 8, 25)
        )
        record_recognized_attendance(
            db, org_obj, s_tue, p1, 0.93, action_mode="auto", now=datetime(2026, 11, 10, 15, 30)
        )

        # Emp 2: Lunes solo check-in (sin checkout), Martes y Miércoles falta
        record_recognized_attendance(
            db, org_obj, s_mon, p2, 0.89, action_mode="auto", now=datetime(2026, 11, 9, 8, 0)
        )

    stats_res = client.get(
        f"/api/enterprise/stats?organization_id={org_id}&date_from=2026-11-09&date_to=2026-11-11",
        headers=admin_headers,
    )
    assert stats_res.status_code == 200, stats_res.text
    stats = stats_res.json()

    assert stats["summary"]["total_shifts"] == 2
    assert stats["summary"]["total_employees"] == 3
    assert stats["summary"]["assigned_employees"] == 2
    assert stats["summary"]["unassigned_employees"] == 1
    assert stats["summary"]["scheduled_employee_days"] == 6
    assert stats["summary"]["present_days"] == 3
    assert stats["summary"]["absent_days"] == 3
    assert stats["summary"]["missing_checkout_days"] == 1

    st_emp1 = next(e for e in stats["by_employee"] if e["person_id"] == emp1["id"])
    assert st_emp1["scheduled_days"] == 3
    assert st_emp1["present_days"] == 2
    assert st_emp1["on_time_days"] == 1
    assert st_emp1["late_days"] == 1
    assert st_emp1["early_exit_days"] == 1
    assert st_emp1["absent_days"] == 1
    assert st_emp1["total_late_minutes"] == 25
    assert st_emp1["total_early_exit_minutes"] == 30
    assert st_emp1["total_worked_minutes"] == 908

    st_emp2 = next(e for e in stats["by_employee"] if e["person_id"] == emp2["id"])
    assert st_emp2["missing_checkout_days"] == 1
    assert st_emp2["absent_days"] == 2

    shift_names_in_stats = [s["shift_name"] for s in stats["by_shift"]]
    assert "Matutino Corto" in shift_names_in_stats
    assert "Sin turno asignado" in shift_names_in_stats

    csv_res = client.get(f"/api/attendance/export.csv?organization_id={org_id}", headers=admin_headers)
    assert csv_res.status_code == 200
    assert csv_res.text.startswith("\ufeff")
    assert "Turno,Minutos Trabajados,Minutos Retardo,Minutos Salida Anticipada" in csv_res.text
    assert "Matutino Corto" in csv_res.text
    assert "425" in csv_res.text


def test_alembic_0004_upgrade_and_downgrade(tmp_path: Path, monkeypatch) -> None:
    """Verifica el ciclo completo upgrade 0004 -> downgrade 0003 -> upgrade 0004 sobre SQLite."""
    db_file = tmp_path / "alembic_0004.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("IDENTIA_DATABASE_URL", db_url)
    get_settings.cache_clear()

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))

    try:
        command.upgrade(cfg, "0004_enterprise_work_shifts")
        eng = create_db_engine(db_url)
        insp = inspect(eng)
        assert "work_shifts" in insp.get_table_names()
        assert "default_work_shift_id" in {c["name"] for c in insp.get_columns("groups")}
        assert "work_shift_id" in {c["name"] for c in insp.get_columns("persons")}
        assert "work_shift_id" in {c["name"] for c in insp.get_columns("attendance_sessions")}
        ev_cols = {c["name"] for c in insp.get_columns("attendance_events")}
        assert {"work_shift_id", "worked_minutes", "late_minutes", "early_exit_minutes"}.issubset(ev_cols)
        with eng.connect() as conn:
            rev = conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
        eng.dispose()
        assert rev == "0004_enterprise_work_shifts"

        # Downgrade limpio a 0003
        command.downgrade(cfg, "0003_academic_periods_and_classrooms")
        eng2 = create_db_engine(db_url)
        insp2 = inspect(eng2)
        assert "work_shifts" not in insp2.get_table_names()
        assert "default_work_shift_id" not in {c["name"] for c in insp2.get_columns("groups")}
        assert "work_shift_id" not in {c["name"] for c in insp2.get_columns("persons")}
        ev_cols2 = {c["name"] for c in insp2.get_columns("attendance_events")}
        assert "early_exit_minutes" not in ev_cols2
        eng2.dispose()

        # Re-upgrade a 0004
        command.upgrade(cfg, "0004_enterprise_work_shifts")
        eng3 = create_db_engine(db_url)
        with eng3.connect() as conn:
            rev3 = conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
        eng3.dispose()
        assert rev3 == "0004_enterprise_work_shifts"
    finally:
        get_settings.cache_clear()


def test_supervisor_permissions_and_department_shift_schedule_sync(raw_api_client) -> None:
    """Verifica permisos de Supervisor en empresa y sincronización de horario con turno por defecto."""
    client, _, _, _ = raw_api_client
    settings = get_settings()
    sa_headers = _auth_header(
        client,
        settings.bootstrap_superadmin_email,
        settings.bootstrap_superadmin_password,
    )
    org_id, admin_headers = _create_enterprise_org(
        client,
        sa_headers,
        name="Planta Industrial Alfa",
        admin_email="alfa.admin@identia.local",
    )

    sup_res = client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "email": "alfa.sup@identia.local",
            "full_name": "Carlos Supervisor",
            "password": "Supervisor2026!",
            "role": "supervisor",
        },
    )
    assert sup_res.status_code == 201, sup_res.text
    sup_headers = _auth_header(client, "alfa.sup@identia.local", "Supervisor2026!")

    shift_a = client.post(
        "/api/enterprise/shifts",
        headers=admin_headers,
        json={
            "organization_id": org_id,
            "name": "Turno Matutino 7-15",
            "code": "MAT7",
            "start_time": "07:00",
            "end_time": "15:00",
            "days_of_week": [0, 1, 2, 3, 4],
        },
    ).json()
    shift_b = client.post(
        "/api/enterprise/shifts",
        headers=admin_headers,
        json={
            "organization_id": org_id,
            "name": "Turno Nocturno 22-06",
            "code": "NOC22",
            "start_time": "22:00",
            "end_time": "06:00",
            "days_of_week": [0, 1, 2, 3, 4],
        },
    ).json()

    # Crear área sin pasar schedule_start/schedule_end debe sincronizarse con shift_a
    dept_res = client.post(
        "/api/groups",
        headers=admin_headers,
        json={
            "organization_id": org_id,
            "name": "Empaque",
            "code": "EMP",
            "default_work_shift_id": shift_a["id"],
        },
    )
    assert dept_res.status_code == 201, dept_res.text
    dept = dept_res.json()
    assert dept["schedule_start"] == "07:00"
    assert dept["schedule_end"] == "15:00"

    # Al cambiar default_work_shift_id también sincroniza schedule_start y schedule_end
    dept_patch = client.patch(
        f"/api/groups/{dept['id']}",
        headers=admin_headers,
        json={"default_work_shift_id": shift_b["id"]},
    )
    assert dept_patch.status_code == 200, dept_patch.text
    assert dept_patch.json()["schedule_start"] == "22:00"
    assert dept_patch.json()["schedule_end"] == "06:00"

    # Permisos operativos del Supervisor (permitidos)
    assert client.get(f"/api/enterprise/shifts?organization_id={org_id}", headers=sup_headers).status_code == 200
    assert client.get(f"/api/enterprise/stats?organization_id={org_id}", headers=sup_headers).status_code == 200
    assert (
        client.post(
            "/api/enterprise/sessions/generate",
            headers=sup_headers,
            json={"organization_id": org_id, "target_date": "2026-06-15"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/enterprise/shifts/{shift_a['id']}/start-session",
            headers=sup_headers,
            json={"session_date": "2026-06-15"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/persons",
            headers=sup_headers,
            json={
                "organization_id": org_id,
                "external_id": "SUP-EMP-01",
                "full_name": "Operario Registrado",
                "role": "employee",
                "biometric_consent": True,
                "group_ids": [dept["id"]],
            },
        ).status_code
        == 201
    )

    # Acciones restringidas al Supervisor -> 403
    assert (
        client.post(
            "/api/enterprise/shifts",
            headers=sup_headers,
            json={
                "organization_id": org_id,
                "name": "No permitido",
                "code": "NP",
                "start_time": "10:00",
                "end_time": "18:00",
            },
        ).status_code
        == 403
    )
    assert client.delete(f"/api/enterprise/shifts/{shift_a['id']}", headers=sup_headers).status_code == 403
    assert client.get(f"/api/users?organization_id={org_id}", headers=sup_headers).status_code == 403
