from pydantic import BaseModel, Field


class TallerCreateIn(BaseModel):
    usuario_id: str
    nombre: str = Field(..., min_length=3)
    direccion: str | None = None
    latitud: float | None = None
    longitud: float | None = None
    servicios: list[str] = Field(default_factory=list)
    disponible: bool = True


class DisponibilidadIn(BaseModel):
    disponible: bool


class TallerOut(BaseModel):
    id: str
    nombre: str
    direccion: str | None = None
    latitud: float | None = None
    longitud: float | None = None
    servicios: list[str]
    disponible: bool
    calificacion: float

    class Config:
        from_attributes = True
