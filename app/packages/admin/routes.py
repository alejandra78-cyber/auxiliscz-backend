from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from uuid import UUID

from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.usuarios import router as usuarios_router
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import Usuario

from .services import estado_paquete_admin

router = APIRouter()


@router.get("/estado")
def estado():
    return estado_paquete_admin()


class UsuarioAdminOut(BaseModel):
    id: UUID
    nombre: str
    email: EmailStr
    telefono: str | None = None
    rol: str

    class Config:
        from_attributes = True


@router.get("/usuarios/lista", response_model=list[UsuarioAdminOut])
def listar_usuarios_admin(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    if current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede listar usuarios")
    usuarios = db.query(Usuario).order_by(Usuario.creado_en.desc()).all()
    return usuarios


@router.get("/usuarios/taller-candidatos", response_model=list[UsuarioAdminOut])
def listar_candidatos_taller(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    if current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede listar candidatos a taller")
    usuarios = (
        db.query(Usuario)
        .filter(Usuario.rol == "taller")
        .filter(Usuario.taller == None)  # noqa: E711
        .order_by(Usuario.creado_en.desc())
        .all()
    )
    return usuarios


# Compatibilidad y reorganización: expone funcionalidades existentes bajo /api/admin/*
router.include_router(usuarios_router, prefix="/usuarios")
router.include_router(dashboard_router, prefix="/reportes")
