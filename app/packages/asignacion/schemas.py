from pydantic import BaseModel, Field


class AsignacionDemoOut(BaseModel):
    mensaje: str


class BuscarCandidatosIn(BaseModel):
    lat: float | None = None
    lng: float | None = None
    tipo: str | None = None
    prioridad: int | None = None


class AsignacionOut(BaseModel):
    taller_id: str | None = None
    nombre_taller: str | None = None
    mensaje: str
    distancia_km: float | None = None
    puntaje: float | None = None
    motivo_asignacion: str | None = None
    origen_asignacion: str | None = None


class AsignacionCandidatoOut(BaseModel):
    taller_id: str
    nombre: str
    distancia_km: float
    puntaje: float
    capacidad_disponible: int | None = None
    tecnicos_disponibles: int | None = None
    estado_operativo: str | None = None
    motivo: str | None = None


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
    estado_asignacion: str | None = None
    tecnico_id: str | None = None
    tecnico_nombre: str | None = None
    servicio: str | None = None
    incidente_id: str | None = None
    latitud: float | None = None
    longitud: float | None = None
    distancia_km: float | None = None
    puntaje_asignacion: float | None = None
    motivo_asignacion: str | None = None
    origen_asignacion: str | None = None
    motivo_rechazo: str | None = None
    fecha_asignacion: str | None = None
    fecha_respuesta_taller: str | None = None
    creado_en: str | None = None


class EvidenciaOut(BaseModel):
    id: str
    tipo: str
    url_archivo: str | None = None
    transcripcion: str | None = None
    metadata_json: str | None = None
    subido_en: str | None = None


class SolicitudServicioDetalleOut(SolicitudServicioOut):
    evidencias: list[EvidenciaOut] = Field(default_factory=list)


class EvaluarSolicitudIn(BaseModel):
    aprobar: bool = True
    observacion: str | None = None


class RechazarSolicitudIn(BaseModel):
    motivo_rechazo: str | None = None


class AsignarServicioIn(BaseModel):
    tecnico_id: str
    servicio: str
    taller_id: str | None = None
    observacion: str | None = None


class ActualizarEstadoIn(BaseModel):
    estado: str
    tecnico_id: str | None = None
    observacion: str | None = None


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
