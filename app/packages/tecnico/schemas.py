from pydantic import BaseModel, Field


class TecnicoUbicacionIn(BaseModel):
    asignacion_id: str
    latitud: float = Field(..., ge=-90, le=90)
    longitud: float = Field(..., ge=-180, le=180)


class TecnicoUbicacionOut(BaseModel):
    mensaje: str
    estado_servicio: str
    ultima_actualizacion: str


class TecnicoServicioAsignadoOut(BaseModel):
    asignacion_id: str
    incidente_id: str
    codigo_solicitud: str
    estado_servicio: str
    cliente_nombre: str | None = None
    vehiculo_placa: str | None = None
    tipo_problema: str | None = None
    tecnico_nombre: str

