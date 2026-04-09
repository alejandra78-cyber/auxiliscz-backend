from pydantic import BaseModel, Field


class CambiarPasswordIn(BaseModel):
    password_actual: str = Field(..., min_length=6)
    password_nueva: str = Field(..., min_length=6)
    password_nueva_confirmacion: str = Field(..., min_length=6)


class CambiarPasswordOut(BaseModel):
    ok: bool = True
    mensaje: str = "Contraseña actualizada correctamente"

