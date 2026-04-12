from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.models import Incidente
from app.services.asignacion import listar_candidatos, motor_asignacion

from .schemas import AsignacionDemoOut


def estado_paquete_asignacion() -> AsignacionDemoOut:
    return AsignacionDemoOut(mensaje="Paquete asignacion listo")


async def buscar_talleres_candidatos_cercanos(
    db: Session,
    *,
    lat: float,
    lng: float,
    tipo: str,
    prioridad: int,
) -> list[dict]:
    return await listar_candidatos(db, lat=lat, lng=lng, tipo=tipo, prioridad=prioridad)


async def asignar_taller_automaticamente(
    db: Session,
    *,
    incidente_id: str,
    lat: float,
    lng: float,
    tipo: str,
    prioridad: int,
):
    incidente = db.query(Incidente).filter(Incidente.id == incidente_id).first()
    if not incidente:
        raise HTTPException(status_code=404, detail="Incidente no encontrado")

    taller = await motor_asignacion(db, lat=lat, lng=lng, tipo=tipo, prioridad=prioridad)
    if taller:
        incidente.taller_id = taller.id
        incidente.estado = "en_proceso"
        db.commit()
        db.refresh(incidente)
    return taller


async def reasignar_taller(
    db: Session,
    *,
    incidente_id: str,
    lat: float,
    lng: float,
    tipo: str,
    prioridad: int,
):
    incidente = db.query(Incidente).filter(Incidente.id == incidente_id).first()
    if not incidente:
        raise HTTPException(status_code=404, detail="Incidente no encontrado")

    candidatos = await listar_candidatos(db, lat=lat, lng=lng, tipo=tipo, prioridad=prioridad)
    if not candidatos:
        return None

    candidato = None
    for item in candidatos:
        if str(item.get("taller_id")) != str(incidente.taller_id):
            candidato = item
            break

    if not candidato:
        return None

    incidente.taller_id = candidato["taller_id"]
    incidente.estado = "en_proceso"
    db.commit()
    db.refresh(incidente)
    return candidato
