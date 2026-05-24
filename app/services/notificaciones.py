from typing import Any

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.models import DispositivoPush, Notificacion

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
        db.commit()
    return None


async def enviar_push(usuario_id: str, payload: dict[str, Any]) -> dict[str, int]:
    db = SessionLocal()
    try:
        enviados = 0
        fallidas = 0
        tokens = (
            db.query(DispositivoPush)
            .filter(DispositivoPush.usuario_id == usuario_id, DispositivoPush.activo == True)  # noqa: E712
            .all()
        )
        if messaging and tokens:
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
                    fallidas += 1

        db.add(
            Notificacion(
                usuario_id=usuario_id,
                solicitud_id=payload.get("solicitud_id"),
                incidente_id=payload.get("incidente_id"),
                titulo=str(payload.get("titulo", "AuxilioSCZ")),
                mensaje=str(payload.get("cuerpo", "Tienes una nueva actualización")),
                tipo=str(payload.get("tipo", "sistema")),
                estado="no_leida",
            )
        )
        db.commit()
        # Si no hay tokens activos, al menos queda la notificación interna.
        if not tokens:
            enviados = max(enviados, 1)
        return {"enviadas": enviados, "fallidas": fallidas}
    except Exception:
        db.rollback()
        return {"enviadas": 0, "fallidas": 1}
    finally:
        db.close()
