from typing import Any

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.time import local_now_naive
from app.models.models import DispositivoPush

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


def enviar_push_db(db: Session, *, usuario_id: Any, payload: dict[str, Any]) -> dict[str, int]:
    enviados = 0
    fallidas = 0
    tokens = (
        db.query(DispositivoPush)
        .filter(DispositivoPush.usuario_id == usuario_id, DispositivoPush.activo == True)  # noqa: E712
        .all()
    )
    if not messaging or not tokens:
        return {"enviadas": 0, "fallidas": 0}

    for row in tokens:
        try:
            msg = messaging.Message(
                token=row.token,
                notification=messaging.Notification(
                    title=str(payload.get("titulo", "AuxilioSCZ")),
                    body=str(payload.get("cuerpo", "Tienes una nueva actualización")),
                ),
                data={
                    "tipo": str(payload.get("tipo", "sistema")),
                    "solicitud_id": str(payload.get("solicitud_id", "")),
                    "incidente_id": str(payload.get("incidente_id", "")),
                },
            )
            messaging.send(msg)
            enviados += 1
        except Exception:
            row.activo = False
            row.actualizado_en = local_now_naive()
            db.add(row)
            fallidas += 1

    return {"enviadas": enviados, "fallidas": fallidas}


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
    except Exception:
        db.rollback()
        return {"enviadas": 0, "fallidas": 1}
    finally:
        db.close()
