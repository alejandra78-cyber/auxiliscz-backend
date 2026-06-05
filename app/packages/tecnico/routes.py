from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.time import local_now
from app.core.security import get_current_user
from app.api.routes.websocket import manager

from .schemas import TecnicoAccionEstadoIn, TecnicoServicioAsignadoOut, TecnicoUbicacionIn, TecnicoUbicacionOut
from .services import actualizar_estado_desde_tecnico, listar_mis_servicios_asignados, reportar_mi_ubicacion

router = APIRouter()


@router.get("/mis-servicios-asignados", response_model=list[TecnicoServicioAsignadoOut])
def mis_servicios_asignados_endpoint(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return listar_mis_servicios_asignados(db, current_user=current_user)


@router.post("/ubicacion", response_model=TecnicoUbicacionOut)
async def reportar_ubicacion_endpoint(
    payload: TecnicoUbicacionIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    resultado = reportar_mi_ubicacion(
        db,
        current_user=current_user,
        asignacion_id=payload.asignacion_id,
        latitud=payload.latitud,
        longitud=payload.longitud,
    )
    incidente_id = resultado.get("incidente_id")
    if incidente_id:
        await manager.broadcast_tracking(
            str(incidente_id),
            {
                "tipo": "ubicacion_tecnico",
                "incidente_id": str(incidente_id),
                "asignacion_id": payload.asignacion_id,
                "estado_servicio": resultado.get("estado_servicio"),
                "tecnico_nombre": resultado.get("tecnico_nombre"),
                "latitud_tecnico": payload.latitud,
                "longitud_tecnico": payload.longitud,
                "latitud_cliente": resultado.get("latitud_cliente"),
                "longitud_cliente": resultado.get("longitud_cliente"),
                "ultima_actualizacion": resultado.get("ultima_actualizacion") or local_now().isoformat(),
                "mensaje": "Ubicación del técnico actualizada en tiempo real",
            },
        )
    return resultado


@router.post("/seguimiento/accion", response_model=TecnicoUbicacionOut)
async def accion_seguimiento_endpoint(
    payload: TecnicoAccionEstadoIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    resultado = actualizar_estado_desde_tecnico(
        db,
        current_user=current_user,
        asignacion_id=payload.asignacion_id,
        accion=payload.accion,
    )
    incidente_id = resultado.get("incidente_id")
    if incidente_id:
        await manager.broadcast_tracking(
            str(incidente_id),
            {
                "tipo": "ubicacion_tecnico",
                "incidente_id": str(incidente_id),
                "asignacion_id": payload.asignacion_id,
                "estado_servicio": resultado.get("estado_servicio"),
                "estado": resultado.get("estado_servicio"),
                "tecnico_nombre": resultado.get("tecnico_nombre"),
                "latitud_tecnico": resultado.get("latitud_tecnico"),
                "longitud_tecnico": resultado.get("longitud_tecnico"),
                "latitud_cliente": resultado.get("latitud_cliente"),
                "longitud_cliente": resultado.get("longitud_cliente"),
                "ultima_actualizacion": resultado.get("ultima_actualizacion") or local_now().isoformat(),
                "mensaje": resultado.get("mensaje"),
            },
        )
    return resultado


__all__ = ["router"]
