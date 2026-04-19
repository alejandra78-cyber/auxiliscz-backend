import json

from sqlalchemy.orm import Session

from app.models.models import Taller


def crear_taller(
    db: Session,
    *,
    usuario_id: str,
    nombre: str,
    direccion: str | None,
    latitud: float | None,
    longitud: float | None,
    servicios: list[str],
    disponible: bool,
) -> Taller:
    taller = Taller(
        usuario_id=usuario_id,
        nombre=nombre,
        direccion=direccion,
        latitud=latitud,
        longitud=longitud,
        servicios=json.dumps(servicios),
        disponible=disponible,
    )
    db.add(taller)
    db.commit()
    db.refresh(taller)
    return taller


def get_taller_by_usuario_id(db: Session, usuario_id: str) -> Taller | None:
    return db.query(Taller).filter(Taller.usuario_id == usuario_id).first()


def actualizar_disponibilidad(db: Session, taller: Taller, disponible: bool) -> Taller:
    taller.disponible = disponible
    db.add(taller)
    db.commit()
    db.refresh(taller)
    return taller


def parsear_servicios(taller: Taller) -> Taller:
    try:
        taller.servicios = json.loads(taller.servicios or "[]")
    except Exception:
        taller.servicios = []
    return taller
