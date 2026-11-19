from datetime import datetime, timedelta
from pathlib import Path

from app.models import AttendanceEvent
from app.vision.engine import normalize_embedding
from app.vision.quality import FaceBox
from tests.conftest import (
    encode_jpeg_bytes,
    make_pose_landmarks,
    make_sharp_face_image,
    make_unit_vector,
)


def _good_image_bytes() -> bytes:
    return encode_jpeg_bytes(make_sharp_face_image(400, 400, (100, 80, 180, 200), 140, False))


def test_health_and_seeded_organization(api_client) -> None:
    client, _, _, _ = api_client
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["models_loaded"] is True
    assert body["organizations_count"] == 1

    orgs = client.get("/api/organizations").json()
    assert len(orgs) == 1
    assert orgs[0]["mode"] == "enterprise"


def test_enrollment_validation_privacy_and_revocation(api_client) -> None:
    client, _, engine, tmp_path = api_client
    org_id = client.get("/api/organizations").json()[0]["id"]

    # Persona sin consentimiento biométrico
    p_no_consent = client.post(
        "/api/persons",
        json={
            "organization_id": org_id,
            "external_id": "EMP-100",
            "full_name": "Laura Méndez",
            "role": "employee",
            "biometric_consent": False,
        },
    )
    assert p_no_consent.status_code == 201
    person_id = p_no_consent.json()["id"]

    # Debe bloquear enrolamiento sin consentimiento
    blocked = client.post(
        f"/api/persons/{person_id}/enroll-frame",
        data={"pose_label": "frontal"},
        files={"image": ("frame.jpg", _good_image_bytes(), "image/jpeg")},
    )
    assert blocked.status_code == 400

    # Duplicado de external_id devuelve 409
    dup = client.post(
        "/api/persons",
        json={
            "organization_id": org_id,
            "external_id": "EMP-100",
            "full_name": "Otra Persona",
            "biometric_consent": True,
        },
    )
    assert dup.status_code == 409

    # Otorga consentimiento
    upd = client.patch(f"/api/persons/{person_id}", json={"biometric_consent": True})
    assert upd.status_code == 200
    assert upd.json()["biometric_consent"] is True

    # 0 rostros -> rechazado
    engine.next_boxes = []
    no_face = client.post(
        f"/api/persons/{person_id}/enroll-frame",
        data={"pose_label": "frontal"},
        files={"image": ("frame.jpg", _good_image_bytes(), "image/jpeg")},
    )
    assert no_face.status_code == 200
    assert no_face.json()["accepted"] is False

    # 2 rostros -> rechazado
    box1 = FaceBox(100, 80, 180, 200, 0.98, make_pose_landmarks("frontal"))
    box2 = FaceBox(10, 10, 90, 90, 0.91, make_pose_landmarks("frontal"))
    engine.next_boxes = [box1, box2]
    two_faces = client.post(
        f"/api/persons/{person_id}/enroll-frame",
        data={"pose_label": "frontal"},
        files={"image": ("frame.jpg", _good_image_bytes(), "image/jpeg")},
    )
    assert two_faces.json()["accepted"] is False
    assert "varios rostros" in two_faces.json()["message"]

    # 1 rostro válido -> aceptado y genera avatar
    engine.next_boxes = [box1]
    engine.next_embedding = make_unit_vector(42)
    ok_frontal = client.post(
        f"/api/persons/{person_id}/enroll-frame",
        data={"pose_label": "frontal", "store_avatar": "true"},
        files={"image": ("frame.jpg", _good_image_bytes(), "image/jpeg")},
    )
    assert ok_frontal.status_code == 200
    data_frontal = ok_frontal.json()
    assert data_frontal["accepted"] is True
    assert data_frontal["pose_valid"] is True
    assert data_frontal["embeddings_count"] == 1
    assert data_frontal["avatar_saved"] is True

    # Pose incorrecta: rostro frontal enviado como pose "left" -> rechazado
    wrong_pose = client.post(
        f"/api/persons/{person_id}/enroll-frame",
        data={"pose_label": "left"},
        files={"image": ("frame.jpg", _good_image_bytes(), "image/jpeg")},
    )
    assert wrong_pose.json()["accepted"] is False
    assert wrong_pose.json()["pose_valid"] is False

    # Pose "left" válida con dry_run=true -> pose_valid=True pero no persiste vector
    left_box = FaceBox(100, 80, 180, 200, 0.98, make_pose_landmarks("left"))
    engine.next_boxes = [left_box]
    dry = client.post(
        f"/api/persons/{person_id}/enroll-frame",
        data={"pose_label": "left", "dry_run": "true"},
        files={"image": ("frame.jpg", _good_image_bytes(), "image/jpeg")},
    )
    assert dry.status_code == 200
    assert dry.json()["pose_valid"] is True
    assert dry.json()["accepted"] is False
    assert dry.json()["embeddings_count"] == 1

    # Pose inconsistente (otra persona) -> rechazada
    engine.next_embedding = -make_unit_vector(42)
    inconsistent = client.post(
        f"/api/persons/{person_id}/enroll-frame",
        data={"pose_label": "left"},
        files={"image": ("frame.jpg", _good_image_bytes(), "image/jpeg")},
    )
    assert inconsistent.json()["accepted"] is False
    assert "no coincide" in inconsistent.json()["message"]

    # Completa las 5 poses restantes válidas hasta llegar a 6/6
    engine.next_embedding = make_unit_vector(42)
    last_pose_res = None
    for pose in ("left", "right", "up", "down", "smile"):
        engine.next_boxes = [FaceBox(100, 80, 180, 200, 0.98, make_pose_landmarks(pose))]
        res_pose = client.post(
            f"/api/persons/{person_id}/enroll-frame",
            data={"pose_label": pose},
            files={"image": ("frame.jpg", _good_image_bytes(), "image/jpeg")},
        )
        assert res_pose.status_code == 200
        last_pose_res = res_pose.json()
        assert last_pose_res["accepted"] is True

    assert last_pose_res is not None
    assert last_pose_res["is_complete"] is True
    assert last_pose_res["required_poses_count"] == 6

    final_person = [p for p in client.get(f"/api/persons?organization_id={org_id}").json() if p["id"] == person_id][0]
    assert final_person["embeddings_count"] == 6

    # Privacidad: ninguna foto cruda .jpg/.png persistida en el directorio temporal de datos
    saved_images = list(Path(tmp_path).rglob("*.jpg")) + list(Path(tmp_path).rglob("*.png"))
    assert saved_images == []

    # Revocación de biometría
    revoked = client.delete(f"/api/persons/{person_id}/biometrics")
    assert revoked.status_code == 200
    assert revoked.json()["deleted_embeddings"] == 6
    assert revoked.json()["avatar_cleared"] is True


def test_enterprise_checkin_cooldown_checkout_and_csv(api_client) -> None:
    client, SessionLocal, engine, _ = api_client
    org_id = client.get("/api/organizations").json()[0]["id"]

    # Crea persona A y persona B
    p1 = client.post(
        "/api/persons",
        json={
            "organization_id": org_id,
            "external_id": "EMP-01",
            "full_name": "Diego Morales",
            "biometric_consent": True,
        },
    ).json()
    p2 = client.post(
        "/api/persons",
        json={
            "organization_id": org_id,
            "external_id": "EMP-02",
            "full_name": "Sofía Herrera",
            "biometric_consent": True,
        },
    ).json()

    v1 = make_unit_vector(101)
    v2 = make_unit_vector(202)
    engine.next_boxes = [FaceBox(100, 80, 180, 200, 0.99, [])]

    engine.next_embedding = v1
    assert (
        client.post(
            f"/api/persons/{p1['id']}/enroll-frame",
            data={"pose_label": "frontal"},
            files={"image": ("f.jpg", _good_image_bytes(), "image/jpeg")},
        ).json()["accepted"]
        is True
    )

    engine.next_embedding = v2
    assert (
        client.post(
            f"/api/persons/{p2['id']}/enroll-frame",
            data={"pose_label": "frontal"},
            files={"image": ("f.jpg", _good_image_bytes(), "image/jpeg")},
        ).json()["accepted"]
        is True
    )

    # Rostro desconocido
    engine.next_embedding = make_unit_vector(999)
    unk = client.post(
        "/api/attendance/recognize-frame",
        data={"organization_id": str(org_id)},
        files={"image": ("f.jpg", _good_image_bytes(), "image/jpeg")},
    ).json()
    assert unk["match_status"] == "unknown"

    # Coincidencia ambigua (equidistante entre v1 y v2)
    engine.next_embedding = normalize_embedding(v1 + v2)
    amb = client.post(
        "/api/attendance/recognize-frame",
        data={"organization_id": str(org_id)},
        files={"image": ("f.jpg", _good_image_bytes(), "image/jpeg")},
    ).json()
    assert amb["match_status"] == "ambiguous"

    # Primer reconocimiento -> check_in
    engine.next_embedding = v1
    checkin = client.post(
        "/api/attendance/recognize-frame",
        data={"organization_id": str(org_id), "action_mode": "auto"},
        files={"image": ("f.jpg", _good_image_bytes(), "image/jpeg")},
    ).json()
    assert checkin["match_status"] == "matched"
    assert checkin["attendance_action"] == "recorded"
    assert checkin["event"]["event_type"] == "check_in"
    event_id = checkin["event"]["id"]

    # Segundo inmediato -> cooldown sin duplicado
    cd = client.post(
        "/api/attendance/recognize-frame",
        data={"organization_id": str(org_id), "action_mode": "auto"},
        files={"image": ("f.jpg", _good_image_bytes(), "image/jpeg")},
    ).json()
    assert cd["attendance_action"] == "cooldown"

    # Simula que pasaron 90 minutos moviendo el timestamp de entrada
    with SessionLocal() as db:
        ev = db.get(AttendanceEvent, event_id)
        assert ev is not None
        ev.timestamp = datetime.now() - timedelta(minutes=90)
        db.commit()

    # Siguiente reconocimiento -> check_out con worked_minutes >= 89
    checkout = client.post(
        "/api/attendance/recognize-frame",
        data={"organization_id": str(org_id), "action_mode": "auto"},
        files={"image": ("f.jpg", _good_image_bytes(), "image/jpeg")},
    ).json()
    assert checkout["attendance_action"] == "recorded"
    assert checkout["event"]["event_type"] == "check_out"
    assert checkout["worked_minutes"] >= 89

    # Exportación CSV con BOM UTF-8
    csv_res = client.get(f"/api/attendance/export.csv?organization_id={org_id}")
    assert csv_res.status_code == 200
    assert csv_res.text.startswith("\ufeff")
    assert "Diego Morales" in csv_res.text


def test_education_mode_session_group_and_manual_fallback(api_client) -> None:
    client, SessionLocal, engine, _ = api_client
    edu_org = client.post(
        "/api/organizations",
        json={
            "name": "Universidad Politécnica Demo",
            "mode": "education",
            "late_tolerance_minutes": 10,
            "cooldown_seconds": 5,
        },
    ).json()

    grp = client.post(
        "/api/groups",
        json={
            "organization_id": edu_org["id"],
            "name": "7B - Programación",
            "code": "PROG-7B",
            "schedule_start": "00:00",
            "schedule_end": "23:59",
        },
    ).json()

    student = client.post(
        "/api/persons",
        json={
            "organization_id": edu_org["id"],
            "external_id": "ALU-2025",
            "full_name": "Valeria Cruz",
            "role": "student",
            "biometric_consent": True,
            "group_ids": [grp["id"]],
        },
    ).json()

    engine.next_boxes = [FaceBox(100, 80, 180, 200, 0.98, [])]
    engine.next_embedding = make_unit_vector(77)
    assert (
        client.post(
            f"/api/persons/{student['id']}/enroll-frame",
            data={"pose_label": "frontal"},
            files={"image": ("f.jpg", _good_image_bytes(), "image/jpeg")},
        ).json()["accepted"]
        is True
    )

    session = client.post(
        "/api/sessions",
        json={
            "organization_id": edu_org["id"],
            "group_id": grp["id"],
            "title": "Clase 1 - Arquitectura",
            "expected_start_time": "00:00",
        },
    ).json()

    rec = client.post(
        "/api/attendance/recognize-frame",
        data={
            "organization_id": str(edu_org["id"]),
            "session_id": str(session["id"]),
        },
        files={"image": ("f.jpg", _good_image_bytes(), "image/jpeg")},
    ).json()
    assert rec["attendance_action"] == "recorded"
    assert rec["event"]["event_type"] == "present"
    assert rec["event"]["status"] == "late"

    # Retrocede timestamp más allá de cooldown (5s) para confirmar already_present
    with SessionLocal() as db:
        ev = db.get(AttendanceEvent, rec["event"]["id"])
        assert ev is not None
        ev.timestamp = datetime.now() - timedelta(seconds=30)
        db.commit()

    again = client.post(
        "/api/attendance/recognize-frame",
        data={
            "organization_id": str(edu_org["id"]),
            "session_id": str(session["id"]),
        },
        files={"image": ("f.jpg", _good_image_bytes(), "image/jpeg")},
    ).json()
    assert again["attendance_action"] == "already_present"

    # Cierra sesión y valida rechazo de reconocimiento sobre sesión cerrada
    closed = client.post(f"/api/sessions/{session['id']}/close")
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"

    on_closed = client.post(
        "/api/attendance/recognize-frame",
        data={
            "organization_id": str(edu_org["id"]),
            "session_id": str(session["id"]),
        },
        files={"image": ("f.jpg", _good_image_bytes(), "image/jpeg")},
    )
    assert on_closed.status_code == 400
