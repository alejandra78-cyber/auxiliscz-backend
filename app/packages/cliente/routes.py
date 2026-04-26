from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user

from .schemas import (
    CancelarSolicitudClienteIn,
    EvaluarServicioIn,
    EvaluarServicioOut,
    EstadoSolicitudClienteOut,
    HistorialServicioItemOut,
    SolicitudClienteDetalleOut,
    SolicitudClienteListItemOut,
    SolicitudSeguimientoOut,
    UbicacionTecnicoOut,
    VehiculoCreateIn,
    VehiculoOut,
    VehiculoUpdateIn,
)
from .services import (
    cancelar_solicitud_cliente,
    consultar_estado_solicitud_cliente,
    consultar_estado_ultima_solicitud_cliente,
    desactivar_vehiculo_cliente,
    evaluar_servicio_cliente,
    editar_vehiculo_cliente,
    historial_servicios_cliente,
    listar_solicitudes_para_seguimiento,
    listar_solicitudes_cliente,
    mis_vehiculos,
    obtener_detalle_solicitud_cliente,
    registrar_vehiculo,
    ver_ubicacion_tecnico,
)

router = APIRouter()


@router.post("/vehiculos", response_model=VehiculoOut)
def registrar_vehiculo_endpoint(
    payload: VehiculoCreateIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return registrar_vehiculo(
        db,
        current_user=current_user,
        placa=payload.placa,
        marca=payload.marca,
        modelo=payload.modelo,
        anio=payload.anio,
        color=payload.color,
        tipo=payload.tipo,
        observacion=payload.observacion,
    )


@router.get("/vehiculos", response_model=list[VehiculoOut])
def mis_vehiculos_endpoint(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return mis_vehiculos(db, current_user=current_user)


@router.put("/vehiculos/{vehiculo_id}", response_model=VehiculoOut)
def editar_vehiculo_endpoint(
    vehiculo_id: str,
    payload: VehiculoUpdateIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return editar_vehiculo_cliente(
        db,
        current_user=current_user,
        vehiculo_id=vehiculo_id,
        marca=payload.marca,
        modelo=payload.modelo,
        anio=payload.anio,
        color=payload.color,
        tipo=payload.tipo,
        observacion=payload.observacion,
    )


@router.patch("/vehiculos/{vehiculo_id}/desactivar", response_model=VehiculoOut)
def desactivar_vehiculo_endpoint(
    vehiculo_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return desactivar_vehiculo_cliente(db, current_user=current_user, vehiculo_id=vehiculo_id)


@router.get("/solicitudes/ultima/estado", response_model=EstadoSolicitudClienteOut)
def estado_ultima_solicitud_cliente_endpoint(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    solicitud = consultar_estado_ultima_solicitud_cliente(db, current_user=current_user)
    ultimo = solicitud.asignaciones[-1] if solicitud.asignaciones else None
    return EstadoSolicitudClienteOut(
        incidente_id=str(solicitud.id),
        codigo_solicitud=f"SOL-{str(solicitud.id).split('-')[0].upper()}",
        estado=str(solicitud.estado),
        prioridad=solicitud.prioridad,
        tipo=str(solicitud.emergencia.tipo) if solicitud.emergencia else None,
        taller_id=str(ultimo.taller_id) if ultimo and ultimo.taller_id else None,
        taller_nombre=ultimo.taller.nombre if ultimo and ultimo.taller else None,
    )


@router.get("/solicitudes/{incidente_id}/estado", response_model=EstadoSolicitudClienteOut)
def estado_solicitud_cliente_endpoint(
    incidente_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    solicitud = consultar_estado_solicitud_cliente(db, incidente_id=incidente_id, current_user=current_user)
    ultimo = solicitud.asignaciones[-1] if solicitud.asignaciones else None
    return EstadoSolicitudClienteOut(
        incidente_id=str(solicitud.id),
        codigo_solicitud=f"SOL-{str(solicitud.id).split('-')[0].upper()}",
        estado=str(solicitud.estado),
        prioridad=solicitud.prioridad,
        tipo=str(solicitud.emergencia.tipo) if solicitud.emergencia else None,
        taller_id=str(ultimo.taller_id) if ultimo and ultimo.taller_id else None,
        taller_nombre=ultimo.taller.nombre if ultimo and ultimo.taller else None,
    )


@router.get("/solicitudes/{incidente_id}/ubicacion-tecnico", response_model=UbicacionTecnicoOut)
def ubicacion_tecnico_endpoint(
    incidente_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return ver_ubicacion_tecnico(db, incidente_id=incidente_id, current_user=current_user)


@router.get("/solicitudes/{incidente_id}/tecnico-ubicacion", response_model=UbicacionTecnicoOut)
def ubicacion_tecnico_legacy_endpoint(
    incidente_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return ver_ubicacion_tecnico(db, incidente_id=incidente_id, current_user=current_user)


@router.get("/solicitudes/seguimiento", response_model=list[SolicitudSeguimientoOut])
def solicitudes_seguimiento_endpoint(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    rows = listar_solicitudes_para_seguimiento(db, current_user=current_user)
    return [
        SolicitudSeguimientoOut(
            incidente_id=str(s.id),
            codigo_solicitud=f"SOL-{str(s.id).split('-')[0].upper()}",
            estado=str(s.estado),
            tipo=str(s.emergencia.tipo) if s.emergencia else None,
            prioridad=s.prioridad,
        )
        for s in rows
    ]


@router.get("/solicitudes", response_model=list[SolicitudClienteListItemOut])
def listar_solicitudes_cliente_endpoint(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return listar_solicitudes_cliente(db, current_user=current_user)


@router.get("/solicitudes/{incidente_id}", response_model=SolicitudClienteDetalleOut)
def detalle_solicitud_cliente_endpoint(
    incidente_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return obtener_detalle_solicitud_cliente(
        db,
        incidente_id=incidente_id,
        current_user=current_user,
    )


@router.patch("/solicitudes/{incidente_id}/cancelar")
def cancelar_solicitud_cliente_endpoint(
    incidente_id: str,
    payload: CancelarSolicitudClienteIn | None = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return cancelar_solicitud_cliente(
        db,
        incidente_id=incidente_id,
        current_user=current_user,
        motivo_cancelacion=payload.motivo_cancelacion if payload else None,
    )


@router.post("/solicitudes/{incidente_id}/evaluar", response_model=EvaluarServicioOut)
def evaluar_servicio_cliente_endpoint(
    incidente_id: str,
    payload: EvaluarServicioIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return evaluar_servicio_cliente(
        db,
        incidente_id=incidente_id,
        current_user=current_user,
        calificacion=payload.calificacion,
        comentario=payload.comentario,
    )


@router.get("/historial-servicios", response_model=list[HistorialServicioItemOut])
def historial_servicios_cliente_endpoint(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return historial_servicios_cliente(db, current_user=current_user)


__all__ = ["router"]
