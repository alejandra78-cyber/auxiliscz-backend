from sqlalchemy.orm import Session

from app.models.models import Usuario


def get_usuario_by_id(db: Session, usuario_id: str) -> Usuario | None:
    return db.query(Usuario).filter(Usuario.id == usuario_id).first()


def get_usuario_by_email(db: Session, email: str) -> Usuario | None:
    return db.query(Usuario).filter(Usuario.email == email).first()


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
        rol=rol,
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


def actualizar_rol(db: Session, usuario: Usuario, nuevo_rol: str) -> Usuario:
    usuario.rol = nuevo_rol
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


def actualizar_password(db: Session, usuario: Usuario, nuevo_hash: str) -> Usuario:
    usuario.password_hash = nuevo_hash
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario
