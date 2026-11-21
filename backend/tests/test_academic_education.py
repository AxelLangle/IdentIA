from datetime import date
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from app.config import BACKEND_DIR, get_settings
from app.db import Base, create_db_engine
from app.vision.quality import FaceBox
from tests.conftest import (
    encode_jpeg_bytes,
    make_pose_landmarks,
    make_sharp_face_image,
    make_unit_vector,
)


def _auth_header(client, email: str, password: str) -> dict[str, str]:
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _setup_school_fixture(client) -> dict:
    """Crea una institución educativa con admin, 2 profesores, carrera, grupo 21026 IS, materias y alumnos."""
    settings = get_settings()
    sa_headers = _auth_header(
        client,
        settings.bootstrap_superadmin_email,
        settings.bootstrap_superadmin_password,
    )

    school = client.post(
        "/api/organizations",
        headers=sa_headers,
        json={
            "name": "Universidad Tecnológica IdentIA",
            "mode": "education",
            "late_tolerance_minutes": 15,
            "cooldown_seconds": 60,
            "admin_user": {
                "full_name": "Director Escolar",
                "email": "director@uni.edu",
                "password": "DirectorPass123!",
            },
        },
    )
    assert school.status_code == 201, school.text
    org_id = school.json()["id"]
    admin_headers = _auth_header(client, "director@uni.edu", "DirectorPass123!")

    prof_1 = client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "email": "profe.arq@uni.edu",
            "full_name": "Prof. Arquitectura",
            "password": "ProfePass1!",
            "role": "teacher",
            "organization_id": org_id,
        },
    )
    assert prof_1.status_code == 201, prof_1.text
    prof_1_id = prof_1.json()["id"]

    prof_2 = client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "email": "profe.bd@uni.edu",
            "full_name": "Prof. Bases Datos",
            "password": "ProfePass2!",
            "role": "teacher",
            "organization_id": org_id,
        },
    )
    assert prof_2.status_code == 201, prof_2.text
    prof_2_id = prof_2.json()["id"]

    career = client.post(
        "/api/academic/careers",
        headers=admin_headers,
        json={
            "organization_id": org_id,
            "name": "Ingeniería en Software",
            "code": "ISW",
            "description": "Carrera de desarrollo y arquitectura",
        },
    )
    assert career.status_code == 201, career.text
    career_id = career.json()["id"]

    group = client.post(
        "/api/groups",
        headers=admin_headers,
        json={
            "organization_id": org_id,
            "name": "21026 IS",
            "code": "21026-IS",
            "career_id": career_id,
            "semester": "6to Cuatrimestre",
            "schedule_start": "08:00",
            "schedule_end": "14:00",
        },
    )
    assert group.status_code == 201, group.text
    group_id = group.json()["id"]

    subj_arq = client.post(
        "/api/academic/subjects",
        headers=admin_headers,
        json={
            "organization_id": org_id,
            "career_id": career_id,
            "name": "Arquitectura de Software",
            "code": "ARQ-101",
        },
    )
    assert subj_arq.status_code == 201, subj_arq.text

    subj_bd = client.post(
        "/api/academic/subjects",
        headers=admin_headers,
        json={
            "organization_id": org_id,
            "career_id": career_id,
            "name": "Bases de Datos",
            "code": "BDD-102",
        },
    )
    assert subj_bd.status_code == 201, subj_bd.text

    # Horarios en martes (day_of_week = 1)
    course_1 = client.post(
        "/api/academic/courses",
        headers=admin_headers,
        json={
            "organization_id": org_id,
            "group_id": group_id,
            "subject_id": subj_arq.json()["id"],
            "teacher_user_id": prof_1_id,
            "term": "2026-3",
            "schedules": [
                {
                    "day_of_week": 1,
                    "start_time": "10:00",
                    "end_time": "11:00",
                    "classroom": "Lab 3",
                }
            ],
        },
    )
    assert course_1.status_code == 201, course_1.text

    course_2 = client.post(
        "/api/academic/courses",
        headers=admin_headers,
        json={
            "organization_id": org_id,
            "group_id": group_id,
            "subject_id": subj_bd.json()["id"],
            "teacher_user_id": prof_2_id,
            "term": "2026-3",
            "schedules": [
                {
                    "day_of_week": 1,
                    "start_time": "11:00",
                    "end_time": "12:00",
                    "classroom": "Aula 12",
                }
            ],
        },
    )
    assert course_2.status_code == 201, course_2.text

    stu_1 = client.post(
        "/api/persons",
        headers=admin_headers,
        json={
            "organization_id": org_id,
            "external_id": "MAT-001",
            "full_name": "Ana López",
            "role": "student",
            "biometric_consent": True,
            "group_ids": [group_id],
        },
    )
    assert stu_1.status_code == 201, stu_1.text

    stu_2 = client.post(
        "/api/persons",
        headers=admin_headers,
        json={
            "organization_id": org_id,
            "external_id": "MAT-002",
            "full_name": "Carlos Ruiz",
            "role": "student",
            "biometric_consent": True,
            "group_ids": [group_id],
        },
    )
    assert stu_2.status_code == 201, stu_2.text

    return {
        "org_id": org_id,
        "admin_headers": admin_headers,
        "prof1_headers": _auth_header(client, "profe.arq@uni.edu", "ProfePass1!"),
        "prof2_headers": _auth_header(client, "profe.bd@uni.edu", "ProfePass2!"),
        "prof_1_id": prof_1_id,
        "prof_2_id": prof_2_id,
        "career_id": career_id,
        "group_id": group_id,
        "course_1": course_1.json(),
        "course_2": course_2.json(),
        "student_1": stu_1.json(),
        "student_2": stu_2.json(),
    }


def test_academic_hierarchy_inheritance_and_schedule_generation(raw_api_client) -> None:
    client, _, _, _ = raw_api_client
    ctx = _setup_school_fixture(client)

    # Los alumnos heredan automáticamente ambas asignaturas de 21026 IS
    inherited_1 = client.get(
        f"/api/academic/students/{ctx['student_1']['id']}/courses",
        headers=ctx["admin_headers"],
    )
    assert inherited_1.status_code == 200
    codes = {c["subject_code"] for c in inherited_1.json()}
    assert codes == {"ARQ-101", "BDD-102"}

    # Generación automática idempotente para el martes 2026-11-17
    tuesday = "2026-11-17"
    gen_1 = client.post(
        "/api/academic/sessions/generate",
        headers=ctx["admin_headers"],
        json={"organization_id": ctx["org_id"], "target_date": tuesday},
    )
    assert gen_1.status_code == 200, gen_1.text
    assert gen_1.json()["created_count"] == 2
    assert gen_1.json()["existing_count"] == 0
    assert {s["subject_code"] for s in gen_1.json()["sessions"]} == {"ARQ-101", "BDD-102"}

    # Re-ejecutar en la misma fecha no duplica sesiones
    gen_2 = client.post(
        "/api/academic/sessions/generate",
        headers=ctx["admin_headers"],
        json={"organization_id": ctx["org_id"], "target_date": tuesday},
    )
    assert gen_2.status_code == 200
    assert gen_2.json()["created_count"] == 0
    assert gen_2.json()["existing_count"] == 2


def test_teacher_strict_isolation_and_kiosk_attendance(raw_api_client) -> None:
    client, _, engine, _ = raw_api_client
    ctx = _setup_school_fixture(client)
    tuesday = "2026-11-17"

    # Enrolar a Ana López desde admin (docente no puede administrar ni modificar biometría)
    engine.next_boxes = [FaceBox(100, 80, 180, 200, 0.98, make_pose_landmarks("frontal"))]
    engine.next_embedding = make_unit_vector(41)
    img_bytes = encode_jpeg_bytes(make_sharp_face_image(400, 400, (100, 80, 180, 200), 140, False))
    enroll_res = client.post(
        f"/api/persons/{ctx['student_1']['id']}/enroll-frame",
        headers=ctx["admin_headers"],
        data={"pose_label": "frontal", "store_avatar": "false"},
        files={"image": ("f.jpg", img_bytes, "image/jpeg")},
    )
    assert enroll_res.status_code == 200 and enroll_res.json()["accepted"] is True

    # Prof 1 no puede modificar estructura académica ni consultar estadísticas globales
    assert (
        client.post(
            "/api/academic/careers",
            headers=ctx["prof1_headers"],
            json={"organization_id": ctx["org_id"], "name": "Otra", "code": "OTR"},
        ).status_code
        == 403
    )
    assert client.get("/api/academic/stats", headers=ctx["prof1_headers"]).status_code == 403

    # Prof 1 ve solo su materia ARQ-101 y no puede consultar la de Prof 2
    p1_courses = client.get("/api/academic/courses", headers=ctx["prof1_headers"])
    assert p1_courses.status_code == 200
    assert [c["subject_code"] for c in p1_courses.json()] == ["ARQ-101"]
    assert (
        client.get(
            f"/api/academic/courses?teacher_user_id={ctx['prof_2_id']}",
            headers=ctx["prof1_headers"],
        ).status_code
        == 403
    )

    # Agenda docente de Prof 1 el martes a las 10:15 muestra ARQ-101 en curso
    agenda = client.get(
        f"/api/academic/teacher/agenda?target_date={tuesday}&current_time=10:15",
        headers=ctx["prof1_headers"],
    )
    assert agenda.status_code == 200, agenda.text
    agenda_data = agenda.json()
    assert agenda_data["current_slot"] is not None
    assert agenda_data["current_slot"]["subject_code"] == "ARQ-101"
    assert agenda_data["current_slot"]["slot_status"] == "in_progress"

    # Inicia su sesión en 1 clic
    start_p1 = client.post(
        f"/api/academic/courses/{ctx['course_1']['id']}/start-session",
        headers=ctx["prof1_headers"],
        json={
            "schedule_id": ctx["course_1"]["schedules"][0]["id"],
            "session_date": tuesday,
        },
    )
    assert start_p1.status_code == 200, start_p1.text
    sess_p1_id = start_p1.json()["id"]

    # Prof 2 inicia su sesión propia; Prof 1 recibe 403 al intentar tocar la de Prof 2
    start_p2 = client.post(
        f"/api/academic/courses/{ctx['course_2']['id']}/start-session",
        headers=ctx["prof2_headers"],
        json={
            "schedule_id": ctx["course_2"]["schedules"][0]["id"],
            "session_date": tuesday,
        },
    )
    assert start_p2.status_code == 200, start_p2.text
    sess_p2_id = start_p2.json()["id"]

    assert (
        client.post(
            f"/api/academic/courses/{ctx['course_2']['id']}/start-session",
            headers=ctx["prof1_headers"],
            json={"session_date": tuesday},
        ).status_code
        == 403
    )
    assert client.post(f"/api/sessions/{sess_p2_id}/close", headers=ctx["prof1_headers"]).status_code == 403
    assert (
        client.get(
            f"/api/attendance/events?session_id={sess_p2_id}",
            headers=ctx["prof1_headers"],
        ).status_code
        == 403
    )
    assert (
        client.get(
            f"/api/attendance/export.csv?session_id={sess_p2_id}",
            headers=ctx["prof1_headers"],
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/attendance/manual",
            headers=ctx["prof1_headers"],
            json={"session_id": sess_p2_id, "person_id": ctx["student_1"]["id"], "event_type": "present"},
        ).status_code
        == 403
    )

    # Prof 1 reconoce biométricamente a Ana López en su propia sesión
    engine.next_boxes = [FaceBox(100, 80, 180, 200, 0.98, make_pose_landmarks("frontal"))]
    engine.next_embedding = make_unit_vector(41)
    rec = client.post(
        "/api/attendance/recognize-frame",
        headers=ctx["prof1_headers"],
        data={
            "organization_id": str(ctx["org_id"]),
            "session_id": str(sess_p1_id),
            "action_mode": "present",
        },
        files={"image": ("kiosk.jpg", img_bytes, "image/jpeg")},
    )
    assert rec.status_code == 200, rec.text
    assert rec.json()["match_status"] == "matched"
    assert rec.json()["attendance_action"] == "recorded"

    # Y Prof 1 no puede mandar frame al kiosco sobre sesión de Prof 2
    rec_forbidden = client.post(
        "/api/attendance/recognize-frame",
        headers=ctx["prof1_headers"],
        data={
            "organization_id": str(ctx["org_id"]),
            "session_id": str(sess_p2_id),
            "action_mode": "present",
        },
        files={"image": ("kiosk.jpg", img_bytes, "image/jpeg")},
    )
    assert rec_forbidden.status_code == 403

    # Listado de sesiones para Prof 1 solo muestra la suya
    sess_list_p1 = client.get("/api/sessions", headers=ctx["prof1_headers"])
    assert sess_list_p1.status_code == 200
    assert [s["id"] for s in sess_list_p1.json()] == [sess_p1_id]


def test_admin_consolidated_stats_by_subject_and_group(raw_api_client) -> None:
    client, _, _, _ = raw_api_client
    ctx = _setup_school_fixture(client)
    tuesday = date(2026, 11, 17).isoformat()

    gen = client.post(
        "/api/academic/sessions/generate",
        headers=ctx["admin_headers"],
        json={"organization_id": ctx["org_id"], "target_date": tuesday},
    )
    assert gen.status_code == 200
    sessions_by_code = {s["subject_code"]: s["id"] for s in gen.json()["sessions"]}
    sess_arq = sessions_by_code["ARQ-101"]
    sess_bd = sessions_by_code["BDD-102"]

    # ARQ-101: asiste 1 de 2 alumnos (50%)
    r1 = client.post(
        "/api/attendance/manual",
        headers=ctx["admin_headers"],
        json={"session_id": sess_arq, "person_id": ctx["student_1"]["id"], "event_type": "present", "status": "on_time"},
    )
    assert r1.status_code == 201

    # BDD-102: asisten 2 de 2 alumnos (100%)
    for sid in (ctx["student_1"]["id"], ctx["student_2"]["id"]):
        r = client.post(
            "/api/attendance/manual",
            headers=ctx["admin_headers"],
            json={"session_id": sess_bd, "person_id": sid, "event_type": "present", "status": "on_time"},
        )
        assert r.status_code == 201

    stats_res = client.get("/api/academic/stats", headers=ctx["admin_headers"])
    assert stats_res.status_code == 200, stats_res.text
    stats = stats_res.json()

    assert stats["summary"]["total_careers"] == 1
    assert stats["summary"]["total_groups"] == 2  # Incluye GEN-01 inicial + 21026 IS
    assert stats["summary"]["total_subjects"] == 2
    assert stats["summary"]["total_courses"] == 2
    assert stats["summary"]["total_sessions"] == 2
    assert stats["summary"]["overall_attendance_rate"] == 75.0

    by_subj = {item["subject_code"]: item for item in stats["by_subject"]}
    assert by_subj["ARQ-101"]["present_count"] == 1
    assert by_subj["ARQ-101"]["absent_count"] == 1
    assert by_subj["ARQ-101"]["attendance_rate"] == 50.0
    assert by_subj["BDD-102"]["present_count"] == 2
    assert by_subj["BDD-102"]["absent_count"] == 0
    assert by_subj["BDD-102"]["attendance_rate"] == 100.0

    filtered_res = client.get(
        f"/api/academic/stats?career_id={ctx['career_id']}",
        headers=ctx["admin_headers"],
    )
    assert filtered_res.status_code == 200, filtered_res.text
    filtered = filtered_res.json()
    assert filtered["summary"]["total_groups"] == 1
    assert len(filtered["by_group"]) == 1
    g_stat = filtered["by_group"][0]
    assert g_stat["group_name"] == "21026 IS"
    assert g_stat["subjects_count"] == 2
    assert g_stat["total_expected"] == 4
    assert g_stat["total_present"] == 3
    assert g_stat["total_absent"] == 1
    assert g_stat["overall_attendance_rate"] == 75.0

    breakdown = {st["external_id"]: st for st in g_stat["students_breakdown"]}
    assert breakdown["MAT-001"]["attendance_rate"] == 100.0
    assert breakdown["MAT-002"]["attendance_rate"] == 50.0


def test_alembic_0002_recovers_from_partial_create_all(
    tmp_path: Path, monkeypatch
) -> None:
    """Verifica que alembic upgrade head completa columnas aunque create_all haya creado tablas nuevas antes."""
    db_file = tmp_path / "partial_alembic.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("IDENTIA_DATABASE_URL", db_url)
    get_settings.cache_clear()

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))

    try:
        # Simula BD creada en Bloque B (0001) y posterior arranque de uvicorn que ejecuta create_all
        command.upgrade(cfg, "0001_initial_rbac_and_biometrics")
        engine = create_db_engine(db_url)
        Base.metadata.create_all(bind=engine)
        engine.dispose()

        # Ahora alembic upgrade head no debe fallar por "table careers already exists"
        command.upgrade(cfg, "head")

        verify_engine = create_db_engine(db_url)
        insp = inspect(verify_engine)
        table_names = set(insp.get_table_names())
        group_cols = {c["name"] for c in insp.get_columns("groups")}
        person_cols = {c["name"] for c in insp.get_columns("persons")}
        session_cols = {c["name"] for c in insp.get_columns("attendance_sessions")}
        with verify_engine.connect() as conn:
            rev = conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
        verify_engine.dispose()

        assert rev == "0005_group_period_type"
        assert "work_shifts" in table_names
        assert {"career_id", "semester", "period_type", "default_classroom", "default_work_shift_id"}.issubset(group_cols)
        assert "work_shift_id" in person_cols
        assert {"course_assignment_id", "schedule_id", "work_shift_id"}.issubset(session_cols)
    finally:
        get_settings.cache_clear()


def test_academic_periods_default_classroom_and_multi_day_schedules(raw_api_client) -> None:
    """Valida periodos académicos (institución/carrera), aula fija en grupo y múltiples días por materia."""
    client, _, _, _ = raw_api_client
    settings = get_settings()
    sa_headers = _auth_header(
        client,
        settings.bootstrap_superadmin_email,
        settings.bootstrap_superadmin_password,
    )

    school = client.post(
        "/api/organizations",
        headers=sa_headers,
        json={
            "name": "Politécnica IdentIA",
            "mode": "education",
            "academic_period_type": "cuatrimestral",
            "admin_user": {
                "full_name": "Admin Poli",
                "email": "admin.poli@uni.edu",
                "password": "PoliPass123!",
            },
        },
    )
    assert school.status_code == 201, school.text
    assert school.json()["academic_period_type"] == "cuatrimestral"
    org_id = school.json()["id"]
    admin_headers = _auth_header(client, "admin.poli@uni.edu", "PoliPass123!")

    # Carrera A hereda cuatrimestral; Carrera B sobrescribe a semestral
    career_a = client.post(
        "/api/academic/careers",
        headers=admin_headers,
        json={"organization_id": org_id, "name": "Ingeniería en Software", "code": "ISW"},
    )
    assert career_a.status_code == 201, career_a.text
    assert career_a.json()["period_type"] is None
    assert career_a.json()["effective_period_type"] == "cuatrimestral"

    career_b = client.post(
        "/api/academic/careers",
        headers=admin_headers,
        json={
            "organization_id": org_id,
            "name": "Derecho",
            "code": "DER",
            "period_type": "semestral",
        },
    )
    assert career_b.status_code == 201, career_b.text
    assert career_b.json()["period_type"] == "semestral"
    assert career_b.json()["effective_period_type"] == "semestral"

    group = client.post(
        "/api/groups",
        headers=admin_headers,
        json={
            "organization_id": org_id,
            "name": "21026 IS",
            "code": "21026-IS",
            "career_id": career_a.json()["id"],
            "semester": "6to Cuatrimestre",
            "default_classroom": "Aula 33",
        },
    )
    assert group.status_code == 201, group.text
    assert group.json()["default_classroom"] == "Aula 33"
    assert group.json()["period_type"] == "cuatrimestral"

    subj = client.post(
        "/api/academic/subjects",
        headers=admin_headers,
        json={
            "organization_id": org_id,
            "career_id": career_a.json()["id"],
            "name": "Computación",
            "code": "CMP-301",
        },
    )
    assert subj.status_code == 201, subj.text

    # Múltiples días en una sola asignación: Lunes y Miércoles en Aula 33, Viernes en Aula 12
    course = client.post(
        "/api/academic/courses",
        headers=admin_headers,
        json={
            "organization_id": org_id,
            "group_id": group.json()["id"],
            "subject_id": subj.json()["id"],
            "term": "2026-3",
            "schedules": [
                {"day_of_week": 0, "start_time": "08:00", "end_time": "09:00", "classroom": "Aula 33"},
                {"day_of_week": 2, "start_time": "08:00", "end_time": "09:00", "classroom": "Aula 33"},
                {"day_of_week": 4, "start_time": "08:00", "end_time": "09:00", "classroom": "Aula 12"},
            ],
        },
    )
    assert course.status_code == 201, course.text
    c_data = course.json()
    assert c_data["group_default_classroom"] == "Aula 33"
    assert c_data["semester"] == "6to Cuatrimestre"
    assert c_data["period_type"] == "cuatrimestral"
    assert len(c_data["schedules"]) == 3
    classrooms_by_day = {sl["day_of_week"]: sl["classroom"] for sl in c_data["schedules"]}
    assert classrooms_by_day == {0: "Aula 33", 2: "Aula 33", 4: "Aula 12"}

    stats = client.get("/api/academic/stats", headers=admin_headers)
    assert stats.status_code == 200, stats.text
    s_data = stats.json()
    assert s_data["by_subject"][0]["career_id"] == career_a.json()["id"]
    assert s_data["by_subject"][0]["semester"] == "6to Cuatrimestre"
    assert s_data["by_subject"][0]["period_type"] == "cuatrimestral"
    g_match = next(item for item in s_data["by_group"] if item["group_id"] == group.json()["id"])
    assert g_match["period_type"] == "cuatrimestral"


def test_period_type_change_requires_admin_password_and_group_override(
    raw_api_client, tmp_path: Path, monkeypatch
) -> None:
    """Valida tipo de periodo propio por grupo, autorización con clave admin y migración 0005."""
    client, _, _, _ = raw_api_client
    settings = get_settings()
    sa_headers = _auth_header(
        client,
        settings.bootstrap_superadmin_email,
        settings.bootstrap_superadmin_password,
    )

    school = client.post(
        "/api/organizations",
        headers=sa_headers,
        json={
            "name": "Instituto Norte",
            "mode": "education",
            "academic_period_type": "semestral",
            "admin_user": {
                "full_name": "Admin Norte",
                "email": "admin@norte.edu",
                "password": "NorteAdmin99!",
            },
        },
    ).json()
    org_id = school["id"]
    admin_headers = _auth_header(client, "admin@norte.edu", "NorteAdmin99!")

    career = client.post(
        "/api/academic/careers",
        headers=admin_headers,
        json={"organization_id": org_id, "name": "Sistemas", "code": "SIS"},
    ).json()

    grp = client.post(
        "/api/groups",
        headers=admin_headers,
        json={
            "organization_id": org_id,
            "name": "301 SIS",
            "code": "301-SIS",
            "career_id": career["id"],
            "semester": "3",
            "default_classroom": "B-12",
        },
    ).json()
    assert grp["period_type"] == "semestral"
    assert grp["custom_period_type"] is None

    # Editar aula fija o número sin cambiar tipo de periodo NO exige contraseña
    edit_no_period = client.patch(
        f"/api/groups/{grp['id']}",
        headers=admin_headers,
        json={"semester": "6", "default_classroom": "B-14"},
    )
    assert edit_no_period.status_code == 200, edit_no_period.text
    assert edit_no_period.json()["default_classroom"] == "B-14"

    # Cambiar tipo de periodo de grupo sin contraseña -> 400
    grp_no_pass = client.patch(
        f"/api/groups/{grp['id']}",
        headers=admin_headers,
        json={"period_type": "cuatrimestral"},
    )
    assert grp_no_pass.status_code == 400

    # Contraseña incorrecta -> 403
    grp_bad_pass = client.patch(
        f"/api/groups/{grp['id']}",
        headers=admin_headers,
        json={"period_type": "cuatrimestral", "authorization_secret": "WrongPass!"},
    )
    assert grp_bad_pass.status_code == 403

    # Contraseña válida de admin -> 200 y prioridad grupo > carrera > institución
    grp_ok = client.patch(
        f"/api/groups/{grp['id']}",
        headers=admin_headers,
        json={"period_type": "cuatrimestral", "authorization_secret": "NorteAdmin99!"},
    )
    assert grp_ok.status_code == 200, grp_ok.text
    assert grp_ok.json()["custom_period_type"] == "cuatrimestral"
    assert grp_ok.json()["period_type"] == "cuatrimestral"

    # Carrera y organización también exigen contraseña admin al cambiar tipo de periodo
    assert (
        client.patch(
            f"/api/academic/careers/{career['id']}",
            headers=admin_headers,
            json={"period_type": "trimestral"},
        ).status_code
        == 400
    )
    assert (
        client.patch(
            f"/api/academic/careers/{career['id']}",
            headers=admin_headers,
            json={"period_type": "trimestral", "authorization_secret": "WrongPass"},
        ).status_code
        == 403
    )
    career_ok = client.patch(
        f"/api/academic/careers/{career['id']}",
        headers=admin_headers,
        json={"period_type": "trimestral", "authorization_secret": "NorteAdmin99!"},
    )
    assert career_ok.status_code == 200
    assert career_ok.json()["effective_period_type"] == "trimestral"

    assert (
        client.patch(
            f"/api/organizations/{org_id}",
            headers=admin_headers,
            json={"academic_period_type": "bimestral"},
        ).status_code
        == 400
    )
    org_ok = client.patch(
        f"/api/organizations/{org_id}",
        headers=admin_headers,
        json={"academic_period_type": "bimestral", "authorization_secret": "NorteAdmin99!"},
    )
    assert org_ok.status_code == 200
    assert org_ok.json()["academic_period_type"] == "bimestral"

    # Estadísticas reflejan el override propio del grupo ("cuatrimestral")
    stats = client.get("/api/academic/stats", headers=admin_headers).json()
    grp_stat = next(g for g in stats["by_group"] if g["group_id"] == grp["id"])
    assert grp_stat["period_type"] == "cuatrimestral"

    # Bitácora de auditoría registró los tres cambios de periodo
    logs = client.get(f"/api/security/audit-logs?organization_id={org_id}", headers=admin_headers).json()
    actions = {entry["action"] for entry in logs}
    assert {
        "change_group_period_type",
        "change_career_period_type",
        "change_org_period_type",
    }.issubset(actions)

    # Ciclo Alembic 0005 -> downgrade 0004 -> upgrade head
    db_file = tmp_path / "alembic_0005.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("IDENTIA_DATABASE_URL", db_url)
    get_settings.cache_clear()
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    try:
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "0004_enterprise_work_shifts")
        eng_down = create_db_engine(db_url)
        cols_down = {c["name"] for c in inspect(eng_down).get_columns("groups")}
        eng_down.dispose()
        assert "period_type" not in cols_down

        command.upgrade(cfg, "head")
        eng_up = create_db_engine(db_url)
        cols_up = {c["name"] for c in inspect(eng_up).get_columns("groups")}
        eng_up.dispose()
        assert "period_type" in cols_up
    finally:
        get_settings.cache_clear()
