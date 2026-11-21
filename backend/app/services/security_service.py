"""Servicio de autorizaciones sensibles, credenciales delegadas y bitácora de auditoría.

Valida contraseñas administrativas o contraseñas delegadas temporales (con verificación
de vigencia y permisos de operación) antes de permitir acciones de alto impacto como
la revocación biométrica o el cambio de tipo de periodo académico.
"""

from dataclasses import dataclass
from datetime import datetime
from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import CredencialDelegada, RegistroAuditoria, Usuario
from app.security import verificar_secreto


@dataclass(frozen=True)
class ResultadoAutorizacion:
    """Resultado de validar una autorización sensible (administrador o credencial delegada)."""

    usuario_autorizador: Usuario | None
    credencial_delegada: CredencialDelegada | None
    metodo: str  # "admin_password" | "delegated_credential"


def registrar_auditoria(
    sesion_bd: Session,
    *,
    id_organizacion: int | None,
    accion: str,
    tipo_objetivo: str,
    id_objetivo: int | None,
    resumen_objetivo: str | None,
    usuario_ejecutor: Usuario | None,
    usuario_autorizador: Usuario | None = None,
    credencial_delegada: CredencialDelegada | None = None,
    detalles: str | None = None,
) -> RegistroAuditoria:
    """Agrega un evento a la bitácora de auditoría sin confirmar la transacción.

    Se deja el `commit` al flujo llamador para que la acción de negocio y su registro
    de auditoría sean atómicos dentro de la misma transacción.
    """
    entrada = RegistroAuditoria(
        id_organizacion=id_organizacion,
        accion=accion,
        tipo_objetivo=tipo_objetivo,
        id_objetivo=id_objetivo,
        resumen_objetivo=resumen_objetivo,
        id_usuario_ejecutor=usuario_ejecutor.id if usuario_ejecutor else None,
        id_usuario_autorizador=usuario_autorizador.id if usuario_autorizador else None,
        id_credencial_delegada=credencial_delegada.id if credencial_delegada else None,
        detalles=detalles,
    )
    sesion_bd.add(entrada)
    return entrada


def verificar_autorizacion_sensible(
    sesion_bd: Session,
    *,
    usuario_actual: Usuario,
    id_organizacion: int,
    secreto_autorizacion: str,
    operacion_requerida: str = "revoke_biometrics",
) -> ResultadoAutorizacion:
    """Valida contraseña de Superadmin, Org Admin de la organización o credencial delegada."""
    secreto_limpio = secreto_autorizacion.strip()
    if not secreto_limpio:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Se requiere la contraseña de autorización.",
        )

    candidatos_admin = list(
        sesion_bd.scalars(
            select(Usuario).where(
                Usuario.esta_activo.is_(True),
                or_(
                    Usuario.rol == "superadmin",
                    (Usuario.rol == "org_admin") & (Usuario.id_organizacion == id_organizacion),
                ),
            )
        ).all()
    )

    # Prioriza verificar primero al propio usuario actual si cuenta con rol administrativo
    candidatos_admin.sort(key=lambda usuario: 0 if usuario.id == usuario_actual.id else 1)

    for administrador in candidatos_admin:
        if verificar_secreto(secreto_limpio, administrador.hash_contrasena):
            return ResultadoAutorizacion(
                usuario_autorizador=administrador,
                credencial_delegada=None,
                metodo="admin_password",
            )

    # Si no coincidió con contraseñas admin, evalúa credenciales delegadas activas
    credenciales = list(
        sesion_bd.scalars(
            select(CredencialDelegada).where(
                CredencialDelegada.id_organizacion == id_organizacion,
                CredencialDelegada.estado == "active",
            )
        ).all()
    )
    ahora = datetime.now()
    for credencial in credenciales:
        if credencial.expira_en is not None and credencial.expira_en < ahora:
            credencial.estado = "expired"
            sesion_bd.flush()
            continue

        operaciones_permitidas = {
            operacion.strip()
            for operacion in credencial.operaciones_permitidas.split(",")
            if operacion.strip()
        }
        if operacion_requerida not in operaciones_permitidas:
            continue

        if verificar_secreto(secreto_limpio, credencial.hash_secreto):
            if (
                credencial.id_usuario_asignado is not None
                and usuario_actual.rol not in ("superadmin", "org_admin")
                and credencial.id_usuario_asignado != usuario_actual.id
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Esta credencial delegada está asignada a otro usuario.",
                )

            usuario_creador = (
                sesion_bd.get(Usuario, credencial.id_usuario_creador)
                if credencial.id_usuario_creador is not None
                else None
            )
            return ResultadoAutorizacion(
                usuario_autorizador=usuario_creador,
                credencial_delegada=credencial,
                metodo="delegated_credential",
            )

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Contraseña de autorización inválida o sin permisos para esta operación.",
    )


def verificar_contrasena_admin(
    sesion_bd: Session,
    *,
    usuario_actual: Usuario,
    id_organizacion: int,
    secreto_autorizacion: str | None,
) -> Usuario:
    """Valida exclusivamente la contraseña de un Superadmin o Admin de la organización.

    No acepta credenciales delegadas; se exige para cambios estructurales como el
    tipo de periodo académico.
    """
    secreto_limpio = (secreto_autorizacion or "").strip()
    if not secreto_limpio:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Se requiere la contraseña de administrador para cambiar el tipo de periodo.",
        )

    candidatos_admin = list(
        sesion_bd.scalars(
            select(Usuario).where(
                Usuario.esta_activo.is_(True),
                or_(
                    Usuario.rol == "superadmin",
                    (Usuario.rol == "org_admin") & (Usuario.id_organizacion == id_organizacion),
                ),
            )
        ).all()
    )
    candidatos_admin.sort(key=lambda usuario: 0 if usuario.id == usuario_actual.id else 1)

    for administrador in candidatos_admin:
        if verificar_secreto(secreto_limpio, administrador.hash_contrasena):
            return administrador

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Contraseña de administrador inválida.",
    )
