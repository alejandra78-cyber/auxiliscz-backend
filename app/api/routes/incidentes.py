import json
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.ai_modules.audio import transcribir_audio
from app.ai_modules.clasificador import clasificar_incidente
from app.ai_modules.resumen import generar_resumen
from app.ai_modules.vision import analizar_imagen
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import Evidencia, HistorialEstado, Incidente, Usuario
from app.services.asignacion import motor_asignacion
from app.services.notificaciones import enviar_push

router = APIRouter()

COMISION_PLATAFORMA = 0.10
ESTADOS_VALIDOS = {"pendiente", "en_proceso", "atendido", "cancelado"}


class EstadoIncidenteIn(BaseModel):
    nuevo_estado: str = Field(..., pattern="^(pendiente|en_proceso|atendido|cancelado)$")
    costo: float | None = None


@router.post("/")
async def crear_incidente(
    background_tasks: BackgroundTasks,
    vehiculo_id: str = Form(...),
    lat: float = Form(...),
    lng: float = Form(...),
    descripcion: Optional[str] = Form(None),
    foto: Optional[UploadFile] = File(None),
    audio: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    incidente = Incidente(
        usuario_id=current_user.id,
        vehiculo_id=vehiculo_id,
        lat_incidente=lat,
        lng_incidente=lng,
        descripcion=descripcion,
        estado="pendiente",
        prioridad=2,
    )
    db.add(incidente)
    db.flush()

    evidencias_datos = []

    if audio:
        contenido_audio = await audio.read()
        transcripcion = await transcribir_audio(contenido_audio)
        db.add(Evidencia(incidente_id=incidente.id, tipo="audio", transcripcion=transcripcion))
        evidencias_datos.append({"tipo": "audio", "texto": transcripcion})

    if foto:
        contenido_foto = await foto.read()
        resultado_vision = await analizar_imagen(contenido_foto)
        db.add(
            Evidencia(
                incidente_id=incidente.id,
                tipo="imagen",
                transcripcion=json.dumps(resultado_vision),
            )
        )
        evidencias_datos.append({"tipo": "imagen", "datos": resultado_vision})

    if descripcion:
        db.add(Evidencia(incidente_id=incidente.id, tipo="texto", transcripcion=descripcion))
        evidencias_datos.append({"tipo": "texto", "texto": descripcion})

    db.commit()

    background_tasks.add_task(
        _procesar_ia_y_asignar,
        incidente_id=str(incidente.id),
        lat=lat,
        lng=lng,
        evidencias=evidencias_datos,
        usuario_id=str(current_user.id),
    )

    return {
        "incidente_id": str(incidente.id),
        "estado": "pendiente",
        "mensaje": "Buscando asistencia...",
    }


async def _procesar_ia_y_asignar(incidente_id, lat, lng, evidencias, usuario_id):
    from app.core.database import SessionLocal
    from app.models.models import AnalisisIA

    db = SessionLocal()
    try:
        clasificacion = await clasificar_incidente(evidencias)
        prioridad = clasificacion.get("prioridad", 2)
        tipo = clasificacion.get("tipo", "otro")
        resumen = await generar_resumen(clasificacion, evidencias)
        taller_asignado = await motor_asignacion(db, lat, lng, tipo, prioridad)

        incidente = db.query(Incidente).filter(Incidente.id == incidente_id).first()
        if not incidente:
            return

        incidente.tipo = tipo
        incidente.prioridad = prioridad
        incidente.estado = "en_proceso"
        if taller_asignado:
            incidente.taller_id = taller_asignado.id

        db.add(
            AnalisisIA(
                incidente_id=incidente.id,
                clasificacion=tipo,
                prioridad_sugerida=prioridad,
                resumen=resumen,
                confianza=clasificacion.get("confianza", 0.8),
            )
        )
        db.add(
            HistorialEstado(
                incidente_id=incidente.id,
                estado_anterior="pendiente",
                estado_nuevo="en_proceso",
            )
        )
        db.commit()

        if taller_asignado:
            await enviar_push(
                usuario_id,
                {
                    "titulo": "Taller asignado",
                    "cuerpo": f"{taller_asignado.nombre} está en camino",
                    "tipo": "asignacion",
                },
            )
    finally:
        db.close()


@router.get("/usuario/mis-incidentes")
def mis_incidentes(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    return (
        db.query(Incidente)
        .filter(Incidente.usuario_id == current_user.id)
        .order_by(Incidente.creado_en.desc())
        .all()
    )


@router.get("/talleres/disponibles")
def incidentes_para_taller(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    if current_user.rol not in {"taller", "admin"}:
        raise HTTPException(status_code=403, detail="Solo taller/admin puede consultar esta vista")
    return db.query(Incidente).filter(Incidente.estado == "pendiente").all()


@router.patch("/{incidente_id}/estado")
def actualizar_estado(
    incidente_id: str,
    payload: EstadoIncidenteIn,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    if current_user.rol not in {"taller", "admin"}:
        raise HTTPException(status_code=403, detail="Solo taller/admin puede actualizar estados")

    if payload.nuevo_estado not in ESTADOS_VALIDOS:
        raise HTTPException(status_code=400, detail="Estado no válido")

    incidente = db.query(Incidente).filter(Incidente.id == incidente_id).first()
    if not incidente:
        raise HTTPException(status_code=404, detail="No encontrado")

    estado_anterior = incidente.estado
    incidente.estado = payload.nuevo_estado

    if payload.costo and payload.nuevo_estado == "atendido":
        incidente.costo_total = payload.costo
        incidente.comision = round(payload.costo * COMISION_PLATAFORMA, 2)

    db.add(
        HistorialEstado(
            incidente_id=incidente.id,
            estado_anterior=estado_anterior,
            estado_nuevo=payload.nuevo_estado,
        )
    )
    db.commit()
    return {"ok": True, "estado": payload.nuevo_estado}


@router.get("/{incidente_id}")
def obtener_incidente(
    incidente_id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    incidente = db.query(Incidente).filter(Incidente.id == incidente_id).first()
    if not incidente:
        raise HTTPException(status_code=404, detail="Incidente no encontrado")

    if str(incidente.usuario_id) != str(current_user.id) and current_user.rol not in {"taller", "admin"}:
        raise HTTPException(status_code=403, detail="No autorizado")
    return incidente

