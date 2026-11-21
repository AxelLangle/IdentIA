"""Gestor de descarga y verificación local de modelos ONNX de OpenCV Zoo.

Asegura que los pesos oficiales de detección facial (`face_detection_yunet_2023mar.onnx`)
y extracción de embeddings (`face_recognition_sface_2021dec.onnx`) estén disponibles
en disco antes de inicializar el motor biométrico.
"""

from dataclasses import dataclass
import os
from pathlib import Path
import urllib.request

from app.config import obtener_configuracion


NOMBRE_ARCHIVO_YUNET = "face_detection_yunet_2023mar.onnx"
NOMBRE_ARCHIVO_SFACE = "face_recognition_sface_2021dec.onnx"

URL_MODELO_YUNET = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_detection_yunet/face_detection_yunet_2023mar.onnx"
)
URL_MODELO_SFACE = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_recognition_sface/face_recognition_sface_2021dec.onnx"
)


@dataclass(frozen=True)
class EspecificacionModelo:
    """Metadatos de descarga y validación de integridad por tamaño mínimo."""

    nombre_archivo: str
    url_descarga: str
    bytes_minimos: int


ESPECIFICACIONES_MODELOS: tuple[EspecificacionModelo, ...] = (
    EspecificacionModelo(
        nombre_archivo=NOMBRE_ARCHIVO_YUNET,
        url_descarga=URL_MODELO_YUNET,
        bytes_minimos=150_000,
    ),
    EspecificacionModelo(
        nombre_archivo=NOMBRE_ARCHIVO_SFACE,
        url_descarga=URL_MODELO_SFACE,
        bytes_minimos=30_000_000,
    ),
)


def _descargar_atomico(especificacion: EspecificacionModelo, ruta_destino: Path) -> None:
    """Descarga un archivo ONNX mediante archivo temporal para evitar descargas corruptas."""
    ruta_destino.parent.mkdir(parents=True, exist_ok=True)
    ruta_temporal = ruta_destino.with_suffix(ruta_destino.suffix + ".tmp")
    peticion_http = urllib.request.Request(
        especificacion.url_descarga,
        headers={"User-Agent": "IdentIA/1.1.0"},
    )
    try:
        with (
            urllib.request.urlopen(peticion_http, timeout=120) as respuesta_http,
            open(ruta_temporal, "wb") as archivo_salida,
        ):
            while True:
                bloque_bytes = respuesta_http.read(1024 * 256)
                if not bloque_bytes:
                    break
                archivo_salida.write(bloque_bytes)

        tamano_bytes = ruta_temporal.stat().st_size
        if tamano_bytes < especificacion.bytes_minimos:
            raise RuntimeError(
                f"El archivo descargado {especificacion.nombre_archivo} es demasiado pequeño "
                f"({tamano_bytes} bytes)."
            )
        # El reemplazo atómico evita dejar modelos truncados si la red se interrumpe
        os.replace(ruta_temporal, ruta_destino)
    except Exception:
        if ruta_temporal.exists():
            ruta_temporal.unlink(missing_ok=True)
        raise


def asegurar_modelos(directorio_modelos: Path | None = None) -> tuple[Path, Path]:
    """Verifica que los modelos YuNet y SFace existan localmente o los descarga si faltan.

    Args:
        directorio_modelos: Carpeta destino opcional; por defecto usa la configuración activa.

    Returns:
        Tupla `(ruta_yunet, ruta_sface)` apuntando a los modelos listos para cargar.
    """
    directorio_objetivo = directorio_modelos or obtener_configuracion().directorio_modelos
    directorio_objetivo.mkdir(parents=True, exist_ok=True)

    rutas_listas: list[Path] = []
    for especificacion in ESPECIFICACIONES_MODELOS:
        ruta_modelo = directorio_objetivo / especificacion.nombre_archivo
        if not ruta_modelo.exists() or ruta_modelo.stat().st_size < especificacion.bytes_minimos:
            _descargar_atomico(especificacion, ruta_modelo)
        rutas_listas.append(ruta_modelo)

    return rutas_listas[0], rutas_listas[1]


if __name__ == "__main__":
    ruta_yunet_lista, ruta_sface_lista = asegurar_modelos()
    print(f"YuNet listo: {ruta_yunet_lista} ({ruta_yunet_lista.stat().st_size} bytes)")
    print(f"SFace listo: {ruta_sface_lista} ({ruta_sface_lista.stat().st_size} bytes)")
