"""Enrutador HTTP de autenticación JWT y administración de usuarios del sistema.

Provee inicio de sesión, consulta del perfil actual y CRUD de cuentas RBAC
con validación dinámica de rol según la modalidad de la organización
(`teacher` solo en escuelas, `supervisor` solo en empresas).
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import obtener_bd
from app.models import Organizacion, Usuario
from app.schemas import (
    RespuestaInicioSesion,
    SolicitudInicioSesion,
    UsuarioActualizar,
    UsuarioCrear,
    UsuarioLeer,
)
from app.security import (
    crear_token_acceso,
    generar_hash_secreto,
    obtener_usuario_actual,
    requerir_roles,
    resolver_alcance_organizacion,
    verificar_secreto,
)
from app.services.security_service import registrar_auditoria

enrutador = APIRouter(prefix="/api", tags=["autenticacion"])


def _validar_rol_para_modo_organizacion(rol: str, organizacion: Organizacion | None) -> None:
    """Impide asignar el rol docente en empresa o el rol supervisor en escuela."""
    if organizacion is None:
        return
    if organizacion.modo == "enterprise" and rol == "teacher":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El rol 'Profesor' solo está disponible en organizaciones escolares. En modo empresa utiliza 'Supervisor'.",
        )
    if organizacion.modo == "education" and rol == "supervisor":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El rol 'Supervisor' solo está disponible en organizaciones empresariales. En modo escolar utiliza 'Profesor'.",
        )


def _serializar_usuario(
    usuario: Usuario,
    mapa_organizaciones: dict[int, Organizacion] | None = None,
) -> UsuarioLeer:
    """Convierte un registro ORM `Usuario` a su esquema JSON público `UsuarioLeer`."""
    organizacion = None
    if usuario.id_organizacion is not None:
        organizacion = (
            mapa_organizaciones.get(usuario.id_organizacion)
            if mapa_organizaciones is not None
            else usuario.organizacion
        )
    return UsuarioLeer(
        id=usuario.id,
        correo=usuario.correo,
        nombre_completo=usuario.nombre_completo,
        rol=usuario.rol,
        id_organizacion=usuario.id_organizacion,
        nombre_organizacion=organizacion.nombre if organizacion else None,
        modo_organizacion=organizacion.modo if organizacion else None,
        esta_activo=usuario.esta_activo,
        id_usuario_creador=usuario.id_usuario_creador,
        creado_en=usuario.creado_en,
    )


@enrutador.post("/auth/login", response_model=RespuestaInicioSesion)
def iniciar_sesion(
    carga: SolicitudInicioSesion,
    sesion_bd: Session = Depends(obtener_bd),
) -> RespuestaInicioSesion:
    """Autentica correo y contraseña con `scrypt` y emite un token JWT."""
    correo_normalizado = carga.correo.strip().lower()
    usuario = sesion_bd.scalars(
        select(Usuario).where(Usuario.correo == correo_normalizado)
    ).first()
    if (
        usuario is None
        or not usuario.esta_activo
        or not verificar_secreto(carga.contrasena, usuario.hash_contrasena)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Correo o contraseña incorrectos.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = crear_token_acceso(usuario)
    return RespuestaInicioSesion(token_acceso=token, usuario=_serializar_usuario(usuario))


@enrutador.get("/auth/me", response_model=UsuarioLeer)
def obtener_perfil_actual(
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
) -> UsuarioLeer:
    """Devuelve la información del usuario autenticado correspondiente al token Bearer."""
    return _serializar_usuario(usuario_actual)


@enrutador.get("/users", response_model=list[UsuarioLeer])
def listar_usuarios(
    id_organizacion: int | None = Query(default=None),
    usuario_actual: Usuario = Depends(requerir_roles("superadmin", "org_admin")),
    sesion_bd: Session = Depends(obtener_bd),
) -> list[UsuarioLeer]:
    """Lista cuentas de usuario respetando el aislamiento multi-organización."""
    consulta = select(Usuario).order_by(Usuario.id.asc())
    if usuario_actual.rol == "superadmin":
        if id_organizacion is not None:
            consulta = consulta.where(Usuario.id_organizacion == id_organizacion)
    else:
        id_org_alcance = resolver_alcance_organizacion(usuario_actual, id_organizacion)
        consulta = consulta.where(Usuario.id_organizacion == id_org_alcance)

    usuarios = list(sesion_bd.scalars(consulta).all())
    mapa_organizaciones = {
        org.id: org for org in sesion_bd.scalars(select(Organizacion)).all()
    }
    return [_serializar_usuario(usuario, mapa_organizaciones) for usuario in usuarios]


@enrutador.post("/users", response_model=UsuarioLeer, status_code=status.HTTP_201_CREATED)
def crear_usuario(
    carga: UsuarioCrear,
    usuario_actual: Usuario = Depends(requerir_roles("superadmin", "org_admin")),
    sesion_bd: Session = Depends(obtener_bd),
) -> UsuarioLeer:
    """Registra un nuevo usuario operativo, docente, supervisor o administrador."""
    if usuario_actual.rol == "org_admin":
        if carga.rol == "superadmin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Un administrador de organización no puede crear usuarios Superadmin.",
            )
        id_org_objetivo: int | None = resolver_alcance_organizacion(
            usuario_actual, carga.id_organizacion
        )
        organizacion_objetivo = sesion_bd.get(Organizacion, id_org_objetivo)
    else:
        if carga.rol == "superadmin":
            id_org_objetivo = None
            organizacion_objetivo = None
        else:
            if carga.id_organizacion is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Debes indicar id_organizacion para este rol.",
                )
            organizacion = sesion_bd.get(Organizacion, carga.id_organizacion)
            if organizacion is None:
                raise HTTPException(status_code=404, detail="Organización no encontrada.")
            id_org_objetivo = organizacion.id
            organizacion_objetivo = organizacion

    _validar_rol_para_modo_organizacion(carga.rol, organizacion_objetivo)

    correo_normalizado = carga.correo.strip().lower()
    existente = sesion_bd.scalars(
        select(Usuario).where(Usuario.correo == correo_normalizado)
    ).first()
    if existente is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe una cuenta registrada con el correo '{correo_normalizado}'.",
        )

    nuevo_usuario = Usuario(
        correo=correo_normalizado,
        nombre_completo=carga.nombre_completo.strip(),
        hash_contrasena=generar_hash_secreto(carga.contrasena),
        rol=carga.rol,
        id_organizacion=id_org_objetivo,
        id_usuario_creador=usuario_actual.id,
    )
    sesion_bd.add(nuevo_usuario)
    sesion_bd.flush()

    registrar_auditoria(
        sesion_bd,
        id_organizacion=id_org_objetivo,
        accion="create_user",
        tipo_objetivo="user",
        id_objetivo=nuevo_usuario.id,
        resumen_objetivo=f"{nuevo_usuario.nombre_completo} ({nuevo_usuario.correo})",
        usuario_ejecutor=usuario_actual,
        usuario_autorizador=usuario_actual,
        detalles=f"Rol asignado: {nuevo_usuario.rol}",
    )

    sesion_bd.commit()
    sesion_bd.refresh(nuevo_usuario)
    return _serializar_usuario(nuevo_usuario)


@enrutador.patch("/users/{id_usuario}", response_model=UsuarioLeer)
def actualizar_usuario(
    id_usuario: int,
    carga: UsuarioActualizar,
    usuario_actual: Usuario = Depends(requerir_roles("superadmin", "org_admin")),
    sesion_bd: Session = Depends(obtener_bd),
) -> UsuarioLeer:
    """Actualiza nombre, rol, estado activo o contraseña de un usuario existente."""
    usuario_objetivo = sesion_bd.get(Usuario, id_usuario)
    if usuario_objetivo is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")

    if usuario_actual.rol == "org_admin":
        if (
            usuario_objetivo.rol == "superadmin"
            or usuario_objetivo.id_organizacion != usuario_actual.id_organizacion
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Acceso denegado a usuarios fuera de tu organización.",
            )
        if carga.rol == "superadmin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No puedes asignar el rol Superadmin.",
            )

    if usuario_objetivo.id == usuario_actual.id and carga.esta_activo is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No puedes desactivar tu propia cuenta activa.",
        )

    cambios_realizados: list[str] = []
    if carga.nombre_completo is not None:
        usuario_objetivo.nombre_completo = carga.nombre_completo.strip()
        cambios_realizados.append("nombre")
    if carga.rol is not None and carga.rol != usuario_objetivo.rol:
        if carga.rol == "superadmin" and usuario_objetivo.id_organizacion is not None:
            usuario_objetivo.id_organizacion = None
        elif carga.rol != "superadmin" and usuario_objetivo.id_organizacion is not None:
            organizacion_objetivo = sesion_bd.get(Organizacion, usuario_objetivo.id_organizacion)
            _validar_rol_para_modo_organizacion(carga.rol, organizacion_objetivo)
        usuario_objetivo.rol = carga.rol
        cambios_realizados.append(f"rol={carga.rol}")
    if carga.esta_activo is not None:
        usuario_objetivo.esta_activo = carga.esta_activo
        cambios_realizados.append(f"activo={carga.esta_activo}")
    if carga.contrasena is not None:
        usuario_objetivo.hash_contrasena = generar_hash_secreto(carga.contrasena)
        cambios_realizados.append("contraseña")

    registrar_auditoria(
        sesion_bd,
        id_organizacion=usuario_objetivo.id_organizacion,
        accion="update_user",
        tipo_objetivo="user",
        id_objetivo=usuario_objetivo.id,
        resumen_objetivo=f"{usuario_objetivo.nombre_completo} ({usuario_objetivo.correo})",
        usuario_ejecutor=usuario_actual,
        usuario_autorizador=usuario_actual,
        detalles=", ".join(cambios_realizados) if cambios_realizados else "actualización",
    )

    sesion_bd.commit()
    sesion_bd.refresh(usuario_objetivo)
    return _serializar_usuario(usuario_objetivo)
