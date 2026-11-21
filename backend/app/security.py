"""Utilidades criptográficas, tokens JWT y control de acceso basado en roles (RBAC).

Gestiona el hashing de contraseñas y credenciales delegadas mediante `scrypt`
con comparación en tiempo constante, generación de códigos delegados legibles,
emisión/verificación de JWT HS256 y aislamiento estricto multi-organización.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from sqlalchemy.orm import Session

from app.config import obtener_configuracion
from app.db import obtener_bd
from app.models import Usuario

# Esquema Bearer opcional para emitir mensajes personalizados de error HTTP 401
esquema_portador = HTTPBearer(auto_error=False)


def generar_hash_secreto(texto_plano: str) -> str:
    """Genera un hash criptográfico `scrypt` con salt aleatorio de 16 bytes.

    Args:
        texto_plano: Contraseña o secreto sin cifrar.

    Returns:
        Cadena codificada con algoritmo, parámetros de costo, salt y digest hexadecimal.
    """
    sal_aleatoria = secrets.token_bytes(16)
    clave_derivada = hashlib.scrypt(
        texto_plano.encode("utf-8"),
        salt=sal_aleatoria,
        n=16384,
        r=8,
        p=1,
        dklen=32,
    )
    return f"scrypt$16384$8$1${sal_aleatoria.hex()}${clave_derivada.hex()}"


def verificar_secreto(texto_plano: str, hash_codificado: str) -> bool:
    """Verifica en tiempo constante si `texto_plano` coincide con un hash `scrypt`.

    Args:
        texto_plano: Secreto ingresado por el usuario.
        hash_codificado: Hash previamente generado con `generar_hash_secreto`.

    Returns:
        `True` si el secreto coincide; `False` ante error de formato o discrepancia.
    """
    try:
        esquema, costo_n, tam_bloque_r, paralelismo_p, sal_hex, digest_hex = hash_codificado.split("$")
        if esquema != "scrypt":
            return False
        sal_bytes = bytes.fromhex(sal_hex)
        digest_esperado = bytes.fromhex(digest_hex)
        clave_derivada = hashlib.scrypt(
            texto_plano.encode("utf-8"),
            salt=sal_bytes,
            n=int(costo_n),
            r=int(tam_bloque_r),
            p=int(paralelismo_p),
            dklen=len(digest_esperado),
        )
        return hmac.compare_digest(clave_derivada, digest_esperado)
    except (ValueError, TypeError):
        return False


def generar_secreto_delegado() -> tuple[str, str]:
    """Genera una contraseña delegada legible sin caracteres ambiguos y su prefijo.

    Se omiten caracteres propensos a confusión visual (`0`, `O`, `1`, `I`).

    Returns:
        Tupla `(secreto_plano, prefijo_identificador)`.
    """
    alfabeto_seguro = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    segmentos = [
        "".join(secrets.choice(alfabeto_seguro) for _ in range(4))
        for _ in range(3)
    ]
    secreto_plano = f"IDN-{'-'.join(segmentos)}"
    prefijo = f"IDN-{segmentos[0]}"
    return secreto_plano, prefijo


def crear_token_acceso(usuario: Usuario) -> str:
    """Firma un token JWT HS256 para autenticar la sesión de un usuario.

    Args:
        usuario: Registro ORM del usuario autenticado.

    Returns:
        Token JWT compacto en formato string.
    """
    configuracion = obtener_configuracion()
    ahora_utc = datetime.now(timezone.utc)
    carga_util = {
        "sub": str(usuario.id),
        "correo": usuario.correo,
        "rol": usuario.rol,
        "id_organizacion": usuario.id_organizacion,
        "iat": ahora_utc,
        "exp": ahora_utc + timedelta(minutes=configuracion.minutos_expiracion_jwt),
    }
    return jwt.encode(
        carga_util,
        configuracion.clave_secreta_jwt,
        algorithm=configuracion.algoritmo_jwt,
    )


def decodificar_token_acceso(token: str) -> dict:
    """Decodifica y valida firma y vigencia de un token JWT HS256."""
    configuracion = obtener_configuracion()
    return jwt.decode(
        token,
        configuracion.clave_secreta_jwt,
        algorithms=[configuracion.algoritmo_jwt],
    )


def obtener_usuario_actual(
    credenciales: HTTPAuthorizationCredentials | None = Depends(esquema_portador),
    sesion_bd: Session = Depends(obtener_bd),
) -> Usuario:
    """Dependencia FastAPI que extrae y valida al usuario activo desde el header Bearer JWT."""
    error_autenticacion = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sesión no autenticada o token expirado.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credenciales is None or not credenciales.credentials:
        raise error_autenticacion

    try:
        carga_util = decodificar_token_acceso(credenciales.credentials)
        id_usuario = int(carga_util["sub"])
    except (jwt.PyJWTError, KeyError, ValueError, TypeError) as excepcion:
        raise error_autenticacion from excepcion

    usuario = sesion_bd.get(Usuario, id_usuario)
    if usuario is None or not usuario.esta_activo:
        raise error_autenticacion
    return usuario


def requerir_roles(*roles_permitidos: str):
    """Fábrica de dependencias que restringe un endpoint a los roles indicados."""

    def _verificador_rol(usuario_actual: Usuario = Depends(obtener_usuario_actual)) -> Usuario:
        if usuario_actual.rol not in roles_permitidos:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No cuentas con permisos suficientes para esta operación.",
            )
        return usuario_actual

    return _verificador_rol


def resolver_alcance_organizacion(
    usuario_actual: Usuario,
    id_organizacion_solicitada: int | None,
) -> int:
    """Resuelve el `id_organizacion` permitido evitando fugas entre inquilinos (multi-tenant)."""
    if usuario_actual.rol == "superadmin":
        if id_organizacion_solicitada is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Debes indicar id_organizacion.",
            )
        return id_organizacion_solicitada

    if usuario_actual.id_organizacion is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario sin organización asignada.",
        )

    if (
        id_organizacion_solicitada is not None
        and id_organizacion_solicitada != usuario_actual.id_organizacion
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado a recursos de otra organización.",
        )
    return usuario_actual.id_organizacion


def validar_acceso_organizacion(usuario_actual: Usuario, id_organizacion_objetivo: int) -> None:
    """Comprueba que el usuario autenticado tenga autorización sobre `id_organizacion_objetivo`."""
    if usuario_actual.rol == "superadmin":
        return
    if usuario_actual.id_organizacion != id_organizacion_objetivo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado a recursos de otra organización.",
        )
