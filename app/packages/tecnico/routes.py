from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user

from .schemas import TecnicoServicioAsignadoOut, TecnicoUbicacionIn, TecnicoUbicacionOut
from .services import listar_mis_servicios_asignados, reportar_mi_ubicacion

router = APIRouter()


@router.get("/mis-servicios-asignados", response_model=list[TecnicoServicioAsignadoOut])
def mis_servicios_asignados_endpoint(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return listar_mis_servicios_asignados(db, current_user=current_user)


@router.post("/ubicacion", response_model=TecnicoUbicacionOut)
def reportar_ubicacion_endpoint(
    payload: TecnicoUbicacionIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return reportar_mi_ubicacion(
        db,
        current_user=current_user,
        asignacion_id=payload.asignacion_id,
        latitud=payload.latitud,
        longitud=payload.longitud,
    )


__all__ = ["router"]
