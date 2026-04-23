from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    nombre: str = Field(..., min_length=3)
    email: EmailStr
    password: str = Field(..., min_length=6)
    telefono: str | None = None
    rol: str = Field(default="conductor", pattern="^(conductor|taller|tecnico|admin)$")


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
    nuevo_rol: str = Field(..., pattern="^(conductor|taller|tecnico|admin)$")


class RecuperarPasswordRequestIn(BaseModel):
    email: EmailStr


class RecuperarPasswordRequestOut(BaseModel):
    ok: bool = True
    mensaje: str = "Si el correo existe, se generó un token de recuperación"
    reset_token: str | None = None


class ResetPasswordIn(BaseModel):
    reset_token: str
    nueva_password: str = Field(..., min_length=6)


class ValidateResetTokenIn(BaseModel):
    reset_token: str


class ValidateResetTokenOut(BaseModel):
    ok: bool = True
    mensaje: str = "Token válido"


class CambiarPasswordIn(BaseModel):
    password_actual: str = Field(..., min_length=6)
    password_nueva: str = Field(..., min_length=6)
    password_nueva_confirmacion: str = Field(..., min_length=6)


class CambiarPasswordOut(BaseModel):
    ok: bool = True
    mensaje: str = "Contraseña actualizada correctamente"


class DeviceTokenIn(BaseModel):
    token: str = Field(..., min_length=20, max_length=512)
    plataforma: str | None = Field(default="unknown", max_length=30)


class DeviceTokenOut(BaseModel):
    ok: bool = True
    mensaje: str = "Token de dispositivo actualizado"
