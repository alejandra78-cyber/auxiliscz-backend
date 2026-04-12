from pydantic import BaseModel


class ReportarEmergenciaOut(BaseModel):
    incidente_id: str
    estado: str
    mensaje: str


class EstadoSolicitudOut(BaseModel):
    incidente_id: str
    estado: str
    prioridad: int | None = None
    tipo: str | None = None
    taller_id: str | None = None


class UbicacionGpsIn(BaseModel):
    lat: float
    lng: float


class UbicacionGpsOut(BaseModel):
    incidente_id: str
    lat: float
    lng: float
    mensaje: str = "Ubicacion actualizada correctamente"


class ImagenIncidenteOut(BaseModel):
    incidente_id: str
    evidencia_id: str
    mensaje: str = "Imagen registrada correctamente"
