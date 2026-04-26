import uuid
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import (
    Auditoria,
    Cotizacion,
    Evaluacion,
    Incidente,
    Pago,
    Rol,
    Taller,
    Usuario,
    UsuarioRol,
)

from .services import estado_paquete_admin

router = APIRouter()


def _only_admin(current_user) -> None:
    if current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="Solo admin")


class UsuarioAdminOut(BaseModel):
    id: str
    nombre: str
    email: EmailStr
    telefono: str | None = None
    estado: str
    rol: str


class UsuarioEstadoIn(BaseModel):
    estado: str


class UsuarioRolIn(BaseModel):
    rol: str


class AdminResumenOut(BaseModel):
    incidentes: dict
    talleres: dict
    servicios_completados: int
    pagos: dict
    comision_total: float
    promedio_calificacion: float
    incidentes_por_tipo: dict
    incidentes_por_estado: dict


@router.get("/estado")
def estado():
    return estado_paquete_admin()


@router.get("/usuarios/me")
def mi_usuario_admin(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _only_admin(current_user)
    return {
        "id": str(current_user.id),
        "nombre": current_user.nombre,
        "email": current_user.email,
        "telefono": current_user.telefono,
        "rol": current_user.rol,
    }


@router.get("/usuarios", response_model=list[UsuarioAdminOut])
def listar_usuarios_admin(
    rol: str | None = None,
    estado: str | None = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _only_admin(current_user)
    query = db.query(Usuario)
    if (estado or "").strip():
        query = query.filter(Usuario.estado == estado.strip().lower())
    rows = query.order_by(Usuario.creado_en.desc()).all()
    out: list[UsuarioAdminOut] = []
    rol_filter = (rol or "").strip().lower()
    for u in rows:
        urol = u.rol
        if rol_filter and rol_filter != urol:
            continue
        out.append(
            UsuarioAdminOut(
                id=str(u.id),
                nombre=u.nombre,
                email=u.email,
                telefono=u.telefono,
                estado=u.estado or "activo",
                rol=urol,
            )
        )
    return out


@router.patch("/usuarios/{usuario_id}/estado", response_model=UsuarioAdminOut)
def cambiar_estado_usuario(
    usuario_id: str,
    payload: UsuarioEstadoIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _only_admin(current_user)
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    nuevo = (payload.estado or "").strip().lower()
    if nuevo not in {"activo", "inactivo", "bloqueado"}:
        raise HTTPException(status_code=400, detail="Estado no válido")
    usuario.estado = nuevo
    db.add(
        Auditoria(
            id=uuid.uuid4(),
            usuario_id=current_user.id,
            accion="cu26_cambiar_estado_usuario",
            modulo="admin",
            detalle=f"usuario_id={usuario.id}; estado={nuevo}",
        )
    )
    db.commit()
    db.refresh(usuario)
    return UsuarioAdminOut(
        id=str(usuario.id),
        nombre=usuario.nombre,
        email=usuario.email,
        telefono=usuario.telefono,
        estado=usuario.estado or "activo",
        rol=usuario.rol,
    )


@router.patch("/usuarios/{usuario_id}/rol", response_model=UsuarioAdminOut)
def cambiar_rol_usuario(
    usuario_id: str,
    payload: UsuarioRolIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _only_admin(current_user)
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    nuevo_rol = (payload.rol or "").strip().lower()
    if nuevo_rol not in {"admin", "taller", "tecnico", "cliente", "conductor"}:
        raise HTTPException(status_code=400, detail="Rol no válido")
    rol_row = db.query(Rol).filter(Rol.nombre == nuevo_rol).first()
    if not rol_row:
        rol_row = Rol(id=uuid.uuid4(), nombre=nuevo_rol, descripcion=f"Rol {nuevo_rol}")
        db.add(rol_row)
        db.flush()
    db.query(UsuarioRol).filter(UsuarioRol.usuario_id == usuario.id).delete()
    db.add(UsuarioRol(id=uuid.uuid4(), usuario_id=usuario.id, rol_id=rol_row.id))
    db.add(
        Auditoria(
            id=uuid.uuid4(),
            usuario_id=current_user.id,
            accion="cu26_cambiar_rol_usuario",
            modulo="admin",
            detalle=f"usuario_id={usuario.id}; rol={nuevo_rol}",
        )
    )
    db.commit()
    db.refresh(usuario)
    return UsuarioAdminOut(
        id=str(usuario.id),
        nombre=usuario.nombre,
        email=usuario.email,
        telefono=usuario.telefono,
        estado=usuario.estado or "activo",
        rol=usuario.rol,
    )


@router.get("/reportes/resumen", response_model=AdminResumenOut)
def resumen_reportes(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _only_admin(current_user)

    total_incidentes = db.query(Incidente).count()
    hoy = datetime.now().date()
    incidentes_hoy = db.query(Incidente).filter(func.date(Incidente.creado_en) == hoy).count()
    incidentes_mes = (
        db.query(Incidente)
        .filter(func.date_part("year", Incidente.creado_en) == hoy.year)
        .filter(func.date_part("month", Incidente.creado_en) == hoy.month)
        .count()
    )

    talleres_total = db.query(Taller).count()
    talleres_aprobados = db.query(Taller).filter(Taller.estado_aprobacion == "aprobado").count()
    talleres_pendientes = db.query(Taller).filter(Taller.estado_aprobacion == "pendiente").count()

    pagos_rows = db.query(Pago).all()
    pagos_total = len(pagos_rows)
    pagos_pagados = sum(1 for p in pagos_rows if (p.estado or "").lower() == "pagado")
    comision_total = float(sum(float(p.comision_plataforma or 0) for p in pagos_rows))
    ingresos_total = float(sum(float(p.monto or 0) for p in pagos_rows if (p.estado or "").lower() == "pagado"))

    servicios_completados = (
        db.query(Incidente)
        .filter(Incidente.estado.in_(["trabajo_completado", "esperando_pago", "pagado", "finalizado"]))
        .count()
    )

    avg_eval = db.query(func.avg(Evaluacion.estrellas)).scalar()
    promedio_calificacion = float(round(avg_eval or 0, 2))

    por_tipo = defaultdict(int)
    for t, c in db.query(Incidente.tipo, func.count(Incidente.id)).group_by(Incidente.tipo).all():
        por_tipo[str(t or "otro")] = int(c)

    por_estado = defaultdict(int)
    for e, c in db.query(Incidente.estado, func.count(Incidente.id)).group_by(Incidente.estado).all():
        por_estado[str(e or "desconocido")] = int(c)

    return AdminResumenOut(
        incidentes={
            "total": int(total_incidentes),
            "hoy": int(incidentes_hoy),
            "este_mes": int(incidentes_mes),
        },
        talleres={
            "total": int(talleres_total),
            "aprobados": int(talleres_aprobados),
            "pendientes": int(talleres_pendientes),
        },
        servicios_completados=int(servicios_completados),
        pagos={
            "total": int(pagos_total),
            "pagados": int(pagos_pagados),
            "ingresos_total": ingresos_total,
        },
        comision_total=comision_total,
        promedio_calificacion=promedio_calificacion,
        incidentes_por_tipo=dict(por_tipo),
        incidentes_por_estado=dict(por_estado),
    )
