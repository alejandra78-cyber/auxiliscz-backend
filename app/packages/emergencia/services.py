import json

from fastapi import BackgroundTasks, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.ai_modules.audio import transcribir_audio
from app.ai_modules.resumen import generar_resumen
from app.ai_modules.vision import analizar_imagen
from app.models.models import AnalisisIA, Usuario
from app.packages.asignacion.services import asignar_taller_automaticamente
from app.services.notificaciones import enviar_push

from .repository import (
    agregar_evidencia,
    actualizar_ubicacion_incidente,
    crear_incidente,
    obtener_incidente_por_id,
    registrar_historial,
)

PRIORIDAD_POR_TIPO = {
    "choque": 1,
    "motor": 1,
    "bateria": 2,
    "llanta": 2,
    "llave": 2,
    "otro": 3,
    "incierto": 2,
}


async def transcribir_audio_a_texto(audio_bytes: bytes, idioma: str = "es") -> str:
    return await transcribir_audio(audio_bytes, idioma)


async def clasificar_incidente_por_imagenes(imagen_bytes: bytes) -> dict:
    return await analizar_imagen(imagen_bytes)


def asignar_nivel_prioridad(tipo_incidente: str) -> int:
    return PRIORIDAD_POR_TIPO.get(tipo_incidente, 2)


async def generar_ficha_resumen_incidente(clasificacion: dict, evidencias: list[dict]) -> str:
    return await generar_resumen(clasificacion, evidencias)


async def reportar_emergencia(
    db: Session,
    *,
    background_tasks: BackgroundTasks,
    current_user: Usuario,
    vehiculo_id: str,
    lat: float,
    lng: float,
    descripcion: str | None,
    foto: UploadFile | None,
    audio: UploadFile | None,
) -> str:
    incidente = crear_incidente(
        db,
        usuario_id=current_user.id,
        vehiculo_id=vehiculo_id,
        lat=lat,
        lng=lng,
        descripcion=descripcion,
    )

    evidencias_datos: list[dict] = []

    if audio:
        contenido_audio = await audio.read()
        transcripcion = await transcribir_audio_a_texto(contenido_audio)
        agregar_evidencia(
            db,
            incidente_id=incidente.id,
            tipo="audio",
            transcripcion=transcripcion,
        )
        evidencias_datos.append({"tipo": "audio", "texto": transcripcion})

    if foto:
        contenido_foto = await foto.read()
        analisis_imagen = await clasificar_incidente_por_imagenes(contenido_foto)
        agregar_evidencia(
            db,
            incidente_id=incidente.id,
            tipo="imagen",
            transcripcion=json.dumps(analisis_imagen, ensure_ascii=False),
        )
        evidencias_datos.append({"tipo": "imagen", "datos": analisis_imagen})

    if descripcion:
        agregar_evidencia(
            db,
            incidente_id=incidente.id,
            tipo="texto",
            transcripcion=descripcion,
        )
        evidencias_datos.append({"tipo": "texto", "texto": descripcion})

    db.commit()

    background_tasks.add_task(
        _procesar_asignacion_automatica,
        incidente_id=str(incidente.id),
        lat=lat,
        lng=lng,
        evidencias=evidencias_datos,
        usuario_id=str(current_user.id),
    )

    return str(incidente.id)


async def _procesar_asignacion_automatica(
    *,
    incidente_id: str,
    lat: float,
    lng: float,
    evidencias: list[dict],
    usuario_id: str,
) -> None:
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        incidente = obtener_incidente_por_id(db, incidente_id)
        if not incidente:
            return

        tipo = "otro"
        confianza = 0.7
        if evidencias:
            clasificacion = evidencias[0] if evidencias[0].get("tipo") == "imagen" else {}
            tipo = clasificacion.get("datos", {}).get("categoria_probable", "otro")
            confianza = float(clasificacion.get("datos", {}).get("confianza", 0.7))

        prioridad = asignar_nivel_prioridad(tipo)
        resumen = await generar_ficha_resumen_incidente(
            {"tipo": tipo, "prioridad": prioridad, "confianza": confianza},
            evidencias,
        )

        taller = await asignar_taller_automaticamente(
            db,
            incidente_id=incidente_id,
            lat=lat,
            lng=lng,
            tipo=tipo,
            prioridad=prioridad,
        )

        estado_anterior = incidente.estado
        incidente.tipo = tipo
        incidente.prioridad = prioridad
        incidente.estado = "en_proceso"
        if taller:
            incidente.taller_id = taller.id

        analisis = AnalisisIA(
            incidente_id=incidente.id,
            clasificacion=tipo,
            prioridad_sugerida=prioridad,
            resumen=resumen,
            confianza=confianza,
        )
        db.add(analisis)
        registrar_historial(
            db,
            incidente_id=incidente.id,
            estado_anterior=estado_anterior,
            estado_nuevo="en_proceso",
        )
        db.commit()

        if taller:
            await enviar_push(
                usuario_id,
                {
                    "titulo": "Taller asignado",
                    "cuerpo": f"{taller.nombre} esta en camino",
                    "tipo": "asignacion",
                },
            )
    finally:
        db.close()


def consultar_estado_solicitud(db: Session, *, incidente_id: str, current_user: Usuario):
    incidente = obtener_incidente_por_id(db, incidente_id)
    if not incidente:
        raise HTTPException(status_code=404, detail="Incidente no encontrado")

    if str(incidente.usuario_id) != str(current_user.id) and current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="No autorizado para consultar esta solicitud")

    return incidente


def enviar_ubicacion_gps(
    db: Session,
    *,
    incidente_id: str,
    lat: float,
    lng: float,
    current_user: Usuario,
):
    incidente = obtener_incidente_por_id(db, incidente_id)
    if not incidente:
        raise HTTPException(status_code=404, detail="Incidente no encontrado")
    if str(incidente.usuario_id) != str(current_user.id) and current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="No autorizado para actualizar ubicacion")
    return actualizar_ubicacion_incidente(db, incidente=incidente, lat=lat, lng=lng)


async def cargar_imagen_incidente(
    db: Session,
    *,
    incidente_id: str,
    imagen: UploadFile,
    current_user: Usuario,
):
    incidente = obtener_incidente_por_id(db, incidente_id)
    if not incidente:
        raise HTTPException(status_code=404, detail="Incidente no encontrado")
    if str(incidente.usuario_id) != str(current_user.id) and current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="No autorizado para adjuntar imagen")

    contenido = await imagen.read()
    analisis = await clasificar_incidente_por_imagenes(contenido)
    evidencia = agregar_evidencia(
        db,
        incidente_id=incidente.id,
        tipo="imagen",
        transcripcion=json.dumps(analisis, ensure_ascii=False),
    )
    db.commit()
    db.refresh(evidencia)
    return evidencia
