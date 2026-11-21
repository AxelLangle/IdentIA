"""Pruebas de autenticación JWT, aislamiento multi-organización y credenciales delegadas."""

from app.config import obtener_configuracion
from app.vision.quality import CuadroRostro
from tests.conftest import (
    codificar_bytes_jpeg,
    crear_imagen_rostro_nitida,
    crear_puntos_pose,
    crear_vector_unitario,
)


def _encabezado_autorizacion(cliente, correo: str, contrasena: str) -> dict[str, str]:
    """Inicia sesión en `/api/auth/login` y devuelve el header `Authorization`."""
    respuesta = cliente.post(
        "/api/auth/login",
        json={"correo": correo, "contrasena": contrasena},
    )
    assert respuesta.status_code == 200, respuesta.text
    return {"Authorization": f"Bearer {respuesta.json()['token_acceso']}"}


def _enrolar_frontal(
    cliente,
    encabezados: dict[str, str],
    id_persona: int,
    motor,
    semilla: int,
) -> None:
    """Enrola rápidamente la toma frontal de una persona usando el motor simulado."""
    motor.siguientes_cuadros = [CuadroRostro(100, 80, 180, 200, 0.98, crear_puntos_pose("frontal"))]
    motor.siguiente_vector = crear_vector_unitario(semilla)
    bytes_img = codificar_bytes_jpeg(
        crear_imagen_rostro_nitida(400, 400, (100, 80, 180, 200), 140, False)
    )
    respuesta = cliente.post(
        f"/api/persons/{id_persona}/enroll-frame",
        headers=encabezados,
        data={"etiqueta_pose": "frontal", "guardar_avatar": "true"},
        files={"imagen": ("f.jpg", bytes_img, "image/jpeg")},
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["aceptado"] is True


def test_autenticacion_y_aislamiento_multiorganizacion(cliente_api_sin_autenticar) -> None:
    """Valida HTTP 401 sin token, escalamiento prohibido y aislamiento estricto entre orgs."""
    cliente, _, _, _ = cliente_api_sin_autenticar
    configuracion = obtener_configuracion()

    # Endpoints protegidos deben rechazar peticiones sin Bearer token
    assert cliente.get("/api/organizations").status_code == 401
    assert cliente.get("/api/auth/me").status_code == 401

    # Login con contraseña errónea
    login_invalido = cliente.post(
        "/api/auth/login",
        json={
            "correo": configuracion.correo_superadmin_inicial,
            "contrasena": "clave-incorrecta",
        },
    )
    assert login_invalido.status_code == 401

    # Superadmin crea Organización Alpha y Organización Beta con sus respectivos admins
    encabezados_sa = _encabezado_autorizacion(
        cliente,
        configuracion.correo_superadmin_inicial,
        configuracion.contrasena_superadmin_inicial,
    )

    org_a = cliente.post(
        "/api/organizations",
        headers=encabezados_sa,
        json={
            "nombre": "Empresa Alpha",
            "modo": "enterprise",
            "usuario_administrador": {
                "nombre_completo": "Admin Alpha",
                "correo": "alpha@identia.local",
                "contrasena": "AlphaPass123",
            },
        },
    )
    assert org_a.status_code == 201
    id_org_a = org_a.json()["id"]

    org_b = cliente.post(
        "/api/organizations",
        headers=encabezados_sa,
        json={
            "nombre": "Escuela Beta",
            "modo": "education",
            "usuario_administrador": {
                "nombre_completo": "Admin Beta",
                "correo": "beta@identia.local",
                "contrasena": "BetaPass123",
            },
        },
    )
    assert org_b.status_code == 201
    id_org_b = org_b.json()["id"]

    encabezados_alpha = _encabezado_autorizacion(cliente, "alpha@identia.local", "AlphaPass123")
    encabezados_beta = _encabezado_autorizacion(cliente, "beta@identia.local", "BetaPass123")

    # Cada org_admin únicamente observa su propia organización
    orgs_alpha = cliente.get("/api/organizations", headers=encabezados_alpha).json()
    assert [org["id"] for org in orgs_alpha] == [id_org_a]

    orgs_beta = cliente.get("/api/organizations", headers=encabezados_beta).json()
    assert [org["id"] for org in orgs_beta] == [id_org_b]

    # Un org_admin no puede crear organizaciones ni crear cuentas superadmin
    assert (
        cliente.post(
            "/api/organizations",
            headers=encabezados_alpha,
            json={"nombre": "Org Ilegal", "modo": "enterprise"},
        ).status_code
        == 403
    )
    assert (
        cliente.post(
            "/api/users",
            headers=encabezados_alpha,
            json={
                "correo": "falso_sa@identia.local",
                "nombre_completo": "Falso SA",
                "contrasena": "Password123",
                "rol": "superadmin",
            },
        ).status_code
        == 403
    )

    # Admin Alpha da de alta una persona dentro de Org A
    persona_a = cliente.post(
        "/api/persons",
        headers=encabezados_alpha,
        json={
            "id_organizacion": id_org_a,
            "identificador_externo": "ALP-01",
            "nombre_completo": "Empleado Alpha",
            "consentimiento_biometrico": True,
        },
    )
    assert persona_a.status_code == 201
    id_persona_a = persona_a.json()["id"]

    # Admin Beta recibe 403 al intentar acceder o mutar recursos de Org A
    assert (
        cliente.get(
            f"/api/persons?id_organizacion={id_org_a}", headers=encabezados_beta
        ).status_code
        == 403
    )
    assert (
        cliente.get(
            f"/api/groups?id_organizacion={id_org_a}", headers=encabezados_beta
        ).status_code
        == 403
    )
    assert (
        cliente.get(
            f"/api/users?id_organizacion={id_org_a}", headers=encabezados_beta
        ).status_code
        == 403
    )
    assert (
        cliente.get(
            f"/api/security/audit-logs?id_organizacion={id_org_a}", headers=encabezados_beta
        ).status_code
        == 403
    )
    assert cliente.delete(f"/api/persons/{id_persona_a}", headers=encabezados_beta).status_code == 403
    assert (
        cliente.patch(
            f"/api/organizations/{id_org_a}",
            headers=encabezados_beta,
            json={"segundos_enfriamiento": 10},
        ).status_code
        == 403
    )

    # Superadmin conserva visibilidad transversal sobre todas las organizaciones
    todas_orgs = cliente.get("/api/organizations", headers=encabezados_sa).json()
    assert {id_org_a, id_org_b}.issubset({org["id"] for org in todas_orgs})
    assert (
        cliente.get(
            f"/api/persons?id_organizacion={id_org_a}", headers=encabezados_sa
        ).status_code
        == 200
    )
    assert (
        cliente.get(
            f"/api/persons?id_organizacion={id_org_b}", headers=encabezados_sa
        ).status_code
        == 200
    )


def test_credenciales_delegadas_revocacion_lote_y_auditoria(cliente_api_sin_autenticar) -> None:
    """Comprueba emisión, restricción de destinatario, revocación por lote, auditoría y baja de clave."""
    cliente, _, motor, _ = cliente_api_sin_autenticar
    configuracion = obtener_configuracion()
    encabezados_sa = _encabezado_autorizacion(
        cliente,
        configuracion.correo_superadmin_inicial,
        configuracion.contrasena_superadmin_inicial,
    )

    res_org = cliente.post(
        "/api/organizations",
        headers=encabezados_sa,
        json={
            "nombre": "Corporativo Seguridad",
            "modo": "enterprise",
            "usuario_administrador": {
                "nombre_completo": "María Admin",
                "correo": "maria.admin@identia.local",
                "contrasena": "MariaAdmin2026!",
            },
        },
    )
    assert res_org.status_code == 201
    id_organizacion = res_org.json()["id"]

    encabezados_admin = _encabezado_autorizacion(
        cliente, "maria.admin@identia.local", "MariaAdmin2026!"
    )

    # Admin de organización crea dos operadores subordinados
    op_1 = cliente.post(
        "/api/users",
        headers=encabezados_admin,
        json={
            "correo": "op1@identia.local",
            "nombre_completo": "Operador Uno",
            "contrasena": "Operador1Pass",
            "rol": "operator",
        },
    ).json()
    cliente.post(
        "/api/users",
        headers=encabezados_admin,
        json={
            "correo": "op2@identia.local",
            "nombre_completo": "Operador Dos",
            "contrasena": "Operador2Pass",
            "rol": "operator",
        },
    )

    encabezados_op1 = _encabezado_autorizacion(cliente, "op1@identia.local", "Operador1Pass")
    encabezados_op2 = _encabezado_autorizacion(cliente, "op2@identia.local", "Operador2Pass")

    # Crea y enrola 2 empleados
    persona_1 = cliente.post(
        "/api/persons",
        headers=encabezados_op1,
        json={
            "id_organizacion": id_organizacion,
            "identificador_externo": "SEG-01",
            "nombre_completo": "Persona Uno",
            "consentimiento_biometrico": True,
        },
    ).json()
    persona_2 = cliente.post(
        "/api/persons",
        headers=encabezados_op1,
        json={
            "id_organizacion": id_organizacion,
            "identificador_externo": "SEG-02",
            "nombre_completo": "Persona Dos",
            "consentimiento_biometrico": True,
        },
    ).json()
    _enrolar_frontal(cliente, encabezados_op1, persona_1["id"], motor, 11)
    _enrolar_frontal(cliente, encabezados_op1, persona_2["id"], motor, 22)

    # Contraseña incorrecta -> HTTP 403
    revocacion_erronea = cliente.post(
        "/api/persons/biometrics/revoke",
        headers=encabezados_op1,
        json={"ids_personas": [persona_1["id"]], "secreto_autorizacion": "Incorrecta999"},
    )
    assert revocacion_erronea.status_code == 403

    # Admin genera credencial delegada exclusiva para Operador Uno
    res_credencial = cliente.post(
        "/api/security/delegated-credentials",
        headers=encabezados_admin,
        json={
            "etiqueta": "Clave temporal turno matutino",
            "id_usuario_asignado": op_1["id"],
            "expira_en_dias": 7,
        },
    )
    assert res_credencial.status_code == 201
    datos_credencial = res_credencial.json()
    id_credencial = datos_credencial["credencial"]["id"]
    secreto_plano = datos_credencial["secreto_plano"]
    assert secreto_plano.startswith("IDN-")

    credenciales_listadas = cliente.get(
        "/api/security/delegated-credentials", headers=encabezados_admin
    ).json()
    assert credenciales_listadas[0]["nombre_creador"] == "María Admin"
    assert credenciales_listadas[0]["nombre_asignado"] == "Operador Uno"
    assert "hash_secreto" not in credenciales_listadas[0]

    # Operador Dos no puede utilizar una clave asignada a Operador Uno
    operador_equivocado = cliente.post(
        "/api/persons/biometrics/revoke",
        headers=encabezados_op2,
        json={"ids_personas": [persona_1["id"]], "secreto_autorizacion": secreto_plano},
    )
    assert operador_equivocado.status_code == 403

    # Operador Uno sí revoca por lote con la clave delegada
    lote_ok = cliente.post(
        "/api/persons/biometrics/revoke",
        headers=encabezados_op1,
        json={
            "ids_personas": [persona_1["id"], persona_2["id"]],
            "secreto_autorizacion": secreto_plano,
            "motivo": "Cambio de cámara en sucursal",
        },
    )
    assert lote_ok.status_code == 200
    cuerpo_lote = lote_ok.json()
    assert cuerpo_lote["cantidad_personas_revocadas"] == 2
    assert cuerpo_lote["vectores_eliminados"] == 2
    assert cuerpo_lote["nombre_autorizador"] == "María Admin"
    assert cuerpo_lote["metodo_autorizacion"] == "delegated_credential"

    # Verifica bitácora de auditoría completa
    registros = cliente.get(
        f"/api/security/audit-logs?id_organizacion={id_organizacion}",
        headers=encabezados_admin,
    ).json()
    registros_revocacion = [r for r in registros if r["accion"] == "revoke_biometrics"]
    assert len(registros_revocacion) == 2
    assert all(r["nombre_ejecutor"] == "Operador Uno" for r in registros_revocacion)
    assert all(r["nombre_autorizador"] == "María Admin" for r in registros_revocacion)
    assert all(r["nombre_asignado_credencial"] == "Operador Uno" for r in registros_revocacion)

    # Tras revocar la credencial delegada, deja de autorizar inmediatamente
    cred_revocada = cliente.post(
        f"/api/security/delegated-credentials/{id_credencial}/revoke",
        headers=encabezados_admin,
    )
    assert cred_revocada.status_code == 200
    assert cred_revocada.json()["estado"] == "revoked"

    _enrolar_frontal(cliente, encabezados_op1, persona_1["id"], motor, 33)
    despues_revocar = cliente.post(
        "/api/persons/biometrics/revoke",
        headers=encabezados_op1,
        json={"ids_personas": [persona_1["id"]], "secreto_autorizacion": secreto_plano},
    )
    assert despues_revocar.status_code == 403


def test_validacion_dinamica_rol_por_modo_organizacion(cliente_api_sin_autenticar) -> None:
    """Valida que `supervisor` sea exclusivo de empresa y `teacher` exclusivo de escuela."""
    cliente, _, _, _ = cliente_api_sin_autenticar
    configuracion = obtener_configuracion()
    encabezados_sa = _encabezado_autorizacion(
        cliente,
        configuracion.correo_superadmin_inicial,
        configuracion.contrasena_superadmin_inicial,
    )

    org_empresa = cliente.post(
        "/api/organizations",
        headers=encabezados_sa,
        json={
            "nombre": "Empresa Logística Norte",
            "modo": "enterprise",
            "usuario_administrador": {
                "nombre_completo": "Admin Empresa",
                "correo": "admin.ent@identia.local",
                "contrasena": "AdminEnt2026!",
            },
        },
    ).json()
    org_escuela = cliente.post(
        "/api/organizations",
        headers=encabezados_sa,
        json={
            "nombre": "Escuela Técnica Sur",
            "modo": "education",
            "usuario_administrador": {
                "nombre_completo": "Admin Escuela",
                "correo": "admin.edu@identia.local",
                "contrasena": "AdminEdu2026!",
            },
        },
    ).json()

    encabezados_empresa = _encabezado_autorizacion(
        cliente, "admin.ent@identia.local", "AdminEnt2026!"
    )
    encabezados_escuela = _encabezado_autorizacion(
        cliente, "admin.edu@identia.local", "AdminEdu2026!"
    )

    # Empresa: rechaza teacher (400), acepta supervisor (201)
    profesor_en_empresa = cliente.post(
        "/api/users",
        headers=encabezados_empresa,
        json={
            "correo": "no.profe@identia.local",
            "nombre_completo": "Intento Profe",
            "contrasena": "Password123!",
            "rol": "teacher",
        },
    )
    assert profesor_en_empresa.status_code == 400

    supervisor_valido = cliente.post(
        "/api/users",
        headers=encabezados_empresa,
        json={
            "correo": "sup@identia.local",
            "nombre_completo": "Supervisor Planta",
            "contrasena": "Password123!",
            "rol": "supervisor",
        },
    )
    assert supervisor_valido.status_code == 201
    id_supervisor = supervisor_valido.json()["id"]

    # Cambiar un usuario de empresa a teacher también debe fallar (400)
    cambio_invalido = cliente.patch(
        f"/api/users/{id_supervisor}",
        headers=encabezados_empresa,
        json={"rol": "teacher"},
    )
    assert cambio_invalido.status_code == 400

    # Escuela: rechaza supervisor (400), acepta teacher (201)
    supervisor_en_escuela = cliente.post(
        "/api/users",
        headers=encabezados_escuela,
        json={
            "correo": "no.sup@identia.local",
            "nombre_completo": "Intento Supervisor",
            "contrasena": "Password123!",
            "rol": "supervisor",
        },
    )
    assert supervisor_en_escuela.status_code == 400

    profesor_valido = cliente.post(
        "/api/users",
        headers=encabezados_escuela,
        json={
            "correo": "profe@identia.local",
            "nombre_completo": "Profesor Titular",
            "contrasena": "Password123!",
            "rol": "teacher",
        },
    )
    assert profesor_valido.status_code == 201
    assert org_empresa["modo"] == "enterprise" and org_escuela["modo"] == "education"
