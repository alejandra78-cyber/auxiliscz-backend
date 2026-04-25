from pydantic import BaseModel, Field
from uuid import UUID


class VehiculoCreateIn(BaseModel):
    placa: str = Field(..., min_length=5, max_length=20)
    marca: str = Field(..., min_length=2, max_length=80)
    modelo: str = Field(..., min_length=1, max_length=80)
    anio: int | None = Field(default=None, ge=1950, le=2100)
    color: str | None = None
    tipo: str | None = Field(default=None, max_length=40)
    observacion: str | None = Field(default=None, max_length=500)


class VehiculoUpdateIn(BaseModel):
    marca: str = Field(..., min_length=2, max_length=80)
    modelo: str = Field(..., min_length=1, max_length=80)
    anio: int | None = Field(default=None, ge=1950, le=2100)
    color: str | None = None
    tipo: str | None = Field(default=None, max_length=40)
    observacion: str | None = Field(default=None, max_length=500)


class VehiculoOut(BaseModel):
    id: UUID
    placa: str
    marca: str | None = None
    modelo: str | None = None
    anio: int | None = None
    color: str | None = None
    tipo: str | None = None
    observacion: str | None = None
    activo: bool = True

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


class CancelarSolicitudClienteIn(BaseModel):
    motivo_cancelacion: str | None = Field(default=None, max_length=500)


class SolicitudAccionesOut(BaseModel):
    puede_cancelar: bool = False
    puede_ver_tecnico: bool = False
    puede_ver_cotizacion: bool = False
    puede_pagar: bool = False
    puede_evaluar_servicio: bool = False


class SolicitudVehiculoOut(BaseModel):
    id: str
    placa: str
    marca: str | None = None
    modelo: str | None = None
    color: str | None = None
    tipo: str | None = None


class SolicitudTallerOut(BaseModel):
    id: str | None = None
    nombre: str | None = None
    estado: str | None = None


class SolicitudTecnicoOut(BaseModel):
    id: str | None = None
    nombre: str | None = None
    estado: str | None = None


class SolicitudUbicacionOut(BaseModel):
    latitud: float | None = None
    longitud: float | None = None


class HistorialEstadoOut(BaseModel):
    estado_anterior: str | None = None
    estado_nuevo: str
    comentario: str | None = None
    creado_en: str | None = None


class CotizacionActualOut(BaseModel):
    id: str
    monto: float
    estado: str
    detalle: str | None = None
    creado_en: str | None = None


class PagoActualOut(BaseModel):
    id: str
    estado: str
    monto: float | None = None
    metodo: str | None = None
    pagado_en: str | None = None


class SolicitudClienteListItemOut(BaseModel):
    incidente_id: str
    codigo_solicitud: str
    estado: str
    prioridad: int | None = None
    tipo: str | None = None
    fecha_reporte: str | None = None
    vehiculo: SolicitudVehiculoOut | None = None
    acciones_disponibles: SolicitudAccionesOut


class SolicitudClienteDetalleOut(BaseModel):
    incidente_id: str
    codigo_solicitud: str
    estado: str
    prioridad: int | None = None
    tipo_problema: str | None = None
    fecha_reporte: str | None = None
    fecha_actualizacion: str | None = None
    resumen_ia: str | None = None
    vehiculo: SolicitudVehiculoOut | None = None
    ubicacion: SolicitudUbicacionOut | None = None
    taller_asignado: SolicitudTallerOut | None = None
    tecnico_asignado: SolicitudTecnicoOut | None = None
    historial: list[HistorialEstadoOut] = []
    cotizacion_actual: CotizacionActualOut | None = None
    pago_actual: PagoActualOut | None = None
    acciones_disponibles: SolicitudAccionesOut
