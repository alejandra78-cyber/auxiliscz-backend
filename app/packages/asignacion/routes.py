from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user

from .schemas import (
    ActualizarEstadoIn,
    AsignacionCandidatoOut,
    AsignacionOut,
    AsignarServicioIn,
    BuscarCandidatosIn,
    EvidenciaOut,
    EvaluarSolicitudIn,
    RechazarSolicitudIn,
    ServicioCatalogoOut,
    SolicitudServicioDetalleOut,
    SolicitudServicioOut,
    SugerenciaAsignacionOut,
    TecnicoDisponibleOut,
)
from .services import (
    actualizar_estado_servicio,
    asignar_taller_automaticamente,
    asignar_servicio,
    buscar_talleres_candidatos_cercanos,
    codigo_solicitud,
    evaluar_solicitud_servicio,
    estado_paquete_asignacion,
    listar_servicios_catalogo,
    listar_solicitudes_servicio,
    listar_candidatos_para_solicitud,
    listar_tecnicos_disponibles,
    obtener_detalle_solicitud_servicio,
    reasignar_taller,
    sugerir_asignacion_inteligente,
)

router = APIRouter()


def _to_solicitud_out(i) -> SolicitudServicioOut:
    ultimo = (
        sorted(
            i.asignaciones,
            key=lambda x: (x.fecha_asignacion or x.asignado_en or x.id),
        )[-1]
        if i.asignaciones
        else None
    )
    resumen_ia = None
    if getattr(i, "evidencias", None):
        for link in reversed(i.evidencias):
            ev = getattr(link, "evidencia", None)
            if ev and ev.tipo == "resumen_ia" and ev.transcripcion:
                resumen_ia = ev.transcripcion
                break
    latitud = None
    longitud = None
    if i.emergencia and i.emergencia.ubicaciones:
        last = sorted(i.emergencia.ubicaciones, key=lambda u: u.registrado_en or u.id)[-1]
        latitud = float(last.latitud) if last.latitud is not None else None
        longitud = float(last.longitud) if last.longitud is not None else None
    return SolicitudServicioOut(
        id=str(i.id),
        codigo_solicitud=codigo_solicitud(i),
        estado=str(i.estado),
        tipo=str(i.emergencia.tipo) if i.emergencia else None,
        tipo_sugerido_ia=str(i.emergencia.tipo) if i.emergencia else None,
        descripcion=str(i.emergencia.descripcion) if i.emergencia and i.emergencia.descripcion else None,
        prioridad=i.prioridad,
        prioridad_sugerida_ia=i.prioridad,
        resumen_ia=resumen_ia,
        cliente_nombre=i.cliente.usuario.nombre if i.cliente and i.cliente.usuario else None,
        vehiculo_id=str(i.vehiculo_id) if i.vehiculo_id else None,
        usuario_id=str(i.cliente.usuario_id) if i.cliente else "",
        taller_id=str(ultimo.taller_id) if ultimo and ultimo.taller_id else None,
        taller_nombre=ultimo.taller.nombre if ultimo and ultimo.taller else None,
        estado_asignacion=(str(ultimo.estado) if ultimo and ultimo.estado else None),
        tecnico_id=str(ultimo.tecnico_id) if ultimo and ultimo.tecnico_id else None,
        tecnico_nombre=ultimo.tecnico.nombre if ultimo and ultimo.tecnico else None,
        servicio=ultimo.servicio if ultimo and ultimo.servicio else None,
        incidente_id=str(i.incidente_id) if i.incidente_id else None,
        latitud=latitud,
        longitud=longitud,
        distancia_km=(float(ultimo.distancia_km) if ultimo and ultimo.distancia_km is not None else None),
        puntaje_asignacion=(float(ultimo.puntaje) if ultimo and ultimo.puntaje is not None else None),
        motivo_asignacion=(str(ultimo.motivo_asignacion) if ultimo and ultimo.motivo_asignacion else None),
        origen_asignacion=(str(ultimo.origen_asignacion) if ultimo and ultimo.origen_asignacion else None),
        motivo_rechazo=(str(ultimo.motivo_rechazo) if ultimo and ultimo.motivo_rechazo else None),
        fecha_asignacion=((ultimo.fecha_asignacion or ultimo.asignado_en).isoformat() if ultimo and (ultimo.fecha_asignacion or ultimo.asignado_en) else None),
        fecha_respuesta_taller=(ultimo.fecha_respuesta_taller.isoformat() if ultimo and ultimo.fecha_respuesta_taller else None),
        creado_en=i.creado_en.isoformat() if i.creado_en else None,
    )


def _to_solicitud_detalle_out(i) -> SolicitudServicioDetalleOut:
    base = _to_solicitud_out(i)
    evidencias: list[EvidenciaOut] = []
    for link in (i.evidencias or []):
        ev = getattr(link, "evidencia", None)
        if not ev:
            continue
        evidencias.append(
            EvidenciaOut(
                id=str(ev.id),
                tipo=str(ev.tipo),
                url_archivo=ev.url_archivo,
                transcripcion=ev.transcripcion,
                subido_en=ev.subido_en.isoformat() if ev.subido_en else None,
            )
        )
    return SolicitudServicioDetalleOut(**base.model_dump(), evidencias=evidencias)


@router.get("/estado")
def estado():
    return estado_paquete_asignacion()


@router.post("/candidatos")
async def buscar_candidatos(payload: BuscarCandidatosIn, db: Session = Depends(get_db)):
    if payload.lat is None or payload.lng is None:
        return []
    return await buscar_talleres_candidatos_cercanos(
        db,
        lat=payload.lat,
        lng=payload.lng,
        tipo=payload.tipo or "otro",
        prioridad=payload.prioridad or 2,
    )


@router.get("/candidatos/{incidente_id}", response_model=list[AsignacionCandidatoOut])
def listar_candidatos_incidente(
    incidente_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return listar_candidatos_para_solicitud(db, incidente_id=incidente_id, current_user=current_user)


@router.post("/asignar/{incidente_id}", response_model=AsignacionOut)
async def asignar_automatico(
    incidente_id: str,
    payload: BuscarCandidatosIn | None = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.rol not in {"admin", "taller"}:
        raise HTTPException(status_code=403, detail="No autorizado para ejecutar asignación inteligente")
    taller = await asignar_taller_automaticamente(
        db,
        solicitud_id=incidente_id,
        lat=(payload.lat if payload else None),
        lng=(payload.lng if payload else None),
        tipo=(payload.tipo if payload else None),
        prioridad=(payload.prioridad if payload else None),
    )
    if not taller:
        return AsignacionOut(mensaje="No se encontraron talleres disponibles")
    return AsignacionOut(
        taller_id=str(taller.id),
        nombre_taller=taller.nombre,
        mensaje="Taller asignado automaticamente",
    )


@router.post("/reasignar/{incidente_id}", response_model=AsignacionOut)
async def reasignar(
    incidente_id: str,
    payload: BuscarCandidatosIn | None = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.rol not in {"admin", "taller"}:
        raise HTTPException(status_code=403, detail="No autorizado para ejecutar reasignación inteligente")
    candidato = await reasignar_taller(
        db,
        solicitud_id=incidente_id,
        lat=(payload.lat if payload else None),
        lng=(payload.lng if payload else None),
        tipo=(payload.tipo if payload else None),
        prioridad=(payload.prioridad if payload else None),
    )
    if not candidato:
        return AsignacionOut(mensaje="No hay un candidato alternativo para reasignar")
    return AsignacionOut(
        taller_id=str(candidato.get("taller_id")),
        nombre_taller=candidato.get("nombre"),
        mensaje="Taller reasignado correctamente",
    )


@router.get("/solicitudes", response_model=list[SolicitudServicioOut])
def solicitudes(
    estado: str | None = None,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    taller_id: str | None = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    rows = listar_solicitudes_servicio(
        db,
        current_user=current_user,
        estado=estado,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        taller_id=taller_id,
    )
    return [_to_solicitud_out(i) for i in rows]


@router.get("/solicitudes/{incidente_id}", response_model=SolicitudServicioDetalleOut)
def detalle_solicitud(
    incidente_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    row = obtener_detalle_solicitud_servicio(db, incidente_id=incidente_id, current_user=current_user)
    return _to_solicitud_detalle_out(row)


@router.get("/servicios/catalogo", response_model=list[ServicioCatalogoOut])
def catalogo_servicios():
    return listar_servicios_catalogo()


@router.get("/tecnicos/disponibles", response_model=list[TecnicoDisponibleOut])
def tecnicos_disponibles(
    solicitud_id: str | None = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    rows = listar_tecnicos_disponibles(db, current_user=current_user, solicitud_id=solicitud_id)
    return [
        TecnicoDisponibleOut(
            id=str(t.id),
            nombre=t.nombre,
            especialidad=None,
            disponible=bool(t.disponible),
        )
        for t in rows
    ]


@router.get("/solicitudes/{incidente_id}/sugerencia-ia", response_model=SugerenciaAsignacionOut)
def sugerencia_asignacion_ia(
    incidente_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return sugerir_asignacion_inteligente(db, incidente_id=incidente_id, current_user=current_user)


@router.post("/solicitudes/{incidente_id}/evaluar", response_model=SolicitudServicioOut)
def evaluar(
    incidente_id: str,
    payload: EvaluarSolicitudIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    i = evaluar_solicitud_servicio(
        db,
        incidente_id=incidente_id,
        current_user=current_user,
        aprobar=payload.aprobar,
        observacion=payload.observacion,
    )
    return _to_solicitud_out(i)


@router.post("/solicitudes/{incidente_id}/aceptar", response_model=SolicitudServicioOut)
def aceptar_solicitud(
    incidente_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    i = evaluar_solicitud_servicio(
        db,
        incidente_id=incidente_id,
        current_user=current_user,
        aprobar=True,
        observacion=None,
    )
    return _to_solicitud_out(i)


@router.post("/solicitudes/{incidente_id}/rechazar", response_model=SolicitudServicioOut)
def rechazar_solicitud(
    incidente_id: str,
    payload: RechazarSolicitudIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    i = evaluar_solicitud_servicio(
        db,
        incidente_id=incidente_id,
        current_user=current_user,
        aprobar=False,
        observacion=payload.motivo_rechazo,
    )
    return _to_solicitud_out(i)


@router.post("/solicitudes/{incidente_id}/asignar", response_model=SolicitudServicioOut)
def asignar_servicio_endpoint(
    incidente_id: str,
    payload: AsignarServicioIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    i = asignar_servicio(
        db,
        incidente_id=incidente_id,
        current_user=current_user,
        tecnico_id=payload.tecnico_id,
        servicio=payload.servicio,
        taller_id=payload.taller_id,
        observacion=payload.observacion,
    )
    return _to_solicitud_out(i)


@router.patch("/solicitudes/{incidente_id}/estado", response_model=SolicitudServicioOut)
def actualizar_estado_endpoint(
    incidente_id: str,
    payload: ActualizarEstadoIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    i = actualizar_estado_servicio(
        db,
        incidente_id=incidente_id,
        current_user=current_user,
        estado=payload.estado,
        observacion=payload.observacion,
        costo=payload.costo,
        tecnico_id=payload.tecnico_id,
    )
    return _to_solicitud_out(i)
