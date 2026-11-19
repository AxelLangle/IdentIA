from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Configuración central de IdentIA parametrizable vía variables IDENTIA_*."""

    model_config = SettingsConfigDict(
        env_prefix="IDENTIA_",
        env_file=".env",
        extra="ignore",
    )

    app_name: str = "IdentIA API"
    base_dir: Path = BACKEND_DIR
    data_dir: Path = BACKEND_DIR / "data"
    models_dir: Path = BACKEND_DIR / "models"
    database_url: str | None = None

    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # Parámetros de detección y reconocimiento ONNX (YuNet + SFace)
    yunet_score_threshold: float = 0.75
    yunet_nms_threshold: float = 0.30
    match_threshold: float = 0.42
    ambiguous_margin: float = 0.05
    self_consistency_threshold: float = 0.25

    # Parámetros de control de calidad en captura e iluminación
    min_face_size_px: int = 64
    kiosk_min_face_size_px: int = 56
    min_blur_variance: float = 18.0
    enroll_min_blur_variance: float = 18.0
    kiosk_min_blur_variance: float = 10.0
    min_brightness: float = 35.0
    enroll_min_brightness: float = 32.0
    kiosk_min_brightness: float = 18.0
    max_brightness: float = 235.0
    enroll_max_shadow_asymmetry: float = 68.0
    kiosk_max_shadow_asymmetry: float = 95.0
    backlight_delta_threshold: float = 70.0

    # Trazabilidad del modelo biométrico
    model_name: str = "sface"
    model_version: str = "sface_2021dec_v2"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        self.data_dir.mkdir(parents=True, exist_ok=True)
        db_path = (self.data_dir / "identia.db").resolve()
        return f"sqlite:///{db_path.as_posix()}"


@lru_cache
def get_settings() -> Settings:
    """Devuelve una instancia cacheada de configuración."""
    return Settings()
