from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user

from .schemas import CambiarPasswordIn, CambiarPasswordOut
from .service import cambiar_password

router = APIRouter()


@router.patch("/cambiar-password", response_model=CambiarPasswordOut)
def cambiar_password_endpoint(
    payload: CambiarPasswordIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    cambiar_password(db, current_user, payload)
    return CambiarPasswordOut()

