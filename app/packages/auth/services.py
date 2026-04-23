import hashlib
import secrets
from datetime import timedelta
from urllib.parse import urlencode

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.security import create_access_token, get_password_hash, verify_password
from app.core.time import local_now_naive
from app.models.models import PasswordResetToken, Usuario
from app.services.emailer import enviar_email

from .models import PERMISOS_POR_ROL, ROLES_VALIDOS
from .repository import (
    actualizar_rol,
    crear_usuario,
    get_usuario_by_email,
    get_usuario_by_id,
    permisos_de_rol,
)
from .schemas import CambiarPasswordIn, RecuperarPasswordRequestOut


def registrar_usuario(db: Session, *, nombre: str, email: str, password: str, telefono: str | None, rol: str) -> Usuario:
    rol_final = rol if rol in ROLES_VALIDOS else "conductor"
    if get_usuario_by_email(db, email):
        raise HTTPException(status_code=400, detail="El email ya está registrado")
    return crear_usuario(
        db,
        nombre=nombre,
        email=email,
        password_hash=get_password_hash(password),
        telefono=telefono,
        rol=rol_final,
    )


def iniciar_sesion(db: Session, *, email: str, password: str) -> str:
    usuario = get_usuario_by_email(db, email)
    if not usuario or not verify_password(password, usuario.password_hash):
        raise HTTPException(status_code=401, detail="Email o contraseña incorrectos")
    if (usuario.estado or "").lower() in {"inactivo", "bloqueado", "pendiente_activacion"}:
        raise HTTPException(status_code=403, detail="Cuenta pendiente de activación o inactiva")
    return create_access_token({"sub": str(usuario.id), "rol": usuario.rol})


def cerrar_sesion() -> dict:
    return {"ok": True, "mensaje": "Sesión cerrada correctamente"}


def obtener_permisos_por_rol(rol: str) -> list[str]:
    # fallback estático si catálogo aún no tiene permisos sembrados
    return PERMISOS_POR_ROL.get(rol, [])


def obtener_permisos_por_rol_db(db: Session, rol: str) -> list[str]:
    permisos = permisos_de_rol(db, rol)
    if permisos:
        return permisos
    return obtener_permisos_por_rol(rol)


def cambiar_rol_usuario(db: Session, *, usuario_id: str, nuevo_rol: str) -> Usuario:
    if nuevo_rol not in ROLES_VALIDOS:
        raise HTTPException(status_code=400, detail="Rol inválido")
    usuario = get_usuario_by_id(db, usuario_id)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return actualizar_rol(db, usuario, nuevo_rol)


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _new_raw_token() -> str:
    return secrets.token_urlsafe(48)


def _issue_password_token(
    db: Session,
    *,
    usuario_id: str,
    scope: str,
    minutes: int,
    commit: bool = True,
) -> str:
    now = local_now_naive()
    db.query(PasswordResetToken).filter(
        PasswordResetToken.usuario_id == usuario_id,
        PasswordResetToken.scope == scope,
        PasswordResetToken.usado_en == None,  # noqa: E711
    ).update({"usado_en": now}, synchronize_session=False)

    raw = _new_raw_token()
    row = PasswordResetToken(
        usuario_id=usuario_id,
        token_hash=_hash_token(raw),
        scope=scope,
        expires_en=now + timedelta(minutes=minutes),
    )
    db.add(row)
    if commit:
        db.commit()
    else:
        db.flush()
    return raw


def solicitar_recuperacion_password(db: Session, *, email: str) -> RecuperarPasswordRequestOut:
    usuario = get_usuario_by_email(db, email.strip().lower())
    if usuario:
        raw_token = _issue_password_token(
            db,
            usuario_id=str(usuario.id),
            scope="password_recovery",
            minutes=30,
        )
        frontend_url = "http://localhost:4200"
        import os
        frontend_url = os.getenv("FRONTEND_BASE_URL", frontend_url).rstrip("/")
        query = urlencode({"reset_token": raw_token})
        reset_url = f"{frontend_url}/recover-password?{query}"
        enviar_email(
            usuario.email,
            "AuxilioSCZ - Recuperación de contraseña",
            (
                f"Hola {usuario.nombre},\n\n"
                "Recibimos una solicitud para restablecer tu contraseña.\n"
                "Si fuiste tú, abre el siguiente enlace:\n\n"
                f"{reset_url}\n\n"
                "El enlace expira en 30 minutos.\n"
                "Si no fuiste tú, ignora este mensaje."
            ),
        )
    return RecuperarPasswordRequestOut()


def generar_token_set_password(db: Session, usuario_id: str, *, minutes: int = 60 * 24) -> str:
    return _issue_password_token(
        db,
        usuario_id=usuario_id,
        scope="password_recovery",
        minutes=minutes,
        commit=True,
    )


def generar_token_activacion_cuenta(
    db: Session,
    usuario_id: str,
    *,
    minutes: int = 60 * 24,
    commit: bool = True,
) -> str:
    return _issue_password_token(
        db,
        usuario_id=usuario_id,
        scope="account_activation",
        minutes=minutes,
        commit=commit,
    )


def validar_token_password(db: Session, *, reset_token: str) -> tuple[PasswordResetToken, Usuario]:
    token_hash = _hash_token(reset_token)
    token_row = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == token_hash).first()
    if not token_row:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")
    if token_row.usado_en is not None:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")
    if token_row.expires_en < local_now_naive():
        raise HTTPException(status_code=401, detail="Token inválido o expirado")
    if token_row.scope not in {"password_recovery", "account_activation"}:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")
    usuario = get_usuario_by_id(db, str(token_row.usuario_id))
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return token_row, usuario


def resetear_password(db: Session, *, reset_token: str, nueva_password: str) -> None:
    token_row, usuario = validar_token_password(db, reset_token=reset_token)
    if len(nueva_password.strip()) < 6:
        raise HTTPException(status_code=400, detail="La contraseña debe tener al menos 6 caracteres")
    nuevo_hash = get_password_hash(nueva_password)
    usuario.password_hash = nuevo_hash
    usuario.estado = "activo"
    token_row.usado_en = local_now_naive()
    db.add(token_row)
    db.add(usuario)
    db.commit()


def cambiar_password(db: Session, usuario: Usuario, payload: CambiarPasswordIn) -> None:
    if not verify_password(payload.password_actual, usuario.password_hash):
        raise HTTPException(status_code=400, detail="La contraseña actual es incorrecta")

    if payload.password_nueva != payload.password_nueva_confirmacion:
        raise HTTPException(status_code=400, detail="La confirmación de contraseña no coincide")

    if payload.password_actual == payload.password_nueva:
        raise HTTPException(status_code=400, detail="La nueva contraseña debe ser diferente a la actual")

    nuevo_hash = get_password_hash(payload.password_nueva)
    actualizar_password(db, usuario, nuevo_hash)
