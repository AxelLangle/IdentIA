from dataclasses import dataclass
import os
from pathlib import Path
import urllib.request

from app.config import get_settings


YUNET_FILENAME = "face_detection_yunet_2023mar.onnx"
SFACE_FILENAME = "face_recognition_sface_2021dec.onnx"

YUNET_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_detection_yunet/face_detection_yunet_2023mar.onnx"
)
SFACE_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_recognition_sface/face_recognition_sface_2021dec.onnx"
)


@dataclass(frozen=True)
class ModelSpec:
    filename: str
    url: str
    min_bytes: int


MODEL_SPECS: tuple[ModelSpec, ...] = (
    ModelSpec(filename=YUNET_FILENAME, url=YUNET_URL, min_bytes=150_000),
    ModelSpec(filename=SFACE_FILENAME, url=SFACE_URL, min_bytes=30_000_000),
)


def _download_atomic(spec: ModelSpec, dest: Path) -> None:
    """Descarga un modelo ONNX de forma atómica validando su tamaño mínimo."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest.with_suffix(dest.suffix + ".tmp")
    request = urllib.request.Request(
        spec.url,
        headers={"User-Agent": "IdentIA/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response, open(tmp_path, "wb") as out:
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                out.write(chunk)
        size = tmp_path.stat().st_size
        if size < spec.min_bytes:
            raise RuntimeError(
                f"El archivo descargado {spec.filename} es demasiado pequeño ({size} bytes)."
            )
        os.replace(tmp_path, dest)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise


def ensure_models(models_dir: Path | None = None) -> tuple[Path, Path]:
    """Asegura que los modelos YuNet y SFace existan localmente y devuelve sus rutas."""
    target_dir = models_dir or get_settings().models_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []
    for spec in MODEL_SPECS:
        model_path = target_dir / spec.filename
        if not model_path.exists() or model_path.stat().st_size < spec.min_bytes:
            _download_atomic(spec, model_path)
        paths.append(model_path)

    return paths[0], paths[1]


if __name__ == "__main__":
    yunet_path, sface_path = ensure_models()
    print(f"YuNet listo: {yunet_path} ({yunet_path.stat().st_size} bytes)")
    print(f"SFace listo: {sface_path} ({sface_path.stat().st_size} bytes)")
