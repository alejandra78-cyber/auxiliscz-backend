from datetime import datetime
from pydantic import BaseModel, Field
from uuid import UUID

class VehiculoCreateIn(BaseModel):
    placa: str = Field(..., min_length=5, max_length=20)
    marca: str | None = None
    modelo: str | None = None
    anio: int | None = Field(default=None, ge=1950, le=2100)
    color: str | None = None

class VehiculoOut(BaseModel):
    id: UUID
    placa: str
    marca: str | None = None
    modelo: str | None = None
    anio: int | None = None
    color: str | None = None

    class Config:
        from_attributes = True

class EstadoSolicitudClienteOut(BaseModel):
    incidente_id: str
    codigo_solicitud: str | None = None
    estado: str
    prioridad: int | None = None
    tipo: str | None = None
    taller_id: str | None = None
    taller_nombre: str | None = None

class UbicacionTecnicoOut(BaseModel):
    incidente_id: str
    codigo_solicitud: str | None = None
    tecnico_id: str | None = None
    tecnico_nombre: str | None = None
    especialidad: str | None = None
    lat: float | None = None
    lng: float | None = None
    estado: str
    mensaje: str


class SolicitudSeguimientoOut(BaseModel):
    incidente_id: str
    codigo_solicitud: str
    estado: str
    tipo: str | None = None
    prioridad: int | None = None 

class EvaluacionCreateIn(BaseModel):
    estrellas: int = Field(..., ge=1, le=5)
    comentario: str | None = Field(default=None, max_length=500)


class EvaluacionOut(BaseModel):
    evaluacion_id: str
    incidente_id: str
    codigo_solicitud: str
    estrellas: int
    comentario: str | None = None
    mensaje: str


class HistorialServicioOut(BaseModel):
    incidente_id: str
    codigo_solicitud: str
    estado: str
    tipo: str | None = None
    prioridad: int | None = None
    vehiculo_placa: str | None = None
    vehiculo: str | None = None
    taller_nombre: str | None = None
    tecnico_nombre: str | None = None
    monto_pagado: float | None = None
    pago_estado: str | None = None
    calificacion: int | None = None
    comentario_evaluacion: str | None = None
    creado_en: datetime | None = None
    actualizado_en: datetime | None = None                  