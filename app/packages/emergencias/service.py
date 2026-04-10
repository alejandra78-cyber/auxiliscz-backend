import json

from fastapi import BackgroundTasks, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.models.models import AnalisisIA, Usuario
from app.packages.asignacion_servicio.service import asignar_taller_automaticamente
from app.packages.ia_incidente.service import (
    asignar_nivel_prioridad,
    clasificar_incidente_por_imagenes,
    generar_ficha_resumen_incidente,
    transcribir_audio_a_texto,
)
from app.services.notificaciones import enviar_push

from .repository import (
    agregar_evidencia,
    actualizar_ubicacion_incidente,
    crear_incidente,
    obtener_incidente_por_id,
    registrar_historial,
)


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
                    "cuerpo": f"{taller.nombre} está en camino",
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
        raise HTTPException(status_code=403, detail="No autorizado para actualizar ubicación")
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
