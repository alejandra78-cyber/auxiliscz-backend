from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user

from .schemas import (
    CambiarPasswordIn,
    CambiarPasswordOut,
    CambiarRolIn,
    LoginIn,
    LogoutOut,
    RecuperarPasswordRequestIn,
    RecuperarPasswordRequestOut,
    RegisterIn,
    ResetPasswordIn,
    RolPermisoOut,
    TokenOut,
    UsuarioOut,
)
from .services import (
    cambiar_password,
    cambiar_rol_usuario,
    cerrar_sesion,
    iniciar_sesion,
    obtener_permisos_por_rol,
    registrar_usuario,
    resetear_password,
    solicitar_recuperacion_password,
)

router = APIRouter()


@router.post("/register", response_model=UsuarioOut)
def register(payload: RegisterIn, db: Session = Depends(get_db)):
    usuario = registrar_usuario(
        db,
        nombre=payload.nombre,
        email=payload.email,
        password=payload.password,
        telefono=payload.telefono,
        rol=payload.rol,
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
def permisos_por_rol(rol: str, current_user=Depends(get_current_user)):
    if current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede consultar permisos")
    return RolPermisoOut(rol=rol, permisos=obtener_permisos_por_rol(rol))


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


@router.patch("/cambiar-password", response_model=CambiarPasswordOut)
def cambiar_password_endpoint(
    payload: CambiarPasswordIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    cambiar_password(db, current_user, payload)
    return CambiarPasswordOut()
