import numpy as np
import pytest

from app.config import get_settings
from app.vision.engine import (
    BiometricEngine,
    bytes_to_embedding,
    cosine_similarity,
    decode_image_bytes,
    embedding_to_bytes,
    enhance_frame_for_detection,
    match_embedding,
    normalize_embedding,
    normalize_face_lighting,
)
from app.vision.models_loader import ensure_models
from app.vision.quality import FaceBox, evaluate_face_quality, validate_expected_pose
from tests.conftest import (
    encode_jpeg_bytes,
    make_pose_landmarks,
    make_sharp_face_image,
    make_unit_vector,
)


def test_embedding_normalization_and_roundtrip() -> None:
    raw = np.array([3.0, 4.0, 0.0, 0.0], dtype=np.float32)
    normed = normalize_embedding(raw)
    assert np.isclose(np.linalg.norm(normed), 1.0, atol=1e-6)
    assert np.isclose(cosine_similarity(normed, normed), 1.0, atol=1e-6)

    serialized = embedding_to_bytes(normed)
    restored = bytes_to_embedding(serialized)
    assert np.allclose(normed, restored, atol=1e-6)


def test_match_embedding_thresholds_and_ambiguity() -> None:
    v1 = make_unit_vector(10)
    v2 = make_unit_vector(20)
    # Vector muy cercano a v1 pero ligeramente perturbado
    query_close_v1 = normalize_embedding(v1 + 0.08 * v2)

    gallery = [
        (1, "Ana López", v1),
        (2, "Carlos Ruiz", v2),
    ]
    decision = match_embedding(query_close_v1, gallery, threshold=0.42, margin=0.05)
    assert decision.status == "matched"
    assert decision.person_id == 1
    assert decision.person_name == "Ana López"

    # Caso ambiguo: dos personas casi equidistantes al query
    v_a = normalize_embedding(np.array([1.0, 0.1, 0.0, 0.0], dtype=np.float32))
    v_b = normalize_embedding(np.array([1.0, 0.12, 0.0, 0.0], dtype=np.float32))
    q_mid = normalize_embedding(np.array([1.0, 0.11, 0.0, 0.0], dtype=np.float32))
    ambiguous = match_embedding(
        q_mid,
        [(1, "Persona A", v_a), (2, "Persona B", v_b)],
        threshold=0.42,
        margin=0.05,
    )
    assert ambiguous.status == "ambiguous"
    assert ambiguous.person_id is None

    # Caso desconocido
    orthogonal = normalize_embedding(np.array([0.0, 0.0, 1.0, 0.0], dtype=np.float32))
    unknown = match_embedding(
        orthogonal,
        [(1, "Persona A", v_a)],
        threshold=0.42,
        margin=0.05,
    )
    assert unknown.status == "unknown"
    assert unknown.person_id is None


def test_quality_gate_rejects_poor_captures_and_accepts_good_ones() -> None:
    good_img = make_sharp_face_image(400, 400, (100, 80, 160, 180), brightness_base=140, blur=False)
    good_box = FaceBox(
        x=100,
        y=80,
        w=160,
        h=180,
        confidence=0.98,
        landmarks=[(145.0, 130.0), (215.0, 130.0), (180.0, 170.0), (155.0, 210.0), (205.0, 210.0)],
    )
    report = evaluate_face_quality(good_img, good_box, min_size_px=64, min_blur=35.0)
    assert report.ok is True
    assert report.pose_hint == "frontal"

    # Muy pequeño
    small_box = FaceBox(x=100, y=80, w=40, h=40, confidence=0.95, landmarks=[])
    small_rep = evaluate_face_quality(good_img, small_box, min_size_px=64)
    assert small_rep.ok is False
    assert "Acércate" in (small_rep.reason or "")

    # Muy oscuro
    dark_img = np.full((400, 400, 3), 15, dtype=np.uint8)
    dark_rep = evaluate_face_quality(dark_img, good_box, min_brightness=35.0)
    assert dark_rep.ok is False
    assert "iluminación" in (dark_rep.reason or "")

    # Borroso / sin textura
    blur_img = make_sharp_face_image(400, 400, (100, 80, 160, 180), brightness_base=140, blur=True)
    blur_rep = evaluate_face_quality(blur_img, good_box, min_blur=35.0)
    assert blur_rep.ok is False
    assert "borrosa" in (blur_rep.reason or "")


def test_decode_image_bytes_downscales_and_rejects_corrupt() -> None:
    big = make_sharp_face_image(2000, 1000)
    decoded = decode_image_bytes(encode_jpeg_bytes(big), max_dim=1280)
    assert max(decoded.shape[:2]) == 1280
    assert decoded.shape[1] == 1280
    assert decoded.shape[0] == 640

    with pytest.raises(ValueError):
        decode_image_bytes(b"not-an-image")


def test_real_onnx_models_load_and_infer() -> None:
    settings = get_settings()
    yunet_path, sface_path = ensure_models(settings.models_dir)
    assert yunet_path.exists()
    assert sface_path.exists()

    engine = BiometricEngine(
        yunet_path=yunet_path,
        sface_path=sface_path,
        score_threshold=settings.yunet_score_threshold,
        nms_threshold=settings.yunet_nms_threshold,
    )
    blank = np.zeros((320, 320, 3), dtype=np.uint8)
    assert engine.detect(blank) == []

    synthetic_row = np.array(
        [100, 80, 120, 140, 135, 130, 185, 130, 160, 160, 140, 195, 180, 195, 0.99],
        dtype=np.float32,
    )
    sample_img = make_sharp_face_image(320, 320, (100, 80, 120, 140))
    emb = engine.extract_embedding(sample_img, synthetic_row)
    assert emb.shape == (128,)
    assert emb.dtype == np.float32
    assert np.isclose(np.linalg.norm(emb), 1.0, atol=1e-5)


def test_lighting_normalization_rescues_dark_crops() -> None:
    # En iluminación normal, normalize_face_lighting no debe alterar la imagen para preservar precisión nativa
    well_lit = np.full((112, 112, 3), 135, dtype=np.uint8)
    well_lit[20:90, 25:85] = 155
    assert np.array_equal(normalize_face_lighting(well_lit), well_lit)

    dark_crop = np.full((112, 112, 3), 25, dtype=np.uint8)
    dark_crop[20:90, 25:85] = 40
    normalized = normalize_face_lighting(dark_crop)
    assert normalized.shape == (112, 112, 3)
    assert float(np.mean(normalized)) > 70.0
    assert float(np.mean(normalized)) > float(np.mean(dark_crop)) * 2.0

    dark_frame = np.full((240, 320, 3), 28, dtype=np.uint8)
    boosted = enhance_frame_for_detection(dark_frame)
    assert boosted.shape == dark_frame.shape
    assert float(np.mean(boosted)) > float(np.mean(dark_frame))


def test_relative_pitch_and_natural_smile() -> None:
    # Cámara alta: frontal en pitch_ratio=0.57 y mentón arriba suave en pitch_ratio=0.50
    gentle_up_box = FaceBox(
        100,
        80,
        180,
        200,
        0.98,
        [(150.0, 145.0), (230.0, 145.0), (190.0, 185.0), (162.0, 225.0), (218.0, 225.0)],
    )
    ok_up, msg_up = validate_expected_pose(gentle_up_box, "up", frontal_pitch_ratio=0.57)
    assert ok_up is True, msg_up

    # Sonrisa natural (+3% respecto a frontal_mouth_ratio=0.70 -> mouth_ratio=0.721)
    natural_smile_box = FaceBox(
        100,
        80,
        180,
        200,
        0.98,
        [(150.0, 145.0), (230.0, 145.0), (190.0, 188.0), (161.0, 225.0), (219.0, 225.0)],
    )
    ok_smile, msg_smile = validate_expected_pose(
        natural_smile_box, "smile", frontal_mouth_ratio=0.70
    )
    assert ok_smile is True, msg_smile

    neutral_box = FaceBox(100, 80, 180, 200, 0.98, make_pose_landmarks("frontal"))
    ok_neutral, _ = validate_expected_pose(neutral_box, "smile", frontal_mouth_ratio=0.70)
    assert ok_neutral is False


def test_pose_validation_geometry_all_six_poses() -> None:
    poses = ("frontal", "left", "right", "up", "down", "smile")
    for expected in poses:
        box = FaceBox(100, 80, 180, 200, 0.98, make_pose_landmarks(expected))
        ok, feedback = validate_expected_pose(box, expected, frontal_mouth_ratio=0.70)
        assert ok is True, f"Pose {expected} debería pasar: {feedback}"

        # Un rostro frontal no debe pasar como pose lateral/vertical/sonrisa
        if expected != "frontal":
            frontal_box = FaceBox(100, 80, 180, 200, 0.98, make_pose_landmarks("frontal"))
            ok_wrong, msg_wrong = validate_expected_pose(
                frontal_box, expected, frontal_mouth_ratio=0.70
            )
            assert ok_wrong is False
            assert msg_wrong is not None

    # Verifica polaridad exacta izquierda vs derecha
    left_box = FaceBox(100, 80, 180, 200, 0.98, make_pose_landmarks("left"))
    ok_swap, msg_swap = validate_expected_pose(left_box, "right")
    assert ok_swap is False
    assert "izquierda" in (msg_swap or "").lower()


def test_backlight_and_side_shadow_detection() -> None:
    # Fondo muy brillante (240) con rostro muy oscuro (25) -> contraluz fuerte
    backlight_img = np.full((400, 400, 3), 240, dtype=np.uint8)
    backlight_img[80:280, 100:280] = 25
    box = FaceBox(100, 80, 180, 200, 0.98, make_pose_landmarks("frontal"))

    enroll_rep = evaluate_face_quality(
        backlight_img,
        box,
        min_brightness=45.0,
        backlight_delta_threshold=70.0,
        strict_lighting=True,
    )
    assert enroll_rep.ok is False
    assert enroll_rep.backlight_detected is True
    assert "Contraluz" in (enroll_rep.reason or "")

    # Sombra lateral marcada: mitad izquierda brillante (200), derecha oscura (60) -> asimetría 140
    shadow_img = make_sharp_face_image(400, 400, (100, 80, 180, 200), brightness_base=140)
    shadow_img[80:280, 100:190] = 200
    shadow_img[80:280, 190:280] = 60

    strict_rep = evaluate_face_quality(
        shadow_img,
        box,
        min_brightness=32.0,
        max_shadow_asymmetry=68.0,
        strict_lighting=True,
    )
    assert strict_rep.ok is False
    assert strict_rep.shadow_asymmetry > 68.0
    assert "Sombra lateral" in (strict_rep.reason or "")

    # En modo kiosco (strict_lighting=False), tolera sombra moderada si nitidez/brillo cumplen
    kiosk_img = make_sharp_face_image(400, 400, (100, 80, 180, 200), brightness_base=140)
    kiosk_img[80:280, 100:190] = np.clip(kiosk_img[80:280, 100:190].astype(np.int16) + 35, 0, 255).astype(np.uint8)
    kiosk_img[80:280, 190:280] = np.clip(kiosk_img[80:280, 190:280].astype(np.int16) - 35, 0, 255).astype(np.uint8)
    kiosk_rep = evaluate_face_quality(
        kiosk_img,
        box,
        min_brightness=20.0,
        strict_lighting=False,
    )
    assert kiosk_rep.ok is True

    # Contraluz moderado (rostro nítido brillo ~55 con fondo brillante 235):
    # bloqueado en enrolamiento (strict_lighting=True), permitido en kiosco (strict_lighting=False)
    mod_face = make_sharp_face_image(400, 400, (100, 80, 180, 200), brightness_base=55)
    mod_backlight = np.full((400, 400, 3), 235, dtype=np.uint8)
    mod_backlight[80:280, 100:280] = mod_face[80:280, 100:280]

    strict_bl = evaluate_face_quality(
        mod_backlight,
        box,
        min_brightness=32.0,
        backlight_delta_threshold=70.0,
        strict_lighting=True,
    )
    assert strict_bl.ok is False
    assert strict_bl.backlight_detected is True
    assert "Contraluz" in (strict_bl.reason or "")

    kiosk_bl = evaluate_face_quality(
        mod_backlight,
        box,
        min_brightness=18.0,
        backlight_delta_threshold=70.0,
        strict_lighting=False,
    )
    assert kiosk_bl.ok is True
    assert kiosk_bl.backlight_detected is True
