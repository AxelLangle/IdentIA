"""Enrutadores HTTP de FastAPI y convertidores compartidos de geometría facial."""

from app.schemas import EsquemaCuadroRostro, EsquemaReporteCalidad
from app.vision.quality import CuadroRostro, ReporteCalidad


def convertir_a_esquema_cuadro_rostro(
    cuadro: CuadroRostro,
    ancho_imagen: int,
    alto_imagen: int,
) -> EsquemaCuadroRostro:
    """Convierte una detección `CuadroRostro` a coordenadas absolutas y normalizadas (0..1)."""
    return EsquemaCuadroRostro(
        coordenada_x=cuadro.coordenada_x,
        coordenada_y=cuadro.coordenada_y,
        ancho=cuadro.ancho,
        alto=cuadro.alto,
        confianza=round(cuadro.confianza, 4),
        ancho_imagen=ancho_imagen,
        alto_imagen=alto_imagen,
        coordenada_x_normalizada=round(max(0.0, cuadro.coordenada_x) / max(ancho_imagen, 1), 4),
        coordenada_y_normalizada=round(max(0.0, cuadro.coordenada_y) / max(alto_imagen, 1), 4),
        ancho_normalizado=round(max(0.0, cuadro.ancho) / max(ancho_imagen, 1), 4),
        alto_normalizado=round(max(0.0, cuadro.alto) / max(alto_imagen, 1), 4),
    )


def convertir_a_esquema_calidad(calidad: ReporteCalidad) -> EsquemaReporteCalidad:
    """Convierte un `ReporteCalidad` interno al esquema JSON de respuesta HTTP."""
    return EsquemaReporteCalidad(
        es_valida=calidad.es_valida,
        motivo=calidad.motivo,
        puntaje_nitidez=round(calidad.puntaje_nitidez, 2),
        brillo=round(calidad.brillo, 2),
        ancho_rostro=calidad.ancho_rostro,
        alto_rostro=calidad.alto_rostro,
        pose_estimada=calidad.pose_estimada,
        asimetria_sombra=round(calidad.asimetria_sombra, 2),
        contraluz_detectado=calidad.contraluz_detectado,
        relacion_giro_horizontal=round(calidad.relacion_giro_horizontal, 4),
        relacion_inclinacion_vertical=round(calidad.relacion_inclinacion_vertical, 4),
        relacion_boca=round(calidad.relacion_boca, 4),
        pose_coincide=calidad.pose_coincide,
        retroalimentacion_pose=calidad.retroalimentacion_pose,
    )
