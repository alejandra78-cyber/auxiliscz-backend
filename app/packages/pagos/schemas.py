from pydantic import BaseModel, Field


class PagosDemoOut(BaseModel):
    mensaje: str


class CotizacionCreateIn(BaseModel):
    incidente_id: str
    monto_total: float = Field(..., gt=0)
    detalle: str = Field(..., min_length=3, max_length=4000)
    observaciones: str | None = Field(default=None, max_length=2000)
    validez_hasta: str | None = None


class CotizacionOut(BaseModel):
    id: str
    incidente_id: str | None = None
    solicitud_id: str | None = None
    asignacion_id: str | None = None
    taller_id: str | None = None
    cliente_id: str | None = None
    monto_total: float
    detalle: str | None = None
    observaciones: str | None = None
    estado: str
    fecha_emision: str | None = None
    validez_hasta: str | None = None
    fecha_respuesta_cliente: str | None = None
    codigo_solicitud: str | None = None
    cliente_nombre: str | None = None
    vehiculo_placa: str | None = None
    tipo_problema: str | None = None


class CotizacionDecisionIn(BaseModel):
    observaciones: str | None = Field(default=None, max_length=2000)


class CotizacionDecisionOut(BaseModel):
    cotizacion_id: str
    estado_cotizacion: str
    incidente_id: str | None = None
    estado_incidente: str | None = None
    estado_solicitud: str | None = None
    mensaje: str


class PagoProcesarIn(BaseModel):
    cotizacion_id: str
    metodo_pago: str = Field(..., min_length=2, max_length=50)
    comprobante_url: str | None = Field(default=None, max_length=500)
    referencia: str | None = Field(default=None, max_length=120)


class PagoOut(BaseModel):
    id: str
    codigo_visible: str
    cotizacion_id: str
    incidente_id: str | None = None
    estado: str
    metodo_pago: str | None = None
    monto_total: float
    comision_plataforma: float | None = None
    monto_taller: float | None = None
    comprobante_url: str | None = None
    referencia: str | None = None
    fecha_pago: str | None = None
    fecha_verificacion: str | None = None
    mensaje: str | None = None
