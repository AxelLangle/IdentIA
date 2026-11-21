"""Fixtures y utilidades sintéticas compartidas para las pruebas de IdentIA.

Genera imágenes BGR nítidas en memoria, vectores unitarios L2 reproducibles,
landmarks calibrados para las 6 poses y un motor biométrico simulado determinista
junto con clientes HTTP aislados sobre bases de datos SQLite temporales.
"""

from collections.abc import Generator
from pathlib import Path
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.config import obtener_configuracion
from app.db import crear_motor_bd, obtener_bd
from app.main import crear_aplicacion
from app.vision.engine import normalizar_vector
from app.vision.quality import CuadroRostro


def crear_imagen_rostro_nitida(
    ancho: int = 400,
    alto: int = 400,
    cuadro_rostro: tuple[int, int, int, int] = (100, 80, 180, 200),
    brillo_base: int = 140,
    desenfocada: bool = False,
) -> np.ndarray:
    """Genera una imagen BGR sintética en memoria con textura tipo tablero para nitidez."""
    imagen = np.full((alto, ancho, 3), brillo_base, dtype=np.uint8)
    coord_x, coord_y, ancho_r, alto_r = cuadro_rostro
    if not desenfocada:
        # Dibuja cuadrícula de alto contraste dentro del rostro para elevar varianza Laplaciana
        for fila in range(coord_y, min(alto, coord_y + alto_r), 8):
            for columna in range(coord_x, min(ancho, coord_x + ancho_r), 8):
                if ((fila // 8) + (columna // 8)) % 2 == 0:
                    cv2.rectangle(
                        imagen,
                        (columna, fila),
                        (min(ancho, columna + 8), min(alto, fila + 8)),
                        (
                            min(255, brillo_base + 55),
                            min(255, brillo_base + 55),
                            min(255, brillo_base + 55),
                        ),
                        -1,
                    )
                else:
                    cv2.rectangle(
                        imagen,
                        (columna, fila),
                        (min(ancho, columna + 8), min(alto, fila + 8)),
                        (
                            max(0, brillo_base - 55),
                            max(0, brillo_base - 55),
                            max(0, brillo_base - 55),
                        ),
                        -1,
                    )
    return imagen


def codificar_bytes_jpeg(imagen_bgr: np.ndarray) -> bytes:
    """Codifica una imagen BGR en memoria a bytes JPEG de prueba."""
    exito, bufer = cv2.imencode(".jpg", imagen_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    assert exito
    return bufer.tobytes()


def crear_vector_unitario(semilla: int, dimensiones: int = 128) -> np.ndarray:
    """Genera un embedding pseudoaleatorio normalizado L2 reproducible a partir de `semilla`."""
    generador = np.random.default_rng(semilla)
    vector = generador.normal(size=dimensiones).astype(np.float32)
    return normalizar_vector(vector)


def crear_puntos_pose(etiqueta_pose: str) -> list[tuple[float, float]]:
    """Genera los 5 puntos de referencia YuNet calibrados para cada una de las 6 poses."""
    ojo_derecho = (150.0, 145.0)
    ojo_izquierdo = (230.0, 145.0)
    boca_derecha = (162.0, 225.0)
    boca_izquierda = (218.0, 225.0)
    nariz = (190.0, 188.0)

    if etiqueta_pose == "left":
        nariz = (210.0, 188.0)
    elif etiqueta_pose == "right":
        nariz = (170.0, 188.0)
    elif etiqueta_pose == "up":
        nariz = (190.0, 173.0)
    elif etiqueta_pose == "down":
        nariz = (190.0, 203.0)
    elif etiqueta_pose == "smile":
        boca_derecha = (152.0, 225.0)
        boca_izquierda = (228.0, 225.0)

    return [ojo_derecho, ojo_izquierdo, nariz, boca_derecha, boca_izquierda]


class MotorBiometricoSimulado:
    """Motor biométrico determinista para pruebas rápidas de integración HTTP."""

    def __init__(self) -> None:
        self.siguientes_cuadros: list[CuadroRostro] = [
            CuadroRostro(
                coordenada_x=100,
                coordenada_y=80,
                ancho=180,
                alto=200,
                confianza=0.98,
                puntos_referencia=crear_puntos_pose("frontal"),
            )
        ]
        self.siguiente_vector: np.ndarray = crear_vector_unitario(1)

    def detectar(
        self,
        imagen_bgr: np.ndarray,
        permitir_respaldo_contraluz: bool = True,
    ) -> list[tuple[CuadroRostro, np.ndarray]]:
        """Devuelve detecciones sintéticas ordenadas por área simulando YuNet."""
        resultados: list[tuple[CuadroRostro, np.ndarray]] = []
        for cuadro in self.siguientes_cuadros:
            fila = np.zeros(15, dtype=np.float32)
            fila[0], fila[1], fila[2], fila[3] = (
                cuadro.coordenada_x,
                cuadro.coordenada_y,
                cuadro.ancho,
                cuadro.alto,
            )
            for indice_punto, (punto_x, punto_y) in enumerate(cuadro.puntos_referencia[:5]):
                fila[4 + indice_punto * 2] = punto_x
                fila[5 + indice_punto * 2] = punto_y
            fila[14] = cuadro.confianza
            resultados.append((cuadro, fila))
        resultados.sort(
            key=lambda elemento: elemento[0].ancho * elemento[0].alto,
            reverse=True,
        )
        return resultados

    def extraer_vector(
        self,
        imagen_bgr: np.ndarray,
        fila_rostro_cruda: np.ndarray,
    ) -> np.ndarray:
        """Devuelve el embedding determinista configurado para la prueba en curso."""
        return normalizar_vector(self.siguiente_vector)


@pytest.fixture()
def motor_simulado() -> MotorBiometricoSimulado:
    """Provee un motor biométrico simulado limpio por cada prueba."""
    return MotorBiometricoSimulado()


@pytest.fixture()
def cliente_api_sin_autenticar(
    tmp_path: Path,
    motor_simulado: MotorBiometricoSimulado,
) -> Generator[
    tuple[TestClient, sessionmaker[Session], MotorBiometricoSimulado, Path],
    None,
    None,
]:
    """Inicializa una instancia FastAPI aislada sobre SQLite temporal sin sesión iniciada."""
    archivo_bd = tmp_path / "prueba_identia.db"
    motor_prueba = crear_motor_bd(f"sqlite:///{archivo_bd.as_posix()}")
    FabricaSesionesPrueba = sessionmaker(
        bind=motor_prueba,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    aplicacion = crear_aplicacion(
        motor_biometrico=motor_simulado,
        inicializar_modelos=False,
        motor_bd_personalizado=motor_prueba,
        fabrica_sesiones=FabricaSesionesPrueba,
    )

    def _sobrescribir_obtener_bd() -> Generator[Session, None, None]:
        sesion_bd = FabricaSesionesPrueba()
        try:
            yield sesion_bd
        finally:
            sesion_bd.close()

    aplicacion.dependency_overrides[obtener_bd] = _sobrescribir_obtener_bd

    with TestClient(aplicacion) as cliente:
        yield cliente, FabricaSesionesPrueba, motor_simulado, tmp_path

    motor_prueba.dispose()


@pytest.fixture()
def cliente_api(
    cliente_api_sin_autenticar: tuple[
        TestClient, sessionmaker[Session], MotorBiometricoSimulado, Path
    ],
) -> tuple[TestClient, sessionmaker[Session], MotorBiometricoSimulado, Path]:
    """Devuelve un `TestClient` autenticado como Superadmin para pruebas generales."""
    cliente, FabricaSesionesPrueba, motor_simulado, ruta_temporal = cliente_api_sin_autenticar
    configuracion = obtener_configuracion()
    respuesta_login = cliente.post(
        "/api/auth/login",
        json={
            "correo": configuracion.correo_superadmin_inicial,
            "contrasena": configuracion.contrasena_superadmin_inicial,
        },
    )
    assert respuesta_login.status_code == 200
    token = respuesta_login.json()["token_acceso"]
    cliente.headers.update({"Authorization": f"Bearer {token}"})
    return cliente, FabricaSesionesPrueba, motor_simulado, ruta_temporal
