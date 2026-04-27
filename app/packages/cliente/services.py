from fastapi import HTTPException
from sqlalchemy.orm import Session

import uuid

from app.models.models import Asignacion, Cliente, Evaluacion, Pago, Solicitud, TrabajoCompletado, Ubicacion, Usuario
from app.packages.emergencia.services import cancelar_solicitud as cancelar_solicitud_emergencia

CANCELABLE_STATES = {
    "pendiente",
    "buscando_taller",
    "pendiente_asignacion",
    "en_revision",
    "en_evaluacion",
    "asignado",
    "pendiente_respuesta",
    "pendiente_respuesta_taller",
    "aceptada",
    "tecnico_asignado",
    "en_camino",
}

EVALUABLE_STATES = {"finalizado", "pagado", "servicio_completado", "completada", "completado"}

from .repository import (
    actualizar_vehiculo,
    crear_vehiculo,
    desactivar_vehiculo,
    get_vehiculo_by_placa,
    get_vehiculo_de_usuario_by_id,
    listar_vehiculos_de_usuario,
)


def _estado_key(value: str | None) -> str:
    return (value or "").strip().lower().replace(" ", "_")


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
    if not solicitud.asignaciones:
        return {
            "incidente_id": str(solicitud.id),
            "codigo_solicitud": _codigo_solicitud(solicitud),
            "tecnico_nombre": None,
            "estado_servicio": str(solicitud.estado),
            "latitud_tecnico": None,
            "longitud_tecnico": None,
            "latitud_cliente": None,
            "longitud_cliente": None,
            "ultima_actualizacion": None,
            "mensaje": "Aún no hay técnico asignado",
        }

    asignacion = (
        db.query(Asignacion)
        .filter(Asignacion.solicitud_id == solicitud.id)
        .order_by(Asignacion.fecha_asignacion.desc().nullslast(), Asignacion.asignado_en.desc().nullslast())
        .first()
    )
    if not asignacion or not asignacion.tecnico:
        return {
            "incidente_id": str(solicitud.id),
            "codigo_solicitud": _codigo_solicitud(solicitud),
            "tecnico_nombre": None,
            "estado_servicio": str(asignacion.estado if asignacion else solicitud.estado),
            "latitud_tecnico": None,
            "longitud_tecnico": None,
            "latitud_cliente": None,
            "longitud_cliente": None,
            "ultima_actualizacion": None,
            "mensaje": "Aún no hay técnico asignado",
        }

    estado_servicio = _estado_key(asignacion.estado or solicitud.estado)
    if estado_servicio not in {"tecnico_asignado", "en_camino", "en_proceso"}:
        return {
            "incidente_id": str(solicitud.id),
            "codigo_solicitud": _codigo_solicitud(solicitud),
            "tecnico_nombre": asignacion.tecnico.nombre,
            "estado_servicio": str(asignacion.estado or solicitud.estado),
            "latitud_tecnico": None,
            "longitud_tecnico": None,
            "latitud_cliente": None,
            "longitud_cliente": None,
            "ultima_actualizacion": None,
            "mensaje": "El técnico aún no inició el seguimiento.",
        }

    ultima_ubicacion = (
        db.query(Ubicacion)
        .filter(Ubicacion.tecnico_id == asignacion.tecnico_id)
        .filter(Ubicacion.asignacion_id == asignacion.id)
        .order_by(Ubicacion.registrado_en.desc())
        .first()
    )
    if not ultima_ubicacion:
        ultima_ubicacion = (
            db.query(Ubicacion)
            .filter(Ubicacion.tecnico_id == asignacion.tecnico_id)
            .filter(Ubicacion.incidente_id == solicitud.incidente_id)
            .order_by(Ubicacion.registrado_en.desc())
            .first()
        )

    lat_cliente = None
    lng_cliente = None
    if solicitud.incidente and solicitud.incidente.latitud is not None and solicitud.incidente.longitud is not None:
        lat_cliente = solicitud.incidente.latitud
        lng_cliente = solicitud.incidente.longitud
    elif solicitud.emergencia and solicitud.emergencia.ubicaciones:
        ubic = sorted(
            solicitud.emergencia.ubicaciones,
            key=lambda x: x.registrado_en or x.id,
            reverse=True,
        )[0]
        lat_cliente = ubic.latitud
        lng_cliente = ubic.longitud

    return {
        "incidente_id": str(solicitud.id),
        "codigo_solicitud": _codigo_solicitud(solicitud),
        "tecnico_nombre": asignacion.tecnico.nombre,
        "estado_servicio": str(asignacion.estado or solicitud.estado),
        "latitud_tecnico": ultima_ubicacion.latitud if ultima_ubicacion else None,
        "longitud_tecnico": ultima_ubicacion.longitud if ultima_ubicacion else None,
        "latitud_cliente": lat_cliente,
        "longitud_cliente": lng_cliente,
        "ultima_actualizacion": (
            ultima_ubicacion.registrado_en.isoformat() if ultima_ubicacion and ultima_ubicacion.registrado_en else None
        ),
        "mensaje": (
            "Ubicación del técnico obtenida"
            if ultima_ubicacion
            else "El técnico aún no inició el seguimiento."
        ),
    }


def _resolver_acciones_disponibles(solicitud: Solicitud) -> dict:
    estado_key = _estado_key(solicitud.estado)
    tiene_tecnico = False
    if solicitud.asignaciones:
        ultima = solicitud.asignaciones[-1]
        tiene_tecnico = ultima.tecnico_id is not None

    cotizacion = solicitud.cotizaciones[-1] if solicitud.cotizaciones else None
    pago = cotizacion.pago if cotizacion and cotizacion.pago else None
    estado_cot = _estado_key(cotizacion.estado) if cotizacion else ""

    puede_ver_cotizacion = cotizacion is not None
    puede_responder_cotizacion = bool(cotizacion and estado_cot in {"emitida", "pendiente", "enviada"})
    puede_pagar = bool(
        cotizacion
        and estado_key in {"trabajo_completado", "esperando_pago"}
        and (pago is None or _estado_key(pago.estado) in {"pendiente", "pendiente_pago", "pendiente_verificacion"})
    )
    puede_evaluar = estado_key in {"finalizado", "servicio_completado", "pagado"}

    return {
        "puede_cancelar": estado_key in CANCELABLE_STATES,
        "puede_ver_tecnico": tiene_tecnico and estado_key in {"tecnico_asignado", "en_camino", "en_proceso"},
        "puede_ver_cotizacion": puede_ver_cotizacion,
        "puede_responder_cotizacion": puede_responder_cotizacion,
        "puede_pagar": puede_pagar,
        "puede_evaluar_servicio": puede_evaluar,
    }


def _serializar_vehiculo(solicitud: Solicitud) -> dict | None:
    vehiculo = solicitud.vehiculo
    if not vehiculo:
        return None
    return {
        "id": str(vehiculo.id),
        "placa": vehiculo.placa,
        "marca": vehiculo.marca,
        "modelo": vehiculo.modelo,
        "color": vehiculo.color,
        "tipo": vehiculo.tipo,
    }


def _serializar_taller_tecnico(solicitud: Solicitud) -> tuple[dict | None, dict | None]:
    if not solicitud.asignaciones:
        return None, None
    asig = solicitud.asignaciones[-1]
    taller = None
    tecnico = None
    if asig.taller:
        taller = {
            "id": str(asig.taller.id),
            "nombre": asig.taller.nombre,
            "estado": asig.estado,
        }
    if asig.tecnico:
        tecnico = {
            "id": str(asig.tecnico.id),
            "nombre": asig.tecnico.nombre,
            "estado": asig.tecnico.estado_operativo,
        }
    return taller, tecnico


def _serializar_ubicacion(solicitud: Solicitud) -> dict | None:
    if solicitud.incidente and solicitud.incidente.latitud is not None and solicitud.incidente.longitud is not None:
        return {
            "latitud": solicitud.incidente.latitud,
            "longitud": solicitud.incidente.longitud,
        }
    if solicitud.emergencia and solicitud.emergencia.ubicaciones:
        last = solicitud.emergencia.ubicaciones[-1]
        return {
            "latitud": last.latitud,
            "longitud": last.longitud,
        }
    return None


def _serializar_cotizacion_pago(solicitud: Solicitud) -> tuple[dict | None, dict | None]:
    cotizacion = solicitud.cotizaciones[-1] if solicitud.cotizaciones else None
    if not cotizacion:
        return None, None
    cot = {
        "id": str(cotizacion.id),
        "monto": cotizacion.monto,
        "estado": cotizacion.estado,
        "detalle": cotizacion.detalle,
        "observaciones": cotizacion.observaciones,
        "validez_hasta": cotizacion.validez_hasta.isoformat() if cotizacion.validez_hasta else None,
        "fecha_respuesta_cliente": (
            cotizacion.fecha_respuesta_cliente.isoformat() if cotizacion.fecha_respuesta_cliente else None
        ),
        "creado_en": cotizacion.creado_en.isoformat() if cotizacion.creado_en else None,
    }
    pago: Pago | None = cotizacion.pago
    if not pago:
        return cot, None
    return cot, {
        "id": str(pago.id),
        "estado": pago.estado,
        "monto": cotizacion.monto,
        "metodo": pago.metodo,
        "pagado_en": pago.pagado_en.isoformat() if pago.pagado_en else None,
    }


def _resolver_resumen_ia(solicitud: Solicitud) -> str | None:
    if solicitud.incidente and (solicitud.incidente.resumen_ia or "").strip():
        return solicitud.incidente.resumen_ia
    for link in reversed(getattr(solicitud, "evidencias", []) or []):
        evidencia = getattr(link, "evidencia", None)
        if not evidencia:
            continue
        if evidencia.tipo == "resumen_ia" and (evidencia.contenido_texto or evidencia.transcripcion):
            return evidencia.contenido_texto or evidencia.transcripcion
    return None


def listar_solicitudes_cliente(db: Session, *, current_user: Usuario) -> list[dict]:
    _validar_identidad_cliente(current_user)
    solicitudes = listar_solicitudes_para_seguimiento(db, current_user=current_user)
    rows: list[dict] = []
    for s in solicitudes:
        rows.append(
            {
                "incidente_id": str(s.id),
                "codigo_solicitud": _codigo_solicitud(s),
                "estado": str(s.estado),
                "prioridad": s.prioridad,
                "tipo": str(s.emergencia.tipo) if s.emergencia and s.emergencia.tipo else (s.incidente.tipo if s.incidente else None),
                "fecha_reporte": s.creado_en.isoformat() if s.creado_en else None,
                "vehiculo": _serializar_vehiculo(s),
                "acciones_disponibles": _resolver_acciones_disponibles(s),
            }
        )
    return rows


def obtener_detalle_solicitud_cliente(db: Session, *, incidente_id: str, current_user: Usuario) -> dict:
    solicitud = consultar_estado_solicitud_cliente(db, incidente_id=incidente_id, current_user=current_user)
    taller, tecnico = _serializar_taller_tecnico(solicitud)
    ubicacion = _serializar_ubicacion(solicitud)
    cotizacion, pago = _serializar_cotizacion_pago(solicitud)
    historial = [
        {
            "estado_anterior": h.estado_anterior,
            "estado_nuevo": h.estado_nuevo,
            "comentario": h.comentario,
            "creado_en": h.creado_en.isoformat() if h.creado_en else None,
        }
        for h in sorted(solicitud.historial, key=lambda x: x.creado_en.isoformat() if x.creado_en else "")
    ]

    return {
        "incidente_id": str(solicitud.id),
        "codigo_solicitud": _codigo_solicitud(solicitud),
        "estado": str(solicitud.estado),
        "prioridad": solicitud.prioridad,
        "tipo_problema": str(solicitud.emergencia.tipo) if solicitud.emergencia and solicitud.emergencia.tipo else (solicitud.incidente.tipo if solicitud.incidente else None),
        "fecha_reporte": solicitud.creado_en.isoformat() if solicitud.creado_en else None,
        "fecha_actualizacion": solicitud.actualizado_en.isoformat() if solicitud.actualizado_en else None,
        "resumen_ia": _resolver_resumen_ia(solicitud),
        "vehiculo": _serializar_vehiculo(solicitud),
        "ubicacion": ubicacion,
        "taller_asignado": taller,
        "tecnico_asignado": tecnico,
        "historial": historial,
        "cotizacion_actual": cotizacion,
        "pago_actual": pago,
        "acciones_disponibles": _resolver_acciones_disponibles(solicitud),
    }


def cancelar_solicitud_cliente(
    db: Session,
    *,
    incidente_id: str,
    current_user: Usuario,
    motivo_cancelacion: str | None = None,
) -> dict:
    _validar_identidad_cliente(current_user)
    solicitud = cancelar_solicitud_emergencia(
        db,
        incidente_id=incidente_id,
        current_user=current_user,
        motivo_cancelacion=motivo_cancelacion,
    )
    return {
        "incidente_id": str(solicitud.id),
        "estado": str(solicitud.estado),
        "mensaje": "Solicitud cancelada correctamente",
    }


def evaluar_servicio_cliente(
    db: Session,
    *,
    incidente_id: str,
    current_user: Usuario,
    calificacion: int,
    comentario: str | None,
) -> dict:
    _validar_identidad_cliente(current_user)
    solicitud = consultar_estado_solicitud_cliente(db, incidente_id=incidente_id, current_user=current_user)
    estado_key = _estado_key(solicitud.estado)
    if estado_key not in EVALUABLE_STATES:
        raise HTTPException(status_code=400, detail="Solo puedes evaluar servicios finalizados/pagados")

    existente = db.query(Evaluacion).filter(Evaluacion.solicitud_id == solicitud.id).first()
    if existente:
        raise HTTPException(status_code=409, detail="Esta solicitud ya tiene una evaluación registrada")

    row = Evaluacion(
        id=uuid.uuid4(),
        solicitud_id=solicitud.id,
        estrellas=int(calificacion),
        comentario=(comentario or "").strip() or None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "incidente_id": str(solicitud.id),
        "codigo_solicitud": _codigo_solicitud(solicitud),
        "calificacion": row.estrellas,
        "comentario": row.comentario,
        "creado_en": row.creado_en.isoformat() if row.creado_en else None,
        "mensaje": "Evaluación registrada correctamente",
    }


def historial_servicios_cliente(db: Session, *, current_user: Usuario) -> list[dict]:
    _validar_identidad_cliente(current_user)
    rows = (
        db.query(Solicitud)
        .join(Cliente, Solicitud.cliente_id == Cliente.id)
        .filter(Cliente.usuario_id == current_user.id)
        .filter(Solicitud.estado.in_(["finalizado", "pagado", "servicio_completado", "cancelado", "cancelada"]))
        .order_by(Solicitud.actualizado_en.desc().nullslast(), Solicitud.creado_en.desc())
        .all()
    )
    out: list[dict] = []
    for s in rows:
        taller, tecnico = _serializar_taller_tecnico(s)
        vehiculo = _serializar_vehiculo(s)
        cot, pago = _serializar_cotizacion_pago(s)
        evaluacion = s.evaluaciones[-1] if s.evaluaciones else None
        trabajo = s.trabajos_completados[-1] if getattr(s, "trabajos_completados", None) else None
        out.append(
            {
                "incidente_id": str(s.id),
                "codigo_solicitud": _codigo_solicitud(s),
                "estado_final": str(s.estado),
                "fecha": s.actualizado_en.isoformat() if s.actualizado_en else (s.creado_en.isoformat() if s.creado_en else None),
                "vehiculo": vehiculo,
                "tipo_problema": str(s.emergencia.tipo) if s.emergencia and s.emergencia.tipo else (s.incidente.tipo if s.incidente else None),
                "taller": taller,
                "tecnico": tecnico,
                "resumen_ia": _resolver_resumen_ia(s),
                "trabajo_realizado": trabajo.descripcion if trabajo else None,
                "monto_pagado": (pago.get("monto") if pago else (cot.get("monto") if cot else None)),
                "evaluacion": (
                    {
                        "calificacion": evaluacion.estrellas,
                        "comentario": evaluacion.comentario,
                        "creado_en": evaluacion.creado_en.isoformat() if evaluacion.creado_en else None,
                    }
                    if evaluacion
                    else None
                ),
            }
        )
    return out
