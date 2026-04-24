from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import get_current_user

router = APIRouter()

@router.post("/evaluar")
def evaluar_servicio(
    solicitud_id: str,
    estrellas: int,
    comentario: str = "",
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return {
        "mensaje": "Evaluación registrada",
        "solicitud_id": solicitud_id,
        "estrellas": estrellas
    }