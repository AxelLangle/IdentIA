"""Control de calidad geométrica, nitidez, iluminación y validación de poses faciales.

Evalúa cada rostro detectado por YuNet antes de extraer o guardar embeddings,
asegurando que la imagen tenga resolución suficiente, buena exposición, ausencia
de contraluz o sombras laterales severas (en enrolamiento) y coincidencia con la
pose solicitada en el asistente guiado de 6 tomas (`frontal`, `left`, `right`,
`up`, `down`, `smile`).
"""

from dataclasses import dataclass
import math
import cv2
import numpy as np


@dataclass(frozen=True)
class CuadroRostro:
    """Caja delimitadora facial y los 5 puntos de referencia detectados por YuNet."""

    coordenada_x: int
    coordenada_y: int
    ancho: int
    alto: int
    confianza: float
    puntos_referencia: list[tuple[float, float]]


@dataclass(frozen=True)
class ReporteCalidad:
    """Resultado completo de evaluación de nitidez, iluminación y orientación facial."""

    es_valida: bool
    motivo: str | None
    puntaje_nitidez: float
    brillo: float
    ancho_rostro: int
    alto_rostro: int
    pose_estimada: str
    asimetria_sombra: float = 0.0
    contraluz_detectado: bool = False
    relacion_giro_horizontal: float = 0.0
    relacion_inclinacion_vertical: float = 0.55
    relacion_boca: float = 0.72
    pose_coincide: bool = True
    retroalimentacion_pose: str | None = None


def calcular_metricas_pose(cuadro: CuadroRostro) -> tuple[float, float, float]:
    """Calcula proporciones normalizadas de giro horizontal, inclinación y apertura de boca.

    Utiliza los 5 landmarks de YuNet: ojo derecho, ojo izquierdo, punta de la nariz,
    comisura derecha y comisura izquierda de la boca.

    Returns:
        Tupla `(relacion_giro_horizontal, relacion_inclinacion_vertical, relacion_boca)`.
    """
    if len(cuadro.puntos_referencia) < 5:
        return 0.0, 0.55, 0.72

    ojo_derecho_x, ojo_derecho_y = cuadro.puntos_referencia[0]
    ojo_izquierdo_x, ojo_izquierdo_y = cuadro.puntos_referencia[1]
    nariz_x, nariz_y = cuadro.puntos_referencia[2]
    boca_derecha_x, boca_derecha_y = cuadro.puntos_referencia[3]
    boca_izquierda_x, boca_izquierda_y = cuadro.puntos_referencia[4]

    distancia_ojos = max(
        math.hypot(ojo_izquierdo_x - ojo_derecho_x, ojo_izquierdo_y - ojo_derecho_y),
        1.0,
    )
    punto_medio_ojos_x = (ojo_derecho_x + ojo_izquierdo_x) / 2.0
    punto_medio_ojos_y = (ojo_derecho_y + ojo_izquierdo_y) / 2.0

    # En la imagen cruda sin espejo: girar a la izquierda del sujeto desplaza la nariz a +X
    relacion_giro_horizontal = (nariz_x - punto_medio_ojos_x) / distancia_ojos

    punto_medio_boca_y = (boca_derecha_y + boca_izquierda_y) / 2.0
    distancia_ojos_boca = max(punto_medio_boca_y - punto_medio_ojos_y, 1.0)
    relacion_inclinacion_vertical = (nariz_y - punto_medio_ojos_y) / distancia_ojos_boca

    ancho_boca = math.hypot(
        boca_izquierda_x - boca_derecha_x,
        boca_izquierda_y - boca_derecha_y,
    )
    relacion_boca = ancho_boca / distancia_ojos

    return relacion_giro_horizontal, relacion_inclinacion_vertical, relacion_boca


def estimar_pose_rostro(cuadro: CuadroRostro) -> str:
    """Estima la etiqueta de orientación más probable a partir de los landmarks."""
    relacion_giro, relacion_inclinacion, _ = calcular_metricas_pose(cuadro)

    if relacion_giro >= 0.13:
        return "left"
    if relacion_giro <= -0.13:
        return "right"
    if relacion_inclinacion <= 0.48:
        return "up"
    if relacion_inclinacion >= 0.60:
        return "down"
    return "frontal"


def validar_pose_esperada(
    cuadro: CuadroRostro,
    pose_esperada: str,
    relacion_boca_frontal: float | None = None,
    relacion_inclinacion_frontal: float | None = None,
) -> tuple[bool, str | None]:
    """Comprueba si la geometría facial coincide con la pose pedida durante el enrolamiento.

    Cuando existe una toma frontal previa, ajusta dinámicamente los umbrales de
    inclinación vertical (`up`/`down`) y sonrisa (`smile`) respecto a la anatomía
    base de la persona.
    """
    relacion_giro, relacion_inclinacion, relacion_boca = calcular_metricas_pose(cuadro)

    if pose_esperada == "frontal":
        if abs(relacion_giro) > 0.14:
            return False, "Centra tu rostro mirando directamente al frente."
        if not (0.40 <= relacion_inclinacion <= 0.68):
            return False, "Nivela la cabeza mirando al frente sin inclinarla."
        return True, None

    if pose_esperada == "left":
        if relacion_giro < -0.08:
            return False, "Giraste hacia tu derecha; gira la cabeza hacia tu izquierda."
        if relacion_giro < 0.13:
            return False, "Gira un poco más la cabeza hacia tu izquierda."
        if relacion_giro > 0.72:
            return False, "No gires tanto; mantén ambos ojos visibles hacia tu izquierda."
        if not (0.34 <= relacion_inclinacion <= 0.74):
            return False, "Mantén la cabeza nivelada mientras giras a tu izquierda."
        return True, None

    if pose_esperada == "right":
        if relacion_giro > 0.08:
            return False, "Giraste hacia tu izquierda; gira la cabeza hacia tu derecha."
        if relacion_giro > -0.13:
            return False, "Gira un poco más la cabeza hacia tu derecha."
        if relacion_giro < -0.72:
            return False, "No gires tanto; mantén ambos ojos visibles hacia tu derecha."
        if not (0.34 <= relacion_inclinacion <= 0.74):
            return False, "Mantén la cabeza nivelada mientras giras a tu derecha."
        return True, None

    if pose_esperada == "up":
        if abs(relacion_giro) > 0.22:
            return False, "Centra tu rostro antes de mirar ligeramente hacia arriba."
        objetivo_arriba = (
            min(relacion_inclinacion_frontal - 0.05, 0.52)
            if relacion_inclinacion_frontal is not None
            else 0.49
        )
        if relacion_inclinacion > objetivo_arriba:
            return False, "Levanta un poco más el mentón mirando ligeramente hacia arriba."
        return True, None

    if pose_esperada == "down":
        if abs(relacion_giro) > 0.22:
            return False, "Centra tu rostro antes de inclinar la cabeza hacia abajo."
        objetivo_abajo = (
            max(relacion_inclinacion_frontal + 0.05, 0.57)
            if relacion_inclinacion_frontal is not None
            else 0.60
        )
        if relacion_inclinacion < objetivo_abajo:
            return False, "Inclina un poco más la cabeza hacia abajo."
        return True, None

    if pose_esperada == "smile":
        if abs(relacion_giro) > 0.18 or not (0.38 <= relacion_inclinacion <= 0.70):
            return False, "Mira al frente centrado antes de sonreír."
        if relacion_boca_frontal is not None:
            if not (relacion_boca >= relacion_boca_frontal * 1.025 or relacion_boca >= 0.78):
                return False, "Mira al frente y sonríe de forma natural."
        elif relacion_boca < 0.76:
            return False, "Mira al frente y sonríe de forma natural."
        return True, None

    return True, None


def evaluar_calidad_rostro(
    imagen_bgr: np.ndarray,
    cuadro_rostro: CuadroRostro,
    tamano_minimo_px: int = 64,
    nitidez_minima: float = 18.0,
    brillo_minimo: float = 35.0,
    brillo_maximo: float = 235.0,
    pose_esperada: str | None = None,
    relacion_boca_frontal: float | None = None,
    relacion_inclinacion_frontal: float | None = None,
    asimetria_sombra_maxima: float = 68.0,
    umbral_delta_contraluz: float = 70.0,
    iluminacion_estricta: bool = True,
) -> ReporteCalidad:
    """Evalúa tamaño mínimo, exposición, contraluz, sombra lateral, nitidez y pose.

    Args:
        imagen_bgr: Fotograma completo decodificado en BGR.
        cuadro_rostro: Detección facial principal devuelta por YuNet.
        tamano_minimo_px: Ancho y alto mínimos exigidos del rostro en píxeles.
        nitidez_minima: Varianza mínima del operador Laplaciano sobre el recorte facial.
        brillo_minimo: Luminancia media mínima permitida (0..255).
        brillo_maximo: Luminancia media máxima permitida antes de considerar sobreexposición.
        pose_esperada: Etiqueta opcional de pose obligatoria para enrolamiento.
        relacion_boca_frontal: Referencia anatómica de boca medida en pose frontal.
        relacion_inclinacion_frontal: Referencia anatómica de inclinación en pose frontal.
        asimetria_sombra_maxima: Diferencia máxima de luminancia entre mitad izquierda y derecha.
        umbral_delta_contraluz: Diferencia fondo-rostro para detectar contraluz severo.
        iluminacion_estricta: Si es `True` (enrolamiento), rechaza contraluz o sombras marcadas.

    Returns:
        Instancia `ReporteCalidad` con métricas y mensaje accionable si falla.
    """
    alto_imagen, ancho_imagen = imagen_bgr.shape[:2]
    x_inicio = max(0, cuadro_rostro.coordenada_x)
    y_inicio = max(0, cuadro_rostro.coordenada_y)
    x_fin = min(ancho_imagen, cuadro_rostro.coordenada_x + cuadro_rostro.ancho)
    y_fin = min(alto_imagen, cuadro_rostro.coordenada_y + cuadro_rostro.alto)

    relacion_giro, relacion_inclinacion, relacion_boca = calcular_metricas_pose(cuadro_rostro)
    pose_estimada = estimar_pose_rostro(cuadro_rostro)
    if pose_esperada is not None:
        pose_coincide, retroalimentacion_pose = validar_pose_esperada(
            cuadro_rostro,
            pose_esperada,
            relacion_boca_frontal=relacion_boca_frontal,
            relacion_inclinacion_frontal=relacion_inclinacion_frontal,
        )
    else:
        pose_coincide, retroalimentacion_pose = True, None

    if x_fin <= x_inicio or y_fin <= y_inicio:
        return ReporteCalidad(
            es_valida=False,
            motivo="El rostro está fuera del encuadre.",
            puntaje_nitidez=0.0,
            brillo=0.0,
            ancho_rostro=0,
            alto_rostro=0,
            pose_estimada=pose_estimada,
            asimetria_sombra=0.0,
            contraluz_detectado=False,
            relacion_giro_horizontal=relacion_giro,
            relacion_inclinacion_vertical=relacion_inclinacion,
            relacion_boca=relacion_boca,
            pose_coincide=pose_coincide,
            retroalimentacion_pose=retroalimentacion_pose,
        )

    recorte_rostro = imagen_bgr[y_inicio:y_fin, x_inicio:x_fin]
    escala_grises = cv2.cvtColor(recorte_rostro, cv2.COLOR_BGR2GRAY)
    brillo = float(np.mean(escala_grises))

    # Estira contraste en baja luz para no confundir subexposición con desenfoque óptico
    fuente_nitidez = escala_grises
    if brillo < 65.0 and (int(escala_grises.max()) - int(escala_grises.min())) > 12:
        fuente_nitidez = cv2.normalize(escala_grises, None, 0, 255, cv2.NORM_MINMAX)
    puntaje_nitidez = float(cv2.Laplacian(fuente_nitidez, cv2.CV_64F).var())

    # Detección de asimetría lateral comparando la mitad izquierda frente a la mitad derecha
    columna_media = escala_grises.shape[1] // 2
    if columna_media > 0 and escala_grises.shape[1] > columna_media:
        brillo_izquierdo = float(np.mean(escala_grises[:, :columna_media]))
        brillo_derecho = float(np.mean(escala_grises[:, columna_media:]))
        asimetria_sombra = abs(brillo_izquierdo - brillo_derecho)
    else:
        asimetria_sombra = 0.0

    # Detección de contraluz comparando la luminancia promedio del fondo contra la del rostro
    mascara_fondo = np.ones((alto_imagen, ancho_imagen), dtype=bool)
    mascara_fondo[y_inicio:y_fin, x_inicio:x_fin] = False
    if np.any(mascara_fondo):
        imagen_grises = cv2.cvtColor(imagen_bgr, cv2.COLOR_BGR2GRAY)
        brillo_fondo = float(np.mean(imagen_grises[mascara_fondo]))
    else:
        brillo_fondo = brillo
    contraluz_detectado = (
        (brillo_fondo - brillo) >= umbral_delta_contraluz and brillo < 90.0
    )

    def _construir_rechazo(motivo: str) -> ReporteCalidad:
        return ReporteCalidad(
            es_valida=False,
            motivo=motivo,
            puntaje_nitidez=puntaje_nitidez,
            brillo=brillo,
            ancho_rostro=cuadro_rostro.ancho,
            alto_rostro=cuadro_rostro.alto,
            pose_estimada=pose_estimada,
            asimetria_sombra=asimetria_sombra,
            contraluz_detectado=contraluz_detectado,
            relacion_giro_horizontal=relacion_giro,
            relacion_inclinacion_vertical=relacion_inclinacion,
            relacion_boca=relacion_boca,
            pose_coincide=pose_coincide,
            retroalimentacion_pose=retroalimentacion_pose,
        )

    if cuadro_rostro.ancho < tamano_minimo_px or cuadro_rostro.alto < tamano_minimo_px:
        return _construir_rechazo(
            "Acércate más a la cámara para mejorar la resolución del rostro."
        )

    if brillo < brillo_minimo:
        if contraluz_detectado:
            return _construir_rechazo(
                "Contraluz fuerte detectado. Ilumina tu rostro de frente o evita luz intensa detrás de ti."
            )
        return _construir_rechazo(
            "Poca iluminación en el rostro. Busca un entorno mejor iluminado."
        )

    if brillo > brillo_maximo:
        return _construir_rechazo("Exceso de luz o sobreexposición directa en el rostro.")

    if iluminacion_estricta and contraluz_detectado:
        return _construir_rechazo(
            "Contraluz detectado durante el registro. Evita tener luz intensa detrás de ti "
            "para obtener la máxima precisión en el reconocimiento."
        )

    if iluminacion_estricta and asimetria_sombra > asimetria_sombra_maxima:
        return _construir_rechazo(
            "Sombra lateral muy marcada en el rostro. Busca iluminación más pareja para el registro."
        )

    if puntaje_nitidez < nitidez_minima:
        return _construir_rechazo(
            "Imagen borrosa, mantente inmóvil un momento frente a la cámara."
        )

    return ReporteCalidad(
        es_valida=True,
        motivo=None,
        puntaje_nitidez=puntaje_nitidez,
        brillo=brillo,
        ancho_rostro=cuadro_rostro.ancho,
        alto_rostro=cuadro_rostro.alto,
        pose_estimada=pose_estimada,
        asimetria_sombra=asimetria_sombra,
        contraluz_detectado=contraluz_detectado,
        relacion_giro_horizontal=relacion_giro,
        relacion_inclinacion_vertical=relacion_inclinacion,
        relacion_boca=relacion_boca,
        pose_coincide=pose_coincide,
        retroalimentacion_pose=retroalimentacion_pose,
    )
