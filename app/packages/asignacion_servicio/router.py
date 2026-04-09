from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db

from .schemas import AsignacionOut, BuscarCandidatosIn
from .service import (
    asignar_taller_automaticamente,
    buscar_talleres_candidatos_cercanos,
    reasignar_taller,
)

router = APIRouter()


@router.post("/candidatos")
async def buscar_candidatos(payload: BuscarCandidatosIn, db: Session = Depends(get_db)):
    return await buscar_talleres_candidatos_cercanos(
        db,
        lat=payload.lat,
        lng=payload.lng,
        tipo=payload.tipo,
        prioridad=payload.prioridad,
    )


@router.post("/asignar/{incidente_id}", response_model=AsignacionOut)
async def asignar_automatico(incidente_id: str, payload: BuscarCandidatosIn, db: Session = Depends(get_db)):
    taller = await asignar_taller_automaticamente(
        db,
        incidente_id=incidente_id,
        lat=payload.lat,
        lng=payload.lng,
        tipo=payload.tipo,
        prioridad=payload.prioridad,
    )
    if not taller:
        return AsignacionOut(mensaje="No se encontraron talleres disponibles")
    return AsignacionOut(
        taller_id=str(taller.id),
        nombre_taller=taller.nombre,
        mensaje="Taller asignado automáticamente",
    )


@router.post("/reasignar/{incidente_id}", response_model=AsignacionOut)
async def reasignar(incidente_id: str, payload: BuscarCandidatosIn, db: Session = Depends(get_db)):
    candidato = await reasignar_taller(
        db,
        incidente_id=incidente_id,
        lat=payload.lat,
        lng=payload.lng,
        tipo=payload.tipo,
        prioridad=payload.prioridad,
    )
    if not candidato:
        return AsignacionOut(mensaje="No hay un candidato alternativo para reasignar")
    return AsignacionOut(
        taller_id=str(candidato.get("taller_id")),
        nombre_taller=candidato.get("nombre"),
        mensaje="Taller reasignado correctamente",
    )

