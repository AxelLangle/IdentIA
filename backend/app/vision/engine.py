"""Motor biométrico ONNX basado en OpenCV YuNet (detección) y SFace (reconocimiento).

Todas las operaciones de imagen ocurren íntegramente en memoria RAM: se decodifica
el fotograma, se detectan rostros con fallback LAB/CLAHE ante contraluz, se alinea
y normaliza la iluminación extrema de la región facial, se extrae el embedding L2
de 128 dimensiones y se realiza la búsqueda 1:N por similitud coseno con margen de
desambiguación.
"""

import base64
from dataclasses import dataclass
import math
from pathlib import Path
import threading
from typing import Literal

import cv2
import numpy as np

from app.vision.quality import CuadroRostro


@dataclass(frozen=True)
class DecisionCoincidencia:
    """Resultado de comparar un vector facial contra la galería activa."""

    estado: Literal["matched", "ambiguous", "unknown"]
    id_persona: int | None
    nombre_persona: str | None
    confianza: float
    puntaje_segundo_candidato: float | None


def decodificar_bytes_imagen(bytes_crudos: bytes, dimension_maxima: int = 1280) -> np.ndarray:
    """Decodifica bytes de imagen en memoria RAM sin escribir archivos temporales.

    Redimensiona proporcionalmente las imágenes de muy alta resolución para acotar
    la latencia de inferencia en CPU.
    """
    if not bytes_crudos:
        raise ValueError("La imagen recibida está vacía.")
    arreglo_bytes = np.frombuffer(bytes_crudos, dtype=np.uint8)
    imagen = cv2.imdecode(arreglo_bytes, cv2.IMREAD_COLOR)
    if imagen is None or imagen.size == 0:
        raise ValueError("No se pudo decodificar la imagen enviada.")

    alto, ancho = imagen.shape[:2]
    lado_mayor = max(alto, ancho)
    if lado_mayor > dimension_maxima:
        escala = dimension_maxima / float(lado_mayor)
        nuevo_ancho = max(1, int(round(ancho * escala)))
        nuevo_alto = max(1, int(round(alto * escala)))
        imagen = cv2.resize(imagen, (nuevo_ancho, nuevo_alto), interpolation=cv2.INTER_AREA)

    return imagen


def normalizar_vector(vector: np.ndarray) -> np.ndarray:
    """Normaliza un vector facial a norma euclidiana L2 unitaria en `float32`."""
    vector_plano = np.asarray(vector, dtype=np.float32).reshape(-1)
    norma = float(np.linalg.norm(vector_plano))
    if norma <= 1e-12:
        raise ValueError("El embedding generado tiene norma cero.")
    return (vector_plano / norma).astype(np.float32)


def vector_a_bytes(vector: np.ndarray) -> bytes:
    """Serializa un vector facial normalizado L2 a secuencia binaria `float32`."""
    return normalizar_vector(vector).tobytes()


def bytes_a_vector(datos_binarios: bytes) -> np.ndarray:
    """Reconstruye un vector normalizado L2 a partir de bytes `float32` almacenados."""
    vector = np.frombuffer(datos_binarios, dtype=np.float32).copy()
    return normalizar_vector(vector)


def similitud_coseno(vector_a: np.ndarray, vector_b: np.ndarray) -> float:
    """Calcula el producto punto normalizado (similitud coseno en [-1, 1]) entre dos vectores."""
    primero = normalizar_vector(vector_a)
    segundo = normalizar_vector(vector_b)
    return float(np.dot(primero, segundo))


def crear_avatar_base64(imagen_bgr: np.ndarray, cuadro: CuadroRostro, tamano: int = 200) -> str:
    """Genera una miniatura JPEG cuadrada en Base64 para identificación visual desacoplada."""
    alto_imagen, ancho_imagen = imagen_bgr.shape[:2]
    margen_x = int(cuadro.ancho * 0.30)
    margen_y = int(cuadro.alto * 0.30)

    x_inicio = max(0, cuadro.coordenada_x - margen_x)
    y_inicio = max(0, cuadro.coordenada_y - margen_y)
    x_fin = min(ancho_imagen, cuadro.coordenada_x + cuadro.ancho + margen_x)
    y_fin = min(alto_imagen, cuadro.coordenada_y + cuadro.alto + margen_y)

    if x_fin <= x_inicio or y_fin <= y_inicio:
        x_inicio, y_inicio, x_fin, y_fin = 0, 0, ancho_imagen, alto_imagen

    recorte = imagen_bgr[y_inicio:y_fin, x_inicio:x_fin]
    redimensionado = cv2.resize(recorte, (tamano, tamano), interpolation=cv2.INTER_AREA)
    codificado_ok, bufer = cv2.imencode(
        ".jpg",
        redimensionado,
        [int(cv2.IMWRITE_JPEG_QUALITY), 75],
    )
    if not codificado_ok:
        raise ValueError("No se pudo codificar la miniatura del avatar.")
    cadena_base64 = base64.b64encode(bufer.tobytes()).decode("ascii")
    return f"data:image/jpeg;base64,{cadena_base64}"


def coincidir_vector(
    vector_consulta: np.ndarray,
    galeria: list[tuple[int, str, np.ndarray]],
    umbral: float = 0.42,
    margen: float = 0.05,
) -> DecisionCoincidencia:
    """Busca la mejor coincidencia 1:N verificando umbral mínimo y margen contra el 2.º lugar."""
    if not galeria:
        return DecisionCoincidencia(
            estado="unknown",
            id_persona=None,
            nombre_persona=None,
            confianza=0.0,
            puntaje_segundo_candidato=None,
        )

    consulta_norm = normalizar_vector(vector_consulta)
    mejor_por_persona: dict[int, tuple[str, float]] = {}

    # Para cada persona en la galería, conserva el puntaje máximo entre todas sus poses
    for id_persona, nombre_persona, vector_guardado in galeria:
        puntaje = float(np.dot(consulta_norm, normalizar_vector(vector_guardado)))
        previo = mejor_por_persona.get(id_persona)
        if previo is None or puntaje > previo[1]:
            mejor_por_persona[id_persona] = (nombre_persona, puntaje)

    clasificacion = sorted(
        ((pid, nombre, puntaje) for pid, (nombre, puntaje) in mejor_por_persona.items()),
        key=lambda elemento: elemento[2],
        reverse=True,
    )

    mejor_id, mejor_nombre, mejor_puntaje = clasificacion[0]
    segundo_puntaje = clasificacion[1][2] if len(clasificacion) > 1 else None

    if mejor_puntaje < umbral:
        return DecisionCoincidencia(
            estado="unknown",
            id_persona=None,
            nombre_persona=None,
            confianza=mejor_puntaje,
            puntaje_segundo_candidato=segundo_puntaje,
        )

    if segundo_puntaje is not None and (mejor_puntaje - segundo_puntaje) < margen:
        return DecisionCoincidencia(
            estado="ambiguous",
            id_persona=None,
            nombre_persona=None,
            confianza=mejor_puntaje,
            puntaje_segundo_candidato=segundo_puntaje,
        )

    return DecisionCoincidencia(
        estado="matched",
        id_persona=mejor_id,
        nombre_persona=mejor_nombre,
        confianza=mejor_puntaje,
        puntaje_segundo_candidato=segundo_puntaje,
    )


def realzar_frame_para_deteccion(imagen_bgr: np.ndarray) -> np.ndarray:
    """Realza luminancia y contraste local en el canal L (CIE LAB) para detectar en contraluz."""
    espacio_lab = cv2.cvtColor(imagen_bgr, cv2.COLOR_BGR2LAB)
    canal_l, canal_a, canal_b = cv2.split(espacio_lab)
    luminancia_media = float(np.mean(canal_l))
    gamma = 0.65 if luminancia_media < 110.0 else 0.80
    tabla_gamma = np.array(
        [np.clip(((indice / 255.0) ** gamma) * 255.0, 0, 255) for indice in range(256)],
        dtype=np.uint8,
    )
    canal_l_gamma = cv2.LUT(canal_l, tabla_gamma)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    canal_l_realzado = clahe.apply(canal_l_gamma)
    imagen_fusionada = cv2.merge([canal_l_realzado, canal_a, canal_b])
    return cv2.cvtColor(imagen_fusionada, cv2.COLOR_LAB2BGR)


def normalizar_iluminacion_rostro(rostro_alineado_bgr: np.ndarray) -> np.ndarray:
    """Compensa solo iluminación extrema (oscuridad o sobreexposición) sobre el recorte alineado.

    Si la luminancia media se encuentra en rango óptimo `[85, 195]`, devuelve la imagen
    sin alteraciones para conservar los rasgos texturales originales.
    """
    espacio_lab = cv2.cvtColor(rostro_alineado_bgr, cv2.COLOR_BGR2LAB)
    canal_l, canal_a, canal_b = cv2.split(espacio_lab)
    luminancia_media = float(np.mean(canal_l))

    if 85.0 <= luminancia_media <= 195.0:
        return rostro_alineado_bgr

    if luminancia_media < 85.0:
        gamma = float(
            np.clip(
                math.log(112.0 / 255.0) / math.log(max(luminancia_media, 8.0) / 255.0),
                0.50,
                1.0,
            )
        )
        tabla_gamma = np.array(
            [np.clip(((indice / 255.0) ** gamma) * 255.0, 0, 255) for indice in range(256)],
            dtype=np.uint8,
        )
        canal_l_gamma = cv2.LUT(canal_l, tabla_gamma)
        clahe = cv2.createCLAHE(clipLimit=1.2, tileGridSize=(2, 2))
        canal_l_norm = cv2.addWeighted(canal_l_gamma, 0.75, clahe.apply(canal_l_gamma), 0.25, 0)
    else:
        gamma = float(
            np.clip(
                math.log(165.0 / 255.0) / math.log(min(luminancia_media, 250.0) / 255.0),
                1.0,
                1.65,
            )
        )
        tabla_gamma = np.array(
            [np.clip(((indice / 255.0) ** gamma) * 255.0, 0, 255) for indice in range(256)],
            dtype=np.uint8,
        )
        canal_l_norm = cv2.LUT(canal_l, tabla_gamma)

    imagen_fusionada = cv2.merge([canal_l_norm, canal_a, canal_b])
    return cv2.cvtColor(imagen_fusionada, cv2.COLOR_LAB2BGR)


class MotorBiometrico:
    """Motor biométrico thread-safe basado en OpenCV YuNet y SFace ONNX."""

    def __init__(
        self,
        ruta_yunet: Path,
        ruta_sface: Path,
        umbral_deteccion: float = 0.75,
        umbral_supresion: float = 0.30,
    ) -> None:
        self.ruta_yunet = Path(ruta_yunet)
        self.ruta_sface = Path(ruta_sface)
        # Los objetos DNN de OpenCV no garantizan reentrancia sin exclusión mutua
        self._cerrojo = threading.Lock()
        self._detector = cv2.FaceDetectorYN.create(
            str(self.ruta_yunet),
            "",
            (320, 320),
            umbral_deteccion,
            umbral_supresion,
            5000,
        )
        self._reconocedor = cv2.FaceRecognizerSF.create(
            str(self.ruta_sface),
            "",
        )

    def detectar(
        self,
        imagen_bgr: np.ndarray,
        permitir_respaldo_contraluz: bool = True,
    ) -> list[tuple[CuadroRostro, np.ndarray]]:
        """Detecta rostros en la imagen y los ordena de mayor a menor área."""
        alto, ancho = imagen_bgr.shape[:2]
        with self._cerrojo:
            self._detector.setInputSize((ancho, alto))
            _, rostros_crudos = self._detector.detect(imagen_bgr)
            if (rostros_crudos is None or len(rostros_crudos) == 0) and permitir_respaldo_contraluz:
                imagen_realzada = realzar_frame_para_deteccion(imagen_bgr)
                self._detector.setInputSize((ancho, alto))
                _, rostros_crudos = self._detector.detect(imagen_realzada)

        if rostros_crudos is None or len(rostros_crudos) == 0:
            return []

        detecciones: list[tuple[CuadroRostro, np.ndarray]] = []
        for fila in rostros_crudos:
            fila_float = np.asarray(fila, dtype=np.float32)
            coord_x, coord_y, ancho_rostro, alto_rostro = (
                int(round(valor)) for valor in fila_float[:4]
            )
            puntos_referencia = [
                (float(fila_float[4]), float(fila_float[5])),
                (float(fila_float[6]), float(fila_float[7])),
                (float(fila_float[8]), float(fila_float[9])),
                (float(fila_float[10]), float(fila_float[11])),
                (float(fila_float[12]), float(fila_float[13])),
            ]
            cuadro = CuadroRostro(
                coordenada_x=coord_x,
                coordenada_y=coord_y,
                ancho=ancho_rostro,
                alto=alto_rostro,
                confianza=float(fila_float[14]),
                puntos_referencia=puntos_referencia,
            )
            detecciones.append((cuadro, fila_float))

        # Prioriza el rostro más cercano a la cámara (mayor área en píxeles)
        detecciones.sort(key=lambda elemento: elemento[0].ancho * elemento[0].alto, reverse=True)
        return detecciones

    def extraer_vector(self, imagen_bgr: np.ndarray, fila_rostro_cruda: np.ndarray) -> np.ndarray:
        """Alinea el rostro, compensa iluminación extrema y extrae el vector L2 (128-D)."""
        with self._cerrojo:
            rostro_alineado = self._reconocedor.alignCrop(imagen_bgr, fila_rostro_cruda)
            rostro_normalizado = normalizar_iluminacion_rostro(rostro_alineado)
            caracteristicas = self._reconocedor.feature(rostro_normalizado)
        return normalizar_vector(caracteristicas)
