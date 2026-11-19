from collections.abc import Generator
from pathlib import Path
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.db import create_db_engine, get_db
from app.main import create_app
from app.vision.engine import normalize_embedding
from app.vision.quality import FaceBox


def make_sharp_face_image(
    width: int = 400,
    height: int = 400,
    face_box: tuple[int, int, int, int] = (100, 80, 180, 200),
    brightness_base: int = 140,
    blur: bool = False,
) -> np.ndarray:
    """Genera una imagen BGR sintética en memoria con textura nítida para pruebas."""
    img = np.full((height, width, 3), brightness_base, dtype=np.uint8)
    x, y, w, h = face_box
    if not blur:
        # Patrón de tablero de alto contraste dentro de la región facial para varianza Laplaciana alta
        for row in range(y, min(height, y + h), 8):
            for col in range(x, min(width, x + w), 8):
                if ((row // 8) + (col // 8)) % 2 == 0:
                    cv2.rectangle(
                        img,
                        (col, row),
                        (min(width, col + 8), min(height, row + 8)),
                        (min(255, brightness_base + 55), min(255, brightness_base + 55), min(255, brightness_base + 55)),
                        -1,
                    )
                else:
                    cv2.rectangle(
                        img,
                        (col, row),
                        (min(width, col + 8), min(height, row + 8)),
                        (max(0, brightness_base - 55), max(0, brightness_base - 55), max(0, brightness_base - 55)),
                        -1,
                    )
    return img


def encode_jpeg_bytes(image_bgr: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".jpg", image_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    assert ok
    return buf.tobytes()


def make_unit_vector(seed: int, dim: int = 128) -> np.ndarray:
    rng = np.random.default_rng(seed)
    vec = rng.normal(size=dim).astype(np.float32)
    return normalize_embedding(vec)


def make_pose_landmarks(pose: str) -> list[tuple[float, float]]:
    """Genera los 5 landmarks de YuNet calibrados para cada una de las 6 poses."""
    right_eye = (150.0, 145.0)
    left_eye = (230.0, 145.0)
    right_mouth = (162.0, 225.0)
    left_mouth = (218.0, 225.0)
    nose = (190.0, 188.0)

    if pose == "left":
        nose = (210.0, 188.0)
    elif pose == "right":
        nose = (170.0, 188.0)
    elif pose == "up":
        nose = (190.0, 173.0)
    elif pose == "down":
        nose = (190.0, 203.0)
    elif pose == "smile":
        right_mouth = (152.0, 225.0)
        left_mouth = (228.0, 225.0)

    return [right_eye, left_eye, nose, right_mouth, left_mouth]


class FakeBiometricEngine:
    """Motor biométrico determinista para pruebas rápidas de integración HTTP."""

    def __init__(self) -> None:
        self.next_boxes: list[FaceBox] = [
            FaceBox(
                x=100,
                y=80,
                w=180,
                h=200,
                confidence=0.98,
                landmarks=make_pose_landmarks("frontal"),
            )
        ]
        self.next_embedding: np.ndarray = make_unit_vector(1)

    def detect(
        self,
        image_bgr: np.ndarray,
        allow_backlight_fallback: bool = True,
    ) -> list[tuple[FaceBox, np.ndarray]]:
        results: list[tuple[FaceBox, np.ndarray]] = []
        for idx, box in enumerate(self.next_boxes):
            row = np.zeros(15, dtype=np.float32)
            row[0], row[1], row[2], row[3] = box.x, box.y, box.w, box.h
            for lm_idx, (lx, ly) in enumerate(box.landmarks[:5]):
                row[4 + lm_idx * 2] = lx
                row[5 + lm_idx * 2] = ly
            row[14] = box.confidence
            results.append((box, row))
        results.sort(key=lambda item: item[0].w * item[0].h, reverse=True)
        return results

    def extract_embedding(self, image_bgr: np.ndarray, raw_face_row: np.ndarray) -> np.ndarray:
        return normalize_embedding(self.next_embedding)


@pytest.fixture()
def fake_engine() -> FakeBiometricEngine:
    return FakeBiometricEngine()


@pytest.fixture()
def api_client(
    tmp_path: Path, fake_engine: FakeBiometricEngine
) -> Generator[tuple[TestClient, sessionmaker[Session], FakeBiometricEngine, Path], None, None]:
    db_file = tmp_path / "test_identia.db"
    test_engine = create_db_engine(f"sqlite:///{db_file.as_posix()}")
    TestingSessionLocal = sessionmaker(
        bind=test_engine, autoflush=False, autocommit=False, expire_on_commit=False
    )

    app = create_app(
        biometric_engine=fake_engine,
        init_models=False,
        db_engine=test_engine,
        session_factory=TestingSessionLocal,
    )

    def _override_get_db() -> Generator[Session, None, None]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app) as client:
        yield client, TestingSessionLocal, fake_engine, tmp_path

    test_engine.dispose()
