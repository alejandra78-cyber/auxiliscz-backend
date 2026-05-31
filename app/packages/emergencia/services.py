import json
import logging
import os
import re
import uuid
import asyncio
from datetime import datetime
from urllib.parse import urlparse
from pathlib import Path

from fastapi import BackgroundTasks, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.ai_modules.audio import transcribir_audio
from app.ai_modules.clasificador import clasificar_incidente
from app.ai_modules.resumen import generar_resumen
from app.ai_modules.vision import analizar_imagen
from app.core.time import local_now_naive
from app.models.models import Asignacion, OperacionOffline, Solicitud, Usuario, Vehiculo
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
TIPOS_INCIDENTE_UI = {"bateria", "llanta", "choque", "motor", "otro"}
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


def _parse_fecha_local(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _json_dict(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _resultado_reporte(solicitud: Solicitud, mensaje: str = "Emergencia registrada correctamente") -> dict:
    return {
        "incidente_id": str(solicitud.id),
        "estado": str(solicitud.estado),
        "tipo": solicitud.incidente.tipo if solicitud.incidente else (solicitud.emergencia.tipo if solicitud.emergencia else None),
        "prioridad": solicitud.incidente.prioridad if solicitud.incidente else solicitud.prioridad,
        "resumen_ia": solicitud.incidente.resumen_ia if solicitud.incidente else None,
        "ia_estado": solicitud.incidente.ia_estado if solicitud.incidente else None,
        "asignacion_id": str(solicitud.asignaciones[-1].id) if solicitud.asignaciones else None,
        "mensaje": mensaje,
    }


def _resultado_solicitud(solicitud: Solicitud) -> dict:
    return {
        "solicitud_id": str(solicitud.id),
        "incidente_id": str(solicitud.incidente_id) if solicitud.incidente_id else str(solicitud.id),
        "estado": str(solicitud.estado),
    }


def _estado_key(value: str | None) -> str:
    raw = (value or "").strip().lower()
    return raw.replace(" ", "_")


def _normalizar_tipo_clasificado(value: str | None) -> str:
    raw = (value or "").strip().lower().replace(" ", "_")
    alias = {
        "batería": "bateria",
        "electrico": "bateria",
        "eléctrico": "bateria",
        "arranque_de_emergencia": "bateria",
        "cambio_de_llanta": "llanta",
        "pinchazo": "llanta",
        "grua": "choque",
        "grúa": "choque",
        "colision": "choque",
        "colisión": "choque",
        "accidente": "choque",
        "remolque": "choque",
        "llave": "otro",
        "incierto": "otro",
    }
    mapped = alias.get(raw, raw)
    if mapped in TIPOS_INCIDENTE_UI:
        return mapped
    if mapped in TIPOS_INCIDENTE_VALIDOS:
        return mapped if mapped != "incierto" else "otro"
    return "otro"


def _prioridad_desde_imagen(analisis: dict) -> int | None:
    if not isinstance(analisis, dict):
        return None
    nivel = str(analisis.get("nivel_danio", "")).strip().lower()
    if nivel == "grave":
        return 1
    if nivel == "moderado":
        return 2
    if nivel == "leve":
        return 3
    return None


def _inferir_choque_por_texto_visual(analisis: dict) -> bool:
    if not isinstance(analisis, dict):
        return False
    texto = " ".join(
        [
            str(analisis.get("problema_detectado", "") or ""),
            str(analisis.get("categoria_probable", "") or ""),
            str(analisis.get("nivel_danio", "") or ""),
        ]
    ).lower()
    claves_choque = [
        "choque",
        "colision",
        "colisión",
        "impacto",
        "frontal",
        "parachoque",
        "paragolpe",
        "capot",
        "capó",
        "daño severo",
        "destroz",
        "deform",
    ]
    return any(k in texto for k in claves_choque)


def _inferir_tipo_por_reglas(*, textos: list[str], hay_imagen: bool) -> str | None:
    base = " ".join([t for t in textos if t]).lower()
    base = re.sub(r"\s+", " ", base)
    reglas = [
        ("choque", ["choque", "colision", "colisión", "accidente", "impacto", "me choc", "chocaron"]),
        ("motor", ["motor", "humo", "sobrecalent", "refrigerante", "aceite", "no acelera"]),
        ("bateria", ["bateria", "batería", "no enciende", "sin corriente", "arranque"]),
        ("llanta", ["llanta", "goma", "neumatico", "neumático", "pinch", "revent"]),
    ]
    for tipo, keys in reglas:
        if any(k in base for k in keys):
            return tipo
    # Si hay solo imagen y no hay señales textuales, priorizamos choque como fallback
    # (caso más común en reportes con daño visible severo).
    if hay_imagen:
        return "choque"
    return None


def _resumen_fallback(*, tipo: str, prioridad: int, textos: list[str], hay_audio: bool, hay_imagen: bool) -> str:
    resumen_txt = " ".join([t.strip() for t in textos if t and t.strip()])[:320]
    evidencia = []
    if hay_imagen:
        evidencia.append("imágenes")
    if hay_audio:
        evidencia.append("audio")
    evidencia_str = ", ".join(evidencia) if evidencia else "texto"
    return (
        "Ficha Técnica de Emergencia Vehicular\n"
        f"Tipo probable: {tipo}\n"
        f"Prioridad sugerida: {prioridad}\n"
        f"Evidencia considerada: {evidencia_str}\n"
        f"Resumen: {resumen_txt or 'Se registró una emergencia y requiere evaluación del taller.'}"
    )


def _read_uploaded_bytes_from_url(url: str | None) -> bytes | None:
    """
    Lee bytes de un archivo subido localmente bajo /uploads/emergencias.
    """
    raw = (url or "").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
        path = parsed.path or raw
        marker = "/uploads/emergencias/"
        if marker not in path:
            return None
        filename = path.split(marker, 1)[1].strip("/\\")
        if not filename:
            return None
        local_path = _UPLOADS_DIR / filename
        if not local_path.exists():
            return None
        return local_path.read_bytes()
    except Exception:
        logger.exception("No se pudieron leer bytes desde url de evidencia=%s", raw)
        return None


async def transcribir_audio_a_texto(audio_bytes: bytes, idioma: str = "es") -> str:
    return await asyncio.wait_for(transcribir_audio(audio_bytes, idioma), timeout=22)


async def clasificar_incidente_por_imagenes(imagen_bytes: bytes) -> dict:
    return await asyncio.wait_for(analizar_imagen(imagen_bytes), timeout=22)


def asignar_nivel_prioridad(tipo_incidente: str) -> int:
    return PRIORIDAD_POR_TIPO.get(tipo_incidente, 2)


async def generar_ficha_resumen_incidente(clasificacion: dict, evidencias: list[dict]) -> str:
    return await asyncio.wait_for(generar_resumen(clasificacion, evidencias), timeout=18)


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
    offline_sync_id: str | None = None,
    fecha_local: str | None = None,
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

    sync_id = (offline_sync_id or "").strip() or None
    operacion_offline: OperacionOffline | None = None
    if sync_id:
        existente = db.query(OperacionOffline).filter(OperacionOffline.offline_sync_id == sync_id).first()
        if existente and existente.estado_sync == "sincronizado":
            return _json_dict(existente.resultado)
        if existente and existente.estado_sync in {"sincronizando", "pendiente_sincronizacion"}:
            raise HTTPException(status_code=409, detail="La emergencia offline ya está siendo sincronizada")
        solicitud_existente = db.query(Solicitud).filter(Solicitud.offline_sync_id == sync_id).first()
        if solicitud_existente:
            return _resultado_reporte(solicitud_existente, "Emergencia sincronizada previamente")
        operacion_offline = OperacionOffline(
            id=uuid.uuid4(),
            offline_sync_id=sync_id,
            usuario_id=current_user.id,
            tenant_id=None,
            tipo_operacion="reportar_emergencia",
            estado_sync="sincronizando",
            fecha_local=_parse_fecha_local(fecha_local),
            payload=json.dumps(
                {
                    "vehiculo_id": vehiculo_id,
                    "lat": lat,
                    "lng": lng,
                    "descripcion": descripcion,
                    "tipo": tipo,
                },
                ensure_ascii=False,
            ),
        )
        db.add(operacion_offline)

    descripcion_limpia = (descripcion or "").strip()
    fotos_recibidas = [f for f in (fotos or []) if f is not None]
    if foto:
        fotos_recibidas.insert(0, foto)
    if not descripcion_limpia and not audio and not fotos_recibidas:
        raise HTTPException(
            status_code=400,
            detail="Debes enviar al menos una evidencia (foto/audio) o texto descriptivo",
        )

    tipo_normalizado = (tipo or "incierto").strip().lower()
    if tipo_normalizado not in TIPOS_INCIDENTE_VALIDOS:
        tipo_normalizado = "incierto"

    solicitud = crear_solicitud_emergencia(
        db,
        usuario_id=current_user.id,
        vehiculo_id=vehiculo_id,
        tipo=tipo_normalizado,
        lat=lat,
        lng=lng,
        descripcion=descripcion_limpia or None,
        offline_sync_id=sync_id,
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
        evidencias_datos.append({"tipo": "audio", "texto": "", "url_archivo": audio_url})

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
        evidencias_datos.append({"tipo": "imagen", "datos": {}, "url_archivo": foto_url})

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
    resumen_ia: str | None = DEFAULT_RESUMEN_IA
    ia_estado = "procesando"

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
    resultado = {
        "incidente_id": str(solicitud.id),
        "estado": str(solicitud.estado),
        "tipo": tipo_ia,
        "prioridad": prioridad_ia,
        "resumen_ia": resumen_ia,
        "ia_estado": ia_estado,
        "mensaje": "Emergencia registrada correctamente",
    }
    if operacion_offline:
        operacion_offline.estado_sync = "sincronizado"
        operacion_offline.resultado = json.dumps(resultado, ensure_ascii=False)
        operacion_offline.error = None
        operacion_offline.sincronizado_en = local_now_naive()
        db.commit()
    return resultado


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

        evidencias_mm: list[dict] = []
        transcripciones_audio: list[str] = []
        analisis_imagenes: list[dict] = []
        textos_libres: list[str] = []
        hay_audio = False
        hay_imagen = False

        for link in list(solicitud.evidencias or []):
            ev = getattr(link, "evidencia", None)
            if not ev:
                continue

            metadata = {}
            try:
                metadata = json.loads(ev.metadata_json or "{}")
            except Exception:
                metadata = {}

            subtipo = str(metadata.get("subtipo") or "").strip().lower()
            if subtipo in {"clasificacion_ia", "resumen_ia"}:
                continue

            tipo_ev = str(ev.tipo or "").strip().lower()
            if tipo_ev == "texto":
                texto = (ev.contenido_texto or ev.transcripcion or "").strip()
                if texto:
                    evidencias_mm.append({"tipo": "texto", "texto": texto})
                    textos_libres.append(texto)
                continue

            if tipo_ev == "audio":
                hay_audio = True
                texto_audio = (ev.transcripcion or "").strip()
                if not texto_audio:
                    audio_bytes = _read_uploaded_bytes_from_url(ev.url_archivo)
                    if audio_bytes:
                        try:
                            texto_audio = (await transcribir_audio_a_texto(audio_bytes, "es")).strip()
                            ev.transcripcion = texto_audio or ev.transcripcion
                            ev.contenido_texto = texto_audio or ev.contenido_texto
                        except Exception:
                            logger.exception("IA audio: transcripción falló para solicitud=%s", solicitud.id)
                if texto_audio:
                    transcripciones_audio.append(texto_audio)
                    textos_libres.append(texto_audio)
                evidencias_mm.append({"tipo": "audio", "texto": texto_audio})
                continue

            if tipo_ev == "imagen":
                hay_imagen = True
                datos_img: dict = {}
                if ev.transcripcion:
                    try:
                        parsed = json.loads(ev.transcripcion)
                        if isinstance(parsed, dict):
                            datos_img = parsed
                    except Exception:
                        datos_img = {}
                if not datos_img:
                    img_bytes = _read_uploaded_bytes_from_url(ev.url_archivo)
                    if img_bytes:
                        try:
                            datos_img = await clasificar_incidente_por_imagenes(img_bytes)
                            ev.transcripcion = json.dumps(datos_img, ensure_ascii=False)
                        except Exception:
                            logger.exception("IA imagen: análisis falló para solicitud=%s", solicitud.id)
                            datos_img = {}
                if datos_img:
                    analisis_imagenes.append(datos_img)
                    textos_libres.extend(
                        [
                            str(datos_img.get("problema_detectado", "") or ""),
                            str(datos_img.get("categoria_probable", "") or ""),
                            str(datos_img.get("nivel_danio", "") or ""),
                        ]
                    )
                    tipo_img = _normalizar_tipo_clasificado(datos_img.get("categoria_probable", tipo))
                    conf_img = float(datos_img.get("confianza", confianza))
                    # La imagen manda cuando tiene confianza razonable.
                    if conf_img >= 0.60:
                        tipo = tipo_img
                    confianza = max(confianza, conf_img)
                evidencias_mm.append({"tipo": "imagen", "datos": datos_img})

        if not evidencias_mm:
            evidencias_mm = evidencias

        # Clasificación multimodal (texto + audio + imagen)
        try:
            clasificacion_mm = await asyncio.wait_for(clasificar_incidente(evidencias_mm), timeout=14)
            if clasificacion_mm:
                tipo_mm = _normalizar_tipo_clasificado(clasificacion_mm.get("tipo", tipo))
                conf_mm = float(clasificacion_mm.get("confianza", confianza))
                # Si no hay imagen concluyente, usamos multimodal.
                if conf_mm >= 0.45:
                    tipo = tipo_mm
                confianza = max(confianza, conf_mm)
        except Exception:
            logger.exception("IA clasificación async falló para solicitud=%s", solicitud.id)
            clasificacion_mm = None
            # No degradar a "otro" de inmediato; luego aplicamos reglas locales.
            confianza = 0.0

        # Reglas de respaldo cuando IA no clasifica bien.
        tipo_regla = _inferir_tipo_por_reglas(textos=textos_libres, hay_imagen=hay_imagen)
        if _normalizar_tipo_clasificado(tipo) in {"otro"} and tipo_regla:
            tipo = tipo_regla
        elif (tipo or "").strip().lower() in {"incierto", ""} and tipo_regla:
            tipo = tipo_regla

        tipo = _normalizar_tipo_clasificado(tipo)
        # Regla de negocio reforzada: si la visión describe daño de colisión,
        # priorizamos categoría choque para evitar falsos "otro".
        if analisis_imagenes and any(_inferir_choque_por_texto_visual(a) for a in analisis_imagenes):
            tipo = "choque"
        prioridad = asignar_nivel_prioridad(tipo)
        # Regla global: daño grave visual => prioridad alta.
        if analisis_imagenes:
            prioridad_visual = _prioridad_desde_imagen(analisis_imagenes[0])
            if prioridad_visual is not None:
                prioridad = min(prioridad, prioridad_visual)
        if solicitud.emergencia:
            solicitud.emergencia.tipo = tipo
            solicitud.emergencia.prioridad = prioridad
        if solicitud.incidente:
            solicitud.incidente.tipo = tipo
            solicitud.incidente.prioridad = prioridad
            solicitud.incidente.descripcion = solicitud.emergencia.descripcion if solicitud.emergencia else solicitud.incidente.descripcion
            solicitud.incidente.ia_estado = "procesado" if clasificacion_mm else "fallido"
            solicitud.incidente.confianza_ia = confianza
            solicitud.incidente.transcripcion_audio = (
                "\n".join(transcripciones_audio).strip() if transcripciones_audio else solicitud.incidente.transcripcion_audio
            )
            solicitud.incidente.analisis_imagen = (
                json.dumps(analisis_imagenes, ensure_ascii=False) if analisis_imagenes else solicitud.incidente.analisis_imagen
            )
        solicitud.prioridad = prioridad

        # Mantener coherencia CU16/CU14-CU15:
        # si ya existe asignación activa creada antes de terminar IA,
        # actualizamos el motivo técnico para reflejar tipo/prioridad finales.
        try:
            asignacion_activa = (
                db.query(Asignacion)
                .filter(Asignacion.solicitud_id == solicitud.id)
                .order_by(Asignacion.fecha_asignacion.desc().nullslast(), Asignacion.asignado_en.desc().nullslast())
                .first()
            )
            if asignacion_activa and (asignacion_activa.estado or "").lower() in {
                "pendiente_respuesta",
                "asignada",
                "aceptada",
                "tecnico_asignado",
                "en_camino",
            }:
                asignacion_activa.motivo_asignacion = (
                    f"tipo={tipo}; prioridad={prioridad}; "
                    f"dist={float(asignacion_activa.distancia_km or 0):.2f}km; "
                    f"estado_ia=procesado"
                )
        except Exception:
            logger.exception("No se pudo sincronizar motivo_asignacion con IA para solicitud=%s", solicitud.id)

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
                evidencias_mm,
            )
            if not (resumen or "").strip():
                resumen = _resumen_fallback(
                    tipo=tipo,
                    prioridad=prioridad,
                    textos=textos_libres,
                    hay_audio=hay_audio,
                    hay_imagen=hay_imagen,
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
            resumen = _resumen_fallback(
                tipo=tipo,
                prioridad=prioridad,
                textos=textos_libres,
                hay_audio=hay_audio,
                hay_imagen=hay_imagen,
            )
            agregar_evidencia_solicitud(
                db,
                solicitud=solicitud,
                tipo="texto",
                transcripcion=resumen,
                contenido_texto=resumen,
                metadata_json=json.dumps({"subtipo": "resumen_ia"}, ensure_ascii=False),
            )
            if solicitud.incidente:
                solicitud.incidente.resumen_ia = resumen
                solicitud.incidente.ia_estado = "procesado"
                # Hubo fallback exitoso local, evitamos dejarlo como fallido vacío.
                solicitud.incidente.ia_estado = "procesado"

        # Persistimos SIEMPRE el resultado IA antes de intentar CU16 nuevamente.
        # Esto evita perder tipo/prioridad/resumen cuando CU16 devuelve "asignación activa".
        db.commit()

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
            detalle = (exc.detail or "").lower()
            if exc.status_code == 400 and (
                "asignación activa" in detalle or "candidatos activos" in detalle
            ):
                # La IA ya quedó guardada arriba; no hacemos rollback para no perderla.
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


def sincronizar_operaciones_offline(
    db: Session,
    *,
    current_user: Usuario,
    operaciones: list,
) -> list[dict]:
    resultados: list[dict] = []
    for op in operaciones:
        sync_id = (op.offline_sync_id or "").strip()
        tipo_operacion = (op.tipo_operacion or "").strip().lower()
        payload = op.payload or {}
        if not sync_id:
            resultados.append(
                {
                    "offline_sync_id": "",
                    "tipo_operacion": tipo_operacion,
                    "estado_sync": "error_sincronizacion",
                    "resultado": None,
                    "error": "offline_sync_id es obligatorio",
                }
            )
            continue
        existente = db.query(OperacionOffline).filter(OperacionOffline.offline_sync_id == sync_id).first()
        if existente and existente.estado_sync == "sincronizado":
            resultados.append(
                {
                    "offline_sync_id": sync_id,
                    "tipo_operacion": existente.tipo_operacion,
                    "estado_sync": "sincronizado",
                    "resultado": _json_dict(existente.resultado),
                    "error": None,
                }
            )
            continue

        row = existente or OperacionOffline(
            id=uuid.uuid4(),
            offline_sync_id=sync_id,
            usuario_id=current_user.id,
            tenant_id=getattr(current_user, "tenant_id", None),
            tipo_operacion=tipo_operacion,
            estado_sync="sincronizando",
            fecha_local=_parse_fecha_local(op.fecha_local),
        )
        row.usuario_id = current_user.id
        row.tenant_id = getattr(current_user, "tenant_id", None)
        row.tipo_operacion = tipo_operacion
        row.estado_sync = "sincronizando"
        row.payload = json.dumps(payload, ensure_ascii=False)
        row.error = None
        db.add(row)
        db.flush()

        try:
            resultado = _procesar_operacion_offline(db, current_user=current_user, tipo_operacion=tipo_operacion, payload=payload)
            row.estado_sync = "sincronizado"
            row.resultado = json.dumps(resultado, ensure_ascii=False)
            row.sincronizado_en = local_now_naive()
            row.error = None
            db.commit()
            resultados.append(
                {
                    "offline_sync_id": sync_id,
                    "tipo_operacion": tipo_operacion,
                    "estado_sync": "sincronizado",
                    "resultado": resultado,
                    "error": None,
                }
            )
        except HTTPException as exc:
            db.rollback()
            row = db.query(OperacionOffline).filter(OperacionOffline.offline_sync_id == sync_id).first()
            if row:
                row.estado_sync = "conflicto" if exc.status_code in {400, 409} else "error_sincronizacion"
                row.error = str(exc.detail)
                row.sincronizado_en = local_now_naive()
                db.add(row)
                db.commit()
            resultados.append(
                {
                    "offline_sync_id": sync_id,
                    "tipo_operacion": tipo_operacion,
                    "estado_sync": "conflicto" if exc.status_code in {400, 409} else "error_sincronizacion",
                    "resultado": None,
                    "error": str(exc.detail),
                }
            )
        except Exception as exc:
            logger.exception("Error sincronizando operacion offline %s", sync_id)
            db.rollback()
            row = db.query(OperacionOffline).filter(OperacionOffline.offline_sync_id == sync_id).first()
            if row:
                row.estado_sync = "error_sincronizacion"
                row.error = str(exc)
                row.sincronizado_en = local_now_naive()
                db.add(row)
                db.commit()
            resultados.append(
                {
                    "offline_sync_id": sync_id,
                    "tipo_operacion": tipo_operacion,
                    "estado_sync": "error_sincronizacion",
                    "resultado": None,
                    "error": str(exc),
                }
            )
    return resultados


def _procesar_operacion_offline(
    db: Session,
    *,
    current_user: Usuario,
    tipo_operacion: str,
    payload: dict,
) -> dict:
    incidente_id = str(payload.get("incidente_id") or payload.get("solicitud_id") or "").strip()
    if not incidente_id:
        raise HTTPException(status_code=400, detail="La operación offline no tiene solicitud asociada")

    if tipo_operacion in {"aceptar_solicitud", "rechazar_solicitud"}:
        from app.packages.asignacion.services import evaluar_solicitud_servicio

        solicitud = evaluar_solicitud_servicio(
            db,
            incidente_id=incidente_id,
            current_user=current_user,
            aprobar=(tipo_operacion == "aceptar_solicitud"),
            observacion=payload.get("observacion") or payload.get("motivo_rechazo"),
        )
        return _resultado_solicitud(solicitud)

    if tipo_operacion in {"actualizar_estado", "accion_servicio"}:
        from app.packages.asignacion.services import actualizar_estado_servicio, ejecutar_accion_operativa_servicio

        if tipo_operacion == "accion_servicio" or payload.get("accion"):
            solicitud = ejecutar_accion_operativa_servicio(
                db,
                incidente_id=incidente_id,
                current_user=current_user,
                accion=str(payload.get("accion") or ""),
                observacion=payload.get("observacion"),
                tecnico_id=payload.get("tecnico_id") or payload.get("tecnicoId"),
                servicio=payload.get("servicio"),
            )
        else:
            solicitud = actualizar_estado_servicio(
                db,
                incidente_id=incidente_id,
                current_user=current_user,
                estado=str(payload.get("estado") or ""),
                observacion=payload.get("observacion"),
                tecnico_id=payload.get("tecnico_id") or payload.get("tecnicoId"),
            )
        return _resultado_solicitud(solicitud)

    if tipo_operacion == "generar_cotizacion":
        from app.packages.pagos.services import cotizacion_out, generar_cotizacion_taller

        cotizacion = generar_cotizacion_taller(
            db,
            current_user=current_user,
            incidente_id=incidente_id,
            monto_total=float(payload.get("monto_total") or payload.get("monto") or 0),
            tiempo_estimado=payload.get("tiempo_estimado"),
            detalle=str(payload.get("detalle") or ""),
            observaciones=payload.get("observaciones"),
            validez_hasta=payload.get("validez_hasta"),
        )
        return cotizacion_out(cotizacion).model_dump()

    raise HTTPException(status_code=400, detail="Tipo de operación offline no soportado")


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
    # Reintento automático de asignación SOLO en etapas tempranas del flujo.
    # Evita reabrir/reasignar servicios que ya están en atención, pago o cerrados.
    estado_sol = _estado_key(solicitud.estado)
    estados_cerrados = {
        "cancelada",
        "cancelado",
        "finalizado",
        "completada",
        "completado",
        "pagado",
    }
    estados_reintento_asignacion = {
        "pendiente",
        "buscando_taller",
        "pendiente_asignacion",
        "sin_taller_disponible",
        "en_revision",
        "en_evaluacion",
    }
    estados_asig_activa = {
        "pendiente_respuesta",
        "aceptada",
        "tecnico_asignado",
        "en_camino",
        "en_diagnostico",
        "diagnostico_completado",
        "en_proceso",
        "atendido",
        "esperando_pago",
        "pagado",
        "finalizado",
    }
    tiene_asignacion_activa = any(
        _estado_key(getattr(a, "estado", None)) in estados_asig_activa for a in (solicitud.asignaciones or [])
    )

    db.commit()

    # Si ya hubo asignaciones históricas, no relanzar CU16 desde cliente.
    if estado_sol in estados_reintento_asignacion and not tiene_asignacion_activa and not (solicitud.asignaciones or []):
        tipo_incidente = (solicitud.incidente.tipo if solicitud.incidente and solicitud.incidente.tipo else None)
        prioridad_incidente = (
            int(solicitud.incidente.prioridad)
            if solicitud.incidente and solicitud.incidente.prioridad is not None
            else int(solicitud.prioridad or 2)
        )
        try:
            from app.packages.asignacion.services import asignar_taller_automaticamente
            import asyncio

            asyncio.run(
                asignar_taller_automaticamente(
                    db,
                    solicitud_id=str(solicitud.id),
                    lat=float(lat),
                    lng=float(lng),
                    tipo=tipo_incidente,
                    prioridad=prioridad_incidente,
                )
            )
        except Exception:
            logger.exception("Reintento CU16 por actualización de ubicación falló para solicitud=%s", solicitud.id)

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
