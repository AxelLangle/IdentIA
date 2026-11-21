"""Entorno de ejecución de migraciones Alembic para IdentIA.

Conecta Alembic con los metadatos declarativos de SQLAlchemy (`BaseDeclarativa.metadata`)
y resuelve dinámicamente la URL de la base de datos desde la configuración central,
habilitando modo por lotes (`render_as_batch=True`) cuando el motor es SQLite.
"""

from logging.config import fileConfig
from pathlib import Path
import sys

from alembic import context
from sqlalchemy import engine_from_config, pool

DIRECTORIO_BACKEND = Path(__file__).resolve().parent.parent
if str(DIRECTORIO_BACKEND) not in sys.path:
    sys.path.insert(0, str(DIRECTORIO_BACKEND))

from app.config import obtener_configuracion  # noqa: E402
from app.db import BaseDeclarativa  # noqa: E402
import app.models  # noqa: E402, F401  (Registra todos los modelos ORM en los metadatos)

configuracion_alembic = context.config

if configuracion_alembic.config_file_name is not None:
    fileConfig(configuracion_alembic.config_file_name)

metadatos_objetivo = BaseDeclarativa.metadata


def obtener_url_base_datos() -> str:
    """Obtiene la URL vigente limpiando caché previo para respetar variables de entorno nuevas."""
    obtener_configuracion.cache_clear()
    return obtener_configuracion().url_base_datos_resuelta


def ejecutar_migraciones_sin_conexion() -> None:
    """Genera el script SQL de migración en modo offline sin abrir conexión activa."""
    url_bd = obtener_url_base_datos()
    context.configure(
        url=url_bd,
        target_metadata=metadatos_objetivo,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=url_bd.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def ejecutar_migraciones_en_linea() -> None:
    """Ejecuta las migraciones directamente contra el motor conectado a la base de datos."""
    url_bd = obtener_url_base_datos()
    seccion_config = configuracion_alembic.get_section(configuracion_alembic.config_ini_section, {})
    seccion_config["sqlalchemy.url"] = url_bd

    motor_conectable = engine_from_config(
        seccion_config,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with motor_conectable.connect() as conexion:
        context.configure(
            connection=conexion,
            target_metadata=metadatos_objetivo,
            render_as_batch=url_bd.startswith("sqlite"),
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    ejecutar_migraciones_sin_conexion()
else:
    ejecutar_migraciones_en_linea()
