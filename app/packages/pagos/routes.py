from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class PagoRequest(BaseModel):
    solicitud_id: str
    metodo: str


@router.post("/procesar")
def procesar_pago(payload: PagoRequest):
    return {
        "pago_id": "PAGO-DEMO-001",
        "solicitud_id": payload.solicitud_id,
        "estado": "completado",
        "metodo": payload.metodo,
        "monto": 100,
        "mensaje": "Pago procesado correctamente",
    }