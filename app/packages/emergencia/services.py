import json

from fastapi import BackgroundTasks, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.ai_modules.audio import transcribir_audio
from app.ai_modules.clasificador import clasificar_incidente
from app.ai_modules.resumen import generar_resumen
from app.ai_modules.vision import analizar_imagen
from app.models.models import Solicitud, Usuario
from app.services.notificaciones import enviar_push

from .repository import (
    agregar_evidencia_solicitud,
    actualizar_ubicacion_solicitud,
    crear_mensaje,
    crear_notificacion,
    crear_solicitud_emergencia,
    listar_notificaciones_usuario,
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
TIPOS_INCIDENTE_VALIDOS = set(PRIORIDAD_POR_TIPO.keys())


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
        # Compatibilidad: si la asignación no tiene taller enlazado pero sí técnico,
        # permitimos acceso al dueño del taller del técnico asignado.
        if a.tecnico and a.tecnico.taller and str(a.tecnico.taller.usuario_id) == str(current_user.id):
            return True
        # Acceso para cuenta técnico vinculada.
        if a.tecnico and a.tecnico.usuario_id and str(a.tecnico.usuario_id) == str(current_user.id):
            return True
    return False


async def reportar_emergencia(
    db: Session,
    *,
    background_tasks: BackgroundTasks,
    current_user: Usuario,
    vehiculo_id: str,
    tipo: str | None,
    lat: float,
    lng: float,
    descripcion: str | None,
    foto: UploadFile | None,
    audio: UploadFile | None,
) -> str:
    tipo_normalizado = (tipo or "otro").strip().lower()
    if tipo_normalizado not in TIPOS_INCIDENTE_VALIDOS:
        tipo_normalizado = "otro"

    solicitud = crear_solicitud_emergencia(
        db,
        usuario_id=current_user.id,
        vehiculo_id=vehiculo_id,
        tipo=tipo_normalizado,
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

    # Notificación de creación al cliente
    crear_notificacion(
        db,
        usuario_id=current_user.id,
        solicitud_id=solicitud.id,
        incidente_id=solicitud.incidente_id,
        titulo="Emergencia reportada",
        mensaje=f"Tu solicitud fue registrada y está en estado {solicitud.estado}",
        tipo="emergencia",
    )

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

    db = SessionLocal()
    try:
        solicitud = obtener_solicitud_por_id_o_incidente(db, solicitud_id)
        if not solicitud:
            return
        tipo = "otro"
        confianza = 0.7
        if solicitud.emergencia and solicitud.emergencia.tipo:
            tipo = str(solicitud.emergencia.tipo)
        if evidencias:
            clasificacion = next((ev for ev in evidencias if ev.get("tipo") == "imagen"), {})
            if clasificacion:
                tipo = clasificacion.get("datos", {}).get("categoria_probable", tipo)
                confianza = float(clasificacion.get("datos", {}).get("confianza", 0.7))

        # Clasificación multimodal (texto + audio + imagen)
        try:
            clasificacion_mm = await clasificar_incidente(evidencias)
            if clasificacion_mm:
                tipo = str(clasificacion_mm.get("tipo", tipo))
                confianza = float(clasificacion_mm.get("confianza", confianza))
        except Exception:
            clasificacion_mm = None

        prioridad = asignar_nivel_prioridad(tipo)
        if solicitud.emergencia:
            solicitud.emergencia.tipo = tipo
            solicitud.emergencia.prioridad = prioridad
        if solicitud.incidente:
            solicitud.incidente.tipo = tipo
            solicitud.incidente.prioridad = prioridad
            solicitud.incidente.descripcion = solicitud.emergencia.descripcion if solicitud.emergencia else solicitud.incidente.descripcion
        solicitud.prioridad = prioridad
        agregar_evidencia_solicitud(
            db,
            solicitud=solicitud,
            tipo="clasificacion_ia",
            transcripcion=json.dumps(
                {
                    "tipo": tipo,
                    "prioridad": prioridad,
                    "confianza": confianza,
                    "multimodal": clasificacion_mm or {},
                },
                ensure_ascii=False,
            ),
        )

        try:
            resumen = await generar_ficha_resumen_incidente(
                {"tipo": tipo, "prioridad": prioridad, "confianza": confianza},
                evidencias,
            )
            agregar_evidencia_solicitud(
                db,
                solicitud=solicitud,
                tipo="resumen_ia",
                transcripcion=resumen,
            )
        except Exception:
            pass

        # Mantener estado pendiente para respetar el flujo:
        # pendiente -> evaluación (aprobada/rechazada) -> asignación -> ejecución.
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
            incidente_id=solicitud.incidente_id,
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


def listar_notificaciones_solicitud(
    db: Session,
    *,
    current_user: Usuario,
    incidente_id: str | None = None,
):
    solicitud_id = None
    if incidente_id:
        solicitud = obtener_solicitud_por_id_o_incidente(db, incidente_id)
        if not solicitud:
            raise HTTPException(status_code=404, detail="Solicitud no encontrada")
        if not _puede_ver_solicitud(solicitud, current_user):
            raise HTTPException(status_code=403, detail="No autorizado para ver notificaciones")
        solicitud_id = solicitud.id

    rows = listar_notificaciones_usuario(db, usuario_id=current_user.id, solicitud_id=solicitud_id)
    return [
        {
            "id": str(n.id),
            "titulo": n.titulo,
            "mensaje": n.mensaje,
            "tipo": n.tipo,
            "estado": n.estado,
            "creada_en": n.creada_en.isoformat() if n.creada_en else None,
        }
        for n in rows
    ]
