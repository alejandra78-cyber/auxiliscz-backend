import uuid
from datetime import datetime
import logging
import os

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.time import local_now_naive
from app.core.tenant import assert_same_tenant, stamp_tenant, tenant_id_from
from app.services.notificaciones import enviar_push_db
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

logger = logging.getLogger(__name__)


def _estado_pago_compatible(db: Session, estado_semantico: str) -> str:
    """
    Retorna un valor compatible con el enum real de pagos.estado.
    Soporta ambos esquemas:
    - nuevo: pendiente_verificacion/pagado
    - legacy: pendiente/completado
    """
    try:
        rows = db.execute(
            text(
                """
                SELECT e.enumlabel
                FROM pg_type t
                JOIN pg_enum e ON t.oid = e.enumtypid
                JOIN pg_namespace n ON n.oid = t.typnamespace
                WHERE n.nspname = 'public'
                  AND t.typname = 'estado_pago_enum'
                """
            )
        ).fetchall()
        permitidos = {str(r[0]) for r in rows}
    except Exception:
        permitidos = set()

    if estado_semantico in permitidos:
        return estado_semantico

    fallback = {
        "pendiente_verificacion": "pendiente",
        "pagado": "completado",
    }
    return fallback.get(estado_semantico, estado_semantico)


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


def _orden_asignacion(a: Asignacion):
    return (
        a.fecha_confirmacion or a.fecha_asignacion or a.asignado_en or datetime.min,
        str(a.id),
    )


def _asignacion_de_taller(solicitud: Solicitud | None, taller_id) -> Asignacion | None:
    if not solicitud or not taller_id:
        return None
    candidatas = [
        a
        for a in (solicitud.asignaciones or [])
        if a.taller_id and str(a.taller_id) == str(taller_id)
    ]
    if not candidatas:
        return None

    prioridad = {
        "confirmada": 4,
        "tecnico_asignado": 4,
        "en_camino": 4,
        "en_diagnostico": 4,
        "diagnostico_completado": 4,
        "en_proceso": 4,
        "cotizacion_enviada": 3,
        "aceptada_para_cotizar": 2,
        "pendiente_respuesta": 1,
    }
    return sorted(
        candidatas,
        key=lambda a: (
            10 if getattr(a, "es_definitiva", False) else 0,
            prioridad.get((a.estado or "").lower(), 0),
            *_orden_asignacion(a),
        ),
    )[-1]


def _asignacion_de_cotizacion(cot: Cotizacion, solicitud: Solicitud | None = None) -> Asignacion | None:
    if cot.asignacion and (not cot.taller_id or str(cot.asignacion.taller_id or "") == str(cot.taller_id)):
        return cot.asignacion
    solicitud = solicitud or cot.solicitud
    return _asignacion_de_taller(solicitud, cot.taller_id)


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

    def _to_iso(value):
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    return CotizacionOut(
        id=str(c.id),
        incidente_id=str(c.incidente_id) if c.incidente_id else None,
        solicitud_id=str(c.solicitud_id) if c.solicitud_id else None,
        asignacion_id=str(c.asignacion_id) if c.asignacion_id else None,
        taller_id=str(c.taller_id) if c.taller_id else None,
        taller_nombre=c.taller.nombre if c.taller else None,
        taller_calificacion=float(c.taller.calificacion) if c.taller and c.taller.calificacion is not None else None,
        cliente_id=str(c.cliente_id) if c.cliente_id else None,
        monto_total=float(c.monto or 0),
        tiempo_estimado=getattr(c, "tiempo_estimado", None),
        detalle=c.detalle,
        observaciones=c.observaciones,
        estado=str(c.estado),
        fecha_emision=_to_iso(c.fecha_emision),
        validez_hasta=_to_iso(c.validez_hasta),
        fecha_respuesta_cliente=_to_iso(c.fecha_respuesta_cliente),
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
            tenant_id=tenant_id_from(solicitud),
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
            tenant_id=tenant_id_from(solicitud),
            usuario_id=usuario_id,
            solicitud_id=solicitud.id,
            incidente_id=solicitud.incidente_id,
            titulo=titulo,
            mensaje=mensaje,
            tipo=tipo,
            estado="no_leida",
        )
    )
    enviar_push_db(
        db,
        usuario_id=usuario_id,
        payload={
            "titulo": titulo,
            "cuerpo": mensaje,
            "tipo": tipo,
            "solicitud_id": solicitud.id,
            "incidente_id": solicitud.incidente_id or "",
        },
    )


def generar_cotizacion_taller(
    db: Session,
    *,
    current_user: Usuario,
    incidente_id: str,
    monto_total: float,
    tiempo_estimado: str | None,
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

    asig = _asignacion_de_taller(solicitud, mi_taller.id)
    if not asig:
        raise HTTPException(status_code=403, detail="La solicitud no pertenece a tu taller")

    estado_asig = (asig.estado or "").strip().lower()
    estados_permitidos_cot = {"aceptada_para_cotizar"}
    if estado_asig not in estados_permitidos_cot:
        raise HTTPException(
            status_code=400,
            detail="Debes aceptar participar antes de generar una cotización o la solicitud ya fue cotizada",
        )

    cotizacion_existente = (
        db.query(Cotizacion)
        .filter(
            Cotizacion.solicitud_id == solicitud.id,
            Cotizacion.taller_id == mi_taller.id,
            Cotizacion.estado.in_(["pendiente", "enviada", "aceptada"]),
        )
        .first()
    )
    if cotizacion_existente:
        raise HTTPException(status_code=409, detail="Ya enviaste una cotización para esta solicitud")

    validez_dt = None
    if (validez_hasta or "").strip():
        try:
            validez_dt = datetime.fromisoformat(validez_hasta.strip())
        except ValueError:
            raise HTTPException(status_code=400, detail="validez_hasta debe estar en formato ISO")

    try:
        cot = Cotizacion(
            id=uuid.uuid4(),
            tenant_id=getattr(mi_taller, "tenant_id", None) or tenant_id_from(solicitud, mi_taller),
            solicitud_id=solicitud.id,
            incidente_id=solicitud.incidente_id,
            asignacion_id=asig.id,
            taller_id=mi_taller.id,
            cliente_id=solicitud.cliente_id,
            monto=float(monto_total),
            tiempo_estimado=(tiempo_estimado or "").strip() or None,
            detalle=detalle.strip(),
            observaciones=(observaciones or "").strip() or None,
            estado="enviada",
            fecha_emision=local_now_naive(),
            validez_hasta=validez_dt,
            creado_en=local_now_naive(),
            actualizado_en=local_now_naive(),
        )
        db.add(cot)
        asig.estado = "cotizacion_enviada"

        _agregar_historial(
            db,
            solicitud,
            "cotizaciones_recibidas",
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
    except IntegrityError as exc:
        db.rollback()
        logger.exception("Error de integridad al generar cotización")
        raise HTTPException(
            status_code=400,
            detail="No se pudo generar la cotización por datos incompatibles. Verifica migraciones de pagos/cotizaciones.",
        ) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Error inesperado al generar cotización")
        raise HTTPException(status_code=500, detail=f"Error interno al generar cotización: {exc}") from exc


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
    if current_user.rol == "admin":
        assert_same_tenant(cot, current_user)

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
    elif current_user.rol != "admin":
        query = query.filter(Cotizacion.tenant_id == tenant_id_from(current_user=current_user))

    if (estado or "").strip():
        query = query.filter(Cotizacion.estado == estado.strip().lower())

    try:
        return query.order_by(Cotizacion.creado_en.desc()).all()
    except Exception as exc:
        logger.exception("Error listando cotizaciones del taller")
        raise HTTPException(
            status_code=500,
            detail=f"No se pudieron listar cotizaciones. Revisa consistencia de la tabla cotizaciones. ({exc})",
        ) from exc


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

    estado_cot_actual = (cot.estado or "").lower()
    if estado_cot_actual == "aceptada" and aceptar:
        solicitud_actual = db.query(Solicitud).filter(Solicitud.id == cot.solicitud_id).first()
        return CotizacionDecisionOut(
            cotizacion_id=str(cot.id),
            estado_cotizacion=str(cot.estado),
            incidente_id=str(solicitud_actual.incidente_id) if solicitud_actual and solicitud_actual.incidente_id else None,
            estado_incidente=(str(solicitud_actual.incidente.estado) if solicitud_actual and solicitud_actual.incidente else None),
            estado_solicitud=str(solicitud_actual.estado) if solicitud_actual else None,
            mensaje="Cotización ya estaba aceptada",
        )
    if estado_cot_actual not in {"emitida", "pendiente", "enviada"}:
        raise HTTPException(status_code=409, detail="La cotización ya fue respondida")

    solicitud = db.query(Solicitud).filter(Solicitud.id == cot.solicitud_id).first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud asociada no encontrada")
    ya_aceptada = (
        db.query(Cotizacion)
        .filter(
            Cotizacion.solicitud_id == solicitud.id,
            Cotizacion.id != cot.id,
            Cotizacion.estado == "aceptada",
        )
        .first()
    )
    if aceptar and ya_aceptada:
        raise HTTPException(status_code=409, detail="Ya existe una cotización aceptada para esta solicitud")

    asig = _asignacion_de_cotizacion(cot, solicitud)

    cot.estado = "aceptada" if aceptar else "rechazada"
    cot.observaciones = ((cot.observaciones or "") + ("\n" if cot.observaciones and observaciones else "") + (observaciones or "")).strip() or cot.observaciones
    cot.fecha_respuesta_cliente = local_now_naive()
    cot.actualizado_en = local_now_naive()

    nuevo_estado = "taller_confirmado" if aceptar else "esperando_cotizaciones"
    if aceptar:
        for otra in db.query(Cotizacion).filter(Cotizacion.solicitud_id == solicitud.id, Cotizacion.id != cot.id).all():
            if (otra.estado or "").lower() not in {"rechazada", "vencida"}:
                otra.estado = "rechazada"
                otra.actualizado_en = local_now_naive()
                otra.fecha_respuesta_cliente = otra.fecha_respuesta_cliente or local_now_naive()
        for otra_asig in solicitud.asignaciones or []:
            if asig and str(otra_asig.id) == str(asig.id):
                continue
            if (otra_asig.estado or "").lower() not in {"rechazada", "cancelada", "cancelado"}:
                otra_asig.estado = "descartada"
                otra_asig.es_definitiva = False
        if asig:
            asig.estado = "confirmada"
            asig.es_definitiva = True
            asig.tipo_asignacion = "definitiva"
            asig.fecha_confirmacion = local_now_naive()
        tenant_elegido = cot.tenant_id or (asig.tenant_id if asig else None) or (cot.taller.tenant_id if cot.taller else None)
        solicitud.tenant_id = tenant_elegido
        if solicitud.incidente:
            solicitud.incidente.tenant_id = tenant_elegido
        if solicitud.emergencia:
            solicitud.emergencia.tenant_id = tenant_elegido
    else:
        if asig and (asig.estado or "").lower() == "cotizacion_enviada":
            asig.estado = "aceptada_para_cotizar"

    _agregar_historial(
        db,
        solicitud,
        nuevo_estado,
        "Cliente seleccionó una cotización y confirmó taller" if aceptar else "Cliente rechazó cotización",
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
    asig = _ultimo_asignacion(solicitud)
    if (solicitud.estado or "").strip().lower() not in {"trabajo_completado", "esperando_pago"}:
        raise HTTPException(
            status_code=400,
            detail="Solo se puede procesar pago cuando el trabajo esté completado",
        )

    metodo = (metodo_pago or "").strip().lower()
    if metodo not in {"qr", "transferencia", "efectivo"}:
        raise HTTPException(status_code=400, detail="Método de pago no válido")

    comision = round(float(cot.monto) * 0.10, 2)
    monto_taller = round(float(cot.monto) - comision, 2)
    auto_confirmar_simulado = os.getenv("PAGOS_SIMULADOS_AUTO_CONFIRMAR", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "si",
    }
    pago_confirmado = metodo == "efectivo" or auto_confirmar_simulado
    estado_semantico = "pagado" if pago_confirmado else "pendiente_verificacion"
    estado_pago = _estado_pago_compatible(db, estado_semantico)

    pago = cot.pago
    if pago:
        estado_pago_actual = (pago.estado or "").strip().lower()
        # Idempotencia estricta: si ya está completado/pagado no repetir.
        if estado_pago_actual in {"completado", "pagado"}:
            return _serializar_pago(
                pago,
                cotizacion_id=str(cot.id),
                mensaje="El pago ya fue registrado anteriormente",
            )
        # Si ya existe pendiente y no se confirmó, evitar duplicados.
        if estado_pago_actual in {"pendiente", "pendiente_verificacion"} and not pago_confirmado:
            return _serializar_pago(
                pago,
                cotizacion_id=str(cot.id),
                mensaje="El pago ya fue registrado y está pendiente de verificación",
            )
    if not pago:
        pago = Pago(
            id=uuid.uuid4(),
            tenant_id=tenant_id_from(cot, solicitud),
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
            fecha_verificacion=local_now_naive() if pago_confirmado else None,
            verificado_por=current_user.id if pago_confirmado else None,
        )
        db.add(pago)
        db.flush()
        cot.pago_id = pago.id
    else:
        pago.tenant_id = tenant_id_from(cot, solicitud)
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
        pago.fecha_verificacion = local_now_naive() if pago_confirmado else None
        pago.verificado_por = current_user.id if pago_confirmado else None

    nuevo_estado = "pagado" if pago_confirmado else "esperando_pago"
    _agregar_historial(
        db,
        solicitud,
        nuevo_estado,
        "Pago confirmado" if pago_confirmado else "Pago pendiente de verificación",
    )
    if asig:
        asig.estado = nuevo_estado
    if pago_confirmado:
        _agregar_historial(
            db,
            solicitud,
            "finalizado",
            "Servicio finalizado por pago confirmado",
        )
        if asig:
            asig.estado = "finalizado"
            asig.fecha_finalizacion = local_now_naive()

    if cot.taller and cot.taller.usuario_id:
        _notificar(
            db,
            usuario_id=cot.taller.usuario_id,
            solicitud=solicitud,
            titulo="Actualización de pago",
            mensaje="El cliente registró pago pendiente de verificación" if not pago_confirmado else "Pago confirmado del servicio",
            tipo="pago_pendiente" if not pago_confirmado else "pago_confirmado",
        )

    db.commit()
    db.refresh(pago)
    return _serializar_pago(
        pago,
        cotizacion_id=str(cot.id),
        mensaje="Pago registrado correctamente" if not pago_confirmado else "Pago procesado y servicio finalizado",
    )
