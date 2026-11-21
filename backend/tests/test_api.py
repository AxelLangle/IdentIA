"""Pruebas de integración HTTP para salud, enrolamiento, privacidad y asistencia."""

from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.config import obtener_configuracion
from app.models import EventoAsistencia, VectorFacial
from app.vision.engine import normalizar_vector
from app.vision.quality import CuadroRostro
from tests.conftest import (
    codificar_bytes_jpeg,
    crear_imagen_rostro_nitida,
    crear_puntos_pose,
    crear_vector_unitario,
)


def _bytes_imagen_valida() -> bytes:
    """Genera un JPEG nítido de prueba para enviar como `multipart/form-data`."""
    return codificar_bytes_jpeg(
        crear_imagen_rostro_nitida(400, 400, (100, 80, 180, 200), 140, False)
    )


def test_salud_y_organizacion_semilla(cliente_api) -> None:
    """Verifica el endpoint `/api/health` y la creación automática de la org demo."""
    cliente, _, _, _ = cliente_api
    respuesta = cliente.get("/api/health")
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["estado"] == "ok"
    assert cuerpo["modelos_cargados"] is True
    assert cuerpo["cantidad_organizaciones"] == 1

    organizaciones = cliente.get("/api/organizations").json()
    assert len(organizaciones) == 1
    assert organizaciones[0]["modo"] == "enterprise"


def test_validacion_enrolamiento_privacidad_y_revocacion(cliente_api) -> None:
    """Prueba consentimiento obligatorio, 6 poses, no guardado de fotos crudas y revocación."""
    cliente, FabricaSesiones, motor, ruta_temporal = cliente_api
    id_organizacion = cliente.get("/api/organizations").json()[0]["id"]

    # Persona sin consentimiento biométrico inicial
    persona_sin_consentimiento = cliente.post(
        "/api/persons",
        json={
            "id_organizacion": id_organizacion,
            "identificador_externo": "EMP-100",
            "nombre_completo": "Laura Méndez",
            "rol": "employee",
            "consentimiento_biometrico": False,
        },
    )
    assert persona_sin_consentimiento.status_code == 201
    id_persona = persona_sin_consentimiento.json()["id"]

    # El enrolamiento debe bloquearse mientras no exista consentimiento
    bloqueado = cliente.post(
        f"/api/persons/{id_persona}/enroll-frame",
        data={"etiqueta_pose": "frontal"},
        files={"imagen": ("frame.jpg", _bytes_imagen_valida(), "image/jpeg")},
    )
    assert bloqueado.status_code == 400

    # Identificador externo duplicado en la misma organización devuelve HTTP 409
    duplicado = cliente.post(
        "/api/persons",
        json={
            "id_organizacion": id_organizacion,
            "identificador_externo": "EMP-100",
            "nombre_completo": "Otra Persona",
            "consentimiento_biometrico": True,
        },
    )
    assert duplicado.status_code == 409

    # Otorga consentimiento biométrico
    actualizada = cliente.patch(
        f"/api/persons/{id_persona}",
        json={"consentimiento_biometrico": True},
    )
    assert actualizada.status_code == 200
    assert actualizada.json()["consentimiento_biometrico"] is True

    # 0 rostros detectados -> rechazado
    motor.siguientes_cuadros = []
    sin_rostro = cliente.post(
        f"/api/persons/{id_persona}/enroll-frame",
        data={"etiqueta_pose": "frontal"},
        files={"imagen": ("frame.jpg", _bytes_imagen_valida(), "image/jpeg")},
    )
    assert sin_rostro.status_code == 200
    assert sin_rostro.json()["aceptado"] is False

    # 2 rostros simultáneos -> rechazado
    cuadro_1 = CuadroRostro(100, 80, 180, 200, 0.98, crear_puntos_pose("frontal"))
    cuadro_2 = CuadroRostro(10, 10, 90, 90, 0.91, crear_puntos_pose("frontal"))
    motor.siguientes_cuadros = [cuadro_1, cuadro_2]
    dos_rostros = cliente.post(
        f"/api/persons/{id_persona}/enroll-frame",
        data={"etiqueta_pose": "frontal"},
        files={"imagen": ("frame.jpg", _bytes_imagen_valida(), "image/jpeg")},
    )
    assert dos_rostros.json()["aceptado"] is False
    assert "varios rostros" in dos_rostros.json()["mensaje"]

    # 1 rostro frontal válido -> aceptado y guarda miniatura avatar
    motor.siguientes_cuadros = [cuadro_1]
    motor.siguiente_vector = crear_vector_unitario(42)
    frontal_ok = cliente.post(
        f"/api/persons/{id_persona}/enroll-frame",
        data={"etiqueta_pose": "frontal", "guardar_avatar": "true"},
        files={"imagen": ("frame.jpg", _bytes_imagen_valida(), "image/jpeg")},
    )
    assert frontal_ok.status_code == 200
    datos_frontales = frontal_ok.json()
    assert datos_frontales["aceptado"] is True
    assert datos_frontales["pose_valida"] is True
    assert datos_frontales["cantidad_vectores"] == 1
    assert datos_frontales["avatar_guardado"] is True

    # Pose incorrecta: rostro mirando al frente enviado como pose "left" -> rechazado
    pose_incorrecta = cliente.post(
        f"/api/persons/{id_persona}/enroll-frame",
        data={"etiqueta_pose": "left"},
        files={"imagen": ("frame.jpg", _bytes_imagen_valida(), "image/jpeg")},
    )
    assert pose_incorrecta.json()["aceptado"] is False
    assert pose_incorrecta.json()["pose_valida"] is False

    # Pose "left" válida con solo_validacion=true -> valida pose pero no persiste vector
    cuadro_izquierda = CuadroRostro(100, 80, 180, 200, 0.98, crear_puntos_pose("left"))
    motor.siguientes_cuadros = [cuadro_izquierda]
    solo_validacion = cliente.post(
        f"/api/persons/{id_persona}/enroll-frame",
        data={"etiqueta_pose": "left", "solo_validacion": "true"},
        files={"imagen": ("frame.jpg", _bytes_imagen_valida(), "image/jpeg")},
    )
    assert solo_validacion.status_code == 200
    assert solo_validacion.json()["pose_valida"] is True
    assert solo_validacion.json()["aceptado"] is False
    assert solo_validacion.json()["cantidad_vectores"] == 1

    # Rostro inconsistente (otra persona) -> rechazado
    motor.siguiente_vector = -crear_vector_unitario(42)
    inconsistente = cliente.post(
        f"/api/persons/{id_persona}/enroll-frame",
        data={"etiqueta_pose": "left"},
        files={"imagen": ("frame.jpg", _bytes_imagen_valida(), "image/jpeg")},
    )
    assert inconsistente.json()["aceptado"] is False
    assert "no coincide" in inconsistente.json()["mensaje"]

    # Completa las 5 poses restantes válidas hasta alcanzar 6/6
    motor.siguiente_vector = crear_vector_unitario(42)
    ultima_respuesta = None
    for pose in ("left", "right", "up", "down", "smile"):
        motor.siguientes_cuadros = [
            CuadroRostro(100, 80, 180, 200, 0.98, crear_puntos_pose(pose))
        ]
        res_pose = cliente.post(
            f"/api/persons/{id_persona}/enroll-frame",
            data={"etiqueta_pose": pose},
            files={"imagen": ("frame.jpg", _bytes_imagen_valida(), "image/jpeg")},
        )
        assert res_pose.status_code == 200
        ultima_respuesta = res_pose.json()
        assert ultima_respuesta["aceptado"] is True

    assert ultima_respuesta is not None
    assert ultima_respuesta["enrolamiento_completo"] is True
    assert ultima_respuesta["cantidad_poses_requeridas"] == 6

    persona_final = [
        p
        for p in cliente.get(f"/api/persons?id_organizacion={id_organizacion}").json()
        if p["id"] == id_persona
    ][0]
    assert persona_final["cantidad_vectores"] == 6

    with FabricaSesiones() as sesion_bd:
        vector_frontal = sesion_bd.scalars(
            select(VectorFacial).where(
                VectorFacial.id_persona == id_persona,
                VectorFacial.etiqueta_pose == "frontal",
            )
        ).one()
        assert vector_frontal.relacion_inclinacion_vertical is not None
        assert vector_frontal.relacion_boca is not None

    # Privacidad: ninguna imagen cruda .jpg/.png persistida en disco
    imagenes_guardadas = list(Path(ruta_temporal).rglob("*.jpg")) + list(
        Path(ruta_temporal).rglob("*.png")
    )
    assert imagenes_guardadas == []

    # Revocación biométrica protegida con contraseña administrativa
    configuracion = obtener_configuracion()
    revocado = cliente.request(
        "DELETE",
        f"/api/persons/{id_persona}/biometrics",
        json={
            "secreto_autorizacion": configuracion.contrasena_superadmin_inicial,
            "motivo": "Prueba de revocación individual",
        },
    )
    assert revocado.status_code == 200
    assert revocado.json()["vectores_eliminados"] == 6
    assert revocado.json()["avatar_eliminado"] is True


def test_empresa_entrada_enfriamiento_salida_y_csv(cliente_api) -> None:
    """Valida flujo empresarial completo: reconocimiento, ambigüedad, cooldown, salida y CSV."""
    cliente, FabricaSesiones, motor, _ = cliente_api
    id_organizacion = cliente.get("/api/organizations").json()[0]["id"]

    persona_1 = cliente.post(
        "/api/persons",
        json={
            "id_organizacion": id_organizacion,
            "identificador_externo": "EMP-01",
            "nombre_completo": "Diego Morales",
            "consentimiento_biometrico": True,
        },
    ).json()
    persona_2 = cliente.post(
        "/api/persons",
        json={
            "id_organizacion": id_organizacion,
            "identificador_externo": "EMP-02",
            "nombre_completo": "Sofía Herrera",
            "consentimiento_biometrico": True,
        },
    ).json()

    vector_1 = crear_vector_unitario(101)
    vector_2 = crear_vector_unitario(202)
    motor.siguientes_cuadros = [CuadroRostro(100, 80, 180, 200, 0.99, [])]

    motor.siguiente_vector = vector_1
    assert (
        cliente.post(
            f"/api/persons/{persona_1['id']}/enroll-frame",
            data={"etiqueta_pose": "frontal"},
            files={"imagen": ("f.jpg", _bytes_imagen_valida(), "image/jpeg")},
        ).json()["aceptado"]
        is True
    )

    motor.siguiente_vector = vector_2
    assert (
        cliente.post(
            f"/api/persons/{persona_2['id']}/enroll-frame",
            data={"etiqueta_pose": "frontal"},
            files={"imagen": ("f.jpg", _bytes_imagen_valida(), "image/jpeg")},
        ).json()["aceptado"]
        is True
    )

    # Rostro desconocido
    motor.siguiente_vector = crear_vector_unitario(999)
    desconocido = cliente.post(
        "/api/attendance/recognize-frame",
        data={"id_organizacion": str(id_organizacion)},
        files={"imagen": ("f.jpg", _bytes_imagen_valida(), "image/jpeg")},
    ).json()
    assert desconocido["estado_coincidencia"] == "unknown"

    # Coincidencia ambigua entre dos personas equidistantes
    motor.siguiente_vector = normalizar_vector(vector_1 + vector_2)
    ambiguo = cliente.post(
        "/api/attendance/recognize-frame",
        data={"id_organizacion": str(id_organizacion)},
        files={"imagen": ("f.jpg", _bytes_imagen_valida(), "image/jpeg")},
    ).json()
    assert ambiguo["estado_coincidencia"] == "ambiguous"

    # Primer reconocimiento -> check_in
    motor.siguiente_vector = vector_1
    entrada = cliente.post(
        "/api/attendance/recognize-frame",
        data={"id_organizacion": str(id_organizacion), "modo_accion": "auto"},
        files={"imagen": ("f.jpg", _bytes_imagen_valida(), "image/jpeg")},
    ).json()
    assert entrada["estado_coincidencia"] == "matched"
    assert entrada["accion_asistencia"] == "recorded"
    assert entrada["evento"]["tipo_evento"] == "check_in"
    id_evento = entrada["evento"]["id"]

    # Segundo inmediato -> bloqueado por enfriamiento (cooldown)
    enfriamiento = cliente.post(
        "/api/attendance/recognize-frame",
        data={"id_organizacion": str(id_organizacion), "modo_accion": "auto"},
        files={"imagen": ("f.jpg", _bytes_imagen_valida(), "image/jpeg")},
    ).json()
    assert enfriamiento["accion_asistencia"] == "cooldown"

    # Simula paso de 90 minutos retrocediendo la fecha/hora de la entrada
    with FabricaSesiones() as sesion_bd:
        evento = sesion_bd.get(EventoAsistencia, id_evento)
        assert evento is not None
        evento.fecha_hora = datetime.now() - timedelta(minutes=90)
        sesion_bd.commit()

    # Siguiente reconocimiento -> check_out con minutos_trabajados >= 89
    salida = cliente.post(
        "/api/attendance/recognize-frame",
        data={"id_organizacion": str(id_organizacion), "modo_accion": "auto"},
        files={"imagen": ("f.jpg", _bytes_imagen_valida(), "image/jpeg")},
    ).json()
    assert salida["accion_asistencia"] == "recorded"
    assert salida["evento"]["tipo_evento"] == "check_out"
    assert salida["minutos_trabajados"] >= 89

    # Exportación CSV con BOM UTF-8
    respuesta_csv = cliente.get(f"/api/attendance/export.csv?id_organizacion={id_organizacion}")
    assert respuesta_csv.status_code == 200
    assert respuesta_csv.text.startswith("\ufeff")
    assert "Diego Morales" in respuesta_csv.text


def test_modo_educativo_sesion_grupo_y_cierre(cliente_api) -> None:
    """Valida pase de lista escolar, prevención de duplicados y bloqueo al cerrar sesión."""
    cliente, FabricaSesiones, motor, _ = cliente_api
    org_educativa = cliente.post(
        "/api/organizations",
        json={
            "nombre": "Universidad Politécnica Demo",
            "modo": "education",
            "minutos_tolerancia_retardo": 10,
            "segundos_enfriamiento": 5,
        },
    ).json()

    grupo = cliente.post(
        "/api/groups",
        json={
            "id_organizacion": org_educativa["id"],
            "nombre": "7B - Programación",
            "codigo": "PROG-7B",
            "hora_inicio_horario": "00:00",
            "hora_fin_horario": "23:59",
        },
    ).json()

    alumno = cliente.post(
        "/api/persons",
        json={
            "id_organizacion": org_educativa["id"],
            "identificador_externo": "ALU-2025",
            "nombre_completo": "Valeria Cruz",
            "rol": "student",
            "consentimiento_biometrico": True,
            "ids_grupos": [grupo["id"]],
        },
    ).json()

    motor.siguientes_cuadros = [CuadroRostro(100, 80, 180, 200, 0.98, [])]
    motor.siguiente_vector = crear_vector_unitario(77)
    assert (
        cliente.post(
            f"/api/persons/{alumno['id']}/enroll-frame",
            data={"etiqueta_pose": "frontal"},
            files={"imagen": ("f.jpg", _bytes_imagen_valida(), "image/jpeg")},
        ).json()["aceptado"]
        is True
    )

    sesion = cliente.post(
        "/api/sessions",
        json={
            "id_organizacion": org_educativa["id"],
            "id_grupo": grupo["id"],
            "titulo": "Clase 1 - Arquitectura",
            "hora_inicio_esperada": "00:00",
        },
    ).json()

    reconocimiento = cliente.post(
        "/api/attendance/recognize-frame",
        data={
            "id_organizacion": str(org_educativa["id"]),
            "id_sesion": str(sesion["id"]),
        },
        files={"imagen": ("f.jpg", _bytes_imagen_valida(), "image/jpeg")},
    ).json()
    assert reconocimiento["accion_asistencia"] == "recorded"
    assert reconocimiento["evento"]["tipo_evento"] == "present"
    assert reconocimiento["evento"]["estado"] == "late"

    # Retrocede timestamp más allá de cooldown (5s) para confirmar already_present
    with FabricaSesiones() as sesion_bd:
        evento = sesion_bd.get(EventoAsistencia, reconocimiento["evento"]["id"])
        assert evento is not None
        evento.fecha_hora = datetime.now() - timedelta(seconds=30)
        sesion_bd.commit()

    repetido = cliente.post(
        "/api/attendance/recognize-frame",
        data={
            "id_organizacion": str(org_educativa["id"]),
            "id_sesion": str(sesion["id"]),
        },
        files={"imagen": ("f.jpg", _bytes_imagen_valida(), "image/jpeg")},
    ).json()
    assert repetido["accion_asistencia"] == "already_present"

    # Cierra la sesión y verifica que ya no acepte reconocimientos
    cerrada = cliente.post(f"/api/sessions/{sesion['id']}/close")
    assert cerrada.status_code == 200
    assert cerrada.json()["estado"] == "closed"

    sobre_cerrada = cliente.post(
        "/api/attendance/recognize-frame",
        data={
            "id_organizacion": str(org_educativa["id"]),
            "id_sesion": str(sesion["id"]),
        },
        files={"imagen": ("f.jpg", _bytes_imagen_valida(), "image/jpeg")},
    )
    assert sobre_cerrada.status_code == 400
