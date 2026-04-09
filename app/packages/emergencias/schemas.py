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

