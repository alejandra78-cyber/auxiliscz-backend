import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from app.core.time import local_now_naive
from app.models.models import Asignacion, Notificacion, Solicitud, Tecnico, Ubicacion, Usuario

ESTADOS_COMPARTIR_UBICACION = {"tecnico_asignado", "en_camino", "en_proceso"}


def _estado_key(value: str | None) -> str:
    return (value or "").strip().lower().replace(" ", "_")


def _obtener_tecnico_de_usuario(db: Session, current_user: Usuario) -> Tecnico:
    tecnico = db.query(Tecnico).filter(Tecnico.usuario_id == current_user.id).first()
    if not tecnico:
        raise HTTPException(status_code=404, detail="No existe perfil técnico asociado")
    return tecnico


def _codigo_solicitud(solicitud_id: str) -> str:
    return f"SOL-{str(solicitud_id).split('-')[0].upper()}"


def listar_mis_servicios_asignados(db: Session, *, current_user: Usuario) -> list[dict]:
    if current_user.rol != "tecnico":
        raise HTTPException(status_code=403, detail="Solo técnico puede ver sus servicios asignados")

    tecnico = _obtener_tecnico_de_usuario(db, current_user)
    rows = (
        db.query(Asignacion)
        .options(
            joinedload(Asignacion.solicitud).joinedload(Solicitud.cliente),
            joinedload(Asignacion.solicitud).joinedload(Solicitud.vehiculo),
            joinedload(Asignacion.solicitud).joinedload(Solicitud.emergencia),
        )
        .filter(Asignacion.tecnico_id == tecnico.id)
        .filter(Asignacion.estado.in_(list(ESTADOS_COMPARTIR_UBICACION)))
        .order_by(Asignacion.fecha_asignacion.desc().nullslast(), Asignacion.asignado_en.desc().nullslast())
        .all()
    )

    out: list[dict] = []
    for row in rows:
        solicitud = row.solicitud
        if not solicitud:
            continue
        out.append(
            {
                "asignacion_id": str(row.id),
                "incidente_id": str(solicitud.id),
                "codigo_solicitud": _codigo_solicitud(str(solicitud.id)),
                "estado_servicio": str(row.estado or solicitud.estado or "pendiente"),
                "cliente_nombre": (
                    solicitud.cliente.usuario.nombre
                    if solicitud.cliente and solicitud.cliente.usuario
                    else None
                ),
                "vehiculo_placa": solicitud.vehiculo.placa if solicitud.vehiculo else None,
                "tipo_problema": (
                    solicitud.incidente.tipo
                    if solicitud.incidente and solicitud.incidente.tipo
                    else (solicitud.emergencia.tipo if solicitud.emergencia else None)
                ),
                "tecnico_nombre": tecnico.nombre,
            }
        )
    return out


def reportar_mi_ubicacion(
    db: Session,
    *,
    current_user: Usuario,
    asignacion_id: str,
    latitud: float,
    longitud: float,
) -> dict:
    if current_user.rol != "tecnico":
        raise HTTPException(status_code=403, detail="Solo técnico puede reportar ubicación")

    tecnico = _obtener_tecnico_de_usuario(db, current_user)
    asignacion = (
        db.query(Asignacion)
        .options(
            joinedload(Asignacion.solicitud).joinedload(Solicitud.emergencia),
            joinedload(Asignacion.solicitud).joinedload(Solicitud.cliente),
        )
        .filter(Asignacion.id == asignacion_id)
        .first()
    )
    if not asignacion:
        raise HTTPException(status_code=404, detail="Asignación no encontrada")
    if str(asignacion.tecnico_id or "") != str(tecnico.id):
        raise HTTPException(status_code=403, detail="No autorizado para esta asignación")

    estado = _estado_key(asignacion.estado)
    if estado not in ESTADOS_COMPARTIR_UBICACION:
        raise HTTPException(
            status_code=400,
            detail="Solo puedes compartir ubicación en estados tecnico_asignado, en_camino o en_proceso",
        )

    solicitud = asignacion.solicitud
    if not solicitud or not solicitud.emergencia:
        raise HTTPException(status_code=400, detail="La asignación no está vinculada a una emergencia válida")

    ahora = local_now_naive()
    db.add(
        Ubicacion(
            id=uuid.uuid4(),
            emergencia_id=solicitud.emergencia.id,
            tecnico_id=tecnico.id,
            asignacion_id=asignacion.id,
            incidente_id=solicitud.incidente_id,
            latitud=float(latitud),
            longitud=float(longitud),
            fuente="tecnico_web",
            tipo="tecnico",
            registrado_en=ahora,
        )
    )

    tecnico.latitud_actual = float(latitud)
    tecnico.longitud_actual = float(longitud)
    tecnico.lat_actual = float(latitud)
    tecnico.lng_actual = float(longitud)
    tecnico.ultima_actualizacion_ubicacion = ahora
    if _estado_key(asignacion.estado) == "en_camino":
        tecnico.estado_operativo = "en_camino"
        tecnico.disponible = False
        if solicitud.cliente:
            db.add(
                Notificacion(
                    id=uuid.uuid4(),
                    usuario_id=solicitud.cliente.usuario_id,
                    solicitud_id=solicitud.id,
                    incidente_id=solicitud.incidente_id,
                    titulo="Técnico en seguimiento",
                    mensaje=f"El técnico {tecnico.nombre} está compartiendo ubicación en tiempo real.",
                    tipo="seguimiento_tecnico",
                    estado="no_leida",
                )
            )

    db.add(tecnico)
    db.commit()
    return {
        "mensaje": "Ubicación enviada correctamente",
        "estado_servicio": asignacion.estado or "tecnico_asignado",
        "ultima_actualizacion": ahora.isoformat(),
    }

