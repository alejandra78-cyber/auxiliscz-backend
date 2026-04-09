from sqlalchemy.orm import Session

from app.models.models import Usuario


def actualizar_password(db: Session, usuario: Usuario, nuevo_hash: str) -> Usuario:
    usuario.password_hash = nuevo_hash
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario

