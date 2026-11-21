"""Lanzador de escritorio autónomo para IdentIA (Release 1.1.0).

Inicia el servidor integrado FastAPI + Uvicorn sirviendo tanto la API biométrica
ONNX como la aplicación web React precompilada, elige automáticamente un puerto
disponible si el puerto 8000 está ocupado y abre el navegador predeterminado en
cuanto `/api/health` responde correctamente.
"""

import argparse
import multiprocessing
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser


def _configurar_salida_consola_segura() -> None:
    """Evita errores de codificación cuando la consola Windows usa tablas OEM."""
    for flujo in (sys.stdout, sys.stderr):
        if flujo is not None and hasattr(flujo, "reconfigure"):
            try:
                flujo.reconfigure(errors="replace")
            except Exception:
                pass


def _puerto_disponible(anfitrion: str, puerto: int) -> bool:
    """Comprueba si es posible enlazar un socket TCP en el anfitrión y puerto dados."""
    anfitrion_prueba = "127.0.0.1" if anfitrion == "0.0.0.0" else anfitrion
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as conector:
        try:
            conector.bind((anfitrion_prueba, puerto))
            return True
        except OSError:
            return False


def buscar_puerto_disponible(
    anfitrion: str, puerto_inicial: int, intentos_maximos: int = 20
) -> int:
    """Devuelve el primer puerto TCP libre comenzando desde `puerto_inicial`."""
    for desplazamiento in range(intentos_maximos):
        puerto_candidato = puerto_inicial + desplazamiento
        if _puerto_disponible(anfitrion, puerto_candidato):
            return puerto_candidato
    return puerto_inicial


def abrir_navegador_cuando_este_listo(
    url_salud: str, url_aplicacion: str, tiempo_espera_segundos: float = 30.0
) -> None:
    """Espera en segundo plano a que `/api/health` responda HTTP 200 y abre la UI."""
    limite_tiempo = time.monotonic() + tiempo_espera_segundos
    while time.monotonic() < limite_tiempo:
        try:
            with urllib.request.urlopen(url_salud, timeout=1.0) as respuesta:
                if respuesta.status == 200:
                    webbrowser.open(url_aplicacion)
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.25)


def construir_analizador_argumentos() -> argparse.ArgumentParser:
    """Configura los parámetros de línea de comandos aceptados por el ejecutable."""
    analizador = argparse.ArgumentParser(
        prog="IdentIA-1.1.0",
        description="Servidor de escritorio todo-en-uno para IdentIA v1.1.0.",
    )
    analizador.add_argument(
        "--anfitrion",
        default="127.0.0.1",
        help="Interfaz IP donde escuchará el servidor (por defecto 127.0.0.1).",
    )
    analizador.add_argument(
        "--puerto",
        type=int,
        default=8000,
        help="Puerto HTTP preferido para iniciar IdentIA (por defecto 8000).",
    )
    analizador.add_argument(
        "--sin-navegador",
        action="store_true",
        help="Inicia el servidor sin abrir automáticamente una pestaña del navegador.",
    )
    return analizador


def ejecutar_servidor_escritorio() -> None:
    """Inicializa la aplicación FastAPI empaquetada y levanta Uvicorn."""
    _configurar_salida_consola_segura()

    analizador = construir_analizador_argumentos()
    argumentos = analizador.parse_args()

    # Importamos los módulos de la aplicación después de freeze_support() y CLI
    import uvicorn
    from app.config import obtener_configuracion
    from app.main import crear_aplicacion

    configuracion = obtener_configuracion()
    puerto_efectivo = buscar_puerto_disponible(argumentos.anfitrion, argumentos.puerto)

    if puerto_efectivo != argumentos.puerto:
        print(
            f"[IdentIA] El puerto {argumentos.puerto} está ocupado; "
            f"se utilizará el puerto disponible {puerto_efectivo}."
        )

    anfitrion_navegador = (
        "127.0.0.1" if argumentos.anfitrion == "0.0.0.0" else argumentos.anfitrion
    )
    url_aplicacion = f"http://{anfitrion_navegador}:{puerto_efectivo}"
    url_salud = f"{url_aplicacion}/api/health"

    print("============================================================")
    print("  IdentIA v1.1.0 - Control de Asistencia Biométrico")
    print(f"  URL local        : {url_aplicacion}")
    print(f"  Base de datos    : {configuracion.directorio_datos}")
    print(f"  Modelos ONNX     : {configuracion.directorio_modelos}")
    print(
        f"  Interfaz web     : {configuracion.directorio_frontend_compilado or 'Solo API'}"
    )
    print("  Presiona Ctrl + C en esta ventana para detener IdentIA.")
    print("============================================================")

    aplicacion = crear_aplicacion()

    if not argumentos.sin_navegador:
        hilo_navegador = threading.Thread(
            target=abrir_navegador_cuando_este_listo,
            args=(url_salud, url_aplicacion),
            daemon=True,
        )
        hilo_navegador.start()

    uvicorn.run(
        aplicacion,
        host=argumentos.anfitrion,
        port=puerto_efectivo,
        log_level="info",
    )


if __name__ == "__main__":
    multiprocessing.freeze_support()
    ejecutar_servidor_escritorio()
