import base64
from dataclasses import dataclass
import math
from pathlib import Path
import threading
from typing import Literal

import cv2
import numpy as np

from app.vision.quality import FaceBox


@dataclass(frozen=True)
class MatchDecision:
    """Resultado de comparación 1:N contra la galería de embeddings."""

    status: Literal["matched", "ambiguous", "unknown"]
    person_id: int | None
    person_name: str | None
    confidence: float
    second_best_score: float | None


def decode_image_bytes(raw_bytes: bytes, max_dim: int = 1280) -> np.ndarray:
    """Decodifica una imagen en memoria RAM sin escribir archivos en disco."""
    if not raw_bytes:
        raise ValueError("La imagen recibida está vacía.")
    arr = np.frombuffer(raw_bytes, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise ValueError("No se pudo decodificar la imagen enviada.")

    h, w = image.shape[:2]
    longest = max(h, w)
    if longest > max_dim:
        scale = max_dim / float(longest)
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)

    return image


def normalize_embedding(vec: np.ndarray) -> np.ndarray:
    """Normaliza un embedding facial a norma L2 unitaria en float32."""
    flat = np.asarray(vec, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(flat))
    if norm <= 1e-12:
        raise ValueError("El embedding generado tiene norma cero.")
    return (flat / norm).astype(np.float32)


def embedding_to_bytes(vec: np.ndarray) -> bytes:
    """Serializa un vector normalizado a bytes float32."""
    return normalize_embedding(vec).tobytes()


def bytes_to_embedding(data: bytes) -> np.ndarray:
    """Deserializa bytes float32 a vector normalizado."""
    vec = np.frombuffer(data, dtype=np.float32).copy()
    return normalize_embedding(vec)


def cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    """Calcula la similitud coseno entre dos embeddings."""
    a = normalize_embedding(vec_a)
    b = normalize_embedding(vec_b)
    return float(np.dot(a, b))


def create_avatar_base64(image_bgr: np.ndarray, box: FaceBox, size: int = 200) -> str:
    """Genera una miniatura JPEG ligera en base64 para identificación visual."""
    img_h, img_w = image_bgr.shape[:2]
    pad_w = int(box.w * 0.30)
    pad_h = int(box.h * 0.30)

    x1 = max(0, box.x - pad_w)
    y1 = max(0, box.y - pad_h)
    x2 = min(img_w, box.x + box.w + pad_w)
    y2 = min(img_h, box.y + box.h + pad_h)

    if x2 <= x1 or y2 <= y1:
        x1, y1, x2, y2 = 0, 0, img_w, img_h

    crop = image_bgr[y1:y2, x1:x2]
    resized = cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA)
    ok, buffer = cv2.imencode(".jpg", resized, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
    if not ok:
        raise ValueError("No se pudo codificar la miniatura del avatar.")
    encoded = base64.b64encode(buffer.tobytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def match_embedding(
    query_vec: np.ndarray,
    gallery: list[tuple[int, str, np.ndarray]],
    threshold: float = 0.42,
    margin: float = 0.05,
) -> MatchDecision:
    """Busca la mejor coincidencia en la galería verificando umbral y margen."""
    if not gallery:
        return MatchDecision(
            status="unknown",
            person_id=None,
            person_name=None,
            confidence=0.0,
            second_best_score=None,
        )

    q = normalize_embedding(query_vec)
    best_per_person: dict[int, tuple[str, float]] = {}

    for person_id, person_name, stored_vec in gallery:
        score = float(np.dot(q, normalize_embedding(stored_vec)))
        prev = best_per_person.get(person_id)
        if prev is None or score > prev[1]:
            best_per_person[person_id] = (person_name, score)

    ranked = sorted(
        ((pid, name, score) for pid, (name, score) in best_per_person.items()),
        key=lambda item: item[2],
        reverse=True,
    )

    best_id, best_name, best_score = ranked[0]
    second_score = ranked[1][2] if len(ranked) > 1 else None

    if best_score < threshold:
        return MatchDecision(
            status="unknown",
            person_id=None,
            person_name=None,
            confidence=best_score,
            second_best_score=second_score,
        )

    if second_score is not None and (best_score - second_score) < margin:
        return MatchDecision(
            status="ambiguous",
            person_id=None,
            person_name=None,
            confidence=best_score,
            second_best_score=second_score,
        )

    return MatchDecision(
        status="matched",
        person_id=best_id,
        person_name=best_name,
        confidence=best_score,
        second_best_score=second_score,
    )


def enhance_frame_for_detection(image_bgr: np.ndarray) -> np.ndarray:
    """Realza luminancia y contraste local en canal L para detectar rostros a contraluz."""
    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)
    l_ch, a_ch, b_ch = cv2.split(lab)
    mean_l = float(np.mean(l_ch))
    gamma = 0.65 if mean_l < 110.0 else 0.80
    lut = np.array(
        [np.clip(((i / 255.0) ** gamma) * 255.0, 0, 255) for i in range(256)],
        dtype=np.uint8,
    )
    l_gamma = cv2.LUT(l_ch, lut)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    l_enhanced = clahe.apply(l_gamma)
    merged = cv2.merge([l_enhanced, a_ch, b_ch])
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)


def normalize_face_lighting(aligned_bgr: np.ndarray) -> np.ndarray:
    """Compensa sombras y contraluz en el recorte alineado sin alterar colores cromáticos."""
    lab = cv2.cvtColor(aligned_bgr, cv2.COLOR_BGR2LAB)
    l_ch, a_ch, b_ch = cv2.split(lab)
    mean_l = max(float(np.mean(l_ch)), 1.0)

    if mean_l < 110.0 or mean_l > 175.0:
        gamma = float(np.clip(math.log(128.0 / 255.0) / math.log(mean_l / 255.0), 0.45, 1.80))
        lut = np.array(
            [np.clip(((i / 255.0) ** gamma) * 255.0, 0, 255) for i in range(256)],
            dtype=np.uint8,
        )
        l_ch = cv2.LUT(l_ch, lut)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
    l_norm = clahe.apply(l_ch)
    merged = cv2.merge([l_norm, a_ch, b_ch])
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)


class BiometricEngine:
    """Motor biométrico thread-safe basado en OpenCV YuNet y SFace ONNX."""

    def __init__(
        self,
        yunet_path: Path,
        sface_path: Path,
        score_threshold: float = 0.75,
        nms_threshold: float = 0.30,
    ) -> None:
        self.yunet_path = Path(yunet_path)
        self.sface_path = Path(sface_path)
        self._lock = threading.Lock()
        self._detector = cv2.FaceDetectorYN.create(
            str(self.yunet_path),
            "",
            (320, 320),
            score_threshold,
            nms_threshold,
            5000,
        )
        self._recognizer = cv2.FaceRecognizerSF.create(
            str(self.sface_path),
            "",
        )

    def detect(
        self,
        image_bgr: np.ndarray,
        allow_backlight_fallback: bool = True,
    ) -> list[tuple[FaceBox, np.ndarray]]:
        """Detecta rostros en la imagen ordenados de mayor a menor área."""
        h, w = image_bgr.shape[:2]
        with self._lock:
            self._detector.setInputSize((w, h))
            _, raw_faces = self._detector.detect(image_bgr)
            if (raw_faces is None or len(raw_faces) == 0) and allow_backlight_fallback:
                boosted = enhance_frame_for_detection(image_bgr)
                self._detector.setInputSize((w, h))
                _, raw_faces = self._detector.detect(boosted)

        if raw_faces is None or len(raw_faces) == 0:
            return []

        results: list[tuple[FaceBox, np.ndarray]] = []
        for row in raw_faces:
            row_f = np.asarray(row, dtype=np.float32)
            x, y, bw, bh = (int(round(v)) for v in row_f[:4])
            landmarks = [
                (float(row_f[4]), float(row_f[5])),
                (float(row_f[6]), float(row_f[7])),
                (float(row_f[8]), float(row_f[9])),
                (float(row_f[10]), float(row_f[11])),
                (float(row_f[12]), float(row_f[13])),
            ]
            box = FaceBox(
                x=x,
                y=y,
                w=bw,
                h=bh,
                confidence=float(row_f[14]),
                landmarks=landmarks,
            )
            results.append((box, row_f))

        results.sort(key=lambda item: item[0].w * item[0].h, reverse=True)
        return results

    def extract_embedding(self, image_bgr: np.ndarray, raw_face_row: np.ndarray) -> np.ndarray:
        """Alinea el rostro, normaliza su iluminación y extrae el vector L2 (128-D)."""
        with self._lock:
            aligned = self._recognizer.alignCrop(image_bgr, raw_face_row)
            normalized = normalize_face_lighting(aligned)
            feature = self._recognizer.feature(normalized)
        return normalize_embedding(feature)
