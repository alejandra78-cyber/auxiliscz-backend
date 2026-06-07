import logging
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.time import local_now_naive
from app.models.models import DispositivoPush

logger = logging.getLogger("auxilioscz.push")

try:
    from firebase_admin import messaging
except Exception:  # pragma: no cover
    messaging = None


def registrar_token_dispositivo(db: Session, *, usuario_id: str, token: str, plataforma: str | None = None) -> None:
    raw = (token or "").strip()
    if not raw:
        return None
    row = db.query(DispositivoPush).filter(DispositivoPush.token == raw).first()
    if row:
        row.usuario_id = usuario_id
        row.plataforma = (plataforma or row.plataforma or "unknown").strip()[:30]
        row.activo = True
        row.actualizado_en = local_now_naive()
    else:
        db.add(
            DispositivoPush(
                usuario_id=usuario_id,
                token=raw,
                plataforma=(plataforma or "unknown").strip()[:30],
                activo=True,
            )
        )
    db.commit()
    return None


def desactivar_token_dispositivo(db: Session, *, usuario_id: str, token: str) -> None:
    raw = (token or "").strip()
    if not raw:
        return None
    row = (
        db.query(DispositivoPush)
        .filter(DispositivoPush.usuario_id == usuario_id, DispositivoPush.token == raw)
        .first()
    )
    if row:
        row.activo = False
        row.actualizado_en = local_now_naive()
        db.commit()
    return None


def _es_error_token_invalido(exc: Exception) -> bool:
    name = exc.__class__.__name__.lower()
    text = str(exc).lower()
    invalid_markers = {
        "unregistered",
        "senderidmismatch",
        "registration-token-not-registered",
        "requested entity was not found",
        "invalid registration token",
    }
    return any(marker in name or marker in text for marker in invalid_markers)


def enviar_push_db(db: Session, *, usuario_id: Any, payload: dict[str, Any]) -> dict[str, int]:
    enviados = 0
    fallidas = 0
    errores: list[dict[str, str]] = []
    tokens = (
        db.query(DispositivoPush)
        .filter(DispositivoPush.usuario_id == usuario_id, DispositivoPush.activo == True)  # noqa: E712
        .all()
    )
    if not messaging:
        logger.warning("FCM no disponible: firebase_admin.messaging no está inicializado")
        return {"enviadas": 0, "fallidas": 0, "errores": [{"error": "Firebase Admin no está inicializado"}]}
    if not tokens:
        logger.info("FCM sin tokens activos para usuario=%s", usuario_id)
        return {"enviadas": 0, "fallidas": 0, "errores": [{"error": "No hay tokens activos para este usuario"}]}

    for row in tokens:
        try:
            title = str(payload.get("titulo") or payload.get("title") or "AuxilioSCZ")
            body = str(payload.get("cuerpo") or payload.get("body") or "Tienes una nueva actualización")
            data = {
                "tipo": str(payload.get("tipo", "sistema")),
                "solicitud_id": str(payload.get("solicitud_id", "")),
                "incidente_id": str(payload.get("incidente_id", "")),
                "titulo": title,
                "cuerpo": body,
            }
            msg = messaging.Message(
                token=row.token,
                notification=messaging.Notification(title=title, body=body),
                data=data,
                android=messaging.AndroidConfig(
                    priority="high",
                    ttl=timedelta(hours=1),
                    notification=messaging.AndroidNotification(
                        channel_id="auxilioscz_alertas",
                        priority="high",
                        sound="default",
                        visibility="public",
                        notification_count=1,
                        default_sound=True,
                        default_vibrate_timings=True,
                    ),
                ),
                apns=messaging.APNSConfig(
                    headers={"apns-priority": "10"},
                    payload=messaging.APNSPayload(
                        aps=messaging.Aps(sound="default", content_available=True)
                    ),
                ),
                webpush=messaging.WebpushConfig(
                    notification=messaging.WebpushNotification(
                        title=title,
                        body=body,
                    ),
                ),
            )
            message_id = messaging.send(msg)
            logger.info("FCM enviado usuario=%s token_id=%s message_id=%s tipo=%s", usuario_id, row.id, message_id, data["tipo"])
            enviados += 1
        except Exception as exc:
            error_text = str(exc)
            logger.warning("FCM falló usuario=%s token_id=%s plataforma=%s error=%s", usuario_id, row.id, row.plataforma, error_text)
            errores.append(
                {
                    "token_id": str(row.id),
                    "plataforma": str(row.plataforma or "unknown"),
                    "error": error_text,
                    "tipo_error": exc.__class__.__name__,
                }
            )
            if _es_error_token_invalido(exc):
                row.activo = False
                row.actualizado_en = local_now_naive()
                db.add(row)
            fallidas += 1

    return {"enviadas": enviados, "fallidas": fallidas, "errores": errores}


async def enviar_push(usuario_id: str, payload: dict[str, Any]) -> dict[str, int]:
    db = SessionLocal()
    try:
        resultado = enviar_push_db(
            db,
            usuario_id=usuario_id,
            payload=payload,
        )
        db.commit()
        return resultado
    except Exception as exc:
        db.rollback()
        return {"enviadas": 0, "fallidas": 1, "errores": [{"error": str(exc), "tipo_error": exc.__class__.__name__}]}
    finally:
        db.close()
