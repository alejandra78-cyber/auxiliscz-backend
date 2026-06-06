from pydantic import BaseModel, Field


class TecnicoUbicacionIn(BaseModel):
    asignacion_id: str
    latitud: float = Field(..., ge=-90, le=90)
    longitud: float = Field(..., ge=-180, le=180)


class TecnicoUbicacionOut(BaseModel):
    mensaje: str
    estado_servicio: str
    ultima_actualizacion: str


class TecnicoAccionEstadoIn(BaseModel):
    asignacion_id: str
    accion: str = Field(..., min_length=3, max_length=40)


class TrabajoCompletadoIn(BaseModel):
    asignacion_id: str
    descripcion: str = Field(..., min_length=5, max_length=4000)
    observaciones: str | None = Field(default=None, max_length=2000)
    evidencias: list[str] = Field(default_factory=list)


class TecnicoServicioAsignadoOut(BaseModel):
    asignacion_id: str
    incidente_id: str
    codigo_solicitud: str
    estado_servicio: str
    cliente_nombre: str | None = None
    vehiculo_placa: str | None = None
    tipo_problema: str | None = None
    tecnico_nombre: str

