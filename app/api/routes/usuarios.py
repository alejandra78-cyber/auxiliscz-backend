from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import Usuario

router = APIRouter()


class UsuarioOut(BaseModel):
    id: str
    nombre: str
    email: EmailStr
    telefono: str | None = None
    rol: str

    class Config:
        from_attributes = True


class UsuarioUpdateIn(BaseModel):
    nombre: str = Field(..., min_length=3)
    telefono: str | None = None


@router.get("/me", response_model=UsuarioOut)
def read_current_user(current_user=Depends(get_current_user)):
    return current_user


@router.patch("/me", response_model=UsuarioOut)
def update_current_user(
    payload: UsuarioUpdateIn,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    current_user.nombre = payload.nombre
    current_user.telefono = payload.telefono
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return current_user
