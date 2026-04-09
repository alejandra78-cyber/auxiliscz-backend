from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.models import Usuario
from app.packages.auth.router import router as cambiar_password_router

router = APIRouter()
router.include_router(cambiar_password_router)


class RegisterIn(BaseModel):
    nombre: str = Field(..., min_length=3)
    email: EmailStr
    password: str = Field(..., min_length=6)
    telefono: str | None = None


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str


class UsuarioOut(BaseModel):
    id: str
    nombre: str
    email: EmailStr
    telefono: str | None = None
    rol: str

    class Config:
        from_attributes = True


@router.post("/register", response_model=UsuarioOut)
def register(datos: RegisterIn, db: Session = Depends(get_db)):
    existing = db.query(Usuario).filter(Usuario.email == datos.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="El email ya está registrado")

    usuario = Usuario(
        nombre=datos.nombre,
        email=datos.email,
        password_hash=get_password_hash(datos.password),
        telefono=datos.telefono,
        rol="conductor"
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


@router.post("/login", response_model=TokenOut)
def login(datos: LoginIn, db: Session = Depends(get_db)):
    usuario = db.query(Usuario).filter(Usuario.email == datos.email).first()
    if not usuario or not verify_password(datos.password, usuario.password_hash):
        raise HTTPException(status_code=401, detail="Email o contraseña incorrectos")

    token = create_access_token({"sub": str(usuario.id), "rol": usuario.rol})
    return {"access_token": token, "token_type": "bearer"}
