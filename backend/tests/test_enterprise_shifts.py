"""Pruebas de turnos laborales empresariales, jornadas nocturnas, estadísticas y Alembic 0004."""

from datetime import date, datetime
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.config import DIRECTORIO_BACKEND, obtener_configuracion
from app.db import crear_motor_bd
from app.models import Organizacion, Persona, SesionAsistencia
from app.services.attendance_service import registrar_asistencia_reconocida
from app.services.enterprise_service import generar_sesiones_turno_para_fecha


def _encabezado_autorizacion(cliente, correo: str, contrasena: str) -> dict[str, str]:
    """Inicia sesión en `/api/auth/login` y devuelve el encabezado Bearer JWT."""
    respuesta = cliente.post(
        "/api/auth/login",
        json={"correo": correo, "contrasena": contrasena},
    )
    assert respuesta.status_code == 200, respuesta.text
    return {"Authorization": f"Bearer {respuesta.json()['token_acceso']}"}


def _crear_organizacion_empresarial(
    cliente,
    encabezados_sa: dict[str, str],
    *,
    nombre: str,
    correo_admin: str,
    contrasena_admin: str = "EmpresaPass123!",
    minutos_tolerancia_retardo: int = 15,
) -> tuple[int, dict[str, str]]:
    """Crea una organización empresarial con su administrador y retorna `(id_org, headers)`."""
    respuesta = cliente.post(
        "/api/organizations",
        headers=encabezados_sa,
        json={
            "nombre": nombre,
            "modo": "enterprise",
            "minutos_tolerancia_retardo": minutos_tolerancia_retardo,
            "segundos_enfriamiento": 30,
            "usuario_administrador": {
                "nombre_completo": f"Admin {nombre}",
                "correo": correo_admin,
                "contrasena": contrasena_admin,
            },
        },
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"], _encabezado_autorizacion(cliente, correo_admin, contrasena_admin)


def test_crud_turnos_validaciones_y_rbac_multiorganizacion(cliente_api_sin_autenticar) -> None:
    """Valida alta, edición, borrado, cruce medianoche, validaciones y aislamiento RBAC."""
    cliente, _, _, _ = cliente_api_sin_autenticar
    configuracion = obtener_configuracion()
    encabezados_sa = _encabezado_autorizacion(
        cliente,
        configuracion.correo_superadmin_inicial,
        configuracion.contrasena_superadmin_inicial,
    )

    org_a, admin_a = _crear_organizacion_empresarial(
        cliente, encabezados_sa, nombre="Planta Alfa", correo_admin="admin.alfa@corp.com"
    )
    org_b, admin_b = _crear_organizacion_empresarial(
        cliente, encabezados_sa, nombre="Planta Beta", correo_admin="admin.beta@corp.com"
    )

    res_operador = cliente.post(
        "/api/users",
        headers=admin_a,
        json={
            "correo": "kiosco.alfa@corp.com",
            "nombre_completo": "Operador Kiosco",
            "contrasena": "OperPass123!",
            "rol": "operator",
            "id_organizacion": org_a,
        },
    )
    assert res_operador.status_code == 201, res_operador.text
    encabezados_op = _encabezado_autorizacion(cliente, "kiosco.alfa@corp.com", "OperPass123!")

    # Turno diurno
    res_diurno = cliente.post(
        "/api/enterprise/shifts",
        headers=admin_a,
        json={
            "id_organizacion": org_a,
            "nombre": "Matutino",
            "codigo": "mat-01",
            "hora_inicio": "08:00",
            "hora_fin": "17:00",
            "dias_semana": [0, 1, 2, 3, 4],
            "minutos_tolerancia_retardo": None,
            "minutos_tolerancia_salida_anticipada": 10,
        },
    )
    assert res_diurno.status_code == 201, res_diurno.text
    turno_diurno = res_diurno.json()
    assert turno_diurno["codigo"] == "MAT-01"
    assert turno_diurno["cruza_medianoche"] is False
    assert turno_diurno["duracion_esperada_minutos"] == 540
    assert turno_diurno["minutos_tolerancia_retardo_efectiva"] == 15

    # Turno nocturno con cruce de medianoche
    res_nocturno = cliente.post(
        "/api/enterprise/shifts",
        headers=admin_a,
        json={
            "id_organizacion": org_a,
            "nombre": "Nocturno Logística",
            "codigo": "NOC-01",
            "hora_inicio": "22:00",
            "hora_fin": "06:00",
            "dias_semana": [0, 1, 2, 3, 4],
            "minutos_tolerancia_retardo": 10,
            "minutos_tolerancia_salida_anticipada": 15,
        },
    )
    assert res_nocturno.status_code == 201, res_nocturno.text
    turno_nocturno = res_nocturno.json()
    assert turno_nocturno["cruza_medianoche"] is True
    assert turno_nocturno["duracion_esperada_minutos"] == 480

    # Validaciones de entrada/salida iguales, días vacíos y código duplicado
    horas_iguales = cliente.post(
        "/api/enterprise/shifts",
        headers=admin_a,
        json={
            "id_organizacion": org_a,
            "nombre": "Inválido",
            "codigo": "INV-1",
            "hora_inicio": "09:00",
            "hora_fin": "09:00",
            "dias_semana": [0, 1],
        },
    )
    assert horas_iguales.status_code == 400

    dias_vacios = cliente.post(
        "/api/enterprise/shifts",
        headers=admin_a,
        json={
            "id_organizacion": org_a,
            "nombre": "Sin días",
            "codigo": "INV-2",
            "hora_inicio": "09:00",
            "hora_fin": "17:00",
            "dias_semana": [],
        },
    )
    assert dias_vacios.status_code == 400

    codigo_duplicado = cliente.post(
        "/api/enterprise/shifts",
        headers=admin_a,
        json={
            "id_organizacion": org_a,
            "nombre": "Matutino Duplicado",
            "codigo": "MAT-01",
            "hora_inicio": "07:00",
            "hora_fin": "15:00",
            "dias_semana": [0],
        },
    )
    assert codigo_duplicado.status_code == 409

    # Aislamiento multi-inquilino (Admin B no accede a Org A)
    assert (
        cliente.get(f"/api/enterprise/shifts?id_organizacion={org_a}", headers=admin_b).status_code
        == 403
    )
    assert (
        cliente.patch(
            f"/api/enterprise/shifts/{turno_diurno['id']}",
            headers=admin_b,
            json={"nombre": "Hack"},
        ).status_code
        == 403
    )
    assert (
        cliente.delete(
            f"/api/enterprise/shifts/{turno_diurno['id']}", headers=admin_b
        ).status_code
        == 403
    )
    assert (
        cliente.get(f"/api/enterprise/stats?id_organizacion={org_a}", headers=admin_b).status_code
        == 403
    )

    # RBAC de operador: no modifica catálogo ni consulta stats, pero sí lista y abre kiosco
    assert (
        cliente.post(
            "/api/enterprise/shifts",
            headers=encabezados_op,
            json={
                "id_organizacion": org_a,
                "nombre": "Operador No Puede",
                "codigo": "OP-NO",
                "hora_inicio": "10:00",
                "hora_fin": "18:00",
            },
        ).status_code
        == 403
    )
    assert (
        cliente.delete(
            f"/api/enterprise/shifts/{turno_diurno['id']}", headers=encabezados_op
        ).status_code
        == 403
    )
    assert (
        cliente.get(
            f"/api/enterprise/stats?id_organizacion={org_a}", headers=encabezados_op
        ).status_code
        == 403
    )
    assert (
        cliente.get(
            f"/api/enterprise/shifts?id_organizacion={org_a}", headers=encabezados_op
        ).status_code
        == 200
    )
    iniciar_sesion = cliente.post(
        f"/api/enterprise/shifts/{turno_diurno['id']}/start-session",
        headers=encabezados_op,
        json={"fecha_sesion": "2026-11-16"},
    )
    assert iniciar_sesion.status_code == 200, iniciar_sesion.text
    assert iniciar_sesion.json()["id_turno_laboral"] == turno_diurno["id"]

    # Eliminar turno vinculado a un empleado limpia la FK (ON DELETE SET NULL) sin errores
    empleado = cliente.post(
        "/api/persons",
        headers=admin_a,
        json={
            "id_organizacion": org_a,
            "identificador_externo": "EMP-DEL-1",
            "nombre_completo": "Carlos Ruiz",
            "rol": "employee",
            "consentimiento_biometrico": True,
            "id_turno_laboral": turno_nocturno["id"],
        },
    )
    assert empleado.status_code == 201, empleado.text
    assert empleado.json()["origen_turno"] == "direct"

    assert (
        cliente.delete(
            f"/api/enterprise/shifts/{turno_nocturno['id']}", headers=admin_a
        ).status_code
        == 204
    )
    personas_despues = cliente.get(
        f"/api/persons?id_organizacion={org_a}", headers=admin_a
    ).json()
    emp_despues = next(p for p in personas_despues if p["id"] == empleado.json()["id"])
    assert emp_despues["id_turno_laboral"] is None
    assert emp_despues["id_turno_laboral_efectivo"] is None
    assert emp_despues["origen_turno"] == "none"


def test_puntualidad_retardo_salida_anticipada_y_herencia_departamento(
    cliente_api_sin_autenticar,
) -> None:
    """Valida reglas de puntualidad, retardo, salida temprana y herencia por departamento."""
    cliente, FabricaSesiones, _, _ = cliente_api_sin_autenticar
    configuracion = obtener_configuracion()
    encabezados_sa = _encabezado_autorizacion(
        cliente,
        configuracion.correo_superadmin_inicial,
        configuracion.contrasena_superadmin_inicial,
    )

    id_org, encabezados_admin = _crear_organizacion_empresarial(
        cliente,
        encabezados_sa,
        nombre="Fábrica Central",
        correo_admin="admin@fabrica.com",
        minutos_tolerancia_retardo=15,
    )

    turno = cliente.post(
        "/api/enterprise/shifts",
        headers=encabezados_admin,
        json={
            "id_organizacion": id_org,
            "nombre": "Oficina 9-6",
            "codigo": "OF-0918",
            "hora_inicio": "09:00",
            "hora_fin": "18:00",
            "dias_semana": [0, 1, 2, 3, 4],
            "minutos_tolerancia_retardo": 10,
            "minutos_tolerancia_salida_anticipada": 15,
        },
    ).json()

    departamento = cliente.post(
        "/api/groups",
        headers=encabezados_admin,
        json={
            "id_organizacion": id_org,
            "nombre": "Producción",
            "codigo": "PROD",
            "hora_inicio_horario": "09:00",
            "hora_fin_horario": "18:00",
            "id_turno_laboral_defecto": turno["id"],
        },
    )
    assert departamento.status_code == 201, departamento.text
    assert departamento.json()["nombre_turno_laboral_defecto"] == "Oficina 9-6"

    emp_directo = cliente.post(
        "/api/persons",
        headers=encabezados_admin,
        json={
            "id_organizacion": id_org,
            "identificador_externo": "EMP-D1",
            "nombre_completo": "Ana López",
            "rol": "employee",
            "consentimiento_biometrico": True,
            "id_turno_laboral": turno["id"],
        },
    ).json()
    assert emp_directo["origen_turno"] == "direct"

    emp_grupo = cliente.post(
        "/api/persons",
        headers=encabezados_admin,
        json={
            "id_organizacion": id_org,
            "identificador_externo": "EMP-G2",
            "nombre_completo": "Luis García",
            "rol": "employee",
            "consentimiento_biometrico": True,
            "ids_grupos": [departamento.json()["id"]],
        },
    ).json()
    assert emp_grupo["id_turno_laboral"] is None
    assert emp_grupo["id_turno_laboral_efectivo"] == turno["id"]
    assert emp_grupo["origen_turno"] == "group"

    res_sesion = cliente.post(
        "/api/sessions",
        headers=encabezados_admin,
        json={
            "id_organizacion": id_org,
            "titulo": "Jornada Lunes 2026-11-16",
            "fecha_sesion": "2026-11-16",
        },
    )
    assert res_sesion.status_code == 201, res_sesion.text
    id_sesion = res_sesion.json()["id"]

    with FabricaSesiones() as sesion_bd:
        org_obj = sesion_bd.get(Organizacion, id_org)
        ses_obj = sesion_bd.get(SesionAsistencia, id_sesion)
        p1 = sesion_bd.get(Persona, emp_directo["id"])
        p2 = sesion_bd.get(Persona, emp_grupo["id"])
        assert org_obj and ses_obj and p1 and p2

        # Emp 1: llega dentro de tolerancia (09:08 <= 09:10) pero sale anticipado (17:20 < 17:45)
        r1_entrada = registrar_asistencia_reconocida(
            sesion_bd, org_obj, ses_obj, p1, 0.92, modo_accion="auto", ahora=datetime(2026, 11, 16, 9, 8)
        )
        assert r1_entrada.evento is not None
        assert r1_entrada.evento.tipo_evento == "check_in"
        assert r1_entrada.evento.estado == "on_time"
        assert r1_entrada.minutos_retardo == 0

        r1_salida = registrar_asistencia_reconocida(
            sesion_bd, org_obj, ses_obj, p1, 0.93, modo_accion="auto", ahora=datetime(2026, 11, 16, 17, 20)
        )
        assert r1_salida.evento is not None
        assert r1_salida.evento.tipo_evento == "check_out"
        assert r1_salida.evento.estado == "early_exit"
        assert r1_salida.minutos_salida_anticipada == 40
        assert r1_salida.minutos_trabajados == 492

        # Emp 2 (turno heredado): llega con retardo (09:22) y sale en horario normal (17:50 >= 17:45)
        r2_entrada = registrar_asistencia_reconocida(
            sesion_bd, org_obj, ses_obj, p2, 0.91, modo_accion="auto", ahora=datetime(2026, 11, 16, 9, 22)
        )
        assert r2_entrada.evento is not None
        assert r2_entrada.evento.tipo_evento == "check_in"
        assert r2_entrada.evento.estado == "late"
        assert r2_entrada.minutos_retardo == 22

        r2_salida = registrar_asistencia_reconocida(
            sesion_bd, org_obj, ses_obj, p2, 0.94, modo_accion="auto", ahora=datetime(2026, 11, 16, 17, 50)
        )
        assert r2_salida.evento is not None
        assert r2_salida.evento.tipo_evento == "check_out"
        assert r2_salida.evento.estado == "on_time"
        assert r2_salida.minutos_salida_anticipada == 0
        assert r2_salida.minutos_trabajados == 508


def test_turno_nocturno_cruce_medianoche_salida_dia_siguiente(cliente_api_sin_autenticar) -> None:
    """Valida que un turno 22:00-06:00 cierre al día siguiente sobre la sesión de entrada."""
    cliente, FabricaSesiones, _, _ = cliente_api_sin_autenticar
    configuracion = obtener_configuracion()
    encabezados_sa = _encabezado_autorizacion(
        cliente,
        configuracion.correo_superadmin_inicial,
        configuracion.contrasena_superadmin_inicial,
    )

    id_org, encabezados_admin = _crear_organizacion_empresarial(
        cliente, encabezados_sa, nombre="Logística 24/7", correo_admin="admin@log247.com"
    )

    nocturno = cliente.post(
        "/api/enterprise/shifts",
        headers=encabezados_admin,
        json={
            "id_organizacion": id_org,
            "nombre": "Nocturno",
            "codigo": "NOC-2206",
            "hora_inicio": "22:00",
            "hora_fin": "06:00",
            "dias_semana": [0, 1, 2, 3, 4],
            "minutos_tolerancia_retardo": 15,
            "minutos_tolerancia_salida_anticipada": 10,
        },
    ).json()

    emp_a = cliente.post(
        "/api/persons",
        headers=encabezados_admin,
        json={
            "id_organizacion": id_org,
            "identificador_externo": "NOC-A",
            "nombre_completo": "Elena Torres",
            "consentimiento_biometrico": True,
            "id_turno_laboral": nocturno["id"],
        },
    ).json()
    emp_b = cliente.post(
        "/api/persons",
        headers=encabezados_admin,
        json={
            "id_organizacion": id_org,
            "identificador_externo": "NOC-B",
            "nombre_completo": "Mateo Vega",
            "consentimiento_biometrico": True,
            "id_turno_laboral": nocturno["id"],
        },
    ).json()

    ses_dia1 = cliente.post(
        f"/api/enterprise/shifts/{nocturno['id']}/start-session",
        headers=encabezados_admin,
        json={"fecha_sesion": "2026-11-16"},
    ).json()
    ses_dia2 = cliente.post(
        f"/api/enterprise/shifts/{nocturno['id']}/start-session",
        headers=encabezados_admin,
        json={"fecha_sesion": "2026-11-17"},
    ).json()

    with FabricaSesiones() as sesion_bd:
        org_obj = sesion_bd.get(Organizacion, id_org)
        s1 = sesion_bd.get(SesionAsistencia, ses_dia1["id"])
        s2 = sesion_bd.get(SesionAsistencia, ses_dia2["id"])
        pa = sesion_bd.get(Persona, emp_a["id"])
        pb = sesion_bd.get(Persona, emp_b["id"])
        assert org_obj and s1 and s2 and pa and pb

        ent_a = registrar_asistencia_reconocida(
            sesion_bd, org_obj, s1, pa, 0.90, modo_accion="auto", ahora=datetime(2026, 11, 16, 22, 5)
        )
        assert ent_a.evento and ent_a.evento.estado == "on_time"

        ent_b = registrar_asistencia_reconocida(
            sesion_bd, org_obj, s1, pb, 0.91, modo_accion="auto", ahora=datetime(2026, 11, 16, 22, 0)
        )
        assert ent_b.evento and ent_b.evento.estado == "on_time"

        # Al día siguiente marcan en la sesión del día 2 y el motor cierra la entrada del día 1
        sal_a = registrar_asistencia_reconocida(
            sesion_bd, org_obj, s2, pa, 0.92, modo_accion="auto", ahora=datetime(2026, 11, 17, 5, 30)
        )
        assert sal_a.accion == "recorded"
        assert sal_a.evento is not None
        assert sal_a.evento.id_sesion == s1.id
        assert sal_a.evento.tipo_evento == "check_out"
        assert sal_a.evento.estado == "early_exit"
        assert sal_a.minutos_salida_anticipada == 30
        assert sal_a.minutos_trabajados == 445

        sal_b = registrar_asistencia_reconocida(
            sesion_bd, org_obj, s2, pb, 0.95, modo_accion="auto", ahora=datetime(2026, 11, 17, 5, 55)
        )
        assert sal_b.accion == "recorded"
        assert sal_b.evento is not None
        assert sal_b.evento.id_sesion == s1.id
        assert sal_b.evento.tipo_evento == "check_out"
        assert sal_b.evento.estado == "on_time"
        assert sal_b.minutos_salida_anticipada == 0
        assert sal_b.minutos_trabajados == 475


def test_asignacion_masiva_generacion_sesiones_estadisticas_y_csv(
    cliente_api_sin_autenticar,
) -> None:
    """Valida asignación en lote, generación idempotente, estadísticas y CSV empresarial."""
    cliente, FabricaSesiones, _, _ = cliente_api_sin_autenticar
    configuracion = obtener_configuracion()
    encabezados_sa = _encabezado_autorizacion(
        cliente,
        configuracion.correo_superadmin_inicial,
        configuracion.contrasena_superadmin_inicial,
    )

    id_org, encabezados_admin = _crear_organizacion_empresarial(
        cliente,
        encabezados_sa,
        nombre="Corporativo Norte",
        correo_admin="admin@norte.com",
        minutos_tolerancia_retardo=10,
    )

    matutino = cliente.post(
        "/api/enterprise/shifts",
        headers=encabezados_admin,
        json={
            "id_organizacion": id_org,
            "nombre": "Matutino Corto",
            "codigo": "M1",
            "hora_inicio": "08:00",
            "hora_fin": "16:00",
            "dias_semana": [0, 1, 2],
            "minutos_tolerancia_retardo": 10,
            "minutos_tolerancia_salida_anticipada": 10,
        },
    ).json()

    cliente.post(
        "/api/enterprise/shifts",
        headers=encabezados_admin,
        json={
            "id_organizacion": id_org,
            "nombre": "Vespertino",
            "codigo": "V1",
            "hora_inicio": "14:00",
            "hora_fin": "22:00",
            "dias_semana": [0, 1, 2, 3, 4],
        },
    )

    emp1 = cliente.post(
        "/api/persons",
        headers=encabezados_admin,
        json={
            "id_organizacion": id_org,
            "identificador_externo": "N-01",
            "nombre_completo": "Sofía Salas",
            "consentimiento_biometrico": True,
        },
    ).json()
    emp2 = cliente.post(
        "/api/persons",
        headers=encabezados_admin,
        json={
            "id_organizacion": id_org,
            "identificador_externo": "N-02",
            "nombre_completo": "Jorge Méndez",
            "consentimiento_biometrico": True,
        },
    ).json()
    emp3 = cliente.post(
        "/api/persons",
        headers=encabezados_admin,
        json={
            "id_organizacion": id_org,
            "identificador_externo": "N-03",
            "nombre_completo": "Lucía Pardo",
            "consentimiento_biometrico": True,
        },
    ).json()

    asignar_lote = cliente.post(
        f"/api/enterprise/shifts/{matutino['id']}/assign-persons",
        headers=encabezados_admin,
        json={"ids_personas": [emp1["id"], emp2["id"], emp3["id"]]},
    )
    assert asignar_lote.status_code == 200, asignar_lote.text
    assert asignar_lote.json()["cantidad_actualizados"] == 3

    limpiar_lote = cliente.post(
        f"/api/enterprise/shifts/{matutino['id']}/assign-persons",
        headers=encabezados_admin,
        json={"ids_personas": [emp3["id"]], "limpiar_turno": True},
    )
    assert limpiar_lote.status_code == 200
    assert limpiar_lote.json()["cantidad_actualizados"] == 1

    # Generación idempotente de jornadas para lunes 2026-11-09
    gen1 = cliente.post(
        "/api/enterprise/sessions/generate",
        headers=encabezados_admin,
        json={"id_organizacion": id_org, "fecha_objetivo": "2026-11-09"},
    )
    assert gen1.status_code == 200, gen1.text
    assert gen1.json()["cantidad_creadas"] == 2
    assert gen1.json()["cantidad_existentes"] == 0

    gen2 = cliente.post(
        "/api/enterprise/sessions/generate",
        headers=encabezados_admin,
        json={"id_organizacion": id_org, "fecha_objetivo": "2026-11-09"},
    )
    assert gen2.status_code == 200
    assert gen2.json()["cantidad_creadas"] == 0
    assert gen2.json()["cantidad_existentes"] == 2

    with FabricaSesiones() as sesion_bd:
        _, _, lista_lunes = generar_sesiones_turno_para_fecha(
            sesion_bd,
            id_organizacion=id_org,
            fecha_objetivo=date(2026, 11, 9),
            id_turno_laboral=matutino["id"],
        )
        _, _, lista_martes = generar_sesiones_turno_para_fecha(
            sesion_bd,
            id_organizacion=id_org,
            fecha_objetivo=date(2026, 11, 10),
            id_turno_laboral=matutino["id"],
        )
        generar_sesiones_turno_para_fecha(
            sesion_bd,
            id_organizacion=id_org,
            fecha_objetivo=date(2026, 11, 11),
            id_turno_laboral=matutino["id"],
        )

        org_obj = sesion_bd.get(Organizacion, id_org)
        p1 = sesion_bd.get(Persona, emp1["id"])
        p2 = sesion_bd.get(Persona, emp2["id"])
        assert org_obj and p1 and p2
        ses_lunes = lista_lunes[0]
        ses_martes = lista_martes[0]

        # Emp 1: Lunes puntual (483m), Martes retardo (+25m) y salida anticipada (-30m, 425m), Miércoles falta
        registrar_asistencia_reconocida(
            sesion_bd, org_obj, ses_lunes, p1, 0.90, modo_accion="auto", ahora=datetime(2026, 11, 9, 8, 2)
        )
        registrar_asistencia_reconocida(
            sesion_bd, org_obj, ses_lunes, p1, 0.91, modo_accion="auto", ahora=datetime(2026, 11, 9, 16, 5)
        )
        registrar_asistencia_reconocida(
            sesion_bd, org_obj, ses_martes, p1, 0.92, modo_accion="auto", ahora=datetime(2026, 11, 10, 8, 25)
        )
        registrar_asistencia_reconocida(
            sesion_bd, org_obj, ses_martes, p1, 0.93, modo_accion="auto", ahora=datetime(2026, 11, 10, 15, 30)
        )

        # Emp 2: Lunes solo check-in (sin salida), Martes y Miércoles falta
        registrar_asistencia_reconocida(
            sesion_bd, org_obj, ses_lunes, p2, 0.89, modo_accion="auto", ahora=datetime(2026, 11, 9, 8, 0)
        )

    res_estadisticas = cliente.get(
        f"/api/enterprise/stats?id_organizacion={id_org}&fecha_desde=2026-11-09&fecha_hasta=2026-11-11",
        headers=encabezados_admin,
    )
    assert res_estadisticas.status_code == 200, res_estadisticas.text
    estadisticas = res_estadisticas.json()

    assert estadisticas["resumen"]["total_turnos"] == 2
    assert estadisticas["resumen"]["total_empleados"] == 3
    assert estadisticas["resumen"]["empleados_asignados"] == 2
    assert estadisticas["resumen"]["empleados_sin_turno"] == 1
    assert estadisticas["resumen"]["dias_empleado_programados"] == 6
    assert estadisticas["resumen"]["dias_asistidos"] == 3
    assert estadisticas["resumen"]["dias_falta"] == 3
    assert estadisticas["resumen"]["dias_sin_salida"] == 1

    est_emp1 = next(e for e in estadisticas["por_empleado"] if e["id_persona"] == emp1["id"])
    assert est_emp1["dias_programados"] == 3
    assert est_emp1["dias_asistidos"] == 2
    assert est_emp1["dias_puntuales"] == 1
    assert est_emp1["dias_con_retardo"] == 1
    assert est_emp1["dias_salida_anticipada"] == 1
    assert est_emp1["dias_falta"] == 1
    assert est_emp1["total_minutos_retardo"] == 25
    assert est_emp1["total_minutos_salida_anticipada"] == 30
    assert est_emp1["total_minutos_trabajados"] == 908

    est_emp2 = next(e for e in estadisticas["por_empleado"] if e["id_persona"] == emp2["id"])
    assert est_emp2["dias_sin_salida"] == 1
    assert est_emp2["dias_falta"] == 2

    nombres_turnos_est = [t["nombre_turno"] for t in estadisticas["por_turno"]]
    assert "Matutino Corto" in nombres_turnos_est
    assert "Sin turno asignado" in nombres_turnos_est

    respuesta_csv = cliente.get(
        f"/api/attendance/export.csv?id_organizacion={id_org}", headers=encabezados_admin
    )
    assert respuesta_csv.status_code == 200
    assert respuesta_csv.text.startswith("\ufeff")
    assert (
        "Turno,Minutos Trabajados,Minutos Retardo,Minutos Salida Anticipada" in respuesta_csv.text
    )
    assert "Matutino Corto" in respuesta_csv.text
    assert "425" in respuesta_csv.text


def test_alembic_0004_subida_y_bajada(tmp_path: Path, monkeypatch) -> None:
    """Verifica el ciclo upgrade 0004 -> downgrade 0003 -> upgrade 0004 usando alias `IDENTIA_DATABASE_URL`."""
    archivo_bd = tmp_path / "alembic_0004.db"
    url_bd = f"sqlite:///{archivo_bd.as_posix()}"
    # Conserva la prueba sobre IDENTIA_DATABASE_URL para verificar retrocompatibilidad del alias
    monkeypatch.setenv("IDENTIA_DATABASE_URL", url_bd)
    obtener_configuracion.cache_clear()

    config_alembic = Config(str(DIRECTORIO_BACKEND / "alembic.ini"))
    config_alembic.set_main_option("script_location", str(DIRECTORIO_BACKEND / "migrations"))

    try:
        command.upgrade(config_alembic, "0004_enterprise_work_shifts")
        motor = crear_motor_bd(url_bd)
        inspector = inspect(motor)
        assert "work_shifts" in inspector.get_table_names()
        assert "default_work_shift_id" in {c["name"] for c in inspector.get_columns("groups")}
        assert "work_shift_id" in {c["name"] for c in inspector.get_columns("persons")}
        assert "work_shift_id" in {c["name"] for c in inspector.get_columns("attendance_sessions")}
        cols_ev = {c["name"] for c in inspector.get_columns("attendance_events")}
        assert {"work_shift_id", "worked_minutes", "late_minutes", "early_exit_minutes"}.issubset(
            cols_ev
        )
        with motor.connect() as conexion:
            revision = conexion.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
        motor.dispose()
        assert revision == "0004_enterprise_work_shifts"

        # Downgrade limpio a 0003
        command.downgrade(config_alembic, "0003_academic_periods_and_classrooms")
        motor2 = crear_motor_bd(url_bd)
        inspector2 = inspect(motor2)
        assert "work_shifts" not in inspector2.get_table_names()
        assert "default_work_shift_id" not in {c["name"] for c in inspector2.get_columns("groups")}
        assert "work_shift_id" not in {c["name"] for c in inspector2.get_columns("persons")}
        cols_ev2 = {c["name"] for c in inspector2.get_columns("attendance_events")}
        assert "early_exit_minutes" not in cols_ev2
        motor2.dispose()

        # Re-upgrade a 0004
        command.upgrade(config_alembic, "0004_enterprise_work_shifts")
        motor3 = crear_motor_bd(url_bd)
        with motor3.connect() as conexion:
            revision3 = conexion.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
        motor3.dispose()
        assert revision3 == "0004_enterprise_work_shifts"
    finally:
        obtener_configuracion.cache_clear()


def test_permisos_supervisor_y_sincronizacion_horario_area(cliente_api_sin_autenticar) -> None:
    """Verifica permisos de Supervisor y sincronización de horario base con el turno del área."""
    cliente, _, _, _ = cliente_api_sin_autenticar
    configuracion = obtener_configuracion()
    encabezados_sa = _encabezado_autorizacion(
        cliente,
        configuracion.correo_superadmin_inicial,
        configuracion.contrasena_superadmin_inicial,
    )
    id_org, encabezados_admin = _crear_organizacion_empresarial(
        cliente,
        encabezados_sa,
        nombre="Planta Industrial Alfa",
        correo_admin="alfa.admin@identia.local",
    )

    res_sup = cliente.post(
        "/api/users",
        headers=encabezados_admin,
        json={
            "correo": "alfa.sup@identia.local",
            "nombre_completo": "Carlos Supervisor",
            "contrasena": "Supervisor2026!",
            "rol": "supervisor",
        },
    )
    assert res_sup.status_code == 201, res_sup.text
    encabezados_sup = _encabezado_autorizacion(
        cliente, "alfa.sup@identia.local", "Supervisor2026!"
    )

    turno_a = cliente.post(
        "/api/enterprise/shifts",
        headers=encabezados_admin,
        json={
            "id_organizacion": id_org,
            "nombre": "Turno Matutino 7-15",
            "codigo": "MAT7",
            "hora_inicio": "07:00",
            "hora_fin": "15:00",
            "dias_semana": [0, 1, 2, 3, 4],
        },
    ).json()
    turno_b = cliente.post(
        "/api/enterprise/shifts",
        headers=encabezados_admin,
        json={
            "id_organizacion": id_org,
            "nombre": "Turno Nocturno 22-06",
            "codigo": "NOC22",
            "hora_inicio": "22:00",
            "hora_fin": "06:00",
            "dias_semana": [0, 1, 2, 3, 4],
        },
    ).json()

    # Crear área sin indicar horas debe sincronizarse automáticamente con turno_a
    res_area = cliente.post(
        "/api/groups",
        headers=encabezados_admin,
        json={
            "id_organizacion": id_org,
            "nombre": "Empaque",
            "codigo": "EMP",
            "id_turno_laboral_defecto": turno_a["id"],
        },
    )
    assert res_area.status_code == 201, res_area.text
    area = res_area.json()
    assert area["hora_inicio_horario"] == "07:00"
    assert area["hora_fin_horario"] == "15:00"

    # Al cambiar turno por defecto también actualiza las horas heredadas
    area_actualizada = cliente.patch(
        f"/api/groups/{area['id']}",
        headers=encabezados_admin,
        json={"id_turno_laboral_defecto": turno_b["id"]},
    )
    assert area_actualizada.status_code == 200, area_actualizada.text
    assert area_actualizada.json()["hora_inicio_horario"] == "22:00"
    assert area_actualizada.json()["hora_fin_horario"] == "06:00"

    # Operaciones permitidas al Supervisor
    assert (
        cliente.get(
            f"/api/enterprise/shifts?id_organizacion={id_org}", headers=encabezados_sup
        ).status_code
        == 200
    )
    assert (
        cliente.get(
            f"/api/enterprise/stats?id_organizacion={id_org}", headers=encabezados_sup
        ).status_code
        == 200
    )
    assert (
        cliente.post(
            "/api/enterprise/sessions/generate",
            headers=encabezados_sup,
            json={"id_organizacion": id_org, "fecha_objetivo": "2026-06-15"},
        ).status_code
        == 200
    )
    assert (
        cliente.post(
            f"/api/enterprise/shifts/{turno_a['id']}/start-session",
            headers=encabezados_sup,
            json={"fecha_sesion": "2026-06-15"},
        ).status_code
        == 200
    )
    assert (
        cliente.post(
            "/api/persons",
            headers=encabezados_sup,
            json={
                "id_organizacion": id_org,
                "identificador_externo": "SUP-EMP-01",
                "nombre_completo": "Operario Registrado",
                "rol": "employee",
                "consentimiento_biometrico": True,
                "ids_grupos": [area["id"]],
            },
        ).status_code
        == 201
    )

    # Operaciones restringidas al Supervisor -> HTTP 403
    assert (
        cliente.post(
            "/api/enterprise/shifts",
            headers=encabezados_sup,
            json={
                "id_organizacion": id_org,
                "nombre": "No permitido",
                "codigo": "NP",
                "hora_inicio": "10:00",
                "hora_fin": "18:00",
            },
        ).status_code
        == 403
    )
    assert (
        cliente.delete(
            f"/api/enterprise/shifts/{turno_a['id']}", headers=encabezados_sup
        ).status_code
        == 403
    )
    assert (
        cliente.get(f"/api/users?id_organizacion={id_org}", headers=encabezados_sup).status_code
        == 403
    )
