from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import Taller, Usuario

from .schemas import TenantAsignarTallerIn, TenantAsignarUsuarioIn, TenantCreate, TenantOpcionOut, TenantOut, TenantUpdate
from .services import (
    actualizar_tenant,
    asignar_taller,
    asignar_usuario,
    crear_tenant,
    listar_tenants,
    require_admin,
    tenant_out,
)

router = APIRouter()


@router.get("", response_model=list[TenantOut])
def listar(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    require_admin(current_user)
    return [tenant_out(db, item) for item in listar_tenants(db)]


@router.get("/usuarios-opciones", response_model=list[TenantOpcionOut])
def usuarios_opciones(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    require_admin(current_user)
    rows = db.query(Usuario).order_by(Usuario.nombre.asc()).all()
    return [
        TenantOpcionOut(
            id=str(row.id),
            label=f"{row.nombre} - {row.email} - {row.rol}",
            tenant_id=str(row.tenant_id) if row.tenant_id else None,
        )
        for row in rows
    ]


@router.get("/talleres-opciones", response_model=list[TenantOpcionOut])
def talleres_opciones(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    require_admin(current_user)
    rows = db.query(Taller).order_by(Taller.nombre.asc()).all()
    return [
        TenantOpcionOut(
            id=str(row.id),
            label=f"{row.nombre} - {row.estado_aprobacion}",
            tenant_id=str(row.tenant_id) if row.tenant_id else None,
        )
        for row in rows
    ]


@router.post("", response_model=TenantOut)
def crear(
    payload: TenantCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    require_admin(current_user)
    tenant = crear_tenant(db, payload=payload, current_user=current_user)
    return tenant_out(db, tenant)


@router.patch("/{tenant_id}", response_model=TenantOut)
def actualizar(
    tenant_id: str,
    payload: TenantUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    require_admin(current_user)
    tenant = actualizar_tenant(db, tenant_id=tenant_id, payload=payload, current_user=current_user)
    return tenant_out(db, tenant)


@router.post("/{tenant_id}/usuarios", response_model=TenantOut)
def asignar_usuario_tenant(
    tenant_id: str,
    payload: TenantAsignarUsuarioIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    require_admin(current_user)
    tenant = asignar_usuario(db, tenant_id=tenant_id, usuario_id=payload.usuario_id, current_user=current_user)
    return tenant_out(db, tenant)


@router.post("/{tenant_id}/talleres", response_model=TenantOut)
def asignar_taller_tenant(
    tenant_id: str,
    payload: TenantAsignarTallerIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    require_admin(current_user)
    tenant = asignar_taller(db, tenant_id=tenant_id, taller_id=payload.taller_id, current_user=current_user)
    return tenant_out(db, tenant)
