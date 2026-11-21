"""Pruebas unitarias y de inferencia real para el módulo de visión biométrica.

Valida normalización L2, búsqueda 1:N con ambigüedad, compuerta de calidad,
decodificación en memoria, carga real de modelos ONNX YuNet/SFace, compensación
de iluminación extrema en espacio LAB, geometría de 6 poses y detección de
contraluz/sombras laterales.
"""

import numpy as np
import pytest

from app.config import obtener_configuracion
from app.vision.engine import (
    MotorBiometrico,
    bytes_a_vector,
    coincidir_vector,
    decodificar_bytes_imagen,
    normalizar_iluminacion_rostro,
    normalizar_vector,
    realzar_frame_para_deteccion,
    similitud_coseno,
    vector_a_bytes,
)
from app.vision.models_loader import asegurar_modelos
from app.vision.quality import (
    CuadroRostro,
    evaluar_calidad_rostro,
    validar_pose_esperada,
)
from tests.conftest import (
    codificar_bytes_jpeg,
    crear_imagen_rostro_nitida,
    crear_puntos_pose,
    crear_vector_unitario,
)


def test_normalizacion_vector_y_serializacion() -> None:
    """Comprueba normalización L2, similitud consigo mismo y ida/vuelta en bytes."""
    vector_crudo = np.array([3.0, 4.0, 0.0, 0.0], dtype=np.float32)
    vector_normalizado = normalizar_vector(vector_crudo)
    assert np.isclose(np.linalg.norm(vector_normalizado), 1.0, atol=1e-6)
    assert np.isclose(similitud_coseno(vector_normalizado, vector_normalizado), 1.0, atol=1e-6)

    bytes_serializados = vector_a_bytes(vector_normalizado)
    vector_restaurado = bytes_a_vector(bytes_serializados)
    assert np.allclose(vector_normalizado, vector_restaurado, atol=1e-6)


def test_umbrales_coincidencia_y_ambiguedad() -> None:
    """Valida decisiones matched, ambiguous y unknown según umbral y margen."""
    vector_1 = crear_vector_unitario(10)
    vector_2 = crear_vector_unitario(20)
    consulta_cercana = normalizar_vector(vector_1 + 0.08 * vector_2)

    galeria = [
        (1, "Ana López", vector_1),
        (2, "Carlos Ruiz", vector_2),
    ]
    decision = coincidir_vector(consulta_cercana, galeria, umbral=0.42, margen=0.05)
    assert decision.estado == "matched"
    assert decision.id_persona == 1
    assert decision.nombre_persona == "Ana López"

    # Caso ambiguo: dos candidatos casi equidistantes al vector de consulta
    vector_a = normalizar_vector(np.array([1.0, 0.1, 0.0, 0.0], dtype=np.float32))
    vector_b = normalizar_vector(np.array([1.0, 0.12, 0.0, 0.0], dtype=np.float32))
    consulta_intermedia = normalizar_vector(np.array([1.0, 0.11, 0.0, 0.0], dtype=np.float32))
    decision_ambigua = coincidir_vector(
        consulta_intermedia,
        [(1, "Persona A", vector_a), (2, "Persona B", vector_b)],
        umbral=0.42,
        margen=0.05,
    )
    assert decision_ambigua.estado == "ambiguous"
    assert decision_ambigua.id_persona is None

    # Caso desconocido: vector ortogonal por debajo del umbral mínimo
    vector_ortogonal = normalizar_vector(np.array([0.0, 0.0, 1.0, 0.0], dtype=np.float32))
    decision_desconocida = coincidir_vector(
        vector_ortogonal,
        [(1, "Persona A", vector_a)],
        umbral=0.42,
        margen=0.05,
    )
    assert decision_desconocida.estado == "unknown"
    assert decision_desconocida.id_persona is None


def test_compuerta_calidad_rechaza_capturas_deficientes_y_acepta_validas() -> None:
    """Verifica rechazo por tamaño reducido, baja luz o desenfoque, y aceptación en condiciones óptimas."""
    imagen_optima = crear_imagen_rostro_nitida(
        400, 400, (100, 80, 160, 180), brillo_base=140, desenfocada=False
    )
    cuadro_optimo = CuadroRostro(
        coordenada_x=100,
        coordenada_y=80,
        ancho=160,
        alto=180,
        confianza=0.98,
        puntos_referencia=[
            (145.0, 130.0),
            (215.0, 130.0),
            (180.0, 170.0),
            (155.0, 210.0),
            (205.0, 210.0),
        ],
    )
    reporte_valido = evaluar_calidad_rostro(
        imagen_optima, cuadro_optimo, tamano_minimo_px=64, nitidez_minima=35.0
    )
    assert reporte_valido.es_valida is True
    assert reporte_valido.pose_estimada == "frontal"

    # Rostro demasiado pequeño
    cuadro_pequeno = CuadroRostro(
        coordenada_x=100,
        coordenada_y=80,
        ancho=40,
        alto=40,
        confianza=0.95,
        puntos_referencia=[],
    )
    reporte_pequeno = evaluar_calidad_rostro(imagen_optima, cuadro_pequeno, tamano_minimo_px=64)
    assert reporte_pequeno.es_valida is False
    assert "Acércate" in (reporte_pequeno.motivo or "")

    # Imagen demasiado oscura
    imagen_oscura = np.full((400, 400, 3), 15, dtype=np.uint8)
    reporte_oscuro = evaluar_calidad_rostro(imagen_oscura, cuadro_optimo, brillo_minimo=35.0)
    assert reporte_oscuro.es_valida is False
    assert "iluminación" in (reporte_oscuro.motivo or "")

    # Imagen borrosa sin textura
    imagen_borrosa = crear_imagen_rostro_nitida(
        400, 400, (100, 80, 160, 180), brillo_base=140, desenfocada=True
    )
    reporte_borroso = evaluar_calidad_rostro(imagen_borrosa, cuadro_optimo, nitidez_minima=35.0)
    assert reporte_borroso.es_valida is False
    assert "borrosa" in (reporte_borroso.motivo or "")


def test_decodificacion_bytes_escala_y_rechaza_corruptos() -> None:
    """Confirma reducción proporcional a `dimension_maxima` y error ante bytes corruptos."""
    imagen_grande = crear_imagen_rostro_nitida(2000, 1000)
    imagen_decodificada = decodificar_bytes_imagen(
        codificar_bytes_jpeg(imagen_grande), dimension_maxima=1280
    )
    assert max(imagen_decodificada.shape[:2]) == 1280
    assert imagen_decodificada.shape[1] == 1280
    assert imagen_decodificada.shape[0] == 640

    with pytest.raises(ValueError):
        decodificar_bytes_imagen(b"no-es-una-imagen")


def test_carga_e_inferencia_modelos_onnx_reales() -> None:
    """Carga los archivos ONNX reales de YuNet y SFace y extrae un vector de 128 dimensiones."""
    configuracion = obtener_configuracion()
    ruta_yunet, ruta_sface = asegurar_modelos(configuracion.directorio_modelos)
    assert ruta_yunet.exists()
    assert ruta_sface.exists()

    motor = MotorBiometrico(
        ruta_yunet=ruta_yunet,
        ruta_sface=ruta_sface,
        umbral_deteccion=configuracion.umbral_deteccion_yunet,
        umbral_supresion=configuracion.umbral_supresion_yunet,
    )
    lienzo_vacio = np.zeros((320, 320, 3), dtype=np.uint8)
    assert motor.detectar(lienzo_vacio) == []

    fila_sintetica = np.array(
        [100, 80, 120, 140, 135, 130, 185, 130, 160, 160, 140, 195, 180, 195, 0.99],
        dtype=np.float32,
    )
    imagen_muestra = crear_imagen_rostro_nitida(320, 320, (100, 80, 120, 140))
    vector = motor.extraer_vector(imagen_muestra, fila_sintetica)
    assert vector.shape == (128,)
    assert vector.dtype == np.float32
    assert np.isclose(np.linalg.norm(vector), 1.0, atol=1e-5)


def test_normalizacion_iluminacion_rescata_recortes_oscuros() -> None:
    """Valida preservación en luz normal y realce en recortes/frames subexpuestos."""
    rostro_bien_iluminado = np.full((112, 112, 3), 135, dtype=np.uint8)
    rostro_bien_iluminado[20:90, 25:85] = 155
    assert np.array_equal(normalizar_iluminacion_rostro(rostro_bien_iluminado), rostro_bien_iluminado)

    recorte_oscuro = np.full((112, 112, 3), 25, dtype=np.uint8)
    recorte_oscuro[20:90, 25:85] = 40
    recorte_normalizado = normalizar_iluminacion_rostro(recorte_oscuro)
    assert recorte_normalizado.shape == (112, 112, 3)
    assert float(np.mean(recorte_normalizado)) > 70.0
    assert float(np.mean(recorte_normalizado)) > float(np.mean(recorte_oscuro)) * 2.0

    frame_oscuro = np.full((240, 320, 3), 28, dtype=np.uint8)
    frame_realzado = realzar_frame_para_deteccion(frame_oscuro)
    assert frame_realzado.shape == frame_oscuro.shape
    assert float(np.mean(frame_realzado)) > float(np.mean(frame_oscuro))


def test_inclinacion_relativa_y_sonrisa_natural() -> None:
    """Comprueba validación relativa de poses `up` y `smile` respecto a la toma frontal."""
    # Cámara alta: frontal en pitch=0.57 y mentón ligeramente arriba en pitch=0.50
    cuadro_arriba_suave = CuadroRostro(
        100,
        80,
        180,
        200,
        0.98,
        [(150.0, 145.0), (230.0, 145.0), (190.0, 185.0), (162.0, 225.0), (218.0, 225.0)],
    )
    arriba_ok, mensaje_arriba = validar_pose_esperada(
        cuadro_arriba_suave, "up", relacion_inclinacion_frontal=0.57
    )
    assert arriba_ok is True, mensaje_arriba

    # Sonrisa natural (+3% respecto a referencia frontal)
    cuadro_sonrisa = CuadroRostro(
        100,
        80,
        180,
        200,
        0.98,
        [(150.0, 145.0), (230.0, 145.0), (190.0, 188.0), (161.0, 225.0), (219.0, 225.0)],
    )
    sonrisa_ok, mensaje_sonrisa = validar_pose_esperada(
        cuadro_sonrisa, "smile", relacion_boca_frontal=0.70
    )
    assert sonrisa_ok is True, mensaje_sonrisa

    cuadro_neutral = CuadroRostro(100, 80, 180, 200, 0.98, crear_puntos_pose("frontal"))
    neutral_ok, _ = validar_pose_esperada(cuadro_neutral, "smile", relacion_boca_frontal=0.70)
    assert neutral_ok is False


def test_geometria_validacion_seis_poses() -> None:
    """Valida aceptación y rechazo cruzado para las 6 poses del asistente guiado."""
    poses = ("frontal", "left", "right", "up", "down", "smile")
    for pose_esperada in poses:
        cuadro = CuadroRostro(100, 80, 180, 200, 0.98, crear_puntos_pose(pose_esperada))
        es_valida, retroalimentacion = validar_pose_esperada(
            cuadro, pose_esperada, relacion_boca_frontal=0.70
        )
        assert es_valida is True, f"Pose {pose_esperada} debería pasar: {retroalimentacion}"

        if pose_esperada != "frontal":
            cuadro_frontal = CuadroRostro(100, 80, 180, 200, 0.98, crear_puntos_pose("frontal"))
            frontal_pasa, mensaje_error = validar_pose_esperada(
                cuadro_frontal, pose_esperada, relacion_boca_frontal=0.70
            )
            assert frontal_pasa is False
            assert mensaje_error is not None

    # Verifica polaridad exacta entre giro izquierdo y derecho
    cuadro_izquierda = CuadroRostro(100, 80, 180, 200, 0.98, crear_puntos_pose("left"))
    intercambio_ok, mensaje_intercambio = validar_pose_esperada(cuadro_izquierda, "right")
    assert intercambio_ok is False
    assert "izquierda" in (mensaje_intercambio or "").lower()


def test_deteccion_contraluz_y_sombra_lateral() -> None:
    """Comprueba bloqueo estricto de contraluz/sombra en registro y tolerancia en kiosco."""
    imagen_contraluz = np.full((400, 400, 3), 240, dtype=np.uint8)
    imagen_contraluz[80:280, 100:280] = 25
    cuadro = CuadroRostro(100, 80, 180, 200, 0.98, crear_puntos_pose("frontal"))

    reporte_registro = evaluar_calidad_rostro(
        imagen_contraluz,
        cuadro,
        brillo_minimo=45.0,
        umbral_delta_contraluz=70.0,
        iluminacion_estricta=True,
    )
    assert reporte_registro.es_valida is False
    assert reporte_registro.contraluz_detectado is True
    assert "Contraluz" in (reporte_registro.motivo or "")

    # Sombra lateral severa: mitad izquierda brillante (200), derecha oscura (60)
    imagen_sombra = crear_imagen_rostro_nitida(400, 400, (100, 80, 180, 200), brillo_base=140)
    imagen_sombra[80:280, 100:190] = 200
    imagen_sombra[80:280, 190:280] = 60

    reporte_sombra = evaluar_calidad_rostro(
        imagen_sombra,
        cuadro,
        brillo_minimo=32.0,
        asimetria_sombra_maxima=68.0,
        iluminacion_estricta=True,
    )
    assert reporte_sombra.es_valida is False
    assert reporte_sombra.asimetria_sombra > 68.0
    assert "Sombra lateral" in (reporte_sombra.motivo or "")

    # En kiosco (`iluminacion_estricta=False`) tolera sombras moderadas
    imagen_kiosco = crear_imagen_rostro_nitida(400, 400, (100, 80, 180, 200), brillo_base=140)
    imagen_kiosco[80:280, 100:190] = np.clip(
        imagen_kiosco[80:280, 100:190].astype(np.int16) + 35, 0, 255
    ).astype(np.uint8)
    imagen_kiosco[80:280, 190:280] = np.clip(
        imagen_kiosco[80:280, 190:280].astype(np.int16) - 35, 0, 255
    ).astype(np.uint8)
    reporte_kiosco = evaluar_calidad_rostro(
        imagen_kiosco,
        cuadro,
        brillo_minimo=20.0,
        iluminacion_estricta=False,
    )
    assert reporte_kiosco.es_valida is True

    # Contraluz moderado: bloqueado en enrolamiento, permitido en kiosco
    rostro_moderado = crear_imagen_rostro_nitida(400, 400, (100, 80, 180, 200), brillo_base=55)
    contraluz_moderado = np.full((400, 400, 3), 235, dtype=np.uint8)
    contraluz_moderado[80:280, 100:280] = rostro_moderado[80:280, 100:280]

    reporte_estricto_contraluz = evaluar_calidad_rostro(
        contraluz_moderado,
        cuadro,
        brillo_minimo=32.0,
        umbral_delta_contraluz=70.0,
        iluminacion_estricta=True,
    )
    assert reporte_estricto_contraluz.es_valida is False
    assert reporte_estricto_contraluz.contraluz_detectado is True
    assert "Contraluz" in (reporte_estricto_contraluz.motivo or "")

    reporte_kiosco_contraluz = evaluar_calidad_rostro(
        contraluz_moderado,
        cuadro,
        brillo_minimo=18.0,
        umbral_delta_contraluz=70.0,
        iluminacion_estricta=False,
    )
    assert reporte_kiosco_contraluz.es_valida is True
    assert reporte_kiosco_contraluz.contraluz_detectado is True
