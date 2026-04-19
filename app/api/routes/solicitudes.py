from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

solicitudes_db = [
    {"id": 1, "estado": "pendiente", "servicio": "Cambio de aceite", "evaluacion": None},
    {"id": 2, "estado": "en_proceso", "servicio": "Revisión de frenos", "evaluacion": None},
]


class EvaluacionSolicitud(BaseModel):
    puntuacion: int
    comentario: str | None = None


@router.patch("/{solicitud_id}/cancelar")
def cancelar_solicitud(solicitud_id: int):
    for solicitud in solicitudes_db:
        if solicitud["id"] == solicitud_id:
            if solicitud["estado"] == "cancelada":
                raise HTTPException(status_code=400, detail="La solicitud ya está cancelada")
            solicitud["estado"] = "cancelada"
            return {
                "mensaje": "Solicitud cancelada correctamente",
                "solicitud": solicitud
            }
    raise HTTPException(status_code=404, detail="Solicitud no encontrada")


@router.get("/{solicitud_id}/estado")
def consultar_estado_solicitud(solicitud_id: int):
    for solicitud in solicitudes_db:
        if solicitud["id"] == solicitud_id:
            return {
                "id": solicitud["id"],
                "estado": solicitud["estado"]
            }
    raise HTTPException(status_code=404, detail="Solicitud no encontrada")


@router.get("/")
def consultar_solicitudes_servicio():
    return solicitudes_db


@router.post("/{solicitud_id}/evaluar")
def evaluar_solicitud(solicitud_id: int, evaluacion: EvaluacionSolicitud):
    for solicitud in solicitudes_db:
        if solicitud["id"] == solicitud_id:
            solicitud["evaluacion"] = {
                "puntuacion": evaluacion.puntuacion,
                "comentario": evaluacion.comentario
            }
            return {
                "mensaje": "Solicitud evaluada correctamente",
                "evaluacion": solicitud["evaluacion"]
            }
    raise HTTPException(status_code=404, detail="Solicitud no encontrada")