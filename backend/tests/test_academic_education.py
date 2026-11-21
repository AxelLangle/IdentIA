"""Pruebas de integración del modelo educativo, portal docente y migraciones Alembic 0002/0003/0005."""

from datetime import date
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.config import DIRECTORIO_BACKEND, obtener_configuracion
from app.db import BaseDeclarativa, crear_motor_bd
from app.vision.quality import CuadroRostro
from tests.conftest import (
    codificar_bytes_jpeg,
    crear_imagen_rostro_nitida,
    crear_puntos_pose,
    crear_vector_unitario,
)


def _encabezado_autorizacion(cliente, correo: str, contrasena: str) -> dict[str, str]:
    """Obtiene el encabezado HTTP Bearer autenticando al usuario en `/api/auth/login`."""
    respuesta = cliente.post(
        "/api/auth/login",
        json={"correo": correo, "contrasena": contrasena},
    )
    assert respuesta.status_code == 200, respuesta.text
    return {"Authorization": f"Bearer {respuesta.json()['token_acceso']}"}


def _configurar_escuela_base(cliente) -> dict:
    """Construye una escuela de prueba con director, 2 docentes, carrera, grupo, 2 materias y 2 alumnos."""
    configuracion = obtener_configuracion()
    encabezados_sa = _encabezado_autorizacion(
        cliente,
        configuracion.correo_superadmin_inicial,
        configuracion.contrasena_superadmin_inicial,
    )

    escuela = cliente.post(
        "/api/organizations",
        headers=encabezados_sa,
        json={
            "nombre": "Universidad Tecnológica IdentIA",
            "modo": "education",
            "minutos_tolerancia_retardo": 15,
            "segundos_enfriamiento": 60,
            "usuario_administrador": {
                "nombre_completo": "Director Escolar",
                "correo": "director@uni.edu",
                "contrasena": "DirectorPass123!",
            },
        },
    )
    assert escuela.status_code == 201, escuela.text
    id_organizacion = escuela.json()["id"]
    encabezados_admin = _encabezado_autorizacion(cliente, "director@uni.edu", "DirectorPass123!")

    prof_1 = cliente.post(
        "/api/users",
        headers=encabezados_admin,
        json={
            "correo": "profe.arq@uni.edu",
            "nombre_completo": "Prof. Arquitectura",
            "contrasena": "ProfePass1!",
            "rol": "teacher",
            "id_organizacion": id_organizacion,
        },
    )
    assert prof_1.status_code == 201, prof_1.text
    id_prof_1 = prof_1.json()["id"]

    prof_2 = cliente.post(
        "/api/users",
        headers=encabezados_admin,
        json={
            "correo": "profe.bd@uni.edu",
            "nombre_completo": "Prof. Bases Datos",
            "contrasena": "ProfePass2!",
            "rol": "teacher",
            "id_organizacion": id_organizacion,
        },
    )
    assert prof_2.status_code == 201, prof_2.text
    id_prof_2 = prof_2.json()["id"]

    carrera = cliente.post(
        "/api/academic/careers",
        headers=encabezados_admin,
        json={
            "id_organizacion": id_organizacion,
            "nombre": "Ingeniería en Software",
            "codigo": "ISW",
            "descripcion": "Carrera de desarrollo y arquitectura",
        },
    )
    assert carrera.status_code == 201, carrera.text
    id_carrera = carrera.json()["id"]

    grupo = cliente.post(
        "/api/groups",
        headers=encabezados_admin,
        json={
            "id_organizacion": id_organizacion,
            "nombre": "21026 IS",
            "codigo": "21026-IS",
            "id_carrera": id_carrera,
            "semestre": "6to Cuatrimestre",
            "hora_inicio_horario": "08:00",
            "hora_fin_horario": "14:00",
        },
    )
    assert grupo.status_code == 201, grupo.text
    id_grupo = grupo.json()["id"]

    materia_arq = cliente.post(
        "/api/academic/subjects",
        headers=encabezados_admin,
        json={
            "id_organizacion": id_organizacion,
            "id_carrera": id_carrera,
            "nombre": "Arquitectura de Software",
            "codigo": "ARQ-101",
        },
    )
    assert materia_arq.status_code == 201, materia_arq.text

    materia_bd = cliente.post(
        "/api/academic/subjects",
        headers=encabezados_admin,
        json={
            "id_organizacion": id_organizacion,
            "id_carrera": id_carrera,
            "nombre": "Bases de Datos",
            "codigo": "BDD-102",
        },
    )
    assert materia_bd.status_code == 201, materia_bd.text

    # Horarios en martes (`dia_semana = 1`)
    curso_1 = cliente.post(
        "/api/academic/courses",
        headers=encabezados_admin,
        json={
            "id_organizacion": id_organizacion,
            "id_grupo": id_grupo,
            "id_materia": materia_arq.json()["id"],
            "id_usuario_docente": id_prof_1,
            "periodo_lectivo": "2026-3",
            "horarios": [
                {
                    "dia_semana": 1,
                    "hora_inicio": "10:00",
                    "hora_fin": "11:00",
                    "aula": "Lab 3",
                }
            ],
        },
    )
    assert curso_1.status_code == 201, curso_1.text

    curso_2 = cliente.post(
        "/api/academic/courses",
        headers=encabezados_admin,
        json={
            "id_organizacion": id_organizacion,
            "id_grupo": id_grupo,
            "id_materia": materia_bd.json()["id"],
            "id_usuario_docente": id_prof_2,
            "periodo_lectivo": "2026-3",
            "horarios": [
                {
                    "dia_semana": 1,
                    "hora_inicio": "11:00",
                    "hora_fin": "12:00",
                    "aula": "Aula 12",
                }
            ],
        },
    )
    assert curso_2.status_code == 201, curso_2.text

    alumno_1 = cliente.post(
        "/api/persons",
        headers=encabezados_admin,
        json={
            "id_organizacion": id_organizacion,
            "identificador_externo": "MAT-001",
            "nombre_completo": "Ana López",
            "rol": "student",
            "consentimiento_biometrico": True,
            "ids_grupos": [id_grupo],
        },
    )
    assert alumno_1.status_code == 201, alumno_1.text

    alumno_2 = cliente.post(
        "/api/persons",
        headers=encabezados_admin,
        json={
            "id_organizacion": id_organizacion,
            "identificador_externo": "MAT-002",
            "nombre_completo": "Carlos Ruiz",
            "rol": "student",
            "consentimiento_biometrico": True,
            "ids_grupos": [id_grupo],
        },
    )
    assert alumno_2.status_code == 201, alumno_2.text

    return {
        "id_organizacion": id_organizacion,
        "encabezados_admin": encabezados_admin,
        "encabezados_prof1": _encabezado_autorizacion(cliente, "profe.arq@uni.edu", "ProfePass1!"),
        "encabezados_prof2": _encabezado_autorizacion(cliente, "profe.bd@uni.edu", "ProfePass2!"),
        "id_prof_1": id_prof_1,
        "id_prof_2": id_prof_2,
        "id_carrera": id_carrera,
        "id_grupo": id_grupo,
        "curso_1": curso_1.json(),
        "curso_2": curso_2.json(),
        "alumno_1": alumno_1.json(),
        "alumno_2": alumno_2.json(),
    }


def test_jerarquia_academica_herencia_y_generacion_sesiones(cliente_api_sin_autenticar) -> None:
    """Valida herencia automática de materias por grupo y generación idempotente de sesiones."""
    cliente, _, _, _ = cliente_api_sin_autenticar
    contexto = _configurar_escuela_base(cliente)

    # Los alumnos heredan automáticamente las materias del grupo 21026 IS
    heredadas = cliente.get(
        f"/api/academic/students/{contexto['alumno_1']['id']}/courses",
        headers=contexto["encabezados_admin"],
    )
    assert heredadas.status_code == 200
    codigos = {curso["codigo_materia"] for curso in heredadas.json()}
    assert codigos == {"ARQ-101", "BDD-102"}

    # Generación idempotente para martes 2026-11-17
    martes = "2026-11-17"
    gen_1 = cliente.post(
        "/api/academic/sessions/generate",
        headers=contexto["encabezados_admin"],
        json={"id_organizacion": contexto["id_organizacion"], "fecha_objetivo": martes},
    )
    assert gen_1.status_code == 200, gen_1.text
    assert gen_1.json()["cantidad_creadas"] == 2
    assert gen_1.json()["cantidad_existentes"] == 0
    assert {s["codigo_materia"] for s in gen_1.json()["sesiones"]} == {"ARQ-101", "BDD-102"}

    # Re-ejecutar en la misma fecha no duplica las sesiones ya abiertas
    gen_2 = cliente.post(
        "/api/academic/sessions/generate",
        headers=contexto["encabezados_admin"],
        json={"id_organizacion": contexto["id_organizacion"], "fecha_objetivo": martes},
    )
    assert gen_2.status_code == 200
    assert gen_2.json()["cantidad_creadas"] == 0
    assert gen_2.json()["cantidad_existentes"] == 2


def test_aislamiento_docente_y_pase_lista_kiosco(cliente_api_sin_autenticar) -> None:
    """Valida aislamiento estricto de docentes sobre su agenda, sesiones y pase de lista."""
    cliente, _, motor, _ = cliente_api_sin_autenticar
    contexto = _configurar_escuela_base(cliente)
    martes = "2026-11-17"

    # Enrola a Ana López desde cuenta administrativa
    motor.siguientes_cuadros = [CuadroRostro(100, 80, 180, 200, 0.98, crear_puntos_pose("frontal"))]
    motor.siguiente_vector = crear_vector_unitario(41)
    bytes_img = codificar_bytes_jpeg(
        crear_imagen_rostro_nitida(400, 400, (100, 80, 180, 200), 140, False)
    )
    res_enrolamiento = cliente.post(
        f"/api/persons/{contexto['alumno_1']['id']}/enroll-frame",
        headers=contexto["encabezados_admin"],
        data={"etiqueta_pose": "frontal", "guardar_avatar": "false"},
        files={"imagen": ("f.jpg", bytes_img, "image/jpeg")},
    )
    assert res_enrolamiento.status_code == 200 and res_enrolamiento.json()["aceptado"] is True

    # Prof 1 no puede modificar catálogo ni ver estadísticas administrativas
    assert (
        cliente.post(
            "/api/academic/careers",
            headers=contexto["encabezados_prof1"],
            json={"id_organizacion": contexto["id_organizacion"], "nombre": "Otra", "codigo": "OTR"},
        ).status_code
        == 403
    )
    assert (
        cliente.get("/api/academic/stats", headers=contexto["encabezados_prof1"]).status_code
        == 403
    )

    # Prof 1 únicamente ve ARQ-101 y recibe 403 si consulta las de Prof 2
    cursos_prof1 = cliente.get("/api/academic/courses", headers=contexto["encabezados_prof1"])
    assert cursos_prof1.status_code == 200
    assert [c["codigo_materia"] for c in cursos_prof1.json()] == ["ARQ-101"]
    assert (
        cliente.get(
            f"/api/academic/courses?id_usuario_docente={contexto['id_prof_2']}",
            headers=contexto["encabezados_prof1"],
        ).status_code
        == 403
    )

    # Agenda diaria de Prof 1 el martes a las 10:15 muestra ARQ-101 en curso
    agenda = cliente.get(
        f"/api/academic/teacher/agenda?fecha_objetivo={martes}&hora_actual=10:15",
        headers=contexto["encabezados_prof1"],
    )
    assert agenda.status_code == 200, agenda.text
    datos_agenda = agenda.json()
    assert datos_agenda["bloque_actual"] is not None
    assert datos_agenda["bloque_actual"]["codigo_materia"] == "ARQ-101"
    assert datos_agenda["bloque_actual"]["estado_bloque"] == "in_progress"

    # Inicia sesión de ARQ-101 en 1 clic
    inicio_p1 = cliente.post(
        f"/api/academic/courses/{contexto['curso_1']['id']}/start-session",
        headers=contexto["encabezados_prof1"],
        json={
            "id_horario": contexto["curso_1"]["horarios"][0]["id"],
            "fecha_sesion": martes,
        },
    )
    assert inicio_p1.status_code == 200, inicio_p1.text
    id_sesion_p1 = inicio_p1.json()["id"]

    # Prof 2 inicia su sesión; Prof 1 recibe 403 al intentar interactuar con ella
    inicio_p2 = cliente.post(
        f"/api/academic/courses/{contexto['curso_2']['id']}/start-session",
        headers=contexto["encabezados_prof2"],
        json={
            "id_horario": contexto["curso_2"]["horarios"][0]["id"],
            "fecha_sesion": martes,
        },
    )
    assert inicio_p2.status_code == 200, inicio_p2.text
    id_sesion_p2 = inicio_p2.json()["id"]

    assert (
        cliente.post(
            f"/api/academic/courses/{contexto['curso_2']['id']}/start-session",
            headers=contexto["encabezados_prof1"],
            json={"fecha_sesion": martes},
        ).status_code
        == 403
    )
    assert (
        cliente.post(
            f"/api/sessions/{id_sesion_p2}/close", headers=contexto["encabezados_prof1"]
        ).status_code
        == 403
    )
    assert (
        cliente.get(
            f"/api/attendance/events?id_sesion={id_sesion_p2}",
            headers=contexto["encabezados_prof1"],
        ).status_code
        == 403
    )
    assert (
        cliente.get(
            f"/api/attendance/export.csv?id_sesion={id_sesion_p2}",
            headers=contexto["encabezados_prof1"],
        ).status_code
        == 403
    )
    assert (
        cliente.post(
            "/api/attendance/manual",
            headers=contexto["encabezados_prof1"],
            json={
                "id_sesion": id_sesion_p2,
                "id_persona": contexto["alumno_1"]["id"],
                "tipo_evento": "present",
            },
        ).status_code
        == 403
    )

    # Prof 1 toma asistencia biométrica a Ana López dentro de su propia sesión
    motor.siguientes_cuadros = [CuadroRostro(100, 80, 180, 200, 0.98, crear_puntos_pose("frontal"))]
    motor.siguiente_vector = crear_vector_unitario(41)
    reconocimiento = cliente.post(
        "/api/attendance/recognize-frame",
        headers=contexto["encabezados_prof1"],
        data={
            "id_organizacion": str(contexto["id_organizacion"]),
            "id_sesion": str(id_sesion_p1),
            "modo_accion": "present",
        },
        files={"imagen": ("kiosk.jpg", bytes_img, "image/jpeg")},
    )
    assert reconocimiento.status_code == 200, reconocimiento.text
    assert reconocimiento.json()["estado_coincidencia"] == "matched"
    assert reconocimiento.json()["accion_asistencia"] == "recorded"

    # Y Prof 1 no puede enviar frames al kiosco usando la sesión de Prof 2
    rec_prohibido = cliente.post(
        "/api/attendance/recognize-frame",
        headers=contexto["encabezados_prof1"],
        data={
            "id_organizacion": str(contexto["id_organizacion"]),
            "id_sesion": str(id_sesion_p2),
            "modo_accion": "present",
        },
        files={"imagen": ("kiosk.jpg", bytes_img, "image/jpeg")},
    )
    assert rec_prohibido.status_code == 403

    # El listado de sesiones para Prof 1 únicamente incluye la suya
    lista_sesiones_p1 = cliente.get("/api/sessions", headers=contexto["encabezados_prof1"])
    assert lista_sesiones_p1.status_code == 200
    assert [s["id"] for s in lista_sesiones_p1.json()] == [id_sesion_p1]


def test_estadisticas_consolidadas_por_materia_y_grupo(cliente_api_sin_autenticar) -> None:
    """Verifica el cálculo consolidado por asignatura, grupo y desglose por estudiante."""
    cliente, _, _, _ = cliente_api_sin_autenticar
    contexto = _configurar_escuela_base(cliente)
    martes = date(2026, 11, 17).isoformat()

    generadas = cliente.post(
        "/api/academic/sessions/generate",
        headers=contexto["encabezados_admin"],
        json={"id_organizacion": contexto["id_organizacion"], "fecha_objetivo": martes},
    )
    assert generadas.status_code == 200
    sesiones_por_codigo = {s["codigo_materia"]: s["id"] for s in generadas.json()["sesiones"]}
    sesion_arq = sesiones_por_codigo["ARQ-101"]
    sesion_bd = sesiones_por_codigo["BDD-102"]

    # ARQ-101: asiste 1 de 2 alumnos (50%)
    reg_1 = cliente.post(
        "/api/attendance/manual",
        headers=contexto["encabezados_admin"],
        json={
            "id_sesion": sesion_arq,
            "id_persona": contexto["alumno_1"]["id"],
            "tipo_evento": "present",
            "estado": "on_time",
        },
    )
    assert reg_1.status_code == 201

    # BDD-102: asisten 2 de 2 alumnos (100%)
    for id_alumno in (contexto["alumno_1"]["id"], contexto["alumno_2"]["id"]):
        reg = cliente.post(
            "/api/attendance/manual",
            headers=contexto["encabezados_admin"],
            json={
                "id_sesion": sesion_bd,
                "id_persona": id_alumno,
                "tipo_evento": "present",
                "estado": "on_time",
            },
        )
        assert reg.status_code == 201

    res_estadisticas = cliente.get(
        "/api/academic/stats", headers=contexto["encabezados_admin"]
    )
    assert res_estadisticas.status_code == 200, res_estadisticas.text
    estadisticas = res_estadisticas.json()

    assert estadisticas["resumen"]["total_carreras"] == 1
    assert estadisticas["resumen"]["total_grupos"] == 2  # Incluye GEN-01 inicial + 21026 IS
    assert estadisticas["resumen"]["total_materias"] == 2
    assert estadisticas["resumen"]["total_cursos"] == 2
    assert estadisticas["resumen"]["total_sesiones"] == 2
    assert estadisticas["resumen"]["tasa_asistencia_general"] == 75.0

    por_materia = {item["codigo_materia"]: item for item in estadisticas["por_materia"]}
    assert por_materia["ARQ-101"]["cantidad_asistencias"] == 1
    assert por_materia["ARQ-101"]["cantidad_faltas"] == 1
    assert por_materia["ARQ-101"]["tasa_asistencia"] == 50.0
    assert por_materia["BDD-102"]["cantidad_asistencias"] == 2
    assert por_materia["BDD-102"]["cantidad_faltas"] == 0
    assert por_materia["BDD-102"]["tasa_asistencia"] == 100.0

    res_filtradas = cliente.get(
        f"/api/academic/stats?id_carrera={contexto['id_carrera']}",
        headers=contexto["encabezados_admin"],
    )
    assert res_filtradas.status_code == 200, res_filtradas.text
    filtradas = res_filtradas.json()
    assert filtradas["resumen"]["total_grupos"] == 1
    assert len(filtradas["por_grupo"]) == 1
    estadistica_grupo = filtradas["por_grupo"][0]
    assert estadistica_grupo["nombre_grupo"] == "21026 IS"
    assert estadistica_grupo["cantidad_materias"] == 2
    assert estadistica_grupo["total_esperados"] == 4
    assert estadistica_grupo["total_asistencias"] == 3
    assert estadistica_grupo["total_faltas"] == 1
    assert estadistica_grupo["tasa_asistencia_general"] == 75.0

    desglose = {
        al["identificador_externo"]: al for al in estadistica_grupo["desglose_estudiantes"]
    }
    assert desglose["MAT-001"]["tasa_asistencia"] == 100.0
    assert desglose["MAT-002"]["tasa_asistencia"] == 50.0


def test_alembic_0002_recupera_create_all_parcial(tmp_path: Path, monkeypatch) -> None:
    """Verifica que `alembic upgrade head` completa columnas aunque `create_all` haya corrido antes."""
    archivo_bd = tmp_path / "alembic_parcial.db"
    url_bd = f"sqlite:///{archivo_bd.as_posix()}"
    monkeypatch.setenv("IDENTIA_URL_BASE_DATOS", url_bd)
    obtener_configuracion.cache_clear()

    config_alembic = Config(str(DIRECTORIO_BACKEND / "alembic.ini"))
    config_alembic.set_main_option("script_location", str(DIRECTORIO_BACKEND / "migrations"))

    try:
        # Simula BD en revisión 0001 y posterior arranque automático con create_all
        command.upgrade(config_alembic, "0001_initial_rbac_and_biometrics")
        motor = crear_motor_bd(url_bd)
        BaseDeclarativa.metadata.create_all(bind=motor)
        motor.dispose()

        # Ahora upgrade head debe completar índices/FKs/columnas idempotente sin fallar
        command.upgrade(config_alembic, "head")

        motor_verificacion = crear_motor_bd(url_bd)
        inspector = inspect(motor_verificacion)
        nombres_tablas = set(inspector.get_table_names())
        cols_grupos = {c["name"] for c in inspector.get_columns("groups")}
        cols_personas = {c["name"] for c in inspector.get_columns("persons")}
        cols_sesiones = {c["name"] for c in inspector.get_columns("attendance_sessions")}
        with motor_verificacion.connect() as conexion:
            revision_actual = conexion.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar_one()
        motor_verificacion.dispose()

        assert revision_actual == "0005_group_period_type"
        assert "work_shifts" in nombres_tablas
        assert {
            "career_id",
            "semester",
            "period_type",
            "default_classroom",
            "default_work_shift_id",
        }.issubset(cols_grupos)
        assert "work_shift_id" in cols_personas
        assert {"course_assignment_id", "schedule_id", "work_shift_id"}.issubset(cols_sesiones)
    finally:
        obtener_configuracion.cache_clear()


def test_periodos_academicos_aula_fija_y_horarios_multidia(cliente_api_sin_autenticar) -> None:
    """Valida herencia de periodos (institución/carrera), aula fija y varios días por curso."""
    cliente, _, _, _ = cliente_api_sin_autenticar
    configuracion = obtener_configuracion()
    encabezados_sa = _encabezado_autorizacion(
        cliente,
        configuracion.correo_superadmin_inicial,
        configuracion.contrasena_superadmin_inicial,
    )

    escuela = cliente.post(
        "/api/organizations",
        headers=encabezados_sa,
        json={
            "nombre": "Politécnica IdentIA",
            "modo": "education",
            "tipo_periodo_academico": "cuatrimestral",
            "usuario_administrador": {
                "nombre_completo": "Admin Poli",
                "correo": "admin.poli@uni.edu",
                "contrasena": "PoliPass123!",
            },
        },
    )
    assert escuela.status_code == 201, escuela.text
    assert escuela.json()["tipo_periodo_academico"] == "cuatrimestral"
    id_organizacion = escuela.json()["id"]
    encabezados_admin = _encabezado_autorizacion(cliente, "admin.poli@uni.edu", "PoliPass123!")

    # Carrera A hereda cuatrimestral; Carrera B sobrescribe a semestral
    carrera_a = cliente.post(
        "/api/academic/careers",
        headers=encabezados_admin,
        json={
            "id_organizacion": id_organizacion,
            "nombre": "Ingeniería en Software",
            "codigo": "ISW",
        },
    )
    assert carrera_a.status_code == 201, carrera_a.text
    assert carrera_a.json()["tipo_periodo"] is None
    assert carrera_a.json()["tipo_periodo_efectivo"] == "cuatrimestral"

    carrera_b = cliente.post(
        "/api/academic/careers",
        headers=encabezados_admin,
        json={
            "id_organizacion": id_organizacion,
            "nombre": "Derecho",
            "codigo": "DER",
            "tipo_periodo": "semestral",
        },
    )
    assert carrera_b.status_code == 201, carrera_b.text
    assert carrera_b.json()["tipo_periodo"] == "semestral"
    assert carrera_b.json()["tipo_periodo_efectivo"] == "semestral"

    grupo = cliente.post(
        "/api/groups",
        headers=encabezados_admin,
        json={
            "id_organizacion": id_organizacion,
            "nombre": "21026 IS",
            "codigo": "21026-IS",
            "id_carrera": carrera_a.json()["id"],
            "semestre": "6to Cuatrimestre",
            "aula_defecto": "Aula 33",
        },
    )
    assert grupo.status_code == 201, grupo.text
    assert grupo.json()["aula_defecto"] == "Aula 33"
    assert grupo.json()["tipo_periodo"] == "cuatrimestral"

    materia = cliente.post(
        "/api/academic/subjects",
        headers=encabezados_admin,
        json={
            "id_organizacion": id_organizacion,
            "id_carrera": carrera_a.json()["id"],
            "nombre": "Computación",
            "codigo": "CMP-301",
        },
    )
    assert materia.status_code == 201, materia.text

    # Múltiples bloques horarios en una asignación: Lunes/Miércoles en Aula 33, Viernes en Aula 12
    curso = cliente.post(
        "/api/academic/courses",
        headers=encabezados_admin,
        json={
            "id_organizacion": id_organizacion,
            "id_grupo": grupo.json()["id"],
            "id_materia": materia.json()["id"],
            "periodo_lectivo": "2026-3",
            "horarios": [
                {
                    "dia_semana": 0,
                    "hora_inicio": "08:00",
                    "hora_fin": "09:00",
                    "aula": "Aula 33",
                },
                {
                    "dia_semana": 2,
                    "hora_inicio": "08:00",
                    "hora_fin": "09:00",
                    "aula": "Aula 33",
                },
                {
                    "dia_semana": 4,
                    "hora_inicio": "08:00",
                    "hora_fin": "09:00",
                    "aula": "Aula 12",
                },
            ],
        },
    )
    assert curso.status_code == 201, curso.text
    datos_curso = curso.json()
    assert datos_curso["aula_defecto_grupo"] == "Aula 33"
    assert datos_curso["semestre"] == "6to Cuatrimestre"
    assert datos_curso["tipo_periodo"] == "cuatrimestral"
    assert len(datos_curso["horarios"]) == 3
    aulas_por_dia = {h["dia_semana"]: h["aula"] for h in datos_curso["horarios"]}
    assert aulas_por_dia == {0: "Aula 33", 2: "Aula 33", 4: "Aula 12"}

    estadisticas = cliente.get("/api/academic/stats", headers=encabezados_admin)
    assert estadisticas.status_code == 200, estadisticas.text
    datos_est = estadisticas.json()
    assert datos_est["por_materia"][0]["id_carrera"] == carrera_a.json()["id"]
    assert datos_est["por_materia"][0]["semestre"] == "6to Cuatrimestre"
    assert datos_est["por_materia"][0]["tipo_periodo"] == "cuatrimestral"
    coincidencia_grupo = next(
        item for item in datos_est["por_grupo"] if item["id_grupo"] == grupo.json()["id"]
    )
    assert coincidencia_grupo["tipo_periodo"] == "cuatrimestral"


def test_cambio_tipo_periodo_exige_clave_admin_y_migracion_0005(
    cliente_api_sin_autenticar, tmp_path: Path, monkeypatch
) -> None:
    """Valida periodo propio por grupo, protección con contraseña admin y ciclo Alembic 0005."""
    cliente, _, _, _ = cliente_api_sin_autenticar
    configuracion = obtener_configuracion()
    encabezados_sa = _encabezado_autorizacion(
        cliente,
        configuracion.correo_superadmin_inicial,
        configuracion.contrasena_superadmin_inicial,
    )

    escuela = cliente.post(
        "/api/organizations",
        headers=encabezados_sa,
        json={
            "nombre": "Instituto Norte",
            "modo": "education",
            "tipo_periodo_academico": "semestral",
            "usuario_administrador": {
                "nombre_completo": "Admin Norte",
                "correo": "admin@norte.edu",
                "contrasena": "NorteAdmin99!",
            },
        },
    ).json()
    id_organizacion = escuela["id"]
    encabezados_admin = _encabezado_autorizacion(cliente, "admin@norte.edu", "NorteAdmin99!")

    carrera = cliente.post(
        "/api/academic/careers",
        headers=encabezados_admin,
        json={"id_organizacion": id_organizacion, "nombre": "Sistemas", "codigo": "SIS"},
    ).json()

    grupo = cliente.post(
        "/api/groups",
        headers=encabezados_admin,
        json={
            "id_organizacion": id_organizacion,
            "nombre": "301 SIS",
            "codigo": "301-SIS",
            "id_carrera": carrera["id"],
            "semestre": "3",
            "aula_defecto": "B-12",
        },
    ).json()
    assert grupo["tipo_periodo"] == "semestral"
    assert grupo["tipo_periodo_personalizado"] is None

    # Editar aula o número sin cambiar tipo_periodo NO solicita contraseña
    editar_sin_periodo = cliente.patch(
        f"/api/groups/{grupo['id']}",
        headers=encabezados_admin,
        json={"semestre": "6", "aula_defecto": "B-14"},
    )
    assert editar_sin_periodo.status_code == 200, editar_sin_periodo.text
    assert editar_sin_periodo.json()["aula_defecto"] == "B-14"

    # Cambiar tipo de periodo sin contraseña -> 400
    grupo_sin_clave = cliente.patch(
        f"/api/groups/{grupo['id']}",
        headers=encabezados_admin,
        json={"tipo_periodo": "cuatrimestral"},
    )
    assert grupo_sin_clave.status_code == 400

    # Contraseña incorrecta -> 403
    grupo_clave_mala = cliente.patch(
        f"/api/groups/{grupo['id']}",
        headers=encabezados_admin,
        json={"tipo_periodo": "cuatrimestral", "secreto_autorizacion": "WrongPass!"},
    )
    assert grupo_clave_mala.status_code == 403

    # Contraseña válida de admin -> 200 y prioridad grupo > carrera > institución
    grupo_ok = cliente.patch(
        f"/api/groups/{grupo['id']}",
        headers=encabezados_admin,
        json={"tipo_periodo": "cuatrimestral", "secreto_autorizacion": "NorteAdmin99!"},
    )
    assert grupo_ok.status_code == 200, grupo_ok.text
    assert grupo_ok.json()["tipo_periodo_personalizado"] == "cuatrimestral"
    assert grupo_ok.json()["tipo_periodo"] == "cuatrimestral"

    # Carrera y organización también exigen clave admin al modificar su periodo
    assert (
        cliente.patch(
            f"/api/academic/careers/{carrera['id']}",
            headers=encabezados_admin,
            json={"tipo_periodo": "trimestral"},
        ).status_code
        == 400
    )
    assert (
        cliente.patch(
            f"/api/academic/careers/{carrera['id']}",
            headers=encabezados_admin,
            json={"tipo_periodo": "trimestral", "secreto_autorizacion": "WrongPass"},
        ).status_code
        == 403
    )
    carrera_ok = cliente.patch(
        f"/api/academic/careers/{carrera['id']}",
        headers=encabezados_admin,
        json={"tipo_periodo": "trimestral", "secreto_autorizacion": "NorteAdmin99!"},
    )
    assert carrera_ok.status_code == 200
    assert carrera_ok.json()["tipo_periodo_efectivo"] == "trimestral"

    assert (
        cliente.patch(
            f"/api/organizations/{id_organizacion}",
            headers=encabezados_admin,
            json={"tipo_periodo_academico": "bimestral"},
        ).status_code
        == 400
    )
    org_ok = cliente.patch(
        f"/api/organizations/{id_organizacion}",
        headers=encabezados_admin,
        json={"tipo_periodo_academico": "bimestral", "secreto_autorizacion": "NorteAdmin99!"},
    )
    assert org_ok.status_code == 200
    assert org_ok.json()["tipo_periodo_academico"] == "bimestral"

    # Las estadísticas reflejan la sobrescritura propia del grupo ("cuatrimestral")
    estadisticas = cliente.get("/api/academic/stats", headers=encabezados_admin).json()
    estadistica_grupo = next(
        g for g in estadisticas["por_grupo"] if g["id_grupo"] == grupo["id"]
    )
    assert estadistica_grupo["tipo_periodo"] == "cuatrimestral"

    # Auditoría registró los tres cambios de periodo
    registros = cliente.get(
        f"/api/security/audit-logs?id_organizacion={id_organizacion}",
        headers=encabezados_admin,
    ).json()
    acciones = {entrada["accion"] for entrada in registros}
    assert {
        "change_group_period_type",
        "change_career_period_type",
        "change_org_period_type",
    }.issubset(acciones)

    # Ciclo Alembic 0005 -> downgrade 0004 -> upgrade head
    archivo_bd = tmp_path / "alembic_0005.db"
    url_bd = f"sqlite:///{archivo_bd.as_posix()}"
    monkeypatch.setenv("IDENTIA_URL_BASE_DATOS", url_bd)
    obtener_configuracion.cache_clear()
    config_alembic = Config(str(DIRECTORIO_BACKEND / "alembic.ini"))
    config_alembic.set_main_option("script_location", str(DIRECTORIO_BACKEND / "migrations"))
    try:
        command.upgrade(config_alembic, "head")
        command.downgrade(config_alembic, "0004_enterprise_work_shifts")
        motor_bajada = crear_motor_bd(url_bd)
        cols_bajada = {c["name"] for c in inspect(motor_bajada).get_columns("groups")}
        motor_bajada.dispose()
        assert "period_type" not in cols_bajada

        command.upgrade(config_alembic, "head")
        motor_subida = crear_motor_bd(url_bd)
        cols_subida = {c["name"] for c in inspect(motor_subida).get_columns("groups")}
        motor_subida.dispose()
        assert "period_type" in cols_subida
    finally:
        obtener_configuracion.cache_clear()
