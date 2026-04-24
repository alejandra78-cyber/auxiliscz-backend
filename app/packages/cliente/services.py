from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.models import Cliente, Solicitud, Turno, Usuario

from .repository import (
    actualizar_vehiculo,
    crear_vehiculo,
    desactivar_vehiculo,
    get_vehiculo_by_placa,
    get_vehiculo_de_usuario_by_id,
    listar_vehiculos_de_usuario,
)


def _normalizar_placa(placa: str) -> str:
    return (placa or "").strip().upper()


def _validar_placa(placa: str) -> None:
    if not placa:
        raise HTTPException(status_code=400, detail="La placa es obligatoria")
    if len(placa) < 5 or len(placa) > 20:
        raise HTTPException(status_code=400, detail="La placa debe tener entre 5 y 20 caracteres")


def _validar_anio(anio: int | None) -> None:
    if anio is None:
        return
    if anio < 1950 or anio > 2100:
        raise HTTPException(status_code=400, detail="El año del vehículo es inválido")


def _validar_identidad_cliente(current_user: Usuario) -> None:
    if current_user.rol not in {"conductor", "cliente", "admin"}:
        raise HTTPException(status_code=403, detail="Solo cliente/admin puede gestionar vehículos")


def registrar_vehiculo(
    db: Session,
    *,
    current_user: Usuario,
    placa: str,
    marca: str | None,
    modelo: str | None,
    anio: int | None,
    color: str | None,
    tipo: str | None,
    observacion: str | None,
):
    _validar_identidad_cliente(current_user)

    placa_norm = _normalizar_placa(placa)
    _validar_placa(placa_norm)
    _validar_anio(anio)
    if not (marca or "").strip():
        raise HTTPException(status_code=400, detail="La marca es obligatoria")
    if not (modelo or "").strip():
        raise HTTPException(status_code=400, detail="El modelo es obligatorio")

    if get_vehiculo_by_placa(db, placa_norm):
        raise HTTPException(status_code=400, detail="La placa ya esta registrada")

    return crear_vehiculo(
        db,
        usuario=current_user,
        placa=placa_norm,
        marca=marca.strip(),
        modelo=modelo.strip(),
        anio=anio,
        color=(color or "").strip() or None,
        tipo=(tipo or "").strip() or None,
        observacion=(observacion or "").strip() or None,
    )


def mis_vehiculos(db: Session, *, current_user: Usuario):
    _validar_identidad_cliente(current_user)
    return listar_vehiculos_de_usuario(db, usuario=current_user)


def editar_vehiculo_cliente(
    db: Session,
    *,
    current_user: Usuario,
    vehiculo_id: str,
    marca: str,
    modelo: str,
    anio: int | None,
    color: str | None,
    tipo: str | None,
    observacion: str | None,
):
    _validar_identidad_cliente(current_user)
    _validar_anio(anio)
    if not (marca or "").strip():
        raise HTTPException(status_code=400, detail="La marca es obligatoria")
    if not (modelo or "").strip():
        raise HTTPException(status_code=400, detail="El modelo es obligatorio")
    vehiculo = get_vehiculo_de_usuario_by_id(db, usuario=current_user, vehiculo_id=vehiculo_id)
    if not vehiculo:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")
    return actualizar_vehiculo(
        db,
        vehiculo=vehiculo,
        marca=marca.strip(),
        modelo=modelo.strip(),
        anio=anio,
        color=(color or "").strip() or None,
        tipo=(tipo or "").strip() or None,
        observacion=(observacion or "").strip() or None,
    )


def desactivar_vehiculo_cliente(db: Session, *, current_user: Usuario, vehiculo_id: str):
    _validar_identidad_cliente(current_user)
    vehiculo = get_vehiculo_de_usuario_by_id(db, usuario=current_user, vehiculo_id=vehiculo_id)
    if not vehiculo:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")
    return desactivar_vehiculo(db, vehiculo=vehiculo)


def consultar_estado_solicitud_cliente(db: Session, *, incidente_id: str, current_user: Usuario):
    solicitud = db.query(Solicitud).filter(Solicitud.id == incidente_id).first()
    if not solicitud:
        solicitud = db.query(Solicitud).filter(Solicitud.incidente_id == incidente_id).first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if (not solicitud.cliente or str(solicitud.cliente.usuario_id) != str(current_user.id)) and current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="No autorizado")
    return solicitud


def _codigo_solicitud(solicitud: Solicitud) -> str:
    return f"SOL-{str(solicitud.id).split('-')[0].upper()}"


def consultar_estado_ultima_solicitud_cliente(db: Session, *, current_user: Usuario):
    solicitud = (
        db.query(Solicitud)
        .join(Cliente, Solicitud.cliente_id == Cliente.id)
        .filter(Cliente.usuario_id == current_user.id)
        .order_by(Solicitud.creado_en.desc())
        .first()
    )
    if not solicitud:
        raise HTTPException(status_code=404, detail="No tienes solicitudes registradas")
    return solicitud


def listar_solicitudes_para_seguimiento(db: Session, *, current_user: Usuario) -> list[Solicitud]:
    return (
        db.query(Solicitud)
        .join(Cliente, Solicitud.cliente_id == Cliente.id)
        .filter(Cliente.usuario_id == current_user.id)
        .order_by(Solicitud.creado_en.desc())
        .all()
    )


def ver_ubicacion_tecnico(db: Session, *, incidente_id: str, current_user: Usuario) -> dict:
    solicitud = db.query(Solicitud).filter(Solicitud.id == incidente_id).first()
    if not solicitud:
        solicitud = db.query(Solicitud).filter(Solicitud.incidente_id == incidente_id).first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if (not solicitud.cliente or str(solicitud.cliente.usuario_id) != str(current_user.id)) and current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="No autorizado")
    if solicitud.estado not in {"asignada", "en_proceso"}:
        return {
            "incidente_id": str(solicitud.id),
            "codigo_solicitud": _codigo_solicitud(solicitud),
            "tecnico_id": None,
            "tecnico_nombre": None,
            "especialidad": None,
            "lat": None,
            "lng": None,
            "estado": str(solicitud.estado),
            "mensaje": "La ubicación solo está disponible cuando el servicio está asignado o en proceso",
        }

    if not solicitud.asignaciones:
        return {
            "incidente_id": str(solicitud.id),
            "codigo_solicitud": _codigo_solicitud(solicitud),
            "tecnico_id": None,
            "tecnico_nombre": None,
            "especialidad": None,
            "lat": None,
            "lng": None,
            "estado": str(solicitud.estado),
            "mensaje": "Aún no hay técnico asignado",
        }
    asig = solicitud.asignaciones[-1]
    tecnico = asig.tecnico

    if not tecnico:
        return {
            "incidente_id": str(solicitud.id),
            "codigo_solicitud": _codigo_solicitud(solicitud),
            "tecnico_id": None,
            "tecnico_nombre": None,
            "especialidad": None,
            "lat": None,
            "lng": None,
            "estado": str(solicitud.estado),
            "mensaje": "Aún no hay técnico asignado",
        }
    turno = (
        db.query(Turno)
        .filter(Turno.tecnico_id == tecnico.id)
        .order_by(Turno.inicio.desc())
        .first()
    )
    return {
        "incidente_id": str(solicitud.id),
        "codigo_solicitud": _codigo_solicitud(solicitud),
        "tecnico_id": str(tecnico.id),
        "tecnico_nombre": tecnico.nombre,
        "especialidad": turno.especialidad if turno else None,
        "lat": tecnico.latitud_actual if tecnico.latitud_actual is not None else tecnico.lat_actual,
        "lng": tecnico.longitud_actual if tecnico.longitud_actual is not None else tecnico.lng_actual,
        "estado": str(solicitud.estado),
        "mensaje": "Ubicación de técnico obtenida",
    }
