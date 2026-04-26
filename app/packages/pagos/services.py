import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.time import local_now_naive
from app.models.models import (
    Asignacion,
    Cliente,
    Cotizacion,
    Historial,
    Notificacion,
    Pago,
    Solicitud,
    Taller,
    Usuario,
)

from .schemas import CotizacionDecisionOut, CotizacionOut, PagosDemoOut


def estado_paquete_pagos() -> PagosDemoOut:
    return PagosDemoOut(mensaje="Paquete pagos operativo")


def _resolver_solicitud(db: Session, incidente_id: str) -> Solicitud | None:
    solicitud = db.query(Solicitud).filter(Solicitud.id == incidente_id).first()
    if solicitud:
        return solicitud
    return db.query(Solicitud).filter(Solicitud.incidente_id == incidente_id).first()


def _codigo_visible(prefix: str, value: str) -> str:
    try:
        raw = int(uuid.UUID(str(value)))
        return f"{prefix}-{str(raw % 1_000_000).zfill(6)}"
    except Exception:
        return f"{prefix}-{str(value).split('-')[0].upper()}"


def _ultimo_asignacion(solicitud: Solicitud) -> Asignacion | None:
    if not solicitud.asignaciones:
        return None
    return sorted(
        solicitud.asignaciones,
        key=lambda x: (x.fecha_asignacion or x.asignado_en or datetime.min),
    )[-1]


def _resolver_taller_usuario(db: Session, current_user: Usuario) -> Taller | None:
    return db.query(Taller).filter(Taller.usuario_id == current_user.id).first()


def _serializar_cotizacion(c: Cotizacion) -> CotizacionOut:
    solicitud = c.solicitud
    cliente_nombre = None
    vehiculo_placa = None
    tipo_problema = None
    codigo_solicitud = None
    if solicitud:
        codigo_solicitud = f"SOL-{str(solicitud.id).split('-')[0].upper()}"
        if solicitud.cliente and solicitud.cliente.usuario:
            cliente_nombre = solicitud.cliente.usuario.nombre
        if solicitud.vehiculo:
            vehiculo_placa = solicitud.vehiculo.placa
        if solicitud.incidente and solicitud.incidente.tipo:
            tipo_problema = solicitud.incidente.tipo
        elif solicitud.emergencia and solicitud.emergencia.tipo:
            tipo_problema = solicitud.emergencia.tipo

    return CotizacionOut(
        id=str(c.id),
        incidente_id=str(c.incidente_id) if c.incidente_id else None,
        solicitud_id=str(c.solicitud_id) if c.solicitud_id else None,
        asignacion_id=str(c.asignacion_id) if c.asignacion_id else None,
        taller_id=str(c.taller_id) if c.taller_id else None,
        cliente_id=str(c.cliente_id) if c.cliente_id else None,
        monto_total=float(c.monto),
        detalle=c.detalle,
        observaciones=c.observaciones,
        estado=str(c.estado),
        fecha_emision=c.fecha_emision.isoformat() if c.fecha_emision else None,
        validez_hasta=c.validez_hasta.isoformat() if c.validez_hasta else None,
        fecha_respuesta_cliente=(
            c.fecha_respuesta_cliente.isoformat() if c.fecha_respuesta_cliente else None
        ),
        codigo_solicitud=codigo_solicitud,
        cliente_nombre=cliente_nombre,
        vehiculo_placa=vehiculo_placa,
        tipo_problema=tipo_problema,
    )


def _serializar_pago(pago: Pago, *, cotizacion_id: str, mensaje: str | None = None) -> dict:
    return {
        "id": str(pago.id),
        "codigo_visible": _codigo_visible("PAG", str(pago.id)),
        "cotizacion_id": cotizacion_id,
        "incidente_id": str(pago.incidente_id) if pago.incidente_id else None,
        "estado": str(pago.estado),
        "metodo_pago": pago.metodo,
        "monto_total": float(pago.monto),
        "comision_plataforma": float(pago.comision_plataforma) if pago.comision_plataforma is not None else None,
        "monto_taller": float(pago.monto_taller) if pago.monto_taller is not None else None,
        "comprobante_url": pago.comprobante_url,
        "referencia": pago.referencia,
        "fecha_pago": pago.pagado_en.isoformat() if pago.pagado_en else None,
        "fecha_verificacion": pago.fecha_verificacion.isoformat() if pago.fecha_verificacion else None,
        "mensaje": mensaje,
    }


def _agregar_historial(db: Session, solicitud: Solicitud, estado_nuevo: str, comentario: str | None) -> None:
    db.add(
        Historial(
            id=uuid.uuid4(),
            solicitud_id=solicitud.id,
            incidente_id=solicitud.incidente_id,
            estado_anterior=solicitud.estado,
            estado_nuevo=estado_nuevo,
            comentario=comentario,
        )
    )
    solicitud.estado = estado_nuevo
    if solicitud.incidente:
        solicitud.incidente.estado = estado_nuevo
    if solicitud.emergencia:
        solicitud.emergencia.estado = estado_nuevo


def _notificar(db: Session, *, usuario_id, solicitud: Solicitud, titulo: str, mensaje: str, tipo: str) -> None:
    db.add(
        Notificacion(
            id=uuid.uuid4(),
            usuario_id=usuario_id,
            solicitud_id=solicitud.id,
            incidente_id=solicitud.incidente_id,
            titulo=titulo,
            mensaje=mensaje,
            tipo=tipo,
            estado="no_leida",
        )
    )


def generar_cotizacion_taller(
    db: Session,
    *,
    current_user: Usuario,
    incidente_id: str,
    monto_total: float,
    detalle: str,
    observaciones: str | None,
    validez_hasta: str | None,
) -> Cotizacion:
    if current_user.rol != "taller":
        raise HTTPException(status_code=403, detail="Solo taller puede generar cotización")

    solicitud = _resolver_solicitud(db, incidente_id)
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    mi_taller = _resolver_taller_usuario(db, current_user)
    if not mi_taller:
        raise HTTPException(status_code=403, detail="El usuario no tiene perfil de taller")

    asig = _ultimo_asignacion(solicitud)
    if not asig or not asig.taller_id or str(asig.taller_id) != str(mi_taller.id):
        raise HTTPException(status_code=403, detail="La solicitud no pertenece a tu taller")

    estado_asig = (asig.estado or "").strip().lower()
    if estado_asig not in {"en_diagnostico", "diagnostico_completado", "en_proceso", "tecnico_asignado"}:
        raise HTTPException(
            status_code=400,
            detail="Solo se puede generar cotización después del diagnóstico",
        )

    validez_dt = None
    if (validez_hasta or "").strip():
        try:
            validez_dt = datetime.fromisoformat(validez_hasta.strip())
        except ValueError:
            raise HTTPException(status_code=400, detail="validez_hasta debe estar en formato ISO")

    cot = Cotizacion(
        id=uuid.uuid4(),
        solicitud_id=solicitud.id,
        incidente_id=solicitud.incidente_id,
        asignacion_id=asig.id,
        taller_id=mi_taller.id,
        cliente_id=solicitud.cliente_id,
        monto=float(monto_total),
        detalle=detalle.strip(),
        observaciones=(observaciones or "").strip() or None,
        estado="emitida",
        fecha_emision=local_now_naive(),
        validez_hasta=validez_dt,
        creado_en=local_now_naive(),
        actualizado_en=local_now_naive(),
    )
    db.add(cot)

    _agregar_historial(
        db,
        solicitud,
        "cotizacion_emitida",
        f"Cotización emitida por taller {mi_taller.nombre}",
    )

    if solicitud.cliente:
        _notificar(
            db,
            usuario_id=solicitud.cliente.usuario_id,
            solicitud=solicitud,
            titulo="Nueva cotización",
            mensaje="Tu solicitud tiene una cotización pendiente de respuesta",
            tipo="cotizacion_emitida",
        )

    db.commit()
    db.refresh(cot)
    return cot


def obtener_cotizacion_cliente(
    db: Session,
    *,
    cotizacion_id: str,
    current_user: Usuario,
) -> Cotizacion:
    if current_user.rol not in {"cliente", "conductor", "admin"}:
        raise HTTPException(status_code=403, detail="Solo cliente/admin puede consultar cotización")

    cot = db.query(Cotizacion).filter(Cotizacion.id == cotizacion_id).first()
    if not cot:
        raise HTTPException(status_code=404, detail="Cotización no encontrada")

    if current_user.rol != "admin":
        cli = db.query(Cliente).filter(Cliente.usuario_id == current_user.id).first()
        if not cli or str(cot.cliente_id or "") != str(cli.id):
            raise HTTPException(status_code=403, detail="No autorizado para esta cotización")

    return cot


def listar_cotizaciones_taller(
    db: Session,
    *,
    current_user: Usuario,
    estado: str | None = None,
) -> list[Cotizacion]:
    if current_user.rol not in {"taller", "admin"}:
        raise HTTPException(status_code=403, detail="Solo taller/admin puede consultar cotizaciones del taller")

    query = db.query(Cotizacion)
    if current_user.rol == "taller":
        taller = _resolver_taller_usuario(db, current_user)
        if not taller:
            raise HTTPException(status_code=403, detail="El usuario no tiene perfil de taller")
        query = query.filter(Cotizacion.taller_id == taller.id)

    if (estado or "").strip():
        query = query.filter(Cotizacion.estado == estado.strip().lower())

    return query.order_by(Cotizacion.creado_en.desc()).all()


def responder_cotizacion_cliente(
    db: Session,
    *,
    cotizacion_id: str,
    current_user: Usuario,
    aceptar: bool,
    observaciones: str | None,
) -> CotizacionDecisionOut:
    if current_user.rol not in {"cliente", "conductor"}:
        raise HTTPException(status_code=403, detail="Solo cliente puede responder cotización")

    cot = db.query(Cotizacion).filter(Cotizacion.id == cotizacion_id).first()
    if not cot:
        raise HTTPException(status_code=404, detail="Cotización no encontrada")

    cli = db.query(Cliente).filter(Cliente.usuario_id == current_user.id).first()
    if not cli or str(cot.cliente_id or "") != str(cli.id):
        raise HTTPException(status_code=403, detail="No autorizado para responder esta cotización")

    if (cot.estado or "").lower() not in {"emitida", "pendiente", "enviada"}:
        raise HTTPException(status_code=409, detail="La cotización ya fue respondida")

    solicitud = db.query(Solicitud).filter(Solicitud.id == cot.solicitud_id).first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud asociada no encontrada")

    cot.estado = "aceptada" if aceptar else "rechazada"
    cot.observaciones = ((cot.observaciones or "") + ("\n" if cot.observaciones and observaciones else "") + (observaciones or "")).strip() or cot.observaciones
    cot.fecha_respuesta_cliente = local_now_naive()
    cot.actualizado_en = local_now_naive()

    nuevo_estado = "cotizacion_aceptada" if aceptar else "cotizacion_rechazada"
    _agregar_historial(
        db,
        solicitud,
        nuevo_estado,
        "Cliente aceptó cotización" if aceptar else "Cliente rechazó cotización",
    )

    if cot.taller and cot.taller.usuario_id:
        _notificar(
            db,
            usuario_id=cot.taller.usuario_id,
            solicitud=solicitud,
            titulo="Respuesta a cotización",
            mensaje="El cliente aceptó la cotización" if aceptar else "El cliente rechazó la cotización",
            tipo="cotizacion_aceptada" if aceptar else "cotizacion_rechazada",
        )

    db.commit()

    return CotizacionDecisionOut(
        cotizacion_id=str(cot.id),
        estado_cotizacion=str(cot.estado),
        incidente_id=str(solicitud.incidente_id) if solicitud.incidente_id else None,
        estado_incidente=(str(solicitud.incidente.estado) if solicitud.incidente else None),
        estado_solicitud=str(solicitud.estado),
        mensaje="Cotización aceptada correctamente" if aceptar else "Cotización rechazada correctamente",
    )


def cotizacion_out(cot: Cotizacion) -> CotizacionOut:
    return _serializar_cotizacion(cot)


def procesar_pago_cliente(
    db: Session,
    *,
    current_user: Usuario,
    cotizacion_id: str,
    metodo_pago: str,
    comprobante_url: str | None,
    referencia: str | None,
) -> dict:
    if current_user.rol not in {"cliente", "conductor"}:
        raise HTTPException(status_code=403, detail="Solo cliente puede procesar pago")

    cot = db.query(Cotizacion).filter(Cotizacion.id == cotizacion_id).first()
    if not cot:
        raise HTTPException(status_code=404, detail="Cotización no encontrada")

    cli = db.query(Cliente).filter(Cliente.usuario_id == current_user.id).first()
    if not cli or str(cot.cliente_id or "") != str(cli.id):
        raise HTTPException(status_code=403, detail="No autorizado para pagar esta cotización")

    if (cot.estado or "").lower() not in {"aceptada", "cotizacion_aceptada"}:
        raise HTTPException(status_code=400, detail="La cotización debe estar aceptada para procesar pago")

    solicitud = db.query(Solicitud).filter(Solicitud.id == cot.solicitud_id).first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud asociada no encontrada")

    metodo = (metodo_pago or "").strip().lower()
    if metodo not in {"qr", "transferencia", "efectivo"}:
        raise HTTPException(status_code=400, detail="Método de pago no válido")

    comision = round(float(cot.monto) * 0.10, 2)
    monto_taller = round(float(cot.monto) - comision, 2)
    estado_pago = "pendiente_verificacion" if metodo in {"qr", "transferencia"} else "pagado"

    pago = cot.pago
    if not pago:
        pago = Pago(
            id=uuid.uuid4(),
            monto=float(cot.monto),
            estado=estado_pago,
            metodo=metodo,
            incidente_id=cot.incidente_id,
            cliente_id=cot.cliente_id,
            taller_id=cot.taller_id,
            comprobante_url=(comprobante_url or "").strip() or None,
            referencia=(referencia or "").strip() or None,
            comision_plataforma=comision,
            monto_taller=monto_taller,
            pagado_en=local_now_naive(),
            fecha_verificacion=local_now_naive() if estado_pago == "pagado" else None,
            verificado_por=current_user.id if estado_pago == "pagado" else None,
        )
        db.add(pago)
        db.flush()
        cot.pago_id = pago.id
    else:
        pago.metodo = metodo
        pago.estado = estado_pago
        pago.incidente_id = cot.incidente_id
        pago.cliente_id = cot.cliente_id
        pago.taller_id = cot.taller_id
        pago.comprobante_url = (comprobante_url or "").strip() or None
        pago.referencia = (referencia or "").strip() or None
        pago.comision_plataforma = comision
        pago.monto_taller = monto_taller
        pago.pagado_en = local_now_naive()
        pago.fecha_verificacion = local_now_naive() if estado_pago == "pagado" else None
        pago.verificado_por = current_user.id if estado_pago == "pagado" else None

    nuevo_estado = "pagado" if estado_pago == "pagado" else "esperando_pago"
    _agregar_historial(
        db,
        solicitud,
        nuevo_estado,
        "Pago confirmado" if estado_pago == "pagado" else "Pago pendiente de verificación",
    )
    if estado_pago == "pagado":
        _agregar_historial(
            db,
            solicitud,
            "finalizado",
            "Servicio finalizado por pago confirmado",
        )

    if cot.taller and cot.taller.usuario_id:
        _notificar(
            db,
            usuario_id=cot.taller.usuario_id,
            solicitud=solicitud,
            titulo="Actualización de pago",
            mensaje="El cliente registró pago pendiente de verificación" if estado_pago != "pagado" else "Pago confirmado del servicio",
            tipo="pago_pendiente" if estado_pago != "pagado" else "pago_confirmado",
        )

    db.commit()
    db.refresh(pago)
    return _serializar_pago(
        pago,
        cotizacion_id=str(cot.id),
        mensaje="Pago registrado correctamente" if estado_pago != "pagado" else "Pago procesado y servicio finalizado",
    )
