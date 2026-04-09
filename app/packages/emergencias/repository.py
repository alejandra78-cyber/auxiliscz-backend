from sqlalchemy.orm import Session

from app.models.models import Evidencia, HistorialEstado, Incidente


def crear_incidente(
    db: Session,
    *,
    usuario_id,
    vehiculo_id: str,
    lat: float,
    lng: float,
    descripcion: str | None,
) -> Incidente:
    incidente = Incidente(
        usuario_id=usuario_id,
        vehiculo_id=vehiculo_id,
        lat_incidente=lat,
        lng_incidente=lng,
        descripcion=descripcion,
        estado="pendiente",
        prioridad=2,
    )
    db.add(incidente)
    db.flush()
    return incidente


def agregar_evidencia(
    db: Session,
    *,
    incidente_id,
    tipo: str,
    transcripcion: str | None = None,
    url_archivo: str | None = None,
) -> Evidencia:
    evidencia = Evidencia(
        incidente_id=incidente_id,
        tipo=tipo,
        transcripcion=transcripcion,
        url_archivo=url_archivo,
    )
    db.add(evidencia)
    return evidencia


def registrar_historial(
    db: Session,
    *,
    incidente_id,
    estado_anterior: str | None,
    estado_nuevo: str,
) -> HistorialEstado:
    historial = HistorialEstado(
        incidente_id=incidente_id,
        estado_anterior=estado_anterior,
        estado_nuevo=estado_nuevo,
    )
    db.add(historial)
    return historial


def obtener_incidente_por_id(db: Session, incidente_id: str) -> Incidente | None:
    return db.query(Incidente).filter(Incidente.id == incidente_id).first()

