from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user

from .schemas import (
    CambiarPasswordIn,
    CambiarPasswordOut,
    CambiarRolIn,
    DeviceTokenIn,
    DeviceTokenOut,
    LoginIn,
    LogoutOut,
    RecuperarPasswordRequestIn,
    RecuperarPasswordRequestOut,
    RegisterIn,
    ResetPasswordIn,
    RolPermisoOut,
    TokenOut,
    UsuarioOut,
    ValidateResetTokenIn,
    ValidateResetTokenOut,
)
from app.services.notificaciones import desactivar_token_dispositivo, registrar_token_dispositivo
from .services import (
    cambiar_password,
    cambiar_rol_usuario,
    cerrar_sesion,
    iniciar_sesion,
    obtener_permisos_por_rol,
    obtener_permisos_por_rol_db,
    registrar_usuario,
    resetear_password,
    solicitar_recuperacion_password,
    validar_token_password,
)

router = APIRouter()


@router.post("/register", response_model=UsuarioOut)
def register(payload: RegisterIn, db: Session = Depends(get_db)):
    nombre_completo = payload.nombre.strip()
    if payload.apellido and payload.apellido.strip():
        nombre_completo = f"{nombre_completo} {payload.apellido.strip()}"
    usuario = registrar_usuario(
        db,
        nombre=nombre_completo,
        email=payload.email,
        password=payload.password,
        telefono=payload.telefono,
        rol="conductor",
    )
    return usuario


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, db: Session = Depends(get_db)):
    token = iniciar_sesion(db, email=payload.email, password=payload.password)
    return TokenOut(access_token=token)


@router.post("/logout", response_model=LogoutOut)
def logout():
    return cerrar_sesion()


@router.get("/roles/{rol}/permisos", response_model=RolPermisoOut)
def permisos_por_rol(rol: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    if current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede consultar permisos")
    return RolPermisoOut(rol=rol, permisos=obtener_permisos_por_rol_db(db, rol))


@router.patch("/roles", response_model=UsuarioOut)
def cambiar_rol(payload: CambiarRolIn, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    if current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede cambiar roles")
    return cambiar_rol_usuario(db, usuario_id=payload.usuario_id, nuevo_rol=payload.nuevo_rol)


@router.post("/password/recovery-request", response_model=RecuperarPasswordRequestOut)
def password_recovery_request(payload: RecuperarPasswordRequestIn, db: Session = Depends(get_db)):
    return solicitar_recuperacion_password(db, email=payload.email)


@router.post("/password/reset")
def password_reset(payload: ResetPasswordIn, db: Session = Depends(get_db)):
    resetear_password(db, reset_token=payload.reset_token, nueva_password=payload.nueva_password)
    return {"ok": True, "mensaje": "Contraseña restablecida correctamente"}


@router.post("/password/validate-token", response_model=ValidateResetTokenOut)
def validate_password_token(payload: ValidateResetTokenIn, db: Session = Depends(get_db)):
    validar_token_password(db, reset_token=payload.reset_token)
    return ValidateResetTokenOut()


@router.patch("/cambiar-password", response_model=CambiarPasswordOut)
def cambiar_password_endpoint(
    payload: CambiarPasswordIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    cambiar_password(db, current_user, payload)
    return CambiarPasswordOut()


@router.post("/device-token", response_model=DeviceTokenOut)
def registrar_device_token(
    payload: DeviceTokenIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    registrar_token_dispositivo(
        db,
        usuario_id=str(current_user.id),
        token=payload.token,
        plataforma=payload.plataforma,
    )
    return DeviceTokenOut()


@router.post("/device-token/remove", response_model=DeviceTokenOut)
def remover_device_token(
    payload: DeviceTokenIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    desactivar_token_dispositivo(
        db,
        usuario_id=str(current_user.id),
        token=payload.token,
    )
    return DeviceTokenOut(mensaje="Token de dispositivo desactivado")
