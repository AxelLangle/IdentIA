"""Punto de entrada principal de la aplicación FastAPI de IdentIA (v1.1.0).

Configura el ciclo de vida (`lifespan`) para crear tablas si no existen
migraciones Alembic, sembrar datos semilla iniciales, cargar los modelos ONNX
(YuNet + SFace), registrar todos los enrutadores HTTP `/api/*` y servir
opcionalmente el frontend React compilado (SPA) en despliegues integrados
como los ejecutables de escritorio.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from app.config import obtener_configuracion
from app.db import (
    BaseDeclarativa,
    FabricaSesionesLocal,
    motor_bd as motor_por_defecto,
    obtener_bd,
)
from app.models import Grupo, Organizacion, Persona, Usuario, VectorFacial
from app.routers import (
    academic,
    attendance,
    auth,
    enterprise,
    organizations,
    persons,
    security,
)
from app.schemas import RespuestaSalud
from app.security import generar_hash_secreto
from app.vision.engine import MotorBiometrico
from app.vision.models_loader import asegurar_modelos


def sembrar_datos_iniciales(sesion_bd: Session) -> None:
    """Crea Superadmin, organización demo y administrador inicial si aún no existen."""
    configuracion = obtener_configuracion()

    superadmin = sesion_bd.scalars(select(Usuario).where(Usuario.rol == "superadmin")).first()
    if superadmin is None:
        superadmin = Usuario(
            correo=configuracion.correo_superadmin_inicial.strip().lower(),
            nombre_completo=configuracion.nombre_superadmin_inicial,
            hash_contrasena=generar_hash_secreto(configuracion.contrasena_superadmin_inicial),
            rol="superadmin",
            id_organizacion=None,
        )
        sesion_bd.add(superadmin)
        sesion_bd.flush()

    organizaciones_existentes = sesion_bd.scalar(select(func.count(Organizacion.id))) or 0
    if organizaciones_existentes == 0:
        organizacion_demo = Organizacion(
            nombre="IdentIA Demo — Empresa",
            modo="enterprise",
            minutos_tolerancia_retardo=15,
            segundos_enfriamiento=60,
            guardar_avatar_por_defecto=True,
        )
        sesion_bd.add(organizacion_demo)
        sesion_bd.flush()

        sesion_bd.add(
            Grupo(
                id_organizacion=organizacion_demo.id,
                nombre="General",
                codigo="GEN-01",
                hora_inicio_horario="09:00",
                hora_fin_horario="18:00",
            )
        )

        correo_admin_org = configuracion.correo_admin_org_inicial.strip().lower()
        admin_existente = sesion_bd.scalars(
            select(Usuario).where(Usuario.correo == correo_admin_org)
        ).first()
        if admin_existente is None:
            sesion_bd.add(
                Usuario(
                    correo=correo_admin_org,
                    nombre_completo="Administrador Empresa Demo",
                    hash_contrasena=generar_hash_secreto(
                        configuracion.contrasena_admin_org_inicial
                    ),
                    rol="org_admin",
                    id_organizacion=organizacion_demo.id,
                    id_usuario_creador=superadmin.id,
                )
            )

    sesion_bd.commit()


def _registrar_servicio_frontend_spa(aplicacion: FastAPI, directorio_frontend: Path) -> None:
    """Configura el servidor de archivos estáticos del frontend React compilado (SPA).

    Se registra después de todos los enrutadores `/api/*` para que las peticiones
    de la API nunca sean interceptadas por el fallback de rutas de React.
    """
    raiz_resuelta = directorio_frontend.resolve()
    archivo_indice = raiz_resuelta / "index.html"
    if not archivo_indice.is_file():
        return

    carpeta_recursos = raiz_resuelta / "assets"
    if carpeta_recursos.is_dir():
        aplicacion.mount(
            "/assets",
            StaticFiles(directory=str(carpeta_recursos)),
            name="recursos_frontend",
        )

    @aplicacion.get("/{ruta_frontend:path}", include_in_schema=False)
    def servir_aplicacion_spa(ruta_frontend: str) -> FileResponse:
        # Cualquier ruta bajo /api que no haya coincidido con un router debe devolver 404 JSON
        if ruta_frontend == "api" or ruta_frontend.startswith("api/"):
            raise HTTPException(status_code=404, detail="Recurso API no encontrado.")

        if ruta_frontend:
            archivo_candidato = (raiz_resuelta / ruta_frontend).resolve()
            # Protege contra path traversal asegurando que el archivo esté dentro de frontend_dist
            if (
                archivo_candidato.is_relative_to(raiz_resuelta)
                and archivo_candidato.is_file()
            ):
                return FileResponse(archivo_candidato)

        return FileResponse(archivo_indice)


def crear_aplicacion(
    motor_biometrico: MotorBiometrico | None = None,
    inicializar_modelos: bool = True,
    motor_bd_personalizado=None,
    fabrica_sesiones=None,
) -> FastAPI:
    """Construye y configura la instancia FastAPI lista para ejecución o pruebas."""
    configuracion = obtener_configuracion()
    motor_bd_activo = motor_bd_personalizado or motor_por_defecto
    fabrica_sesiones_activa = fabrica_sesiones or FabricaSesionesLocal

    @asynccontextmanager
    async def ciclo_de_vida(instancia_app: FastAPI):
        # Si la BD no usa Alembic todavía, crea el esquema completo desde los modelos ORM
        if not inspect(motor_bd_activo).has_table("alembic_version"):
            BaseDeclarativa.metadata.create_all(bind=motor_bd_activo)
        with fabrica_sesiones_activa() as sesion_bd:
            sembrar_datos_iniciales(sesion_bd)

        if motor_biometrico is not None:
            instancia_app.state.motor_biometrico = motor_biometrico
        elif inicializar_modelos:
            ruta_yunet, ruta_sface = asegurar_modelos(configuracion.directorio_modelos)
            instancia_app.state.motor_biometrico = MotorBiometrico(
                ruta_yunet=ruta_yunet,
                ruta_sface=ruta_sface,
                umbral_deteccion=configuracion.umbral_deteccion_yunet,
                umbral_supresion=configuracion.umbral_supresion_yunet,
            )
        else:
            instancia_app.state.motor_biometrico = None
        yield

    aplicacion = FastAPI(
        title=configuracion.nombre_aplicacion,
        version="1.1.0",
        description="Motor biométrico y plataforma de asistencia multi-organización IdentIA.",
        lifespan=ciclo_de_vida,
    )

    aplicacion.add_middleware(
        CORSMiddleware,
        allow_origins=configuracion.origenes_cors,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Registro de todos los enrutadores REST bajo /api
    aplicacion.include_router(auth.enrutador)
    aplicacion.include_router(security.enrutador)
    aplicacion.include_router(organizations.enrutador)
    aplicacion.include_router(persons.enrutador)
    aplicacion.include_router(attendance.enrutador)
    aplicacion.include_router(academic.enrutador)
    aplicacion.include_router(enterprise.enrutador)

    @aplicacion.get("/api/health", response_model=RespuestaSalud, tags=["sistema"])
    def verificar_salud(sesion_bd: Session = Depends(obtener_bd)) -> RespuestaSalud:
        """Devuelve el estado operativo del servidor, carga de modelos y conteos globales."""
        motor_listo = getattr(aplicacion.state, "motor_biometrico", None) is not None
        cantidad_organizaciones = sesion_bd.scalar(select(func.count(Organizacion.id))) or 0
        cantidad_personas = sesion_bd.scalar(select(func.count(Persona.id))) or 0
        cantidad_vectores = sesion_bd.scalar(select(func.count(VectorFacial.id))) or 0
        return RespuestaSalud(
            estado="ok",
            modelos_cargados=motor_listo,
            nombre_modelo=configuracion.nombre_modelo,
            version_modelo=configuracion.version_modelo,
            cantidad_organizaciones=cantidad_organizaciones,
            cantidad_personas=cantidad_personas,
            cantidad_vectores=cantidad_vectores,
        )

    # Sirve el frontend compilado solo si la carpeta está configurada y contiene index.html
    if (
        configuracion.directorio_frontend_compilado is not None
        and configuracion.directorio_frontend_compilado.is_dir()
    ):
        _registrar_servicio_frontend_spa(
            aplicacion,
            configuracion.directorio_frontend_compilado,
        )

    return aplicacion


app = crear_aplicacion()
