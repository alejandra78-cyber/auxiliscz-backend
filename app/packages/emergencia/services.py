import json
import logging
import os
import re
import uuid
from pathlib import Path

from fastapi import BackgroundTasks, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.ai_modules.audio import transcribir_audio
from app.ai_modules.clasificador import clasificar_incidente
from app.ai_modules.resumen import generar_resumen
from app.ai_modules.vision import analizar_imagen
from app.core.time import local_now_naive
from app.models.models import Solicitud, Usuario, Vehiculo
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

logger = logging.getLogger(__name__)

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
DEFAULT_TIPO_IA = "otro"
DEFAULT_PRIORIDAD_IA = 2
DEFAULT_RESUMEN_IA = "No se pudo generar el diagnóstico automáticamente"
ESTADOS_CANCELABLES = {
    "pendiente",
    "buscando_taller",
    "pendiente_asignacion",
    "en_revision",
    "en_evaluacion",
    "asignado",
    "aceptada",
    "tecnico_asignado",
    "pendiente_respuesta",
    "pendiente_respuesta_taller",
    "en_camino",
}
ESTADOS_NO_CANCELABLES = {
    "en_proceso",
    "atendido",
    "servicio_completado",
    "esperando_pago",
    "pagado",
    "completado",
    "completada",
    "finalizado",
    "cancelada",
    "cancelado",
    "rechazada",
}

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_UPLOADS_DIR = _PROJECT_ROOT / "uploads" / "emergencias"
_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def _safe_filename(name: str | None, default_ext: str = ".bin") -> str:
    raw = (name or "").strip()
    ext = Path(raw).suffix.lower()
    if not ext or len(ext) > 8:
        ext = default_ext
    return f"{uuid.uuid4().hex}{ext}"


def _save_uploaded_bytes(content: bytes, original_name: str | None, kind: str) -> str:
    filename = _safe_filename(original_name, default_ext=".jpg" if kind == "imagen" else ".m4a")
    out = _UPLOADS_DIR / filename
    out.write_bytes(content)
    public_base = os.getenv("BACKEND_PUBLIC_URL", "http://127.0.0.1:8000").strip().rstrip("/")
    # Si BACKEND_PUBLIC_URL viene mal, dejamos fallback estable.
    if not re.match(r"^https?://", public_base, re.IGNORECASE):
        public_base = "http://127.0.0.1:8000"
    return f"{public_base}/uploads/emergencias/{filename}"


def _estado_key(value: str | None) -> str:
    raw = (value or "").strip().lower()
    return raw.replace(" ", "_")


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
    fotos: list[UploadFile] | None,
    audio: UploadFile | None,
) -> dict:
    if current_user.rol not in {"conductor", "cliente", "admin"}:
        raise HTTPException(status_code=403, detail="Solo cliente/admin puede reportar emergencias")

    vehiculo = (
        db.query(Vehiculo)
        .filter(Vehiculo.id == vehiculo_id, Vehiculo.usuario_id == current_user.id, Vehiculo.activo == True)  # noqa: E712
        .first()
    )
    if not vehiculo:
        raise HTTPException(status_code=400, detail="El vehículo no existe o no pertenece al cliente autenticado")

    descripcion_limpia = (descripcion or "").strip()
    fotos_recibidas = [f for f in (fotos or []) if f is not None]
    if foto:
        fotos_recibidas.insert(0, foto)
    if not descripcion_limpia and not audio and not fotos_recibidas:
        raise HTTPException(
            status_code=400,
            detail="Debes enviar al menos una evidencia (foto/audio) o texto descriptivo",
        )

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
        descripcion=descripcion_limpia or None,
    )
    evidencias_datos: list[dict] = []
    ia_estado = "pendiente"
    transcripcion_audio: str | None = None
    analisis_imagenes: list[dict] = []

    if audio:
        contenido_audio = await audio.read()
        audio_url = _save_uploaded_bytes(contenido_audio, audio.filename, "audio")
        # Para respuesta rápida de CU11: guardamos audio y dejamos la transcripción para segundo plano.
        transcripcion_audio = None
        agregar_evidencia_solicitud(
            db,
            solicitud=solicitud,
            tipo="audio",
            url_archivo=audio_url,
            transcripcion=None,
            contenido_texto=None,
            metadata_json=json.dumps(
                {"filename": audio.filename, "content_type": audio.content_type},
                ensure_ascii=False,
            ),
        )
        evidencias_datos.append({"tipo": "audio", "texto": ""})

    for foto_file in fotos_recibidas:
        contenido_foto = await foto_file.read()
        foto_url = _save_uploaded_bytes(contenido_foto, foto_file.filename, "imagen")
        # Para respuesta rápida de CU11: guardamos imagen y dejamos análisis visual para segundo plano.
        analisis_imagenes.append({})
        agregar_evidencia_solicitud(
            db,
            solicitud=solicitud,
            tipo="imagen",
            url_archivo=foto_url,
            transcripcion=None,
            metadata_json=json.dumps(
                {"filename": foto_file.filename, "content_type": foto_file.content_type},
                ensure_ascii=False,
            ),
        )
        evidencias_datos.append({"tipo": "imagen", "datos": {}})

    if descripcion_limpia:
        agregar_evidencia_solicitud(
            db,
            solicitud=solicitud,
            tipo="texto",
            transcripcion=descripcion_limpia,
            contenido_texto=descripcion_limpia,
        )
        evidencias_datos.append({"tipo": "texto", "texto": descripcion_limpia})

    tipo_ia = tipo_normalizado
    prioridad_ia = asignar_nivel_prioridad(tipo_ia)
    confianza_ia = None
    resumen_ia: str | None = None
    ia_estado = "pendiente"

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

    if solicitud.emergencia:
        solicitud.emergencia.tipo = tipo_ia
        solicitud.emergencia.prioridad = prioridad_ia
    solicitud.prioridad = prioridad_ia
    if solicitud.incidente:
        solicitud.incidente.tipo = tipo_ia
        solicitud.incidente.prioridad = prioridad_ia
        solicitud.incidente.descripcion = descripcion_limpia or solicitud.incidente.descripcion
        solicitud.incidente.transcripcion_audio = transcripcion_audio
        solicitud.incidente.analisis_imagen = (
            json.dumps(analisis_imagenes, ensure_ascii=False) if analisis_imagenes else None
        )
        solicitud.incidente.resumen_ia = resumen_ia
        solicitud.incidente.confianza_ia = confianza_ia
        solicitud.incidente.ia_estado = ia_estado

    db.commit()

    # CU16 inmediato: asigna taller apenas se crea el incidente (sin esperar IA pesada).
    try:
        from app.packages.asignacion.services import asignar_taller_automaticamente

        await asignar_taller_automaticamente(
            db,
            solicitud_id=str(solicitud.id),
            lat=lat,
            lng=lng,
            tipo=tipo_ia,
            prioridad=prioridad_ia,
        )
    except HTTPException:
        # Si no hay candidato disponible, ya queda marcado por el servicio de asignación.
        pass
    except Exception:
        logger.exception("Asignación automática inicial falló para solicitud=%s", solicitud.id)

    background_tasks.add_task(
        _procesar_asignacion_automatica,
        solicitud_id=str(solicitud.id),
        lat=lat,
        lng=lng,
        evidencias=evidencias_datos,
        usuario_id=str(current_user.id),
    )
    return {
        "incidente_id": str(solicitud.id),
        "estado": str(solicitud.estado),
        "tipo": tipo_ia,
        "prioridad": prioridad_ia,
        "resumen_ia": resumen_ia,
        "ia_estado": ia_estado,
        "mensaje": "Emergencia registrada correctamente",
    }


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
            logger.exception("IA clasificación async falló para solicitud=%s", solicitud.id)
            clasificacion_mm = None
            tipo = DEFAULT_TIPO_IA
            confianza = 0.0

        prioridad = asignar_nivel_prioridad(tipo)
        if solicitud.emergencia:
            solicitud.emergencia.tipo = tipo
            solicitud.emergencia.prioridad = prioridad
        if solicitud.incidente:
            solicitud.incidente.tipo = tipo
            solicitud.incidente.prioridad = prioridad
            solicitud.incidente.descripcion = solicitud.emergencia.descripcion if solicitud.emergencia else solicitud.incidente.descripcion
            solicitud.incidente.ia_estado = "procesado" if clasificacion_mm else "fallido"
            solicitud.incidente.confianza_ia = confianza
        solicitud.prioridad = prioridad
        agregar_evidencia_solicitud(
            db,
            solicitud=solicitud,
            # Compatibilidad DB: tipo_evidencia_enum solo admite imagen/audio/texto.
            tipo="texto",
            transcripcion=json.dumps(
                {
                    "tipo": tipo,
                    "prioridad": prioridad,
                    "confianza": confianza,
                    "multimodal": clasificacion_mm or {},
                },
                ensure_ascii=False,
            ),
            metadata_json=json.dumps({"subtipo": "clasificacion_ia"}, ensure_ascii=False),
        )

        try:
            resumen = await generar_ficha_resumen_incidente(
                {"tipo": tipo, "prioridad": prioridad, "confianza": confianza},
                evidencias,
            )
            agregar_evidencia_solicitud(
                db,
                solicitud=solicitud,
                # Compatibilidad DB: persistimos resumen IA como evidencia de texto con subtipo.
                tipo="texto",
                transcripcion=resumen,
                contenido_texto=resumen,
                metadata_json=json.dumps({"subtipo": "resumen_ia"}, ensure_ascii=False),
            )
            if solicitud.incidente:
                solicitud.incidente.resumen_ia = resumen
        except Exception:
            logger.exception("IA resumen async falló para solicitud=%s", solicitud.id)
            if solicitud.incidente:
                solicitud.incidente.resumen_ia = DEFAULT_RESUMEN_IA
                solicitud.incidente.ia_estado = "fallido"

        # CU16: asignación inteligente automática posterior al reporte/clasificación.
        # Se crea asignación pendiente_respuesta para que el taller la evalúe en CU15.
        try:
            from app.packages.asignacion.services import asignar_taller_automaticamente

            await asignar_taller_automaticamente(
                db,
                solicitud_id=str(solicitud.id),
                lat=lat,
                lng=lng,
                tipo=tipo,
                prioridad=prioridad,
            )
        except HTTPException as exc:
            if exc.status_code == 400 and "asignación activa" in (exc.detail or "").lower():
                db.rollback()
                return
            db.rollback()
            solicitud = obtener_solicitud_por_id_o_incidente(db, solicitud_id)
            if solicitud:
                if solicitud.incidente:
                    solicitud.incidente.estado = "sin_taller_disponible"
                    if not solicitud.incidente.ia_estado:
                        solicitud.incidente.ia_estado = "fallido"
                solicitud.estado = "sin_taller_disponible"
                if solicitud.emergencia:
                    solicitud.emergencia.estado = "sin_taller_disponible"
                crear_notificacion(
                    db,
                    usuario_id=usuario_id,
                    solicitud_id=solicitud.id,
                    incidente_id=solicitud.incidente_id,
                    titulo="Sin taller disponible",
                    mensaje="No se encontró taller disponible de forma automática. Un operador revisará el caso.",
                    tipo="sin_taller_disponible",
                )
                db.commit()
        except Exception:
            db.rollback()
            solicitud = obtener_solicitud_por_id_o_incidente(db, solicitud_id)
            if solicitud:
                if solicitud.incidente:
                    solicitud.incidente.estado = "sin_taller_disponible"
                    if not solicitud.incidente.ia_estado:
                        solicitud.incidente.ia_estado = "fallido"
                solicitud.estado = "sin_taller_disponible"
                if solicitud.emergencia:
                    solicitud.emergencia.estado = "sin_taller_disponible"
                crear_notificacion(
                    db,
                    usuario_id=usuario_id,
                    solicitud_id=solicitud.id,
                    incidente_id=solicitud.incidente_id,
                    titulo="Sin taller disponible",
                    mensaje="No se encontró taller disponible de forma automática. Un operador revisará el caso.",
                    tipo="sin_taller_disponible",
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


def solicitud_es_cancelable(solicitud: Solicitud) -> bool:
    key = _estado_key(solicitud.estado)
    return key in ESTADOS_CANCELABLES


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
    foto_url = _save_uploaded_bytes(contenido, imagen.filename, "imagen")
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
        url_archivo=foto_url,
        transcripcion=json.dumps(analisis, ensure_ascii=False),
        metadata_json=json.dumps(
            {"filename": imagen.filename, "content_type": imagen.content_type},
            ensure_ascii=False,
        ),
    )
    db.commit()
    db.refresh(evidencia)
    return evidencia


def cancelar_solicitud(
    db: Session,
    *,
    incidente_id: str,
    current_user: Usuario,
    motivo_cancelacion: str | None = None,
):
    solicitud = obtener_solicitud_por_id_o_incidente(db, incidente_id)
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if current_user.rol != "admin":
        if not solicitud.cliente or str(solicitud.cliente.usuario_id) != str(current_user.id):
            raise HTTPException(status_code=403, detail="Solo el cliente dueño puede cancelar la solicitud")
    estado_actual = _estado_key(solicitud.estado)
    if estado_actual in ESTADOS_NO_CANCELABLES:
        raise HTTPException(
            status_code=400,
            detail=f"No se puede cancelar una solicitud en estado '{solicitud.estado}'",
        )
    if estado_actual not in ESTADOS_CANCELABLES:
        raise HTTPException(
            status_code=400,
            detail=f"El estado actual '{solicitud.estado}' no permite cancelación",
        )
    estado_anterior = solicitud.estado
    motivo = (motivo_cancelacion or "").strip() or "Cancelada por cliente"

    # Cancelar asignaciones activas y liberar técnico si aplica.
    for asig in solicitud.asignaciones:
        estado_asig = _estado_key(asig.estado)
        if estado_asig in {"cancelada", "cancelado", "rechazada", "finalizado", "completado", "completada"}:
            continue
        asig.estado = "cancelada"
        asig.motivo_cancelacion = motivo
        asig.cancelado_en = local_now_naive()
        if asig.tecnico and _estado_key(asig.tecnico.estado_operativo) in {
            "ocupado",
            "en_camino",
            "en_proceso",
        }:
            asig.tecnico.estado_operativo = "disponible"
            asig.tecnico.disponible = True

        if asig.taller and asig.taller.usuario_id:
            crear_notificacion(
                db,
                usuario_id=asig.taller.usuario_id,
                solicitud_id=solicitud.id,
                incidente_id=solicitud.incidente_id,
                titulo="Solicitud cancelada por cliente",
                mensaje=f"La solicitud {solicitud.id} fue cancelada por el cliente.",
                tipo="cancelacion",
            )

    registrar_cambio_estado(
        db,
        solicitud=solicitud,
        estado_anterior=estado_anterior,
        estado_nuevo="cancelada",
        comentario=motivo,
    )
    if solicitud.incidente:
        solicitud.incidente.motivo_cancelacion = motivo
        solicitud.incidente.cancelado_en = local_now_naive()
        solicitud.incidente.cancelado_por = current_user.id
    crear_notificacion(
        db,
        usuario_id=current_user.id,
        solicitud_id=solicitud.id,
        incidente_id=solicitud.incidente_id,
        titulo="Solicitud cancelada",
        mensaje="Tu solicitud fue cancelada correctamente.",
        tipo="cancelacion",
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
