"""Enrutador HTTP para credenciales delegadas de autorización y bitácora de auditoría.

Permite a Superadmin y Org Admin emitir contraseñas delegadas temporales para
operadores, revocarlas de inmediato y consultar la trazabilidad completa de
eventos sensibles registrados en `audit_logs`.
"""

from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import obtener_bd
from app.models import CredencialDelegada, Organizacion, RegistroAuditoria, Usuario
from app.schemas import (
    CredencialDelegadaCrear,
    CredencialDelegadaLeer,
    RegistroAuditoriaLeer,
    RespuestaCrearCredencialDelegada,
)
from app.security import (
    generar_hash_secreto,
    generar_secreto_delegado,
    requerir_roles,
    resolver_alcance_organizacion,
    validar_acceso_organizacion,
)
from app.services.security_service import registrar_auditoria

enrutador = APIRouter(prefix="/api/security", tags=["seguridad"])


def _serializar_credencial(
    credencial: CredencialDelegada,
    mapa_usuarios: dict[int, Usuario],
) -> CredencialDelegadaLeer:
    """Convierte una credencial delegada ORM a su vista pública sin exponer el hash."""
    creador = (
        mapa_usuarios.get(credencial.id_usuario_creador)
        if credencial.id_usuario_creador
        else None
    )
    operaciones = [
        operacion.strip()
        for operacion in credencial.operaciones_permitidas.split(",")
        if operacion.strip()
    ]
    return CredencialDelegadaLeer(
        id=credencial.id,
        id_organizacion=credencial.id_organizacion,
        etiqueta=credencial.etiqueta,
        prefijo_secreto=credencial.prefijo_secreto,
        id_usuario_creador=credencial.id_usuario_creador,
        nombre_creador=creador.nombre_completo if creador else None,
        id_usuario_asignado=credencial.id_usuario_asignado,
        nombre_asignado=credencial.nombre_asignado,
        operaciones_permitidas=operaciones,
        estado=credencial.estado,
        expira_en=credencial.expira_en,
        creado_en=credencial.creado_en,
        revocado_en=credencial.revocado_en,
    )


@enrutador.get("/delegated-credentials", response_model=list[CredencialDelegadaLeer])
def listar_credenciales_delegadas(
    id_organizacion: int | None = Query(default=None),
    usuario_actual: Usuario = Depends(requerir_roles("superadmin", "org_admin")),
    sesion_bd: Session = Depends(obtener_bd),
) -> list[CredencialDelegadaLeer]:
    """Lista credenciales delegadas de la organización marcando automáticamente las expiradas."""
    id_org_alcance = resolver_alcance_organizacion(usuario_actual, id_organizacion)
    credenciales = list(
        sesion_bd.scalars(
            select(CredencialDelegada)
            .where(CredencialDelegada.id_organizacion == id_org_alcance)
            .order_by(CredencialDelegada.id.desc())
        ).all()
    )

    ahora = datetime.now()
    hubo_cambios = False
    for credencial in credenciales:
        if (
            credencial.estado == "active"
            and credencial.expira_en is not None
            and credencial.expira_en < ahora
        ):
            credencial.estado = "expired"
            hubo_cambios = True
    if hubo_cambios:
        sesion_bd.commit()

    mapa_usuarios = {usuario.id: usuario for usuario in sesion_bd.scalars(select(Usuario)).all()}
    return [_serializar_credencial(credencial, mapa_usuarios) for credencial in credenciales]


@enrutador.post(
    "/delegated-credentials",
    response_model=RespuestaCrearCredencialDelegada,
    status_code=status.HTTP_201_CREATED,
)
def crear_credencial_delegada(
    carga: CredencialDelegadaCrear,
    usuario_actual: Usuario = Depends(requerir_roles("superadmin", "org_admin")),
    sesion_bd: Session = Depends(obtener_bd),
) -> RespuestaCrearCredencialDelegada:
    """Emite una contraseña delegada hasheada y devuelve el secreto en claro una única vez."""
    id_org_alcance = resolver_alcance_organizacion(usuario_actual, carga.id_organizacion)
    organizacion = sesion_bd.get(Organizacion, id_org_alcance)
    if organizacion is None:
        raise HTTPException(status_code=404, detail="Organización no encontrada.")

    nombre_asignado = carga.nombre_asignado.strip() if carga.nombre_asignado else ""
    if carga.id_usuario_asignado is not None:
        usuario_asignado = sesion_bd.get(Usuario, carga.id_usuario_asignado)
        if usuario_asignado is None or not usuario_asignado.esta_activo:
            raise HTTPException(status_code=404, detail="Usuario subordinado no encontrado.")
        if usuario_asignado.id_organizacion not in (id_org_alcance, None):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="El usuario asignado no pertenece a esta organización.",
            )
        if not nombre_asignado:
            nombre_asignado = usuario_asignado.nombre_completo

    if not nombre_asignado:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debes indicar el usuario o el nombre de la persona que utilizará la contraseña.",
        )

    if carga.secreto_personalizado:
        secreto_plano = carga.secreto_personalizado.strip()
        prefijo = f"CUS-{secreto_plano[:4].upper()}"
    else:
        secreto_plano, prefijo = generar_secreto_delegado()

    fecha_expiracion = (
        datetime.now() + timedelta(days=carga.expira_en_dias)
        if carga.expira_en_dias is not None
        else None
    )
    operaciones_limpias = [
        operacion.strip() for operacion in carga.operaciones_permitidas if operacion.strip()
    ] or ["revoke_biometrics"]

    credencial = CredencialDelegada(
        id_organizacion=id_org_alcance,
        etiqueta=carga.etiqueta.strip(),
        prefijo_secreto=prefijo,
        hash_secreto=generar_hash_secreto(secreto_plano),
        id_usuario_creador=usuario_actual.id,
        id_usuario_asignado=carga.id_usuario_asignado,
        nombre_asignado=nombre_asignado,
        operaciones_permitidas=",".join(operaciones_limpias),
        estado="active",
        expira_en=fecha_expiracion,
    )
    sesion_bd.add(credencial)
    sesion_bd.flush()

    registrar_auditoria(
        sesion_bd,
        id_organizacion=id_org_alcance,
        accion="create_delegated_credential",
        tipo_objetivo="delegated_credential",
        id_objetivo=credencial.id,
        resumen_objetivo=f"{credencial.etiqueta} ({credencial.prefijo_secreto})",
        usuario_ejecutor=usuario_actual,
        usuario_autorizador=usuario_actual,
        credencial_delegada=credencial,
        detalles=f"Asignada a: {nombre_asignado} | Permisos: {', '.join(operaciones_limpias)}",
    )

    sesion_bd.commit()
    sesion_bd.refresh(credencial)
    mapa_usuarios = {usuario_actual.id: usuario_actual}
    return RespuestaCrearCredencialDelegada(
        credencial=_serializar_credencial(credencial, mapa_usuarios),
        secreto_plano=secreto_plano,
    )


@enrutador.post(
    "/delegated-credentials/{id_credencial}/revoke",
    response_model=CredencialDelegadaLeer,
)
def revocar_credencial_delegada(
    id_credencial: int,
    usuario_actual: Usuario = Depends(requerir_roles("superadmin", "org_admin")),
    sesion_bd: Session = Depends(obtener_bd),
) -> CredencialDelegadaLeer:
    """Invalida de inmediato una credencial delegada y registra el hecho en auditoría."""
    credencial = sesion_bd.get(CredencialDelegada, id_credencial)
    if credencial is None:
        raise HTTPException(status_code=404, detail="Credencial delegada no encontrada.")
    validar_acceso_organizacion(usuario_actual, credencial.id_organizacion)

    if credencial.estado != "revoked":
        credencial.estado = "revoked"
        credencial.revocado_en = datetime.now()
        registrar_auditoria(
            sesion_bd,
            id_organizacion=credencial.id_organizacion,
            accion="revoke_delegated_credential",
            tipo_objetivo="delegated_credential",
            id_objetivo=credencial.id,
            resumen_objetivo=f"{credencial.etiqueta} ({credencial.prefijo_secreto})",
            usuario_ejecutor=usuario_actual,
            usuario_autorizador=usuario_actual,
            credencial_delegada=credencial,
            detalles=f"Revocada credencial asignada a {credencial.nombre_asignado}",
        )
        sesion_bd.commit()
        sesion_bd.refresh(credencial)

    mapa_usuarios = {usuario.id: usuario for usuario in sesion_bd.scalars(select(Usuario)).all()}
    return _serializar_credencial(credencial, mapa_usuarios)


@enrutador.get("/audit-logs", response_model=list[RegistroAuditoriaLeer])
def listar_registros_auditoria(
    id_organizacion: int | None = Query(default=None),
    limite: int = Query(default=100, ge=1, le=500),
    usuario_actual: Usuario = Depends(requerir_roles("superadmin", "org_admin")),
    sesion_bd: Session = Depends(obtener_bd),
) -> list[RegistroAuditoriaLeer]:
    """Devuelve las entradas más recientes de la bitácora de auditoría de la organización."""
    consulta = (
        select(RegistroAuditoria)
        .order_by(RegistroAuditoria.creado_en.desc(), RegistroAuditoria.id.desc())
        .limit(limite)
    )
    if usuario_actual.rol == "superadmin":
        if id_organizacion is not None:
            consulta = consulta.where(RegistroAuditoria.id_organizacion == id_organizacion)
    else:
        id_org_alcance = resolver_alcance_organizacion(usuario_actual, id_organizacion)
        consulta = consulta.where(RegistroAuditoria.id_organizacion == id_org_alcance)

    registros = list(sesion_bd.scalars(consulta).all())
    mapa_usuarios = {usuario.id: usuario for usuario in sesion_bd.scalars(select(Usuario)).all()}
    mapa_credenciales = {
        credencial.id: credencial
        for credencial in sesion_bd.scalars(select(CredencialDelegada)).all()
    }

    resultados: list[RegistroAuditoriaLeer] = []
    for entrada in registros:
        usuario_ejecutor = (
            mapa_usuarios.get(entrada.id_usuario_ejecutor)
            if entrada.id_usuario_ejecutor
            else None
        )
        usuario_autorizador = (
            mapa_usuarios.get(entrada.id_usuario_autorizador)
            if entrada.id_usuario_autorizador
            else None
        )
        credencial = (
            mapa_credenciales.get(entrada.id_credencial_delegada)
            if entrada.id_credencial_delegada
            else None
        )
        resultados.append(
            RegistroAuditoriaLeer(
                id=entrada.id,
                id_organizacion=entrada.id_organizacion,
                accion=entrada.accion,
                tipo_objetivo=entrada.tipo_objetivo,
                id_objetivo=entrada.id_objetivo,
                resumen_objetivo=entrada.resumen_objetivo,
                id_usuario_ejecutor=entrada.id_usuario_ejecutor,
                nombre_ejecutor=usuario_ejecutor.nombre_completo if usuario_ejecutor else None,
                id_usuario_autorizador=entrada.id_usuario_autorizador,
                nombre_autorizador=(
                    usuario_autorizador.nombre_completo if usuario_autorizador else None
                ),
                id_credencial_delegada=entrada.id_credencial_delegada,
                prefijo_credencial_delegada=credencial.prefijo_secreto if credencial else None,
                nombre_asignado_credencial=credencial.nombre_asignado if credencial else None,
                detalles=entrada.detalles,
                creado_en=entrada.creado_en,
            )
        )
    return resultados
