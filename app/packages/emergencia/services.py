import json

from fastapi import BackgroundTasks, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.ai_modules.audio import transcribir_audio
from app.ai_modules.resumen import generar_resumen
from app.ai_modules.vision import analizar_imagen
from app.models.models import Solicitud, Usuario
from app.packages.asignacion.services import asignar_taller_automaticamente
from app.services.notificaciones import enviar_push

from .repository import (
    agregar_evidencia_solicitud,
    actualizar_ubicacion_solicitud,
    crear_mensaje,
    crear_notificacion,
    crear_solicitud_emergencia,
    listar_mensajes_solicitud as repo_listar_mensajes_solicitud,
    obtener_solicitud_por_id_o_incidente,
    registrar_cambio_estado,
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


def _puede_ver_solicitud(solicitud: Solicitud, current_user: Usuario) -> bool:
    if current_user.rol == "admin":
        return True
    if solicitud.cliente and str(solicitud.cliente.usuario_id) == str(current_user.id):
        return True
    for a in solicitud.asignaciones:
        if a.taller and str(a.taller.usuario_id) == str(current_user.id):
            return True
    return False


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
    solicitud = crear_solicitud_emergencia(
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
        agregar_evidencia_solicitud(
            db,
            solicitud=solicitud,
            tipo="audio",
            transcripcion=transcripcion,
        )
        evidencias_datos.append({"tipo": "audio", "texto": transcripcion})

    if foto:
        contenido_foto = await foto.read()
        try:
            analisis_imagen = await clasificar_incidente_por_imagenes(contenido_foto)
        except Exception:
            analisis_imagen = {
                "problema_detectado": "No se pudo analizar imagen",
                "categoria_probable": "incierto",
                "nivel_danio": "desconocido",
                "confianza": 0.0,
            }
        agregar_evidencia_solicitud(
            db,
            solicitud=solicitud,
            tipo="imagen",
            transcripcion=json.dumps(analisis_imagen, ensure_ascii=False),
        )
        evidencias_datos.append({"tipo": "imagen", "datos": analisis_imagen})

    if descripcion:
        agregar_evidencia_solicitud(
            db,
            solicitud=solicitud,
            tipo="texto",
            transcripcion=descripcion,
        )
        evidencias_datos.append({"tipo": "texto", "texto": descripcion})

    db.commit()

    background_tasks.add_task(
        _procesar_asignacion_automatica,
        solicitud_id=str(solicitud.id),
        lat=lat,
        lng=lng,
        evidencias=evidencias_datos,
        usuario_id=str(current_user.id),
    )
    return str(solicitud.id)


async def _procesar_asignacion_automatica(
    *,
    solicitud_id: str,
    lat: float,
    lng: float,
    evidencias: list[dict],
    usuario_id: str,
) -> None:
    from app.core.database import SessionLocal
    from app.models.models import Asignacion

    db = SessionLocal()
    try:
        solicitud = obtener_solicitud_por_id_o_incidente(db, solicitud_id)
        if not solicitud:
            return
        tipo = "otro"
        confianza = 0.7
        if evidencias:
            clasificacion = evidencias[0] if evidencias[0].get("tipo") == "imagen" else {}
            tipo = clasificacion.get("datos", {}).get("categoria_probable", "otro")
            confianza = float(clasificacion.get("datos", {}).get("confianza", 0.7))

        prioridad = asignar_nivel_prioridad(tipo)
        if solicitud.emergencia:
            solicitud.emergencia.tipo = tipo
            solicitud.emergencia.prioridad = prioridad
            solicitud.emergencia.estado = "en_evaluacion"
        solicitud.prioridad = prioridad
        solicitud.estado = "en_evaluacion"
        registrar_cambio_estado(
            db,
            solicitud=solicitud,
            estado_anterior="pendiente",
            estado_nuevo="en_evaluacion",
            comentario="Clasificación automática inicial",
        )

        try:
            await generar_ficha_resumen_incidente(
                {"tipo": tipo, "prioridad": prioridad, "confianza": confianza},
                evidencias,
            )
        except Exception:
            pass

        taller = await asignar_taller_automaticamente(
            db,
            solicitud_id=solicitud_id,
            lat=lat,
            lng=lng,
            tipo=tipo,
            prioridad=prioridad,
        )
        if taller:
            db.add(
                Asignacion(
                    solicitud_id=solicitud.id,
                    taller_id=taller.id,
                    tecnico_id=None,
                    estado="asignada",
                )
            )
            registrar_cambio_estado(
                db,
                solicitud=solicitud,
                estado_anterior="en_evaluacion",
                estado_nuevo="asignada",
                comentario="Taller asignado automáticamente",
            )
            await enviar_push(
                usuario_id,
                {
                    "titulo": "Taller asignado",
                    "cuerpo": f"{taller.nombre} fue asignado a tu solicitud",
                    "tipo": "asignacion",
                },
            )
        db.commit()
    finally:
        db.close()


def consultar_estado_solicitud(db: Session, *, incidente_id: str, current_user: Usuario):
    solicitud = obtener_solicitud_por_id_o_incidente(db, incidente_id)
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if not _puede_ver_solicitud(solicitud, current_user):
        raise HTTPException(status_code=403, detail="No autorizado para consultar esta solicitud")
    return solicitud


def enviar_ubicacion_gps(
    db: Session,
    *,
    incidente_id: str,
    lat: float,
    lng: float,
    current_user: Usuario,
):
    solicitud = obtener_solicitud_por_id_o_incidente(db, incidente_id)
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if not _puede_ver_solicitud(solicitud, current_user):
        raise HTTPException(status_code=403, detail="No autorizado para actualizar ubicación")
    actualizar_ubicacion_solicitud(db, solicitud=solicitud, lat=lat, lng=lng)
    db.commit()
    db.refresh(solicitud)
    return solicitud


async def cargar_imagen_incidente(
    db: Session,
    *,
    incidente_id: str,
    imagen: UploadFile,
    current_user: Usuario,
):
    solicitud = obtener_solicitud_por_id_o_incidente(db, incidente_id)
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if not _puede_ver_solicitud(solicitud, current_user):
        raise HTTPException(status_code=403, detail="No autorizado para adjuntar imagen")
    contenido = await imagen.read()
    try:
        analisis = await clasificar_incidente_por_imagenes(contenido)
    except Exception:
        analisis = {
            "problema_detectado": "No se pudo analizar imagen",
            "categoria_probable": "incierto",
            "nivel_danio": "desconocido",
            "confianza": 0.0,
        }
    evidencia = agregar_evidencia_solicitud(
        db,
        solicitud=solicitud,
        tipo="imagen",
        transcripcion=json.dumps(analisis, ensure_ascii=False),
    )
    db.commit()
    db.refresh(evidencia)
    return evidencia


def cancelar_solicitud(db: Session, *, incidente_id: str, current_user: Usuario):
    solicitud = obtener_solicitud_por_id_o_incidente(db, incidente_id)
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if not _puede_ver_solicitud(solicitud, current_user):
        raise HTTPException(status_code=403, detail="No autorizado para cancelar esta solicitud")
    if solicitud.estado in {"completada", "cancelada"}:
        raise HTTPException(status_code=400, detail="La solicitud ya no puede cancelarse")
    estado_anterior = solicitud.estado
    registrar_cambio_estado(
        db,
        solicitud=solicitud,
        estado_anterior=estado_anterior,
        estado_nuevo="cancelada",
        comentario="Cancelada por usuario",
    )
    db.commit()
    db.refresh(solicitud)
    return solicitud


def listar_mensajes_solicitud(db: Session, *, incidente_id: str, current_user: Usuario):
    solicitud = obtener_solicitud_por_id_o_incidente(db, incidente_id)
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if not _puede_ver_solicitud(solicitud, current_user):
        raise HTTPException(status_code=403, detail="No autorizado para ver mensajes")
    mensajes = repo_listar_mensajes_solicitud(db, solicitud_id=solicitud.id)
    return [
        {
            "evidencia_id": str(m.id),
            "autor_rol": m.usuario.rol if m.usuario else "desconocido",
            "texto": m.contenido,
            "creado_en": m.creado_en.isoformat() if m.creado_en else None,
        }
        for m in mensajes
    ]


async def enviar_mensaje_solicitud(
    db: Session,
    *,
    incidente_id: str,
    current_user: Usuario,
    texto: str,
):
    solicitud = obtener_solicitud_por_id_o_incidente(db, incidente_id)
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if not _puede_ver_solicitud(solicitud, current_user):
        raise HTTPException(status_code=403, detail="No autorizado para enviar mensajes")
    texto_limpio = (texto or "").strip()
    if not texto_limpio:
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío")
    msg = crear_mensaje(db, solicitud=solicitud, usuario_id=current_user.id, texto=texto_limpio)

    destinatario_id = None
    if current_user.rol == "conductor":
        if solicitud.asignaciones:
            asig = solicitud.asignaciones[-1]
            if asig.taller:
                destinatario_id = asig.taller.usuario_id
    elif current_user.rol == "taller":
        if solicitud.cliente:
            destinatario_id = solicitud.cliente.usuario_id
    if destinatario_id:
        crear_notificacion(
            db,
            usuario_id=destinatario_id,
            solicitud_id=solicitud.id,
            titulo="Nuevo mensaje",
            mensaje=texto_limpio[:250],
            tipo="chat",
        )
    db.commit()
    db.refresh(msg)

    try:
        if destinatario_id:
            await enviar_push(
                str(destinatario_id),
                {"titulo": "Nuevo mensaje", "cuerpo": texto_limpio[:120], "tipo": "chat"},
            )
    except Exception:
        pass

    return {
        "evidencia_id": str(msg.id),
        "autor_rol": current_user.rol,
        "texto": msg.contenido,
        "creado_en": msg.creado_en.isoformat() if msg.creado_en else None,
    }
