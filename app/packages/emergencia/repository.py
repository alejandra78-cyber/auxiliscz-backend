import uuid

from sqlalchemy.orm import Session, joinedload

from app.models.models import (
    Cliente,
    Emergencia,
    Evidencia,
    Historial,
    Mensaje,
    Notificacion,
    Solicitud,
    SolicitudEvidencia,
    Ubicacion,
)


def obtener_solicitud_por_id_o_incidente(db: Session, solicitud_id_o_incidente: str) -> Solicitud | None:
    try:
        raw_id = uuid.UUID(str(solicitud_id_o_incidente))
    except ValueError:
        return None
    solicitud = (
        db.query(Solicitud)
        .options(
            joinedload(Solicitud.emergencia),
            joinedload(Solicitud.cliente).joinedload(Cliente.usuario),
            joinedload(Solicitud.asignaciones),
        )
        .filter(Solicitud.id == raw_id)
        .first()
    )
    if solicitud:
        return solicitud
    return (
        db.query(Solicitud)
        .options(
            joinedload(Solicitud.emergencia),
            joinedload(Solicitud.cliente).joinedload(Cliente.usuario),
            joinedload(Solicitud.asignaciones),
        )
        .filter(Solicitud.incidente_id == raw_id)
        .first()
    )


def obtener_o_crear_cliente(db: Session, *, usuario_id) -> Cliente:
    cliente = db.query(Cliente).filter(Cliente.usuario_id == usuario_id).first()
    if cliente:
        return cliente
    cliente = Cliente(id=uuid.uuid4(), usuario_id=usuario_id)
    db.add(cliente)
    db.flush()
    return cliente


def crear_solicitud_emergencia(
    db: Session,
    *,
    usuario_id,
    vehiculo_id,
    lat: float,
    lng: float,
    descripcion: str | None,
) -> Solicitud:
    cliente = obtener_o_crear_cliente(db, usuario_id=usuario_id)
    solicitud = Solicitud(
        id=uuid.uuid4(),
        cliente_id=cliente.id,
        vehiculo_id=vehiculo_id,
        estado="pendiente",
        prioridad=2,
    )
    db.add(solicitud)
    db.flush()

    emergencia = Emergencia(
        id=uuid.uuid4(),
        solicitud_id=solicitud.id,
        tipo="otro",
        descripcion=descripcion,
        estado="pendiente",
        prioridad=2,
    )
    db.add(emergencia)
    db.flush()

    db.add(
        Ubicacion(
            id=uuid.uuid4(),
            emergencia_id=emergencia.id,
            latitud=lat,
            longitud=lng,
            fuente="gps",
        )
    )
    db.add(
        Historial(
            id=uuid.uuid4(),
            solicitud_id=solicitud.id,
            estado_anterior=None,
            estado_nuevo="pendiente",
            comentario="Solicitud creada",
        )
    )
    return solicitud


def actualizar_ubicacion_solicitud(db: Session, *, solicitud: Solicitud, lat: float, lng: float) -> None:
    if solicitud.emergencia is None:
        solicitud.emergencia = Emergencia(
            id=uuid.uuid4(),
            solicitud_id=solicitud.id,
            tipo="otro",
            descripcion=None,
            estado=solicitud.estado,
            prioridad=solicitud.prioridad,
        )
        db.add(solicitud.emergencia)
        db.flush()
    db.add(
        Ubicacion(
            id=uuid.uuid4(),
            emergencia_id=solicitud.emergencia.id,
            latitud=lat,
            longitud=lng,
            fuente="gps",
        )
    )


def agregar_evidencia_solicitud(
    db: Session,
    *,
    solicitud: Solicitud,
    tipo: str,
    transcripcion: str | None = None,
    url_archivo: str | None = None,
) -> Evidencia:
    evidencia = Evidencia(
        id=uuid.uuid4(),
        tipo=tipo,
        transcripcion=transcripcion,
        url_archivo=url_archivo,
    )
    db.add(evidencia)
    db.flush()
    db.add(
        SolicitudEvidencia(
            id=uuid.uuid4(),
            solicitud_id=solicitud.id,
            evidencia_id=evidencia.id,
        )
    )
    return evidencia


def registrar_cambio_estado(
    db: Session,
    *,
    solicitud: Solicitud,
    estado_anterior: str | None,
    estado_nuevo: str,
    comentario: str | None = None,
) -> None:
    solicitud.estado = estado_nuevo
    if solicitud.emergencia:
        solicitud.emergencia.estado = estado_nuevo
    db.add(
        Historial(
            id=uuid.uuid4(),
            solicitud_id=solicitud.id,
            estado_anterior=estado_anterior,
            estado_nuevo=estado_nuevo,
            comentario=comentario,
        )
    )


def listar_mensajes_solicitud(db: Session, *, solicitud_id) -> list[Mensaje]:
    return (
        db.query(Mensaje)
        .filter(Mensaje.solicitud_id == solicitud_id)
        .order_by(Mensaje.creado_en.asc())
        .all()
    )


def crear_mensaje(
    db: Session,
    *,
    solicitud: Solicitud,
    usuario_id,
    texto: str,
) -> Mensaje:
    msg = Mensaje(id=uuid.uuid4(), solicitud_id=solicitud.id, usuario_id=usuario_id, contenido=texto)
    db.add(msg)
    db.flush()
    return msg


def crear_notificacion(
    db: Session,
    *,
    usuario_id,
    solicitud_id,
    titulo: str,
    mensaje: str,
    tipo: str = "sistema",
) -> None:
    db.add(
        Notificacion(
            id=uuid.uuid4(),
            usuario_id=usuario_id,
            solicitud_id=solicitud_id,
            titulo=titulo,
            mensaje=mensaje,
            tipo=tipo,
            estado="no_leida",
        )
    )
