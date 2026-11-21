"""Configuración central de IdentIA.

Define los parámetros de rutas, base de datos, CORS, umbrales del motor
biométrico ONNX (YuNet + SFace), control de calidad en captura e iluminación,
autenticación JWT y credenciales semilla. Soporta ejecución estándar en
desarrollo y ejecución empaquetada como binario de escritorio (PyInstaller).
"""

from functools import lru_cache
from pathlib import Path
import sys
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# Determina si la aplicación se está ejecutando desde un binario congelado (PyInstaller)
APLICACION_EMPAQUETADA: bool = bool(getattr(sys, "frozen", False))

# Ruta raíz del código fuente del backend (usada en desarrollo y pruebas)
DIRECTORIO_BACKEND: Path = Path(__file__).resolve().parent.parent


def _resolver_directorio_base_por_defecto() -> Path:
    """Devuelve el directorio base efectivo según el modo de ejecución."""
    if APLICACION_EMPAQUETADA:
        # En ejecutable portable o único, los archivos editables viven junto al .exe
        return Path(sys.executable).resolve().parent
    return DIRECTORIO_BACKEND


def _resolver_directorio_datos_por_defecto() -> Path:
    """Devuelve la carpeta persistente donde se almacena la base de datos SQLite."""
    if APLICACION_EMPAQUETADA:
        return Path(sys.executable).resolve().parent / "datos_identia"
    return DIRECTORIO_BACKEND / "data"


def _resolver_directorio_modelos_por_defecto() -> Path:
    """Resuelve la carpeta de modelos ONNX priorizando recursos embebidos offline."""
    if APLICACION_EMPAQUETADA:
        ruta_meipass = getattr(sys, "_MEIPASS", None)
        if ruta_meipass:
            modelos_embebidos = Path(ruta_meipass) / "models"
            if modelos_embebidos.exists():
                return modelos_embebidos
        return Path(sys.executable).resolve().parent / "modelos_identia"
    return DIRECTORIO_BACKEND / "models"


def _resolver_directorio_frontend_por_defecto() -> Path | None:
    """Devuelve la carpeta `frontend_dist` embebida cuando corre como ejecutable."""
    if APLICACION_EMPAQUETADA:
        ruta_meipass = getattr(sys, "_MEIPASS", None)
        if ruta_meipass:
            frontend_embebido = Path(ruta_meipass) / "frontend_dist"
            if frontend_embebido.exists():
                return frontend_embebido
    return None


class ConfiguracionIdentia(BaseSettings):
    """Configuración central de IdentIA parametrizable vía variables `IDENTIA_*`.

    Se conservan alias de validación para variables históricas (`IDENTIA_DATABASE_URL`,
    `IDENTIA_DATA_DIR`, etc.) junto con sus equivalentes en español para mantener
    compatibilidad con entornos de pruebas, scripts y despliegues existentes.
    """

    model_config = SettingsConfigDict(
        env_prefix="IDENTIA_",
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

    # --- Metadatos y rutas del sistema de archivos ---
    nombre_aplicacion: str = Field(
        default="IdentIA API",
        validation_alias=AliasChoices("IDENTIA_NOMBRE_APLICACION", "IDENTIA_APP_NAME"),
    )
    directorio_base: Path = Field(
        default_factory=_resolver_directorio_base_por_defecto,
        validation_alias=AliasChoices("IDENTIA_DIRECTORIO_BASE", "IDENTIA_BASE_DIR"),
    )
    directorio_datos: Path = Field(
        default_factory=_resolver_directorio_datos_por_defecto,
        validation_alias=AliasChoices("IDENTIA_DIRECTORIO_DATOS", "IDENTIA_DATA_DIR"),
    )
    directorio_modelos: Path = Field(
        default_factory=_resolver_directorio_modelos_por_defecto,
        validation_alias=AliasChoices("IDENTIA_DIRECTORIO_MODELOS", "IDENTIA_MODELS_DIR"),
    )
    directorio_frontend_compilado: Path | None = Field(
        default_factory=_resolver_directorio_frontend_por_defecto,
        validation_alias=AliasChoices(
            "IDENTIA_DIRECTORIO_FRONTEND",
            "IDENTIA_FRONTEND_DIST_DIR",
        ),
    )
    url_base_datos: str | None = Field(
        default=None,
        validation_alias=AliasChoices("IDENTIA_URL_BASE_DATOS", "IDENTIA_DATABASE_URL"),
    )

    # --- Orígenes permitidos para CORS (incluye Vite dev y servidor local integrado) ---
    origenes_cors: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ],
        validation_alias=AliasChoices("IDENTIA_ORIGENES_CORS", "IDENTIA_CORS_ORIGINS"),
    )

    # --- Parámetros de detección y reconocimiento ONNX (YuNet + SFace) ---
    umbral_deteccion_yunet: float = Field(
        default=0.75,
        validation_alias=AliasChoices("IDENTIA_UMBRAL_DETECCION_YUNET", "IDENTIA_YUNET_SCORE_THRESHOLD"),
    )
    umbral_supresion_yunet: float = Field(
        default=0.30,
        validation_alias=AliasChoices("IDENTIA_UMBRAL_SUPRESION_YUNET", "IDENTIA_YUNET_NMS_THRESHOLD"),
    )
    umbral_coincidencia: float = Field(
        default=0.42,
        validation_alias=AliasChoices("IDENTIA_UMBRAL_COINCIDENCIA", "IDENTIA_MATCH_THRESHOLD"),
    )
    margen_ambiguedad: float = Field(
        default=0.05,
        validation_alias=AliasChoices("IDENTIA_MARGEN_AMBIGUEDAD", "IDENTIA_AMBIGUOUS_MARGIN"),
    )
    umbral_autoconsistencia: float = Field(
        default=0.25,
        validation_alias=AliasChoices(
            "IDENTIA_UMBRAL_AUTOCONSISTENCIA",
            "IDENTIA_SELF_CONSISTENCY_THRESHOLD",
        ),
    )

    # --- Parámetros de control de calidad en captura e iluminación ---
    tamano_minimo_rostro_px: int = Field(
        default=64,
        validation_alias=AliasChoices("IDENTIA_TAMANO_MINIMO_ROSTRO_PX", "IDENTIA_MIN_FACE_SIZE_PX"),
    )
    tamano_minimo_rostro_kiosco_px: int = Field(
        default=56,
        validation_alias=AliasChoices(
            "IDENTIA_TAMANO_MINIMO_ROSTRO_KIOSCO_PX",
            "IDENTIA_KIOSK_MIN_FACE_SIZE_PX",
        ),
    )
    varianza_minima_nitidez: float = Field(
        default=18.0,
        validation_alias=AliasChoices("IDENTIA_VARIANZA_MINIMA_NITIDEZ", "IDENTIA_MIN_BLUR_VARIANCE"),
    )
    varianza_minima_nitidez_registro: float = Field(
        default=18.0,
        validation_alias=AliasChoices(
            "IDENTIA_VARIANZA_MINIMA_NITIDEZ_REGISTRO",
            "IDENTIA_ENROLL_MIN_BLUR_VARIANCE",
        ),
    )
    varianza_minima_nitidez_kiosco: float = Field(
        default=10.0,
        validation_alias=AliasChoices(
            "IDENTIA_VARIANZA_MINIMA_NITIDEZ_KIOSCO",
            "IDENTIA_KIOSK_MIN_BLUR_VARIANCE",
        ),
    )
    brillo_minimo: float = Field(
        default=35.0,
        validation_alias=AliasChoices("IDENTIA_BRILLO_MINIMO", "IDENTIA_MIN_BRIGHTNESS"),
    )
    brillo_minimo_registro: float = Field(
        default=32.0,
        validation_alias=AliasChoices(
            "IDENTIA_BRILLO_MINIMO_REGISTRO",
            "IDENTIA_ENROLL_MIN_BRIGHTNESS",
        ),
    )
    brillo_minimo_kiosco: float = Field(
        default=18.0,
        validation_alias=AliasChoices(
            "IDENTIA_BRILLO_MINIMO_KIOSCO",
            "IDENTIA_KIOSK_MIN_BRIGHTNESS",
        ),
    )
    brillo_maximo: float = Field(
        default=235.0,
        validation_alias=AliasChoices("IDENTIA_BRILLO_MAXIMO", "IDENTIA_MAX_BRIGHTNESS"),
    )
    asimetria_sombra_maxima_registro: float = Field(
        default=68.0,
        validation_alias=AliasChoices(
            "IDENTIA_ASIMETRIA_SOMBRA_MAXIMA_REGISTRO",
            "IDENTIA_ENROLL_MAX_SHADOW_ASYMMETRY",
        ),
    )
    asimetria_sombra_maxima_kiosco: float = Field(
        default=95.0,
        validation_alias=AliasChoices(
            "IDENTIA_ASIMETRIA_SOMBRA_MAXIMA_KIOSCO",
            "IDENTIA_KIOSK_MAX_SHADOW_ASYMMETRY",
        ),
    )
    umbral_delta_contraluz: float = Field(
        default=70.0,
        validation_alias=AliasChoices(
            "IDENTIA_UMBRAL_DELTA_CONTRALUZ",
            "IDENTIA_BACKLIGHT_DELTA_THRESHOLD",
        ),
    )

    # --- Trazabilidad del modelo biométrico ---
    nombre_modelo: str = Field(
        default="sface",
        validation_alias=AliasChoices("IDENTIA_NOMBRE_MODELO", "IDENTIA_MODEL_NAME"),
    )
    version_modelo: str = Field(
        default="sface_2021dec_v2",
        validation_alias=AliasChoices("IDENTIA_VERSION_MODELO", "IDENTIA_MODEL_VERSION"),
    )

    # --- Autenticación JWT y usuarios semilla iniciales (bootstrap) ---
    clave_secreta_jwt: str = Field(
        default="identia-dev-secret-change-in-production-32bytes-min",
        validation_alias=AliasChoices("IDENTIA_CLAVE_SECRETA_JWT", "IDENTIA_JWT_SECRET_KEY"),
    )
    algoritmo_jwt: str = Field(
        default="HS256",
        validation_alias=AliasChoices("IDENTIA_ALGORITMO_JWT", "IDENTIA_JWT_ALGORITHM"),
    )
    minutos_expiracion_jwt: int = Field(
        default=480,
        validation_alias=AliasChoices("IDENTIA_MINUTOS_EXPIRACION_JWT", "IDENTIA_JWT_EXPIRE_MINUTES"),
    )
    correo_superadmin_inicial: str = Field(
        default="admin@identia.local",
        validation_alias=AliasChoices(
            "IDENTIA_CORREO_SUPERADMIN_INICIAL",
            "IDENTIA_BOOTSTRAP_SUPERADMIN_EMAIL",
        ),
    )
    contrasena_superadmin_inicial: str = Field(
        default="IdentIA2026!",
        validation_alias=AliasChoices(
            "IDENTIA_CONTRASENA_SUPERADMIN_INICIAL",
            "IDENTIA_BOOTSTRAP_SUPERADMIN_PASSWORD",
        ),
    )
    nombre_superadmin_inicial: str = Field(
        default="Superadmin IdentIA",
        validation_alias=AliasChoices(
            "IDENTIA_NOMBRE_SUPERADMIN_INICIAL",
            "IDENTIA_BOOTSTRAP_SUPERADMIN_NAME",
        ),
    )
    correo_admin_org_inicial: str = Field(
        default="empresa@identia.local",
        validation_alias=AliasChoices(
            "IDENTIA_CORREO_ADMIN_ORG_INICIAL",
            "IDENTIA_BOOTSTRAP_ORG_ADMIN_EMAIL",
        ),
    )
    contrasena_admin_org_inicial: str = Field(
        default="Empresa2026!",
        validation_alias=AliasChoices(
            "IDENTIA_CONTRASENA_ADMIN_ORG_INICIAL",
            "IDENTIA_BOOTSTRAP_ORG_ADMIN_PASSWORD",
        ),
    )

    @property
    def url_base_datos_resuelta(self) -> str:
        """Calcula la cadena de conexión SQLAlchemy asegurando que el directorio exista."""
        if self.url_base_datos:
            return self.url_base_datos
        self.directorio_datos.mkdir(parents=True, exist_ok=True)
        ruta_bd = (self.directorio_datos / "identia.db").resolve()
        return f"sqlite:///{ruta_bd.as_posix()}"


@lru_cache
def obtener_configuracion() -> ConfiguracionIdentia:
    """Devuelve una instancia cacheada de la configuración global de IdentIA."""
    return ConfiguracionIdentia()
