from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user

from .schemas import EstadoSolicitudOut, ReportarEmergenciaOut
from .service import consultar_estado_solicitud, reportar_emergencia

router = APIRouter()


@router.post("/reportar", response_model=ReportarEmergenciaOut)
async def reportar_emergencia_endpoint(
    background_tasks: BackgroundTasks,
    vehiculo_id: str = Form(...),
    lat: float = Form(...),
    lng: float = Form(...),
    descripcion: str | None = Form(None),
    foto: UploadFile | None = File(None),
    audio: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    incidente_id = await reportar_emergencia(
        db,
        background_tasks=background_tasks,
        current_user=current_user,
        vehiculo_id=vehiculo_id,
        lat=lat,
        lng=lng,
        descripcion=descripcion,
        foto=foto,
        audio=audio,
    )
    return ReportarEmergenciaOut(
        incidente_id=incidente_id,
        estado="pendiente",
        mensaje="Emergencia registrada correctamente",
    )


@router.get("/solicitud/{incidente_id}", response_model=EstadoSolicitudOut)
def consultar_estado_solicitud_endpoint(
    incidente_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    incidente = consultar_estado_solicitud(
        db,
        incidente_id=incidente_id,
        current_user=current_user,
    )
    return EstadoSolicitudOut(
        incidente_id=str(incidente.id),
        estado=str(incidente.estado),
        prioridad=incidente.prioridad,
        tipo=str(incidente.tipo) if incidente.tipo else None,
        taller_id=str(incidente.taller_id) if incidente.taller_id else None,
    )

