from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.models import Usuario

from .repository import (
    actualizar_disponibilidad,
    crear_taller,
    get_taller_by_usuario_id,
    parsear_servicios,
)


def registrar_taller(
    db: Session,
    *,
    current_user: Usuario,
    usuario_id: str,
    nombre: str,
    direccion: str | None,
    latitud: float | None,
    longitud: float | None,
    servicios: list[str],
    disponible: bool,
):
    if current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede registrar talleres")
    if get_taller_by_usuario_id(db, usuario_id):
        raise HTTPException(status_code=400, detail="El usuario ya tiene un taller registrado")
    taller = crear_taller(
        db,
        usuario_id=usuario_id,
        nombre=nombre,
        direccion=direccion,
        latitud=latitud,
        longitud=longitud,
        servicios=servicios,
        disponible=disponible,
    )
    return parsear_servicios(taller)


def obtener_mi_taller(db: Session, *, current_user: Usuario):
    if current_user.rol not in {"taller", "admin"}:
        raise HTTPException(status_code=403, detail="Solo taller/admin puede consultar taller")
    taller = get_taller_by_usuario_id(db, str(current_user.id))
    if not taller:
        raise HTTPException(status_code=404, detail="No existe taller asociado a este usuario")
    return parsear_servicios(taller)


def gestionar_disponibilidad(db: Session, *, current_user: Usuario, disponible: bool):
    if current_user.rol != "taller":
        raise HTTPException(status_code=403, detail="Solo taller puede gestionar disponibilidad")
    taller = get_taller_by_usuario_id(db, str(current_user.id))
    if not taller:
        raise HTTPException(status_code=404, detail="No existe taller asociado a este usuario")
    return parsear_servicios(actualizar_disponibilidad(db, taller, disponible))
