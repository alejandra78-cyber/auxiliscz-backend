from pydantic import BaseModel


class AsignacionDemoOut(BaseModel):
    mensaje: str


class BuscarCandidatosIn(BaseModel):
    lat: float
    lng: float
    tipo: str
    prioridad: int


class AsignacionOut(BaseModel):
    taller_id: str | None = None
    nombre_taller: str | None = None
    mensaje: str
