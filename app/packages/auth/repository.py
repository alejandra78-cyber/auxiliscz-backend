from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.models import Rol, RolPermiso, Usuario, UsuarioRol


def get_usuario_by_id(db: Session, usuario_id: str) -> Usuario | None:
    return db.query(Usuario).filter(Usuario.id == usuario_id).first()


def get_usuario_by_email(db: Session, email: str) -> Usuario | None:
    return db.query(Usuario).filter(func.lower(Usuario.email) == email.strip().lower()).first()


def crear_usuario(
    db: Session,
    *,
    nombre: str,
    email: str,
    password_hash: str,
    telefono: str | None,
    rol: str,
) -> Usuario:
    usuario = Usuario(
        nombre=nombre,
        email=email,
        password_hash=password_hash,
        telefono=telefono,
    )
    db.add(usuario)
    db.flush()
    rol_obj = db.query(Rol).filter(Rol.nombre == rol).first()
    if not rol_obj:
        rol_obj = Rol(nombre=rol, descripcion=f"Rol {rol}")
        db.add(rol_obj)
        db.flush()
    db.add(UsuarioRol(usuario_id=usuario.id, rol_id=rol_obj.id))
    db.commit()
    db.refresh(usuario)
    return usuario


def actualizar_rol(db: Session, usuario: Usuario, nuevo_rol: str) -> Usuario:
    rol_obj = db.query(Rol).filter(Rol.nombre == nuevo_rol).first()
    if not rol_obj:
        rol_obj = Rol(nombre=nuevo_rol, descripcion=f"Rol {nuevo_rol}")
        db.add(rol_obj)
        db.flush()
    db.query(UsuarioRol).filter(UsuarioRol.usuario_id == usuario.id).delete()
    db.add(UsuarioRol(usuario_id=usuario.id, rol_id=rol_obj.id))
    db.commit()
    db.refresh(usuario)
    return usuario


def permisos_de_rol(db: Session, rol: str) -> list[str]:
    rol_obj = db.query(Rol).filter(Rol.nombre == rol).first()
    if not rol_obj:
        return []
    rows = (
        db.query(RolPermiso)
        .filter(RolPermiso.rol_id == rol_obj.id)
        .all()
    )
    return [rp.permiso.codigo for rp in rows if rp.permiso]


def actualizar_password(db: Session, usuario: Usuario, nuevo_hash: str) -> Usuario:
    usuario.password_hash = nuevo_hash
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario
