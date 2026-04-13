import os
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.models import DispositivoPush

try:
    import firebase_admin
    from firebase_admin import credentials, messaging
except Exception:  # pragma: no cover - fallback when dependency is unavailable
    firebase_admin = None
    credentials = None
    messaging = None

_firebase_warning_logged = False


def _firebase_ready() -> bool:
    global _firebase_warning_logged
    if firebase_admin is None:
        if not _firebase_warning_logged:
            print("[FIREBASE] firebase-admin no está instalado o no pudo importarse.")
            _firebase_warning_logged = True
        return False
    try:
        firebase_admin.get_app()
        return True
    except Exception:
        pass

    credentials_path = os.getenv("FIREBASE_CREDENTIALS_PATH", "./firebase-credentials.json")
    resolved = Path(credentials_path)
    if not resolved.is_absolute():
        resolved = Path.cwd() / resolved

    if not resolved.exists():
        if not _firebase_warning_logged:
            print(
                f"[FIREBASE] No se encontró credencial en: {resolved}. "
                "Configura FIREBASE_CREDENTIALS_PATH y coloca firebase-credentials.json."
            )
            _firebase_warning_logged = True
        return False

    try:
        cred = credentials.Certificate(str(resolved))
        firebase_admin.initialize_app(cred)
        _firebase_warning_logged = False
        return True
    except Exception:
        if not _firebase_warning_logged:
            print("[FIREBASE] Error inicializando Firebase Admin con las credenciales proporcionadas.")
            _firebase_warning_logged = True
        return False


def registrar_token_dispositivo(db: Session, *, usuario_id: str, token: str, plataforma: str | None = None) -> None:
    normalized = token.strip()
    if not normalized:
        return

    dispositivo = db.query(DispositivoPush).filter(DispositivoPush.token == normalized).first()
    if dispositivo:
        dispositivo.usuario_id = usuario_id
        dispositivo.plataforma = (plataforma or dispositivo.plataforma or "unknown").strip() or "unknown"
        dispositivo.activo = True
    else:
        db.add(
            DispositivoPush(
                usuario_id=usuario_id,
                token=normalized,
                plataforma=(plataforma or "unknown").strip() or "unknown",
                activo=True,
            )
        )
    db.commit()


def desactivar_token_dispositivo(db: Session, *, usuario_id: str, token: str) -> None:
    normalized = token.strip()
    if not normalized:
        return
    dispositivo = (
        db.query(DispositivoPush)
        .filter(DispositivoPush.usuario_id == usuario_id, DispositivoPush.token == normalized)
        .first()
    )
    if dispositivo:
        dispositivo.activo = False
        db.commit()


async def enviar_push(usuario_id: str, payload: dict[str, Any]) -> dict[str, int]:
    db = SessionLocal()
    try:
        dispositivos = (
            db.query(DispositivoPush.token)
            .filter(DispositivoPush.usuario_id == usuario_id, DispositivoPush.activo.is_(True))
            .all()
        )
        tokens = [row[0] for row in dispositivos]
    finally:
        db.close()

    if not tokens:
        print(f"[NOTIFICACION] usuario={usuario_id} sin tokens registrados payload={payload}")
        return {"enviadas": 0, "fallidas": 0}

    if not _firebase_ready() or messaging is None:
        print(f"[NOTIFICACION_SIMULADA] usuario={usuario_id} tokens={len(tokens)} payload={payload}")
        return {"enviadas": len(tokens), "fallidas": 0}

    enviadas = 0
    fallidas = 0
    titulo = str(payload.get("titulo", "AuxilioSCZ"))
    cuerpo = str(payload.get("cuerpo", "Tienes una nueva actualización"))
    data = {k: str(v) for k, v in payload.items() if v is not None}

    for token in tokens:
        try:
            msg = messaging.Message(
                notification=messaging.Notification(title=titulo, body=cuerpo),
                data=data,
                token=token,
            )
            messaging.send(msg)
            enviadas += 1
        except Exception:
            fallidas += 1

    return {"enviadas": enviadas, "fallidas": fallidas}
