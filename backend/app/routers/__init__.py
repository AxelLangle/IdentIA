"""Routers HTTP y utilidades compartidas de serialización de IdentIA."""

from app.schemas import FaceBoxSchema, QualityReportSchema
from app.vision.quality import FaceBox, QualityReport


def to_face_box_schema(box: FaceBox, img_w: int, img_h: int) -> FaceBoxSchema:
    """Convierte una detección FaceBox a coordenadas absolutas y normalizadas."""
    return FaceBoxSchema(
        x=box.x,
        y=box.y,
        w=box.w,
        h=box.h,
        confidence=round(box.confidence, 4),
        image_width=img_w,
        image_height=img_h,
        nx=round(max(0.0, box.x) / max(img_w, 1), 4),
        ny=round(max(0.0, box.y) / max(img_h, 1), 4),
        nw=round(max(0.0, box.w) / max(img_w, 1), 4),
        nh=round(max(0.0, box.h) / max(img_h, 1), 4),
    )


def to_quality_schema(quality: QualityReport) -> QualityReportSchema:
    """Convierte un QualityReport interno a esquema JSON de respuesta."""
    return QualityReportSchema(
        ok=quality.ok,
        reason=quality.reason,
        blur_score=round(quality.blur_score, 2),
        brightness=round(quality.brightness, 2),
        face_width=quality.face_width,
        face_height=quality.face_height,
        pose_hint=quality.pose_hint,
        shadow_asymmetry=round(quality.shadow_asymmetry, 2),
        backlight_detected=quality.backlight_detected,
        yaw_ratio=round(quality.yaw_ratio, 4),
        pitch_ratio=round(quality.pitch_ratio, 4),
        mouth_ratio=round(quality.mouth_ratio, 4),
        pose_matches=quality.pose_matches,
        pose_feedback=quality.pose_feedback,
    )
