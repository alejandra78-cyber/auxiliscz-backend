from pydantic import BaseModel, Field
from typing import Any


class ReportarEmergenciaOut(BaseModel):
    incidente_id: str
    estado: str
    tipo: str | None = None
    prioridad: int | None = None
    resumen_ia: str | None = None
    ia_estado: str | None = None
    asignacion_id: str | None = None
    mensaje: str


class EstadoSolicitudOut(BaseModel):
    incidente_id: str
    estado: str
    es_cancelable: bool = False
    fecha_actualizacion: str | None = None
    prioridad: int | None = None
    tipo: str | None = None
    resumen_ia: str | None = None
    taller_id: str | None = None
    taller_nombre: str | None = None
    tecnico_id: str | None = None
    tecnico_nombre: str | None = None


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


class CancelarSolicitudOut(BaseModel):
    incidente_id: str
    estado: str
    mensaje: str = "Solicitud cancelada correctamente"


class CancelarSolicitudIn(BaseModel):
    motivo_cancelacion: str | None = None


class MensajeIn(BaseModel):
    texto: str


class MensajeOut(BaseModel):
    evidencia_id: str
    autor_rol: str
    texto: str
    creado_en: str | None = None


class NotificacionOut(BaseModel):
    id: str
    solicitud_id: str | None = None
    incidente_id: str | None = None
    titulo: str
    mensaje: str
    tipo: str
    estado: str
    creada_en: str | None = None


class OperacionOfflineIn(BaseModel):
    offline_sync_id: str
    tipo_operacion: str
    fecha_local: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class SyncOfflineIn(BaseModel):
    operaciones: list[OperacionOfflineIn]


class OperacionOfflineOut(BaseModel):
    offline_sync_id: str
    tipo_operacion: str
    estado_sync: str
    resultado: dict[str, Any] | None = None
    error: str | None = None


class SyncOfflineOut(BaseModel):
    resultados: list[OperacionOfflineOut]
