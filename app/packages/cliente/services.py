from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.models import Cliente, Evaluacion, Pago, Solicitud, Turno, Usuario

from .repository import crear_vehiculo, get_vehiculo_by_placa, listar_vehiculos_de_usuario


def registrar_vehiculo(
    db: Session,
    *,
    current_user: Usuario,
    placa: str,
    marca: str | None,
    modelo: str | None,
    anio: int | None,
    color: str | None,
):
    if current_user.rol not in {"conductor", "admin"}:
        raise HTTPException(status_code=403, detail="Solo cliente/admin puede registrar vehiculos")

    if get_vehiculo_by_placa(db, placa):
        raise HTTPException(status_code=400, detail="La placa ya esta registrada")

    return crear_vehiculo(
        db,
        usuario=current_user,
        placa=placa,
        marca=marca,
        modelo=modelo,
        anio=anio,
        color=color,
    )


def mis_vehiculos(db: Session, *, current_user: Usuario):
    return listar_vehiculos_de_usuario(db, usuario=current_user)


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
        "lat": tecnico.lat_actual,
        "lng": tecnico.lng_actual,
        "estado": str(solicitud.estado),
        "mensaje": "Ubicación de técnico obtenida",
    }

def evaluar_servicio_cliente(
    db: Session,
    *,
    incidente_id: str,
    current_user: Usuario,
    estrellas: int,
    comentario: str | None,
) -> Evaluacion:
    solicitud = consultar_estado_solicitud_cliente(
        db,
        incidente_id=incidente_id,
        current_user=current_user,
    )

    if solicitud.estado not in {"completado", "pagado", "finalizado"}:
        raise HTTPException(
            status_code=400,
            detail="Solo puedes evaluar servicios completados o pagados",
        )

    existente = (
        db.query(Evaluacion)
        .filter(Evaluacion.solicitud_id == solicitud.id)
        .first()
    )

    if existente:
        raise HTTPException(status_code=400, detail="Ya evaluaste este servicio")

    evaluacion = Evaluacion(
        solicitud_id=solicitud.id,
        estrellas=estrellas,
        comentario=comentario,
    )

    db.add(evaluacion)
    db.commit()
    db.refresh(evaluacion)
    return evaluacion


def listar_historial_servicios_cliente(db: Session, *, current_user: Usuario) -> list[dict]:
    solicitudes = (
        db.query(Solicitud)
        .join(Cliente, Solicitud.cliente_id == Cliente.id)
        .filter(Cliente.usuario_id == current_user.id)
        .order_by(Solicitud.creado_en.desc())
        .all()
    )

    historial = []

    for solicitud in solicitudes:
        asignacion = solicitud.asignaciones[-1] if solicitud.asignaciones else None
        evaluacion = solicitud.evaluaciones[-1] if solicitud.evaluaciones else None
        cotizacion = solicitud.cotizaciones[-1] if solicitud.cotizaciones else None
        pago = None

        if cotizacion and cotizacion.pago_id:
            pago = db.query(Pago).filter(Pago.id == cotizacion.pago_id).first()

        vehiculo_nombre = None
        if solicitud.vehiculo:
            partes = [solicitud.vehiculo.marca, solicitud.vehiculo.modelo]
            vehiculo_nombre = " ".join([p for p in partes if p]) or None

        historial.append(
            {
                "incidente_id": str(solicitud.id),
                "codigo_solicitud": _codigo_solicitud(solicitud),
                "estado": str(solicitud.estado),
                "tipo": str(solicitud.emergencia.tipo) if solicitud.emergencia else None,
                "prioridad": solicitud.prioridad,
                "vehiculo_placa": solicitud.vehiculo.placa if solicitud.vehiculo else None,
                "vehiculo": vehiculo_nombre,
                "taller_nombre": asignacion.taller.nombre if asignacion and asignacion.taller else None,
                "tecnico_nombre": asignacion.tecnico.nombre if asignacion and asignacion.tecnico else None,
                "monto_pagado": float(pago.monto) if pago else None,
                "pago_estado": pago.estado if pago else None,
                "calificacion": evaluacion.estrellas if evaluacion else None,
                "comentario_evaluacion": evaluacion.comentario if evaluacion else None,
                "creado_en": solicitud.creado_en,
                "actualizado_en": solicitud.actualizado_en,
            }
        )

    return historial
