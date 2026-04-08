import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional, List
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import Incidente, Evidencia, HistorialEstado, Taller
from app.services.asignacion import motor_asignacion
from app.services.notificaciones import enviar_push
from app.ai_modules.clasificador import clasificar_incidente
from app.ai_modules.audio import transcribir_audio
from app.ai_modules.vision import analizar_imagen
from app.ai_modules.resumen import generar_resumen
import json, math

router = APIRouter()

COMISION_PLATAFORMA = 0.10  # 10%


def calcular_distancia_km(lat1, lng1, lat2, lng2) -> float:
    """Haversine para distancia entre dos coordenadas GPS."""
    R = 6371
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = math.sin(d_lat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lng/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


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
    current_user=Depends(get_current_user)
):
    incidente = Incidente(
        usuario_id=current_user.id,
        vehiculo_id=vehiculo_id,
        lat_incidente=lat,
        lng_incidente=lng,
        descripcion=descripcion,
        estado="pendiente",
        prioridad=2
    )
    db.add(incidente)
    db.flush()  # obtener ID antes de commit

    evidencias_datos = []

    # Procesar audio
    if audio:
        contenido_audio = await audio.read()
        transcripcion = await transcribir_audio(contenido_audio)
        ev_audio = Evidencia(
            incidente_id=incidente.id,
            tipo="audio",
            transcripcion=transcripcion
        )
        db.add(ev_audio)
        evidencias_datos.append({"tipo": "audio", "texto": transcripcion})

    # Procesar imagen
    if foto:
        contenido_foto = await foto.read()
        resultado_vision = await analizar_imagen(contenido_foto)
        ev_foto = Evidencia(
            incidente_id=incidente.id,
            tipo="imagen",
            transcripcion=json.dumps(resultado_vision)
        )
        db.add(ev_foto)
        evidencias_datos.append({"tipo": "imagen", "datos": resultado_vision})

    # Texto libre
    if descripcion:
        ev_texto = Evidencia(
            incidente_id=incidente.id,
            tipo="texto",
            transcripcion=descripcion
        )
        db.add(ev_texto)
        evidencias_datos.append({"tipo": "texto", "texto": descripcion})

    db.commit()

    # Clasificación IA en background
    background_tasks.add_task(
        _procesar_ia_y_asignar,
        incidente_id=str(incidente.id),
        lat=lat, lng=lng,
        evidencias=evidencias_datos,
        usuario_id=str(current_user.id)
    )

    return {"incidente_id": str(incidente.id), "estado": "pendiente", "mensaje": "Buscando asistencia..."}


async def _procesar_ia_y_asignar(incidente_id, lat, lng, evidencias, usuario_id):
    """Tarea en background: IA → asignación → notificación."""
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        # 1. Clasificación multimodal
        clasificacion = await clasificar_incidente(evidencias)
        prioridad = clasificacion.get("prioridad", 2)
        tipo = clasificacion.get("tipo", "otro")

        # 2. Resumen estructurado
        resumen = await generar_resumen(clasificacion, evidencias)

        # 3. Motor de asignación
        taller_asignado = await motor_asignacion(db, lat, lng, tipo, prioridad)

        # 4. Actualizar incidente
        incidente = db.query(Incidente).filter(Incidente.id == incidente_id).first()
        if incidente:
            incidente.tipo = tipo
            incidente.prioridad = prioridad
            incidente.estado = "en_proceso"
            if taller_asignado:
                incidente.taller_id = taller_asignado.id

            from app.models.models import AnalisisIA
            analisis = AnalisisIA(
                incidente_id=incidente.id,
                clasificacion=tipo,
                prioridad_sugerida=prioridad,
                resumen=resumen,
                confianza=clasificacion.get("confianza", 0.8)
            )
            db.add(analisis)

            historial = HistorialEstado(
                incidente_id=incidente.id,
                estado_anterior="pendiente",
                estado_nuevo="en_proceso"
            )
            db.add(historial)
            db.commit()

            # 5. Notificaciones push
            await enviar_push(usuario_id, {
                "titulo": "Taller asignado",
                "cuerpo": f"{taller_asignado.nombre} está en camino",
                "tipo": "asignacion"
            })
    finally:
        db.close()


@router.get("/{incidente_id}")
def obtener_incidente(incidente_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    incidente = db.query(Incidente).filter(Incidente.id == incidente_id).first()
    if not incidente:
        raise HTTPException(status_code=404, detail="Incidente no encontrado")
    return incidente


@router.get("/usuario/mis-incidentes")
def mis_incidentes(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return db.query(Incidente).filter(Incidente.usuario_id == current_user.id).all()


@router.patch("/{incidente_id}/estado")
def actualizar_estado(
    incidente_id: str,
    nuevo_estado: str,
    costo: Optional[float] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    incidente = db.query(Incidente).filter(Incidente.id == incidente_id).first()
    if not incidente:
        raise HTTPException(status_code=404, detail="No encontrado")

    estado_anterior = incidente.estado
    incidente.estado = nuevo_estado

    if costo and nuevo_estado == "atendido":
        incidente.costo_total = costo
        incidente.comision = round(costo * COMISION_PLATAFORMA, 2)

    historial = HistorialEstado(
        incidente_id=incidente.id,
        estado_anterior=estado_anterior,
        estado_nuevo=nuevo_estado
    )
    db.add(historial)
    db.commit()
    return {"ok": True, "estado": nuevo_estado}


@router.get("/talleres/disponibles")
def incidentes_para_taller(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Solicitudes pendientes visibles para un taller."""
    return db.query(Incidente).filter(Incidente.estado == "pendiente").all()
