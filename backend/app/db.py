"""Módulo de conexión y gestión de sesiones de base de datos SQLAlchemy 2.0.

Configura el motor SQLite con activación automática de llaves foráneas (`PRAGMA foreign_keys=ON`)
y modo WAL (`PRAGMA journal_mode=WAL`) para mejorar la concurrencia de lecturas y escrituras,
manteniendo además compatibilidad con motores externos como PostgreSQL.
"""

from collections.abc import Generator
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import obtener_configuracion


class BaseDeclarativa(DeclarativeBase):
    """Clase base declarativa compartida por todos los modelos ORM de IdentIA."""


def crear_motor_bd(url_base_datos: str | None = None) -> Engine:
    """Crea y configura un motor SQLAlchemy para la URL indicada o la configuración activa.

    Args:
        url_base_datos: Cadena de conexión opcional (útil para pruebas aisladas o scripts).

    Returns:
        Instancia `Engine` lista para abrir sesiones de base de datos.
    """
    url_efectiva = url_base_datos or obtener_configuracion().url_base_datos_resuelta
    es_sqlite = url_efectiva.startswith("sqlite")
    argumentos_conexion = {"check_same_thread": False} if es_sqlite else {}
    motor = create_engine(url_efectiva, connect_args=argumentos_conexion, future=True)

    # En SQLite, las restricciones FOREIGN KEY están deshabilitadas por conexión si no se activan
    if es_sqlite:
        @event.listens_for(motor, "connect")
        def _aplicar_pragmas_sqlite(conexion_dbapi, _registro_conexion) -> None:
            cursor = conexion_dbapi.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return motor


# Motor y fábrica de sesiones globales utilizados en ejecución normal
motor_bd = crear_motor_bd()
FabricaSesionesLocal = sessionmaker(
    bind=motor_bd,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def obtener_bd() -> Generator[Session, None, None]:
    """Dependencia FastAPI que entrega una sesión de base de datos por petición HTTP.

    Garantiza el cierre ordenado de la sesión al finalizar el ciclo de la petición.
    """
    sesion_bd = FabricaSesionesLocal()
    try:
        yield sesion_bd
    finally:
        sesion_bd.close()
