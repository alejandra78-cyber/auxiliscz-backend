from typing import Any

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.models import Notificacion


def registrar_token_dispositivo(db: Session, *, usuario_id: str, token: str, plataforma: str | None = None) -> None:
    # El modelo nuevo no gestiona tokens por tabla separada.
    # Se mantiene función por compatibilidad sin efectos.
    return None


def desactivar_token_dispositivo(db: Session, *, usuario_id: str, token: str) -> None:
    # El modelo nuevo no gestiona tokens por tabla separada.
    # Se mantiene función por compatibilidad sin efectos.
    return None


async def enviar_push(usuario_id: str, payload: dict[str, Any]) -> dict[str, int]:
    db = SessionLocal()
    try:
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
        return {"enviadas": 1, "fallidas": 0}
    except Exception:
        db.rollback()
        return {"enviadas": 0, "fallidas": 1}
    finally:
        db.close()
