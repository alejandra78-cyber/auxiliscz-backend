from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user

from .schemas import VehiculoCreateIn, VehiculoOut
from .services import mis_vehiculos, registrar_vehiculo

router = APIRouter()


@router.post("/vehiculos", response_model=VehiculoOut)
def registrar_vehiculo_endpoint(
    payload: VehiculoCreateIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return registrar_vehiculo(
        db,
        current_user=current_user,
        placa=payload.placa,
        marca=payload.marca,
        modelo=payload.modelo,
        anio=payload.anio,
        color=payload.color,
    )


@router.get("/vehiculos", response_model=list[VehiculoOut])
def mis_vehiculos_endpoint(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return mis_vehiculos(db, current_user=current_user)


__all__ = ["router"]
