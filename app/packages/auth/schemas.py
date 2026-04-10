from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    nombre: str = Field(..., min_length=3)
    email: EmailStr
    password: str = Field(..., min_length=6)
    telefono: str | None = None
    rol: str = Field(default="conductor", pattern="^(conductor|taller|admin)$")


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UsuarioOut(BaseModel):
    id: UUID
    nombre: str
    email: EmailStr
    telefono: str | None = None
    rol: str
    creado_en: datetime | None = None

    class Config:
        from_attributes = True


class LogoutOut(BaseModel):
    ok: bool = True
    mensaje: str = "Sesión cerrada correctamente"


class RolPermisoOut(BaseModel):
    rol: str
    permisos: list[str]


class CambiarRolIn(BaseModel):
    usuario_id: str
    nuevo_rol: str = Field(..., pattern="^(conductor|taller|admin)$")


class RecuperarPasswordRequestIn(BaseModel):
    email: EmailStr


class RecuperarPasswordRequestOut(BaseModel):
    ok: bool = True
    mensaje: str = "Si el correo existe, se generó un token de recuperación"
    reset_token: str | None = None


class ResetPasswordIn(BaseModel):
    reset_token: str
    nueva_password: str = Field(..., min_length=6)


class CambiarPasswordIn(BaseModel):
    password_actual: str = Field(..., min_length=6)
    password_nueva: str = Field(..., min_length=6)
    password_nueva_confirmacion: str = Field(..., min_length=6)


class CambiarPasswordOut(BaseModel):
    ok: bool = True
    mensaje: str = "Contraseña actualizada correctamente"
