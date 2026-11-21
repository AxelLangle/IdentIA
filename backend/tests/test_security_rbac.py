from app.config import get_settings
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


def _enroll_frontal(client, headers: dict[str, str], person_id: int, engine, seed: int) -> None:
    engine.next_boxes = [FaceBox(100, 80, 180, 200, 0.98, make_pose_landmarks("frontal"))]
    engine.next_embedding = make_unit_vector(seed)
    img_bytes = encode_jpeg_bytes(make_sharp_face_image(400, 400, (100, 80, 180, 200), 140, False))
    res = client.post(
        f"/api/persons/{person_id}/enroll-frame",
        headers=headers,
        data={"pose_label": "frontal", "store_avatar": "true"},
        files={"image": ("f.jpg", img_bytes, "image/jpeg")},
    )
    assert res.status_code == 200
    assert res.json()["accepted"] is True


def test_authentication_and_multi_tenant_isolation(raw_api_client) -> None:
    client, _, _, _ = raw_api_client
    settings = get_settings()

    # Endpoints protegidos rechazan acceso sin token
    assert client.get("/api/organizations").status_code == 401
    assert client.get("/api/auth/me").status_code == 401

    # Login inválido
    bad_login = client.post(
        "/api/auth/login",
        json={"email": settings.bootstrap_superadmin_email, "password": "wrong-password"},
    )
    assert bad_login.status_code == 401

    # Superadmin crea Org A (con Admin A) y Org B (con Admin B)
    sa_headers = _auth_header(
        client,
        settings.bootstrap_superadmin_email,
        settings.bootstrap_superadmin_password,
    )

    org_a = client.post(
        "/api/organizations",
        headers=sa_headers,
        json={
            "name": "Empresa Alpha",
            "mode": "enterprise",
            "admin_user": {
                "full_name": "Admin Alpha",
                "email": "alpha@identia.local",
                "password": "AlphaPass123",
            },
        },
    )
    assert org_a.status_code == 201
    org_a_id = org_a.json()["id"]

    org_b = client.post(
        "/api/organizations",
        headers=sa_headers,
        json={
            "name": "Escuela Beta",
            "mode": "education",
            "admin_user": {
                "full_name": "Admin Beta",
                "email": "beta@identia.local",
                "password": "BetaPass123",
            },
        },
    )
    assert org_b.status_code == 201
    org_b_id = org_b.json()["id"]

    alpha_headers = _auth_header(client, "alpha@identia.local", "AlphaPass123")
    beta_headers = _auth_header(client, "beta@identia.local", "BetaPass123")

    # Cada org_admin solo ve su propia organización
    alpha_orgs = client.get("/api/organizations", headers=alpha_headers).json()
    assert [o["id"] for o in alpha_orgs] == [org_a_id]

    beta_orgs = client.get("/api/organizations", headers=beta_headers).json()
    assert [o["id"] for o in beta_orgs] == [org_b_id]

    # Org_admin NO puede crear organizaciones ni escalar a superadmin
    assert (
        client.post(
            "/api/organizations",
            headers=alpha_headers,
            json={"name": "Org Ilegal", "mode": "enterprise"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/users",
            headers=alpha_headers,
            json={
                "email": "fake_sa@identia.local",
                "full_name": "Fake SA",
                "password": "Password123",
                "role": "superadmin",
            },
        ).status_code
        == 403
    )

    # Admin Alpha crea una persona en Org A
    p_a = client.post(
        "/api/persons",
        headers=alpha_headers,
        json={
            "organization_id": org_a_id,
            "external_id": "ALP-01",
            "full_name": "Empleado Alpha",
            "biometric_consent": True,
        },
    )
    assert p_a.status_code == 201
    person_a_id = p_a.json()["id"]

    # Admin Beta recibe 403 al intentar leer, crear o modificar recursos de Org A
    assert client.get(f"/api/persons?organization_id={org_a_id}", headers=beta_headers).status_code == 403
    assert client.get(f"/api/groups?organization_id={org_a_id}", headers=beta_headers).status_code == 403
    assert client.get(f"/api/users?organization_id={org_a_id}", headers=beta_headers).status_code == 403
    assert client.get(f"/api/security/audit-logs?organization_id={org_a_id}", headers=beta_headers).status_code == 403
    assert client.delete(f"/api/persons/{person_a_id}", headers=beta_headers).status_code == 403
    assert (
        client.patch(
            f"/api/organizations/{org_a_id}",
            headers=beta_headers,
            json={"cooldown_seconds": 10},
        ).status_code
        == 403
    )

    # Superadmin sí conserva acceso a todas las organizaciones
    all_orgs = client.get("/api/organizations", headers=sa_headers).json()
    assert {org_a_id, org_b_id}.issubset({o["id"] for o in all_orgs})
    assert client.get(f"/api/persons?organization_id={org_a_id}", headers=sa_headers).status_code == 200
    assert client.get(f"/api/persons?organization_id={org_b_id}", headers=sa_headers).status_code == 200


def test_delegated_credential_revocation_batch_and_audit(raw_api_client) -> None:
    client, _, engine, _ = raw_api_client
    settings = get_settings()
    sa_headers = _auth_header(
        client,
        settings.bootstrap_superadmin_email,
        settings.bootstrap_superadmin_password,
    )

    org_res = client.post(
        "/api/organizations",
        headers=sa_headers,
        json={
            "name": "Corporativo Seguridad",
            "mode": "enterprise",
            "admin_user": {
                "full_name": "María Admin",
                "email": "maria.admin@identia.local",
                "password": "MariaAdmin2026!",
            },
        },
    )
    assert org_res.status_code == 201
    org_id = org_res.json()["id"]

    admin_headers = _auth_header(client, "maria.admin@identia.local", "MariaAdmin2026!")

    # Admin de organización crea dos subordinados operadores
    op1 = client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "email": "op1@identia.local",
            "full_name": "Operador Uno",
            "password": "Operador1Pass",
            "role": "operator",
        },
    ).json()
    client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "email": "op2@identia.local",
            "full_name": "Operador Dos",
            "password": "Operador2Pass",
            "role": "operator",
        },
    )

    op1_headers = _auth_header(client, "op1@identia.local", "Operador1Pass")
    op2_headers = _auth_header(client, "op2@identia.local", "Operador2Pass")

    # Crea y enrola 2 personas en la organización
    p1 = client.post(
        "/api/persons",
        headers=op1_headers,
        json={
            "organization_id": org_id,
            "external_id": "SEG-01",
            "full_name": "Persona Uno",
            "biometric_consent": True,
        },
    ).json()
    p2 = client.post(
        "/api/persons",
        headers=op1_headers,
        json={
            "organization_id": org_id,
            "external_id": "SEG-02",
            "full_name": "Persona Dos",
            "biometric_consent": True,
        },
    ).json()
    _enroll_frontal(client, op1_headers, p1["id"], engine, 11)
    _enroll_frontal(client, op1_headers, p2["id"], engine, 22)

    # Sin contraseña correcta -> 403
    bad_revoke = client.post(
        "/api/persons/biometrics/revoke",
        headers=op1_headers,
        json={"person_ids": [p1["id"]], "authorization_secret": "Incorrecta999"},
    )
    assert bad_revoke.status_code == 403

    # Admin de org crea credencial delegada asignada a Operador Uno
    cred_res = client.post(
        "/api/security/delegated-credentials",
        headers=admin_headers,
        json={
            "label": "Clave temporal turno matutino",
            "assigned_to_user_id": op1["id"],
            "expires_in_days": 7,
        },
    )
    assert cred_res.status_code == 201
    cred_data = cred_res.json()
    cred_id = cred_data["credential"]["id"]
    plain_secret = cred_data["plain_secret"]
    assert plain_secret.startswith("IDN-")
    # La respuesta de listado no expone el secreto en texto plano
    listed_creds = client.get("/api/security/delegated-credentials", headers=admin_headers).json()
    assert listed_creds[0]["created_by_name"] == "María Admin"
    assert listed_creds[0]["assigned_to_name"] == "Operador Uno"
    assert "secret_hash" not in listed_creds[0]

    # Operador Dos NO puede usar la credencial asignada exclusivamente a Operador Uno
    wrong_subordinate = client.post(
        "/api/persons/biometrics/revoke",
        headers=op2_headers,
        json={"person_ids": [p1["id"]], "authorization_secret": plain_secret},
    )
    assert wrong_subordinate.status_code == 403

    # Operador Uno sí puede revocar en lote con la credencial delegada
    batch_ok = client.post(
        "/api/persons/biometrics/revoke",
        headers=op1_headers,
        json={
            "person_ids": [p1["id"], p2["id"]],
            "authorization_secret": plain_secret,
            "reason": "Cambio de cámara en sucursal",
        },
    )
    assert batch_ok.status_code == 200
    body = batch_ok.json()
    assert body["revoked_persons_count"] == 2
    assert body["deleted_embeddings"] == 2
    assert body["authorized_by_name"] == "María Admin"
    assert body["authorization_method"] == "delegated_credential"

    # Verifica que la bitácora de auditoría registró ejecutor, creador de credencial y objetivo
    logs = client.get(f"/api/security/audit-logs?organization_id={org_id}", headers=admin_headers).json()
    revoke_logs = [entry for entry in logs if entry["action"] == "revoke_biometrics"]
    assert len(revoke_logs) == 2
    assert all(entry["executed_by_name"] == "Operador Uno" for entry in revoke_logs)
    assert all(entry["authorized_by_name"] == "María Admin" for entry in revoke_logs)
    assert all(entry["delegated_assigned_to_name"] == "Operador Uno" for entry in revoke_logs)

    # Si el admin revoca la credencial delegada, ya no funciona
    rev_cred = client.post(f"/api/security/delegated-credentials/{cred_id}/revoke", headers=admin_headers)
    assert rev_cred.status_code == 200
    assert rev_cred.json()["status"] == "revoked"

    _enroll_frontal(client, op1_headers, p1["id"], engine, 33)
    after_revoke = client.post(
        "/api/persons/biometrics/revoke",
        headers=op1_headers,
        json={"person_ids": [p1["id"]], "authorization_secret": plain_secret},
    )
    assert after_revoke.status_code == 403


def test_dynamic_role_validation_by_organization_mode(raw_api_client) -> None:
    """Valida que 'supervisor' sea exclusivo de empresa y 'teacher' exclusivo de escuela."""
    client, _, _, _ = raw_api_client
    settings = get_settings()
    sa_headers = _auth_header(
        client,
        settings.bootstrap_superadmin_email,
        settings.bootstrap_superadmin_password,
    )

    ent_org = client.post(
        "/api/organizations",
        headers=sa_headers,
        json={
            "name": "Empresa Logística Norte",
            "mode": "enterprise",
            "admin_user": {
                "full_name": "Admin Empresa",
                "email": "admin.ent@identia.local",
                "password": "AdminEnt2026!",
            },
        },
    ).json()
    edu_org = client.post(
        "/api/organizations",
        headers=sa_headers,
        json={
            "name": "Escuela Técnica Sur",
            "mode": "education",
            "admin_user": {
                "full_name": "Admin Escuela",
                "email": "admin.edu@identia.local",
                "password": "AdminEdu2026!",
            },
        },
    ).json()

    ent_admin_headers = _auth_header(client, "admin.ent@identia.local", "AdminEnt2026!")
    edu_admin_headers = _auth_header(client, "admin.edu@identia.local", "AdminEdu2026!")

    # Empresa: rechaza 'teacher' (400), acepta 'supervisor' (201)
    bad_ent_teacher = client.post(
        "/api/users",
        headers=ent_admin_headers,
        json={
            "email": "no.profe@identia.local",
            "full_name": "Intento Profe",
            "password": "Password123!",
            "role": "teacher",
        },
    )
    assert bad_ent_teacher.status_code == 400

    ok_ent_supervisor = client.post(
        "/api/users",
        headers=ent_admin_headers,
        json={
            "email": "sup@identia.local",
            "full_name": "Supervisor Planta",
            "password": "Password123!",
            "role": "supervisor",
        },
    )
    assert ok_ent_supervisor.status_code == 201
    sup_id = ok_ent_supervisor.json()["id"]

    # Actualizar usuario existente de empresa a 'teacher' también debe fallar (400)
    bad_ent_patch = client.patch(
        f"/api/users/{sup_id}",
        headers=ent_admin_headers,
        json={"role": "teacher"},
    )
    assert bad_ent_patch.status_code == 400

    # Escuela: rechaza 'supervisor' (400), acepta 'teacher' (201)
    bad_edu_supervisor = client.post(
        "/api/users",
        headers=edu_admin_headers,
        json={
            "email": "no.sup@identia.local",
            "full_name": "Intento Supervisor",
            "password": "Password123!",
            "role": "supervisor",
        },
    )
    assert bad_edu_supervisor.status_code == 400

    ok_edu_teacher = client.post(
        "/api/users",
        headers=edu_admin_headers,
        json={
            "email": "profe@identia.local",
            "full_name": "Profesor Titular",
            "password": "Password123!",
            "role": "teacher",
        },
    )
    assert ok_edu_teacher.status_code == 201
    assert ent_org["mode"] == "enterprise" and edu_org["mode"] == "education"
