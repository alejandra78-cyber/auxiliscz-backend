from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr
from app.core.security import get_current_user

router = APIRouter()


class UsuarioOut(BaseModel):
    id: str
    nombre: str
    email: EmailStr
    telefono: str | None = None
    rol: str

    class Config:
        from_attributes = True


@router.get("/me", response_model=UsuarioOut)
def read_current_user(current_user=Depends(get_current_user)):
    return current_user
