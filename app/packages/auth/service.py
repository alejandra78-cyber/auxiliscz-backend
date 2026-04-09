from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.security import get_password_hash, verify_password
from app.models.models import Usuario

from .repository import actualizar_password
from .schemas import CambiarPasswordIn


def cambiar_password(db: Session, usuario: Usuario, payload: CambiarPasswordIn) -> None:
    if not verify_password(payload.password_actual, usuario.password_hash):
        raise HTTPException(status_code=400, detail="La contraseña actual es incorrecta")

    if payload.password_nueva != payload.password_nueva_confirmacion:
        raise HTTPException(status_code=400, detail="La confirmación de contraseña no coincide")

    if payload.password_actual == payload.password_nueva:
        raise HTTPException(
            status_code=400,
            detail="La nueva contraseña debe ser diferente a la actual",
        )

    nuevo_hash = get_password_hash(payload.password_nueva)
    actualizar_password(db, usuario, nuevo_hash)

