"""Enrutador HTTP para gestión de organizaciones y grupos/departamentos.

Permite administrar parámetros globales de la organización (modo empresa o escuela,
tolerancia de retardo, cooldown, guardado de avatar y tipo de periodo académico
protegido con clave de administrador), así como grupos académicos o departamentos
con turno laboral por defecto sincronizado.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import obtener_bd
from app.models import (
    AsignacionCurso,
    Carrera,
    Grupo,
    Organizacion,
    PersonaGrupo,
    TurnoLaboral,
    Usuario,
)
from app.schemas import (
    GrupoActualizar,
    GrupoCrear,
    GrupoLeer,
    OrganizacionActualizar,
    OrganizacionCrear,
    OrganizacionLeer,
)
from app.security import (
    generar_hash_secreto,
    obtener_usuario_actual,
    requerir_roles,
    resolver_alcance_organizacion,
    validar_acceso_organizacion,
)
from app.services.academic_service import obtener_ids_grupos_docente
from app.services.security_service import registrar_auditoria, verificar_contrasena_admin

enrutador = APIRouter(prefix="/api", tags=["organizaciones"])


@enrutador.get("/organizations", response_model=list[OrganizacionLeer])
def listar_organizaciones(
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    sesion_bd: Session = Depends(obtener_bd),
) -> list[Organizacion]:
    """Lista todas las organizaciones (Superadmin) o solo la organización asignada."""
    if usuario_actual.rol == "superadmin":
        return list(sesion_bd.scalars(select(Organizacion).order_by(Organizacion.id.asc())).all())
    if usuario_actual.id_organizacion is None:
        return []
    return list(
        sesion_bd.scalars(
            select(Organizacion)
            .where(Organizacion.id == usuario_actual.id_organizacion)
            .order_by(Organizacion.id.asc())
        ).all()
    )


@enrutador.post("/organizations", response_model=OrganizacionLeer, status_code=status.HTTP_201_CREATED)
def crear_organizacion(
    carga: OrganizacionCrear,
    usuario_actual: Usuario = Depends(requerir_roles("superadmin")),
    sesion_bd: Session = Depends(obtener_bd),
) -> Organizacion:
    """Da de alta una organización junto con su grupo base `GEN-01` y admin inicial opcional."""
    datos_org = carga.model_dump(exclude={"usuario_administrador"})
    organizacion = Organizacion(**datos_org)
    sesion_bd.add(organizacion)
    sesion_bd.flush()

    sesion_bd.add(
        Grupo(
            id_organizacion=organizacion.id,
            nombre="General",
            codigo="GEN-01",
            hora_inicio_horario="09:00",
            hora_fin_horario="18:00",
        )
    )

    resumen_admin = "sin admin inicial"
    if carga.usuario_administrador is not None:
        correo_normalizado = carga.usuario_administrador.correo.strip().lower()
        duplicado = sesion_bd.scalars(
            select(Usuario).where(Usuario.correo == correo_normalizado)
        ).first()
        if duplicado is not None:
            sesion_bd.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Ya existe un usuario con el correo '{correo_normalizado}'.",
            )
        admin_org = Usuario(
            correo=correo_normalizado,
            nombre_completo=carga.usuario_administrador.nombre_completo.strip(),
            hash_contrasena=generar_hash_secreto(carga.usuario_administrador.contrasena),
            rol="org_admin",
            id_organizacion=organizacion.id,
            id_usuario_creador=usuario_actual.id,
        )
        sesion_bd.add(admin_org)
        resumen_admin = f"admin inicial: {correo_normalizado}"

    registrar_auditoria(
        sesion_bd,
        id_organizacion=organizacion.id,
        accion="create_organization",
        tipo_objetivo="organization",
        id_objetivo=organizacion.id,
        resumen_objetivo=organizacion.nombre,
        usuario_ejecutor=usuario_actual,
        usuario_autorizador=usuario_actual,
        detalles=f"Modo: {organizacion.modo} | {resumen_admin}",
    )

    sesion_bd.commit()
    sesion_bd.refresh(organizacion)
    return organizacion


@enrutador.patch("/organizations/{id_organizacion}", response_model=OrganizacionLeer)
def actualizar_organizacion(
    id_organizacion: int,
    carga: OrganizacionActualizar,
    usuario_actual: Usuario = Depends(requerir_roles("superadmin", "org_admin")),
    sesion_bd: Session = Depends(obtener_bd),
) -> Organizacion:
    """Actualiza parámetros operativos de la organización (exige clave admin si cambia el periodo)."""
    validar_acceso_organizacion(usuario_actual, id_organizacion)
    organizacion = sesion_bd.get(Organizacion, id_organizacion)
    if organizacion is None:
        raise HTTPException(status_code=404, detail="Organización no encontrada.")

    datos_parciales = carga.model_dump(exclude_unset=True)
    secreto_autorizacion = datos_parciales.pop("secreto_autorizacion", None)

    if (
        "tipo_periodo_academico" in datos_parciales
        and datos_parciales["tipo_periodo_academico"] is not None
        and datos_parciales["tipo_periodo_academico"] != organizacion.tipo_periodo_academico
    ):
        admin_autorizador = verificar_contrasena_admin(
            sesion_bd,
            usuario_actual=usuario_actual,
            id_organizacion=organizacion.id,
            secreto_autorizacion=secreto_autorizacion,
        )
        registrar_auditoria(
            sesion_bd,
            id_organizacion=organizacion.id,
            accion="change_org_period_type",
            tipo_objetivo="organization",
            id_objetivo=organizacion.id,
            resumen_objetivo=organizacion.nombre,
            usuario_ejecutor=usuario_actual,
            usuario_autorizador=admin_autorizador,
            detalles=(
                f"Periodo general: {organizacion.tipo_periodo_academico} -> "
                f"{datos_parciales['tipo_periodo_academico']}"
            ),
        )

    for campo, valor in datos_parciales.items():
        setattr(organizacion, campo, valor)

    sesion_bd.commit()
    sesion_bd.refresh(organizacion)
    return organizacion


def _serializar_grupos(
    sesion_bd: Session,
    grupos: list[Grupo],
    id_organizacion: int,
) -> list[GrupoLeer]:
    """Serializa grupos con carrera, periodo efectivo, turno heredado y conteos."""
    if not grupos:
        return []

    organizacion = sesion_bd.get(Organizacion, id_organizacion)
    tipo_periodo_org = organizacion.tipo_periodo_academico if organizacion else "semestral"
    mapa_carreras = {
        carrera.id: carrera
        for carrera in sesion_bd.scalars(
            select(Carrera).where(Carrera.id_organizacion == id_organizacion)
        ).all()
    }
    mapa_turnos = {
        turno.id: turno
        for turno in sesion_bd.scalars(
            select(TurnoLaboral).where(TurnoLaboral.id_organizacion == id_organizacion)
        ).all()
    }
    filas_integrantes = sesion_bd.execute(
        select(PersonaGrupo.id_grupo, func.count(PersonaGrupo.id_persona)).group_by(
            PersonaGrupo.id_grupo
        )
    ).all()
    mapa_integrantes = {id_grupo: conteo for id_grupo, conteo in filas_integrantes}

    filas_cursos = sesion_bd.execute(
        select(AsignacionCurso.id_grupo, func.count(AsignacionCurso.id))
        .where(
            AsignacionCurso.id_organizacion == id_organizacion,
            AsignacionCurso.esta_activo.is_(True),
        )
        .group_by(AsignacionCurso.id_grupo)
    ).all()
    mapa_cursos = {id_grupo: conteo for id_grupo, conteo in filas_cursos}

    resultado: list[GrupoLeer] = []
    for grupo in grupos:
        carrera = mapa_carreras.get(grupo.id_carrera) if grupo.id_carrera else None
        turno = (
            mapa_turnos.get(grupo.id_turno_laboral_defecto)
            if grupo.id_turno_laboral_defecto
            else None
        )
        tipo_periodo_efectivo = (
            grupo.tipo_periodo
            or (carrera.tipo_periodo if carrera and carrera.tipo_periodo else None)
            or tipo_periodo_org
        )
        resultado.append(
            GrupoLeer(
                id=grupo.id,
                id_organizacion=grupo.id_organizacion,
                id_carrera=grupo.id_carrera,
                nombre_carrera=carrera.nombre if carrera else None,
                nombre=grupo.nombre,
                codigo=grupo.codigo,
                semestre=grupo.semestre,
                aula_defecto=grupo.aula_defecto,
                id_turno_laboral_defecto=grupo.id_turno_laboral_defecto,
                nombre_turno_laboral_defecto=turno.nombre if turno else None,
                codigo_turno_laboral_defecto=turno.codigo if turno else None,
                tipo_periodo=tipo_periodo_efectivo,
                tipo_periodo_personalizado=grupo.tipo_periodo,
                hora_inicio_horario=grupo.hora_inicio_horario,
                hora_fin_horario=grupo.hora_fin_horario,
                creado_en=grupo.creado_en,
                cantidad_integrantes=mapa_integrantes.get(grupo.id, 0),
                cantidad_cursos=mapa_cursos.get(grupo.id, 0),
            )
        )
    return resultado


@enrutador.get("/groups", response_model=list[GrupoLeer])
def listar_grupos(
    id_organizacion: int | None = Query(default=None),
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    sesion_bd: Session = Depends(obtener_bd),
) -> list[GrupoLeer]:
    """Lista grupos o áreas de la organización; para docentes filtra solo sus grupos."""
    id_org_alcance = resolver_alcance_organizacion(usuario_actual, id_organizacion)
    consulta = (
        select(Grupo)
        .where(Grupo.id_organizacion == id_org_alcance)
        .order_by(Grupo.id.asc())
    )
    if usuario_actual.rol == "teacher":
        ids_grupos_docente = obtener_ids_grupos_docente(sesion_bd, usuario_actual.id)
        if not ids_grupos_docente:
            return []
        consulta = consulta.where(Grupo.id.in_(ids_grupos_docente))

    grupos = list(sesion_bd.scalars(consulta).all())
    return _serializar_grupos(sesion_bd, grupos, id_org_alcance)


@enrutador.post("/groups", response_model=GrupoLeer, status_code=status.HTTP_201_CREATED)
def crear_grupo(
    carga: GrupoCrear,
    usuario_actual: Usuario = Depends(requerir_roles("superadmin", "org_admin")),
    sesion_bd: Session = Depends(obtener_bd),
) -> GrupoLeer:
    """Crea un grupo académico o departamento empresarial sincronizando turno si aplica."""
    validar_acceso_organizacion(usuario_actual, carga.id_organizacion)
    organizacion = sesion_bd.get(Organizacion, carga.id_organizacion)
    if organizacion is None:
        raise HTTPException(status_code=404, detail="Organización no encontrada.")

    if carga.id_carrera is not None:
        carrera = sesion_bd.get(Carrera, carga.id_carrera)
        if carrera is None or carrera.id_organizacion != organizacion.id:
            raise HTTPException(
                status_code=404,
                detail="Carrera no encontrada en la organización.",
            )

    turno_para_defecto: TurnoLaboral | None = None
    if carga.id_turno_laboral_defecto is not None:
        turno_para_defecto = sesion_bd.get(TurnoLaboral, carga.id_turno_laboral_defecto)
        if turno_para_defecto is None or turno_para_defecto.id_organizacion != organizacion.id:
            raise HTTPException(
                status_code=404,
                detail="Turno laboral no encontrado en la organización.",
            )

    datos_grupo = carga.model_dump()
    if turno_para_defecto is not None:
        # Mantiene alineadas las columnas base del horario con el turno asignado por defecto
        datos_grupo["hora_inicio_horario"] = turno_para_defecto.hora_inicio
        datos_grupo["hora_fin_horario"] = turno_para_defecto.hora_fin
    if datos_grupo.get("semestre") is not None:
        datos_grupo["semestre"] = datos_grupo["semestre"].strip() or None
    if datos_grupo.get("aula_defecto") is not None:
        datos_grupo["aula_defecto"] = datos_grupo["aula_defecto"].strip() or None

    grupo = Grupo(**datos_grupo)
    sesion_bd.add(grupo)
    sesion_bd.commit()
    sesion_bd.refresh(grupo)
    return _serializar_grupos(sesion_bd, [grupo], organizacion.id)[0]


@enrutador.patch("/groups/{id_grupo}", response_model=GrupoLeer)
def actualizar_grupo(
    id_grupo: int,
    carga: GrupoActualizar,
    usuario_actual: Usuario = Depends(requerir_roles("superadmin", "org_admin")),
    sesion_bd: Session = Depends(obtener_bd),
) -> GrupoLeer:
    """Actualiza datos de grupo/área; cambiar periodo propio exige contraseña de administrador."""
    grupo = sesion_bd.get(Grupo, id_grupo)
    if grupo is None:
        raise HTTPException(status_code=404, detail="Grupo no encontrado.")
    validar_acceso_organizacion(usuario_actual, grupo.id_organizacion)

    datos_parciales = carga.model_dump(exclude_unset=True)
    secreto_autorizacion = datos_parciales.pop("secreto_autorizacion", None)

    if "tipo_periodo" in datos_parciales and datos_parciales["tipo_periodo"] != grupo.tipo_periodo:
        admin_autorizador = verificar_contrasena_admin(
            sesion_bd,
            usuario_actual=usuario_actual,
            id_organizacion=grupo.id_organizacion,
            secreto_autorizacion=secreto_autorizacion,
        )
        registrar_auditoria(
            sesion_bd,
            id_organizacion=grupo.id_organizacion,
            accion="change_group_period_type",
            tipo_objetivo="group",
            id_objetivo=grupo.id,
            resumen_objetivo=f"{grupo.nombre} ({grupo.codigo})",
            usuario_ejecutor=usuario_actual,
            usuario_autorizador=admin_autorizador,
            detalles=(
                f"Periodo grupo: {grupo.tipo_periodo or 'heredado'} -> "
                f"{datos_parciales['tipo_periodo'] or 'heredado'}"
            ),
        )

    if "id_carrera" in datos_parciales and datos_parciales["id_carrera"] is not None:
        carrera = sesion_bd.get(Carrera, datos_parciales["id_carrera"])
        if carrera is None or carrera.id_organizacion != grupo.id_organizacion:
            raise HTTPException(
                status_code=404,
                detail="Carrera no encontrada en la organización.",
            )

    if (
        "id_turno_laboral_defecto" in datos_parciales
        and datos_parciales["id_turno_laboral_defecto"] is not None
    ):
        turno = sesion_bd.get(TurnoLaboral, datos_parciales["id_turno_laboral_defecto"])
        if turno is None or turno.id_organizacion != grupo.id_organizacion:
            raise HTTPException(
                status_code=404,
                detail="Turno laboral no encontrado en la organización.",
            )
        # Sincroniza horario heredado con el turno por defecto recién seleccionado
        datos_parciales["hora_inicio_horario"] = turno.hora_inicio
        datos_parciales["hora_fin_horario"] = turno.hora_fin

    for campo, valor in datos_parciales.items():
        if campo in ("semestre", "aula_defecto") and isinstance(valor, str):
            setattr(grupo, campo, valor.strip() or None)
        else:
            setattr(grupo, campo, valor)

    sesion_bd.commit()
    sesion_bd.refresh(grupo)
    return _serializar_grupos(sesion_bd, [grupo], grupo.id_organizacion)[0]


@enrutador.delete("/groups/{id_grupo}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_grupo(
    id_grupo: int,
    usuario_actual: Usuario = Depends(requerir_roles("superadmin", "org_admin")),
    sesion_bd: Session = Depends(obtener_bd),
) -> None:
    """Elimina un grupo o departamento de la organización."""
    grupo = sesion_bd.get(Grupo, id_grupo)
    if grupo is None:
        raise HTTPException(status_code=404, detail="Grupo no encontrado.")
    validar_acceso_organizacion(usuario_actual, grupo.id_organizacion)
    sesion_bd.delete(grupo)
    sesion_bd.commit()
