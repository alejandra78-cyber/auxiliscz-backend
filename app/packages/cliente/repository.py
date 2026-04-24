from sqlalchemy.orm import Session

from app.models.models import Cliente, Usuario, Vehiculo


def crear_vehiculo(
    db: Session,
    *,
    usuario: Usuario,
    placa: str,
    marca: str | None,
    modelo: str | None,
    anio: int | None,
    color: str | None,
    tipo: str | None,
    observacion: str | None,
) -> Vehiculo:
    cliente = db.query(Cliente).filter(Cliente.usuario_id == usuario.id).first()
    vehiculo = Vehiculo(
        usuario_id=usuario.id,
        cliente_id=cliente.id if cliente else None,
        placa=placa.upper().strip(),
        marca=marca,
        modelo=modelo,
        anio=anio,
        color=color,
        tipo=tipo,
        observacion=observacion,
        activo=True,
    )
    db.add(vehiculo)
    db.commit()
    db.refresh(vehiculo)
    return vehiculo


def get_vehiculo_by_placa(db: Session, placa: str) -> Vehiculo | None:
    return db.query(Vehiculo).filter(Vehiculo.placa == placa.upper().strip()).first()


def listar_vehiculos_de_usuario(db: Session, *, usuario: Usuario) -> list[Vehiculo]:
    return (
        db.query(Vehiculo)
        .filter(Vehiculo.usuario_id == usuario.id)
        .order_by(Vehiculo.creado_en.desc(), Vehiculo.id.desc())
        .all()
    )


def get_vehiculo_de_usuario_by_id(db: Session, *, usuario: Usuario, vehiculo_id: str) -> Vehiculo | None:
    return (
        db.query(Vehiculo)
        .filter(Vehiculo.id == vehiculo_id, Vehiculo.usuario_id == usuario.id)
        .first()
    )


def actualizar_vehiculo(
    db: Session,
    *,
    vehiculo: Vehiculo,
    marca: str,
    modelo: str,
    anio: int | None,
    color: str | None,
    tipo: str | None,
    observacion: str | None,
) -> Vehiculo:
    vehiculo.marca = marca
    vehiculo.modelo = modelo
    vehiculo.anio = anio
    vehiculo.color = color
    vehiculo.tipo = tipo
    vehiculo.observacion = observacion
    db.add(vehiculo)
    db.commit()
    db.refresh(vehiculo)
    return vehiculo


def desactivar_vehiculo(db: Session, *, vehiculo: Vehiculo) -> Vehiculo:
    vehiculo.activo = False
    db.add(vehiculo)
    db.commit()
    db.refresh(vehiculo)
    return vehiculo
