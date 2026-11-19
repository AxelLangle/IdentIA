from dataclasses import dataclass
import math
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
    """Resultado de evaluación de calidad, iluminación y geometría facial."""

    ok: bool
    reason: str | None
    blur_score: float
    brightness: float
    face_width: int
    face_height: int
    pose_hint: str
    shadow_asymmetry: float = 0.0
    backlight_detected: bool = False
    yaw_ratio: float = 0.0
    pitch_ratio: float = 0.55
    mouth_ratio: float = 0.72
    pose_matches: bool = True
    pose_feedback: str | None = None


def compute_pose_metrics(box: FaceBox) -> tuple[float, float, float]:
    """Calcula yaw_ratio, pitch_ratio y mouth_ratio usando los 5 landmarks de YuNet."""
    if len(box.landmarks) < 5:
        return 0.0, 0.55, 0.72

    right_eye_x, right_eye_y = box.landmarks[0]
    left_eye_x, left_eye_y = box.landmarks[1]
    nose_x, nose_y = box.landmarks[2]
    right_mouth_x, right_mouth_y = box.landmarks[3]
    left_mouth_x, left_mouth_y = box.landmarks[4]

    eye_dist = max(math.hypot(left_eye_x - right_eye_x, left_eye_y - right_eye_y), 1.0)
    mid_eye_x = (right_eye_x + left_eye_x) / 2.0
    mid_eye_y = (right_eye_y + left_eye_y) / 2.0

    # En imagen cruda sin espejo: girar hacia la izquierda del sujeto desplaza la nariz a +X
    yaw_ratio = (nose_x - mid_eye_x) / eye_dist

    mid_mouth_y = (right_mouth_y + left_mouth_y) / 2.0
    eye_to_mouth = max(mid_mouth_y - mid_eye_y, 1.0)
    pitch_ratio = (nose_y - mid_eye_y) / eye_to_mouth

    mouth_width = math.hypot(left_mouth_x - right_mouth_x, left_mouth_y - right_mouth_y)
    mouth_ratio = mouth_width / eye_dist

    return yaw_ratio, pitch_ratio, mouth_ratio


def estimate_pose_hint(box: FaceBox) -> str:
    """Estima la orientación del rostro usando las proporciones de landmarks."""
    yaw_ratio, pitch_ratio, _ = compute_pose_metrics(box)

    if yaw_ratio >= 0.14:
        return "left"
    if yaw_ratio <= -0.14:
        return "right"
    if pitch_ratio <= 0.45:
        return "up"
    if pitch_ratio >= 0.62:
        return "down"
    return "frontal"


def validate_expected_pose(
    box: FaceBox,
    expected_pose: str,
    frontal_mouth_ratio: float | None = None,
) -> tuple[bool, str | None]:
    """Valida estrictamente si el rostro coincide con la pose solicitada."""
    yaw_ratio, pitch_ratio, mouth_ratio = compute_pose_metrics(box)

    if expected_pose == "frontal":
        if abs(yaw_ratio) > 0.12:
            return False, "Centra tu rostro mirando directamente al frente."
        if not (0.45 <= pitch_ratio <= 0.63):
            return False, "Nivela la cabeza mirando al frente sin inclinarla."
        return True, None

    if expected_pose == "left":
        if yaw_ratio < -0.08:
            return False, "Giraste hacia tu derecha; gira la cabeza hacia tu izquierda."
        if yaw_ratio < 0.14:
            return False, "Gira un poco más la cabeza hacia tu izquierda."
        if yaw_ratio > 0.70:
            return False, "No gires tanto; mantén ambos ojos visibles hacia tu izquierda."
        if not (0.38 <= pitch_ratio <= 0.70):
            return False, "Mantén la cabeza nivelada mientras giras a tu izquierda."
        return True, None

    if expected_pose == "right":
        if yaw_ratio > 0.08:
            return False, "Giraste hacia tu izquierda; gira la cabeza hacia tu derecha."
        if yaw_ratio > -0.14:
            return False, "Gira un poco más la cabeza hacia tu derecha."
        if yaw_ratio < -0.70:
            return False, "No gires tanto; mantén ambos ojos visibles hacia tu derecha."
        if not (0.38 <= pitch_ratio <= 0.70):
            return False, "Mantén la cabeza nivelada mientras giras a tu derecha."
        return True, None

    if expected_pose == "up":
        if abs(yaw_ratio) > 0.18:
            return False, "Centra tu rostro antes de mirar ligeramente hacia arriba."
        if pitch_ratio > 0.45:
            return False, "Levanta un poco más el mentón mirando ligeramente hacia arriba."
        return True, None

    if expected_pose == "down":
        if abs(yaw_ratio) > 0.18:
            return False, "Centra tu rostro antes de inclinar la cabeza hacia abajo."
        if pitch_ratio < 0.62:
            return False, "Inclina un poco más la cabeza hacia abajo."
        return True, None

    if expected_pose == "smile":
        if abs(yaw_ratio) > 0.15 or not (0.42 <= pitch_ratio <= 0.66):
            return False, "Mira al frente centrado antes de sonreír."
        if frontal_mouth_ratio is not None:
            if not (mouth_ratio >= frontal_mouth_ratio * 1.05 or mouth_ratio >= 0.82):
                return False, "Mira al frente y sonríe de forma más marcada."
        elif mouth_ratio < 0.78:
            return False, "Mira al frente y sonríe de forma más marcada."
        return True, None

    return True, None


def evaluate_face_quality(
    image_bgr: np.ndarray,
    face_box: FaceBox,
    min_size_px: int = 64,
    min_blur: float = 35.0,
    min_brightness: float = 35.0,
    max_brightness: float = 235.0,
    expected_pose: str | None = None,
    frontal_mouth_ratio: float | None = None,
    max_shadow_asymmetry: float = 52.0,
    backlight_delta_threshold: float = 70.0,
    strict_lighting: bool = True,
) -> QualityReport:
    """Valida tamaño, iluminación, contraluz, sombra lateral, nitidez y pose."""
    img_h, img_w = image_bgr.shape[:2]
    x1 = max(0, face_box.x)
    y1 = max(0, face_box.y)
    x2 = min(img_w, face_box.x + face_box.w)
    y2 = min(img_h, face_box.y + face_box.h)

    yaw_ratio, pitch_ratio, mouth_ratio = compute_pose_metrics(face_box)
    pose_hint = estimate_pose_hint(face_box)
    if expected_pose is not None:
        pose_matches, pose_feedback = validate_expected_pose(
            face_box, expected_pose, frontal_mouth_ratio=frontal_mouth_ratio
        )
    else:
        pose_matches, pose_feedback = True, None

    if x2 <= x1 or y2 <= y1:
        return QualityReport(
            ok=False,
            reason="El rostro está fuera del encuadre.",
            blur_score=0.0,
            brightness=0.0,
            face_width=0,
            face_height=0,
            pose_hint=pose_hint,
            shadow_asymmetry=0.0,
            backlight_detected=False,
            yaw_ratio=yaw_ratio,
            pitch_ratio=pitch_ratio,
            mouth_ratio=mouth_ratio,
            pose_matches=pose_matches,
            pose_feedback=pose_feedback,
        )

    crop = image_bgr[y1:y2, x1:x2]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    brightness = float(np.mean(gray))

    # Contraste estirado en baja luz para no confundir subexposición con desenfoque
    blur_source = gray
    if brightness < 90.0 and (int(gray.max()) - int(gray.min())) > 12:
        blur_source = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    blur_score = float(cv2.Laplacian(blur_source, cv2.CV_64F).var())

    # Detección de asimetría de sombra lateral (mitad izquierda vs derecha)
    mid_col = gray.shape[1] // 2
    if mid_col > 0 and gray.shape[1] > mid_col:
        shadow_asymmetry = abs(float(np.mean(gray[:, :mid_col])) - float(np.mean(gray[:, mid_col:])))
    else:
        shadow_asymmetry = 0.0

    # Detección de contraluz comparando fondo fuera de la caja facial
    bg_mask = np.ones((img_h, img_w), dtype=bool)
    bg_mask[y1:y2, x1:x2] = False
    if np.any(bg_mask):
        img_gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        bg_brightness = float(np.mean(img_gray[bg_mask]))
    else:
        bg_brightness = brightness
    backlight_detected = (
        (bg_brightness - brightness) >= backlight_delta_threshold and brightness < 90.0
    )

    def _fail(reason: str) -> QualityReport:
        return QualityReport(
            ok=False,
            reason=reason,
            blur_score=blur_score,
            brightness=brightness,
            face_width=face_box.w,
            face_height=face_box.h,
            pose_hint=pose_hint,
            shadow_asymmetry=shadow_asymmetry,
            backlight_detected=backlight_detected,
            yaw_ratio=yaw_ratio,
            pitch_ratio=pitch_ratio,
            mouth_ratio=mouth_ratio,
            pose_matches=pose_matches,
            pose_feedback=pose_feedback,
        )

    if face_box.w < min_size_px or face_box.h < min_size_px:
        return _fail("Acércate más a la cámara para mejorar la resolución del rostro.")

    if brightness < min_brightness:
        if backlight_detected:
            return _fail(
                "Contraluz fuerte detectado. Ilumina tu rostro de frente o evita luz intensa detrás de ti."
            )
        return _fail("Poca iluminación en el rostro. Busca un entorno mejor iluminado.")

    if brightness > max_brightness:
        return _fail("Exceso de luz o sobreexposición directa en el rostro.")

    if strict_lighting and shadow_asymmetry > max_shadow_asymmetry:
        return _fail(
            "Sombra lateral muy marcada en el rostro. Busca iluminación más pareja para el registro."
        )

    if blur_score < min_blur:
        return _fail("Imagen borrosa, mantente inmóvil un momento frente a la cámara.")

    return QualityReport(
        ok=True,
        reason=None,
        blur_score=blur_score,
        brightness=brightness,
        face_width=face_box.w,
        face_height=face_box.h,
        pose_hint=pose_hint,
        shadow_asymmetry=shadow_asymmetry,
        backlight_detected=backlight_detected,
        yaw_ratio=yaw_ratio,
        pitch_ratio=pitch_ratio,
        mouth_ratio=mouth_ratio,
        pose_matches=pose_matches,
        pose_feedback=pose_feedback,
    )
