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
    RecomendacionAudioIn,
    RecomendacionAudioOut,
    SolicitudClienteDetalleOut,
    SolicitudClienteListItemOut,
    SolicitudSeguimientoOut,
    UbicacionTecnicoOut,
    VehiculoCreateIn,
    VehiculoOut,
    VehiculoUpdateIn,
)
from .services import (
    _cotizacion_aceptada_cliente,
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
    recomendar_talleres_por_audio,
    registrar_vehiculo,
    ver_ubicacion_tecnico,
)


def _asignacion_confirmada_cliente(solicitud, db: Session | None = None):
    cotizacion_aceptada = _cotizacion_aceptada_cliente(solicitud, db)
    asig_cotizacion = None
    if cotizacion_aceptada and getattr(cotizacion_aceptada, "asignacion_id", None):
        asig_cotizacion = next(
            (
                a
                for a in (solicitud.asignaciones or [])
                if str(a.id) == str(cotizacion_aceptada.asignacion_id)
            ),
            None,
        )
    if cotizacion_aceptada and getattr(cotizacion_aceptada, "taller_id", None):
        asignaciones_taller_cotizado = [
            a
            for a in (solicitud.asignaciones or [])
            if str(a.taller_id or "") == str(cotizacion_aceptada.taller_id)
            and (
                getattr(a, "es_definitiva", False)
                or (getattr(a, "estado", "") or "").lower() not in {"descartada", "rechazada", "cancelada", "cancelado"}
            )
        ]
        if asignaciones_taller_cotizado:
            return sorted(
                asignaciones_taller_cotizado,
                key=lambda a: (
                    1 if getattr(a, "es_definitiva", False) else 0,
                    a.fecha_confirmacion.isoformat() if getattr(a, "fecha_confirmacion", None) else "",
                    a.fecha_asignacion.isoformat() if getattr(a, "fecha_asignacion", None) else "",
                    a.asignado_en.isoformat() if getattr(a, "asignado_en", None) else "",
                ),
            )[-1]
    if asig_cotizacion:
        return asig_cotizacion

    estados_confirmados = {
        "confirmada",
        "tecnico_asignado",
        "en_camino",
        "en_diagnostico",
        "diagnostico_completado",
        "cotizacion_aceptada",
        "en_proceso",
        "trabajo_completado",
        "esperando_pago",
        "pagado",
        "finalizado",
    }
    asignaciones = [
        a
        for a in (solicitud.asignaciones or [])
        if getattr(a, "es_definitiva", False) or (getattr(a, "estado", "") or "").lower() in estados_confirmados
    ]
    if not asignaciones:
        return None
    return sorted(
        asignaciones,
        key=lambda a: (
            1 if getattr(a, "es_definitiva", False) else 0,
            a.fecha_confirmacion.isoformat() if getattr(a, "fecha_confirmacion", None) else "",
            a.fecha_asignacion.isoformat() if getattr(a, "fecha_asignacion", None) else "",
            a.asignado_en.isoformat() if getattr(a, "asignado_en", None) else "",
        ),
    )[-1]

router = APIRouter()


def _taller_visible_cliente(solicitud, db: Session | None = None):
    cotizacion_aceptada = _cotizacion_aceptada_cliente(solicitud, db)
    if cotizacion_aceptada and getattr(cotizacion_aceptada, "taller", None):
        return cotizacion_aceptada.taller
    ultimo = _asignacion_confirmada_cliente(solicitud, db)
    return ultimo.taller if ultimo and getattr(ultimo, "taller", None) else None


def _tipo_prioridad_actual(solicitud):
    tipo = None
    prioridad = None
    if getattr(solicitud, "incidente", None):
        if solicitud.incidente.tipo:
            tipo = str(solicitud.incidente.tipo)
        if solicitud.incidente.prioridad is not None:
            prioridad = int(solicitud.incidente.prioridad)
    if not tipo and getattr(solicitud, "emergencia", None) and solicitud.emergencia.tipo:
        tipo = str(solicitud.emergencia.tipo)
    if prioridad is None:
        prioridad = int(solicitud.prioridad) if solicitud.prioridad is not None else None
    return tipo, prioridad


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
    ultimo = _asignacion_confirmada_cliente(solicitud, db)
    taller = _taller_visible_cliente(solicitud, db)
    tipo, prioridad = _tipo_prioridad_actual(solicitud)
    return EstadoSolicitudClienteOut(
        incidente_id=str(solicitud.id),
        codigo_solicitud=f"SOL-{str(solicitud.id).split('-')[0].upper()}",
        estado=str(solicitud.estado),
        prioridad=prioridad,
        tipo=tipo,
        taller_id=str(taller.id) if taller and getattr(taller, "id", None) else (str(ultimo.taller_id) if ultimo and ultimo.taller_id else None),
        taller_nombre=taller.nombre if taller and getattr(taller, "nombre", None) else (ultimo.taller.nombre if ultimo and ultimo.taller else None),
    )


@router.get("/solicitudes/{incidente_id}/estado", response_model=EstadoSolicitudClienteOut)
def estado_solicitud_cliente_endpoint(
    incidente_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    solicitud = consultar_estado_solicitud_cliente(db, incidente_id=incidente_id, current_user=current_user)
    ultimo = _asignacion_confirmada_cliente(solicitud, db)
    taller = _taller_visible_cliente(solicitud, db)
    tipo, prioridad = _tipo_prioridad_actual(solicitud)
    return EstadoSolicitudClienteOut(
        incidente_id=str(solicitud.id),
        codigo_solicitud=f"SOL-{str(solicitud.id).split('-')[0].upper()}",
        estado=str(solicitud.estado),
        prioridad=prioridad,
        tipo=tipo,
        taller_id=str(taller.id) if taller and getattr(taller, "id", None) else (str(ultimo.taller_id) if ultimo and ultimo.taller_id else None),
        taller_nombre=taller.nombre if taller and getattr(taller, "nombre", None) else (ultimo.taller.nombre if ultimo and ultimo.taller else None),
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
            tipo=_tipo_prioridad_actual(s)[0],
            prioridad=_tipo_prioridad_actual(s)[1],
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


@router.post("/cotizaciones/recomendacion-audio", response_model=RecomendacionAudioOut)
def recomendacion_cotizaciones_audio_endpoint(
    payload: RecomendacionAudioIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return recomendar_talleres_por_audio(
        db,
        current_user=current_user,
        solicitud_id=payload.solicitud_id,
        consulta=payload.consulta,
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
