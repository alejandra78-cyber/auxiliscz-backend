from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user

from .schemas import (
    CancelarSolicitudIn,
    CancelarSolicitudOut,
    EstadoSolicitudOut,
    ImagenIncidenteOut,
    MensajeIn,
    MensajeOut,
    NotificacionOut,
    ReportarEmergenciaOut,
    UbicacionGpsIn,
    UbicacionGpsOut,
)
from .services import (
    cancelar_solicitud,
    cargar_imagen_incidente,
    consultar_estado_solicitud,
    enviar_mensaje_solicitud,
    enviar_ubicacion_gps,
    listar_mensajes_solicitud,
    listar_notificaciones_solicitud,
    reportar_emergencia,
    solicitud_es_cancelable,
)

router = APIRouter()


@router.post("/reportar", response_model=ReportarEmergenciaOut)
async def reportar_emergencia_endpoint(
    background_tasks: BackgroundTasks,
    vehiculo_id: str = Form(...),
    tipo: str | None = Form(None),
    lat: float = Form(...),
    lng: float = Form(...),
    descripcion: str | None = Form(None),
    foto: UploadFile | None = File(None),
    fotos: list[UploadFile] | None = File(None),
    audio: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    data = await reportar_emergencia(
        db,
        background_tasks=background_tasks,
        current_user=current_user,
        vehiculo_id=vehiculo_id,
        tipo=tipo,
        lat=lat,
        lng=lng,
        descripcion=descripcion,
        foto=foto,
        fotos=fotos,
        audio=audio,
    )
    return ReportarEmergenciaOut(
        incidente_id=data["incidente_id"],
        estado=data["estado"],
        tipo=data.get("tipo"),
        prioridad=data.get("prioridad"),
        resumen_ia=data.get("resumen_ia"),
        ia_estado=data.get("ia_estado"),
        asignacion_id=data.get("asignacion_id"),
        mensaje=data["mensaje"],
    )


@router.get("/solicitud/{incidente_id}", response_model=EstadoSolicitudOut)
def consultar_estado_solicitud_endpoint(
    incidente_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    solicitud = consultar_estado_solicitud(
        db,
        incidente_id=incidente_id,
        current_user=current_user,
    )
    ultimo = solicitud.asignaciones[-1] if solicitud.asignaciones else None
    resumen_ia = None
    if solicitud.incidente and solicitud.incidente.resumen_ia:
        resumen_ia = solicitud.incidente.resumen_ia
    if getattr(solicitud, "evidencias", None):
        for link in reversed(solicitud.evidencias):
            ev = getattr(link, "evidencia", None)
            if not ev or not ev.transcripcion:
                continue
            if ev.tipo == "resumen_ia":
                resumen_ia = ev.transcripcion
                break
            # Compatibilidad: resumen IA guardado como tipo texto + metadata_json.subtipo=resumen_ia
            try:
                import json
                meta = json.loads(ev.metadata_json or "{}")
                if meta.get("subtipo") == "resumen_ia":
                    resumen_ia = ev.transcripcion
                    break
            except Exception:
                pass
    return EstadoSolicitudOut(
        incidente_id=str(solicitud.id),
        estado=str(solicitud.estado),
        es_cancelable=solicitud_es_cancelable(solicitud),
        fecha_actualizacion=solicitud.actualizado_en.isoformat() if solicitud.actualizado_en else None,
        prioridad=solicitud.prioridad,
        tipo=str(solicitud.emergencia.tipo) if solicitud.emergencia and solicitud.emergencia.tipo else None,
        resumen_ia=resumen_ia,
        taller_id=str(ultimo.taller_id) if ultimo and ultimo.taller_id else None,
        taller_nombre=ultimo.taller.nombre if ultimo and ultimo.taller else None,
        tecnico_id=str(ultimo.tecnico_id) if ultimo and ultimo.tecnico_id else None,
        tecnico_nombre=ultimo.tecnico.nombre if ultimo and ultimo.tecnico else None,
    )


@router.patch("/solicitud/{incidente_id}/ubicacion", response_model=UbicacionGpsOut)
def enviar_ubicacion_gps_endpoint(
    incidente_id: str,
    payload: UbicacionGpsIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    solicitud = enviar_ubicacion_gps(
        db,
        incidente_id=incidente_id,
        lat=payload.lat,
        lng=payload.lng,
        current_user=current_user,
    )
    lat = payload.lat
    lng = payload.lng
    if solicitud.emergencia and solicitud.emergencia.ubicaciones:
        last = solicitud.emergencia.ubicaciones[-1]
        lat = last.latitud
        lng = last.longitud
    return UbicacionGpsOut(
        incidente_id=str(solicitud.id),
        lat=lat,
        lng=lng,
    )


@router.post("/solicitud/{incidente_id}/imagenes", response_model=ImagenIncidenteOut)
async def cargar_imagen_incidente_endpoint(
    incidente_id: str,
    imagen: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    evidencia = await cargar_imagen_incidente(
        db,
        incidente_id=incidente_id,
        imagen=imagen,
        current_user=current_user,
    )
    return ImagenIncidenteOut(incidente_id=incidente_id, evidencia_id=str(evidencia.id))


@router.patch("/solicitud/{incidente_id}/cancelar", response_model=CancelarSolicitudOut)
def cancelar_solicitud_endpoint(
    incidente_id: str,
    payload: CancelarSolicitudIn | None = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    solicitud = cancelar_solicitud(
        db,
        incidente_id=incidente_id,
        current_user=current_user,
        motivo_cancelacion=(payload.motivo_cancelacion if payload else None),
    )
    return CancelarSolicitudOut(incidente_id=str(solicitud.id), estado=str(solicitud.estado))


@router.get("/solicitud/{incidente_id}/mensajes", response_model=list[MensajeOut])
def listar_mensajes_endpoint(
    incidente_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return listar_mensajes_solicitud(db, incidente_id=incidente_id, current_user=current_user)


@router.post("/solicitud/{incidente_id}/mensajes", response_model=MensajeOut)
async def enviar_mensaje_endpoint(
    incidente_id: str,
    payload: MensajeIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await enviar_mensaje_solicitud(
        db,
        incidente_id=incidente_id,
        current_user=current_user,
        texto=payload.texto,
    )


@router.get("/notificaciones", response_model=list[NotificacionOut])
def listar_notificaciones_endpoint(
    incidente_id: str | None = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return listar_notificaciones_solicitud(
        db,
        current_user=current_user,
        incidente_id=incidente_id,
    )


__all__ = ["router"]
