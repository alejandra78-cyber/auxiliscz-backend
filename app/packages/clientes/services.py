from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.models import Usuario

from .repository import crear_vehiculo, get_vehiculo_by_placa, listar_vehiculos_de_usuario


def registrar_vehiculo(
    db: Session,
    *,
    current_user: Usuario,
    placa: str,
    marca: str | None,
    modelo: str | None,
    anio: int | None,
    color: str | None,
):
    if current_user.rol not in {"conductor", "admin"}:
        raise HTTPException(status_code=403, detail="Solo cliente/admin puede registrar vehículos")

    if get_vehiculo_by_placa(db, placa):
        raise HTTPException(status_code=400, detail="La placa ya está registrada")

    return crear_vehiculo(
        db,
        usuario=current_user,
        placa=placa,
        marca=marca,
        modelo=modelo,
        anio=anio,
        color=color,
    )


def mis_vehiculos(db: Session, *, current_user: Usuario):
    return listar_vehiculos_de_usuario(db, usuario=current_user)
