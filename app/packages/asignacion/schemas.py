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


class SolicitudServicioOut(BaseModel):
    id: str
    codigo_solicitud: str | None = None
    estado: str
    tipo: str | None = None
    tipo_sugerido_ia: str | None = None
    descripcion: str | None = None
    prioridad: int | None = None
    prioridad_sugerida_ia: int | None = None
    resumen_ia: str | None = None
    cliente_nombre: str | None = None
    vehiculo_id: str | None = None
    usuario_id: str
    taller_id: str | None = None
    taller_nombre: str | None = None
    tecnico_id: str | None = None
    tecnico_nombre: str | None = None
    servicio: str | None = None
    creado_en: str | None = None


class EvaluarSolicitudIn(BaseModel):
    aprobar: bool = True
    observacion: str | None = None


class AsignarServicioIn(BaseModel):
    tecnico_id: str
    servicio: str
    taller_id: str | None = None
    observacion: str | None = None


class ActualizarEstadoIn(BaseModel):
    estado: str
    observacion: str | None = None
    costo: float | None = None


class TecnicoDisponibleOut(BaseModel):
    id: str
    nombre: str
    especialidad: str | None = None
    disponible: bool


class ServicioCatalogoOut(BaseModel):
    codigo: str
    nombre: str
    descripcion: str


class SugerenciaAsignacionOut(BaseModel):
    solicitud_id: str
    codigo_solicitud: str
    tecnico_id: str | None = None
    tecnico_nombre: str | None = None
    taller_id: str | None = None
    taller_nombre: str | None = None
    servicio_sugerido: str | None = None
    puntaje: float | None = None
    motivo: str | None = None
