from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user

from .schemas import DisponibilidadIn, TallerCreateIn, TallerOut
from .services import gestionar_disponibilidad, obtener_mi_taller, registrar_taller

router = APIRouter()


@router.post("/", response_model=TallerOut)
def registrar_taller_endpoint(
    payload: TallerCreateIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return registrar_taller(
        db,
        current_user=current_user,
        usuario_id=payload.usuario_id,
        nombre=payload.nombre,
        direccion=payload.direccion,
        latitud=payload.latitud,
        longitud=payload.longitud,
        servicios=payload.servicios,
        disponible=payload.disponible,
    )


@router.get("/mi-taller", response_model=TallerOut)
def mi_taller_endpoint(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return obtener_mi_taller(db, current_user=current_user)


@router.patch("/mi-taller/disponibilidad", response_model=TallerOut)
def disponibilidad_endpoint(
    payload: DisponibilidadIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return gestionar_disponibilidad(db, current_user=current_user, disponible=payload.disponible)
