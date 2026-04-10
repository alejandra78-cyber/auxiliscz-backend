from datetime import timedelta

from fastapi import HTTPException
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.security import ALGORITHM, SECRET_KEY, create_access_token, get_password_hash, verify_password
from app.models.models import Usuario

from .models import PERMISOS_POR_ROL, ROLES_VALIDOS
from .repository import (
    actualizar_password,
    actualizar_rol,
    crear_usuario,
    get_usuario_by_email,
    get_usuario_by_id,
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
    return create_access_token({"sub": str(usuario.id), "rol": usuario.rol})


def cerrar_sesion() -> dict:
    return {"ok": True, "mensaje": "Sesión cerrada correctamente"}


def obtener_permisos_por_rol(rol: str) -> list[str]:
    return PERMISOS_POR_ROL.get(rol, [])


def cambiar_rol_usuario(db: Session, *, usuario_id: str, nuevo_rol: str) -> Usuario:
    if nuevo_rol not in ROLES_VALIDOS:
        raise HTTPException(status_code=400, detail="Rol inválido")
    usuario = get_usuario_by_id(db, usuario_id)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return actualizar_rol(db, usuario, nuevo_rol)


def solicitar_recuperacion_password(db: Session, *, email: str) -> RecuperarPasswordRequestOut:
    usuario = get_usuario_by_email(db, email)
    token = None
    if usuario:
        token = create_access_token(
            {"sub": str(usuario.id), "scope": "password_recovery"},
            expires_delta=timedelta(minutes=30),
        )
    return RecuperarPasswordRequestOut(reset_token=token)


def resetear_password(db: Session, *, reset_token: str, nueva_password: str) -> None:
    try:
        payload = jwt.decode(reset_token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("scope") != "password_recovery":
            raise HTTPException(status_code=401, detail="Token de recuperación inválido")
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token inválido")
    except JWTError:
        raise HTTPException(status_code=401, detail="No se pudo verificar el token de recuperación")

    usuario = get_usuario_by_id(db, user_id)
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    nuevo_hash = get_password_hash(nueva_password)
    actualizar_password(db, usuario, nuevo_hash)


def cambiar_password(db: Session, usuario: Usuario, payload: CambiarPasswordIn) -> None:
    if not verify_password(payload.password_actual, usuario.password_hash):
        raise HTTPException(status_code=400, detail="La contraseña actual es incorrecta")

    if payload.password_nueva != payload.password_nueva_confirmacion:
        raise HTTPException(status_code=400, detail="La confirmación de contraseña no coincide")

    if payload.password_actual == payload.password_nueva:
        raise HTTPException(status_code=400, detail="La nueva contraseña debe ser diferente a la actual")

    nuevo_hash = get_password_hash(payload.password_nueva)
    actualizar_password(db, usuario, nuevo_hash)
