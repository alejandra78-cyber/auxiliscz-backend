from fastapi import APIRouter

from .services import estado_paquete_pagos

router = APIRouter()


@router.get("/estado")
def estado():
    return estado_paquete_pagos()
