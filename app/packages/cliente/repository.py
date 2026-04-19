from sqlalchemy.orm import Session

from app.models.models import Usuario, Vehiculo


def crear_vehiculo(
    db: Session,
    *,
    usuario: Usuario,
    placa: str,
    marca: str | None,
    modelo: str | None,
    anio: int | None,
    color: str | None,
) -> Vehiculo:
    vehiculo = Vehiculo(
        usuario_id=usuario.id,
        placa=placa.upper().strip(),
        marca=marca,
        modelo=modelo,
        anio=anio,
        color=color,
    )
    db.add(vehiculo)
    db.commit()
    db.refresh(vehiculo)
    return vehiculo


def get_vehiculo_by_placa(db: Session, placa: str) -> Vehiculo | None:
    return db.query(Vehiculo).filter(Vehiculo.placa == placa.upper().strip()).first()


def listar_vehiculos_de_usuario(db: Session, *, usuario: Usuario) -> list[Vehiculo]:
    return db.query(Vehiculo).filter(Vehiculo.usuario_id == usuario.id).all()
