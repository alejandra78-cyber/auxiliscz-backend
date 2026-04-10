from pydantic import BaseModel, Field


class VehiculoCreateIn(BaseModel):
    placa: str = Field(..., min_length=5, max_length=20)
    marca: str | None = None
    modelo: str | None = None
    anio: int | None = Field(default=None, ge=1950, le=2100)
    color: str | None = None


class VehiculoOut(BaseModel):
    id: str
    placa: str
    marca: str | None = None
    modelo: str | None = None
    anio: int | None = None
    color: str | None = None

    class Config:
        from_attributes = True
