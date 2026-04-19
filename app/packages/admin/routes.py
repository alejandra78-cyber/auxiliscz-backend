from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from uuid import UUID

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import Rol, Usuario, UsuarioRol

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
    rol_taller = db.query(Rol).filter(Rol.nombre == "taller").first()
    if not rol_taller:
        return []
    usuarios = (
        db.query(Usuario)
        .join(UsuarioRol, UsuarioRol.usuario_id == Usuario.id)
        .filter(UsuarioRol.rol_id == rol_taller.id)
        .filter(Usuario.taller == None)  # noqa: E711
        .order_by(Usuario.creado_en.desc())
        .all()
    )
    return usuarios
