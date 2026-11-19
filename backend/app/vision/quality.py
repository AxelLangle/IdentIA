from dataclasses import dataclass
import cv2
import numpy as np


@dataclass(frozen=True)
class FaceBox:
    """Caja delimitadora y puntos clave faciales detectados por YuNet."""

    x: int
    y: int
    w: int
    h: int
    confidence: float
    landmarks: list[tuple[float, float]]


@dataclass(frozen=True)
class QualityReport:
    """Resultado de evaluación de calidad de un rostro capturado."""

    ok: bool
    reason: str | None
    blur_score: float
    brightness: float
    face_width: int
    face_height: int
    pose_hint: str


def estimate_pose_hint(box: FaceBox) -> str:
    """Estima de manera ligera la orientación del rostro usando landmarks de YuNet."""
    if len(box.landmarks) < 3:
        return "frontal"

    right_eye_x, right_eye_y = box.landmarks[0]
    left_eye_x, left_eye_y = box.landmarks[1]
    nose_x, nose_y = box.landmarks[2]

    mid_eye_x = (right_eye_x + left_eye_x) / 2.0
    mid_eye_y = (right_eye_y + left_eye_y) / 2.0
    eye_dist = max(abs(left_eye_x - right_eye_x), 1.0)

    dx_norm = (nose_x - mid_eye_x) / eye_dist
    dy_norm = (nose_y - mid_eye_y) / eye_dist

    if dx_norm > 0.18:
        return "right"
    if dx_norm < -0.18:
        return "left"
    if dy_norm < 0.35:
        return "up"
    return "frontal"


def evaluate_face_quality(
    image_bgr: np.ndarray,
    face_box: FaceBox,
    min_size_px: int = 64,
    min_blur: float = 35.0,
    min_brightness: float = 35.0,
    max_brightness: float = 235.0,
) -> QualityReport:
    """Valida tamaño mínimo, iluminación y nitidez del recorte facial."""
    img_h, img_w = image_bgr.shape[:2]
    x1 = max(0, face_box.x)
    y1 = max(0, face_box.y)
    x2 = min(img_w, face_box.x + face_box.w)
    y2 = min(img_h, face_box.y + face_box.h)

    pose_hint = estimate_pose_hint(face_box)

    if x2 <= x1 or y2 <= y1:
        return QualityReport(
            ok=False,
            reason="El rostro está fuera del encuadre.",
            blur_score=0.0,
            brightness=0.0,
            face_width=0,
            face_height=0,
            pose_hint=pose_hint,
        )

    crop = image_bgr[y1:y2, x1:x2]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    brightness = float(np.mean(gray))
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    if face_box.w < min_size_px or face_box.h < min_size_px:
        return QualityReport(
            ok=False,
            reason="Acércate más a la cámara para mejorar la resolución del rostro.",
            blur_score=blur_score,
            brightness=brightness,
            face_width=face_box.w,
            face_height=face_box.h,
            pose_hint=pose_hint,
        )

    if brightness < min_brightness:
        return QualityReport(
            ok=False,
            reason="Poca iluminación en el rostro. Busca un entorno mejor iluminado.",
            blur_score=blur_score,
            brightness=brightness,
            face_width=face_box.w,
            face_height=face_box.h,
            pose_hint=pose_hint,
        )

    if brightness > max_brightness:
        return QualityReport(
            ok=False,
            reason="Exceso de luz o contraluz en el rostro.",
            blur_score=blur_score,
            brightness=brightness,
            face_width=face_box.w,
            face_height=face_box.h,
            pose_hint=pose_hint,
        )

    if blur_score < min_blur:
        return QualityReport(
            ok=False,
            reason="Imagen borrosa, mantente inmóvil un momento frente a la cámara.",
            blur_score=blur_score,
            brightness=brightness,
            face_width=face_box.w,
            face_height=face_box.h,
            pose_hint=pose_hint,
        )

    return QualityReport(
        ok=True,
        reason=None,
        blur_score=blur_score,
        brightness=brightness,
        face_width=face_box.w,
        face_height=face_box.h,
        pose_hint=pose_hint,
    )
