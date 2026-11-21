# -*- mode: python ; coding: utf-8 -*-
"""Especificación PyInstaller (--onefile) para generar el ejecutable único IdentIA-1.1.0.exe."""

import os

directorio_backend = os.path.abspath(SPECPATH)
directorio_raiz = os.path.abspath(os.path.join(directorio_backend, ".."))

archivos_datos = [
    (os.path.join(directorio_raiz, "frontend", "dist"), "frontend_dist"),
    (os.path.join(directorio_backend, "models", "face_detection_yunet_2023mar.onnx"), "models"),
    (os.path.join(directorio_backend, "models", "face_recognition_sface_2021dec.onnx"), "models"),
]

importaciones_ocultas = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "sqlalchemy.dialects.sqlite",
    "pydantic_settings",
    "multipart",
    "python_multipart",
    "cv2",
    "numpy",
    "PIL",
    "jwt",
    "app.config",
    "app.db",
    "app.main",
    "app.models",
    "app.schemas",
    "app.security",
    "app.routers.academic",
    "app.routers.attendance",
    "app.routers.auth",
    "app.routers.enterprise",
    "app.routers.organizations",
    "app.routers.persons",
    "app.routers.security",
    "app.services.academic_service",
    "app.services.attendance_service",
    "app.services.enterprise_service",
    "app.services.security_service",
    "app.vision.engine",
    "app.vision.models_loader",
    "app.vision.quality",
]

modulos_excluidos = [
    "pytest",
    "_pytest",
    "tkinter",
    "matplotlib",
    "scipy",
    "IPython",
    "notebook",
    "unittest",
]

analisis = Analysis(
    [os.path.join(directorio_backend, "lanzador_escritorio.py")],
    pathex=[directorio_backend],
    binaries=[],
    datas=archivos_datos,
    hiddenimports=importaciones_ocultas,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=modulos_excluidos,
    noarchive=False,
    optimize=0,
)

# Reducción de tamaño offline: YuNet + SFace procesan frames JPEG en RAM vía cv2.imdecode,
# por lo que no requieren codecs de video FFmpeg ni clasificadores Haar XML.
analisis.binaries = [
    elemento
    for elemento in analisis.binaries
    if "opencv_videoio_ffmpeg" not in elemento[0].lower()
]
analisis.datas = [
    elemento
    for elemento in analisis.datas
    if "haarcascade" not in elemento[0].lower()
]

pyz = PYZ(analisis.pure)

ejecutable = EXE(
    pyz,
    analisis.scripts,
    analisis.binaries,
    analisis.zipfiles,
    analisis.datas,
    [],
    name="IdentIA-1.1.0",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
