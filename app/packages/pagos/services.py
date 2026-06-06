import uuid
from datetime import datetime
import logging
import os
import json
import hmac
import hashlib

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_, text
from sqlalchemy.orm import Session
import httpx

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
COMISION_PLATAFORMA_PORCENTAJE = 0.10


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


def _resolver_asignacion_cotizacion_estricta(
    db: Session,
    *,
    cot: Cotizacion,
    solicitud: Solicitud,
) -> Asignacion:
    if cot.asignacion_id:
        asig = db.query(Asignacion).filter(Asignacion.id == cot.asignacion_id).first()
        if not asig:
            raise HTTPException(status_code=409, detail="La cotización referencia una asignación inexistente")
        if str(asig.solicitud_id or "") != str(solicitud.id):
            raise HTTPException(status_code=409, detail="La asignación de la cotización no pertenece a la solicitud")
        if cot.taller_id and str(asig.taller_id or "") != str(cot.taller_id):
            raise HTTPException(status_code=409, detail="La asignación de la cotización no coincide con el taller cotizado")
        return asig

    candidatas = [
        a
        for a in (solicitud.asignaciones or [])
        if str(a.taller_id or "") == str(cot.taller_id or "")
        and (a.estado or "").lower() not in {"descartada", "rechazada", "cancelada", "cancelado"}
    ]
    if not candidatas:
        raise HTTPException(status_code=409, detail="No existe asignación válida para la cotización aceptada")
    if len(candidatas) > 1:
        raise HTTPException(
            status_code=409,
            detail="Existe más de una asignación para el taller cotizado; no se puede elegir automáticamente",
        )
    return candidatas[0]


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
        "stripe_checkout_url": pago.comprobante_url if (pago.metodo or "").lower() == "stripe" else None,
    }


def _calcular_comision(monto_total: float) -> tuple[float, float]:
    comision = round(float(monto_total) * COMISION_PLATAFORMA_PORCENTAJE, 2)
    monto_taller = round(float(monto_total) - comision, 2)
    return comision, monto_taller


def _cotizaciones_solicitud(solicitud: Solicitud, db: Session | None = None) -> list[Cotizacion]:
    if db is None:
        return [
            cot
            for cot in (solicitud.cotizaciones or [])
            if str(cot.solicitud_id or "") == str(solicitud.id)
        ]

    return (
        db.query(Cotizacion)
        .filter(Cotizacion.solicitud_id == solicitud.id)
        .order_by(Cotizacion.creado_en.asc().nullslast(), Cotizacion.fecha_emision.asc().nullslast())
        .all()
    )


def _cotizacion_aceptada_solicitud(solicitud: Solicitud, db: Session | None = None) -> Cotizacion | None:
    cotizaciones = _cotizaciones_solicitud(solicitud, db)
    aceptadas = [c for c in cotizaciones if (c.estado or "").lower() == "aceptada" and str(c.solicitud_id or "") == str(solicitud.id)]
    if aceptadas:
        return sorted(
            aceptadas,
            key=lambda c: (
                c.fecha_respuesta_cliente or c.actualizado_en or c.creado_en or c.fecha_emision or datetime.min,
                str(c.id),
            ),
        )[-1]

    if db is None:
        return None

    estado_solicitud = (solicitud.estado or "").strip().lower()
    if estado_solicitud not in {
        "taller_confirmado",
        "confirmada",
        "tecnico_asignado",
        "en_camino",
        "tecnico_en_lugar",
        "en_diagnostico",
        "en_atencion",
        "en_proceso",
        "trabajo_completado",
        "esperando_pago",
        "cancelado_con_cobro",
        "finalizado",
    }:
        return None

    asig = _asignacion_definitiva(solicitud)
    if not asig or not asig.taller_id:
        return None

    candidatas = [
        c
        for c in cotizaciones
        if str(c.solicitud_id or "") == str(solicitud.id)
        and str(c.taller_id or "") == str(asig.taller_id)
    ]
    if not candidatas:
        filtros = [Cotizacion.asignacion_id == asig.id]
        if solicitud.incidente_id:
            filtros.append(
                (Cotizacion.incidente_id == solicitud.incidente_id)
                & (Cotizacion.taller_id == asig.taller_id)
            )
        candidatas = (
            db.query(Cotizacion)
            .filter(or_(*filtros))
            .order_by(Cotizacion.creado_en.desc().nullslast(), Cotizacion.fecha_emision.desc().nullslast())
            .all()
        )
    if not candidatas:
        return None

    con_misma_asignacion = [
        c for c in candidatas if c.asignacion_id and str(c.asignacion_id) == str(asig.id)
    ]
    candidata = sorted(
        con_misma_asignacion or candidatas,
        key=lambda c: (
            c.fecha_respuesta_cliente or c.actualizado_en or c.creado_en or c.fecha_emision or datetime.min,
            str(c.id),
        ),
    )[-1]

    ahora = local_now_naive()
    candidata.estado = "aceptada"
    candidata.solicitud_id = solicitud.id
    candidata.incidente_id = candidata.incidente_id or solicitud.incidente_id
    candidata.asignacion_id = candidata.asignacion_id or asig.id
    candidata.taller_id = candidata.taller_id or asig.taller_id
    candidata.cliente_id = candidata.cliente_id or solicitud.cliente_id
    candidata.fecha_respuesta_cliente = candidata.fecha_respuesta_cliente or ahora
    candidata.actualizado_en = ahora
    asig.estado = asig.estado or "confirmada"
    asig.es_definitiva = True
    asig.tipo_asignacion = getattr(asig, "tipo_asignacion", None) or "definitiva"
    asig.fecha_confirmacion = getattr(asig, "fecha_confirmacion", None) or ahora
    for otra in cotizaciones:
        if str(otra.id) == str(candidata.id):
            continue
        if (otra.estado or "").lower() in {"pendiente", "emitida", "enviada", "cotizacion_enviada", "aceptada"}:
            otra.estado = "rechazada"
            otra.actualizado_en = ahora
    db.flush()
    return candidata


def _asignacion_definitiva(solicitud: Solicitud) -> Asignacion | None:
    candidatas = [
        a
        for a in (solicitud.asignaciones or [])
        if getattr(a, "es_definitiva", False)
        or (a.estado or "").lower()
        in {"confirmada", "tecnico_asignado", "en_camino", "tecnico_en_lugar", "en_diagnostico", "en_proceso", "trabajo_completado", "esperando_pago"}
        or (a.estado or "").lower() == "cancelado_con_cobro"
    ]
    if not candidatas:
        return None
    return sorted(candidatas, key=_orden_asignacion)[-1]


def _validar_pago_habilitado(solicitud: Solicitud, cot: Cotizacion) -> Asignacion:
    estado = (solicitud.estado or "").strip().lower()
    asig = _asignacion_definitiva(solicitud)
    if (cot.estado or "").strip().lower() != "aceptada":
        raise HTTPException(status_code=400, detail="La cotización debe estar aceptada")
    if not asig or not getattr(asig, "es_definitiva", False):
        raise HTTPException(status_code=400, detail="Debe existir asignación confirmada")
    if not asig.tecnico_id:
        raise HTTPException(status_code=400, detail="Debe existir técnico asignado")
    if estado not in {"trabajo_completado", "esperando_pago", "cancelado_con_cobro", "finalizado"}:
        raise HTTPException(status_code=400, detail="El pago se habilita cuando el técnico completa el servicio")
    return asig


def crear_o_actualizar_pago_pendiente(
    db: Session,
    *,
    cot: Cotizacion,
    solicitud: Solicitud,
    monto_total: float | None = None,
    tipo: str = "servicio",
) -> Pago:
    monto = round(float(monto_total if monto_total is not None else cot.monto), 2)
    comision, monto_taller = _calcular_comision(monto)
    pago = cot.pago
    if not pago:
        pago = Pago(
            id=uuid.uuid4(),
            tenant_id=tenant_id_from(cot, solicitud),
            monto=monto,
            estado=_estado_pago_compatible(db, "pendiente_verificacion"),
            metodo=None,
            incidente_id=cot.incidente_id,
            cliente_id=cot.cliente_id,
            taller_id=cot.taller_id,
            referencia=f"tipo:{tipo}",
            comision_plataforma=comision,
            monto_taller=monto_taller,
        )
        db.add(pago)
        db.flush()
        cot.pago_id = pago.id
    else:
        estado_actual = (pago.estado or "").lower()
        if estado_actual not in {"pagado", "completado"}:
            pago.monto = monto
            pago.estado = _estado_pago_compatible(db, "pendiente_verificacion")
            pago.incidente_id = cot.incidente_id
            pago.cliente_id = cot.cliente_id
            pago.taller_id = cot.taller_id
            pago.referencia = f"tipo:{tipo}"
            pago.comision_plataforma = comision
            pago.monto_taller = monto_taller
    return pago


def _confirmar_pago(
    db: Session,
    *,
    pago: Pago,
    metodo: str,
    referencia: str | None = None,
    verificado_por=None,
) -> None:
    pago.metodo = metodo
    pago.estado = _estado_pago_compatible(db, "pagado")
    pago.pagado_en = local_now_naive()
    pago.fecha_verificacion = local_now_naive()
    pago.verificado_por = verificado_por
    if referencia:
        pago.referencia = referencia
    cot = pago.cotizaciones[0] if pago.cotizaciones else None
    solicitud = cot.solicitud if cot else None
    if solicitud:
        asig = _asignacion_definitiva(solicitud)
        _agregar_historial(db, solicitud, "pagado", f"Pago confirmado por {metodo}")
        if asig:
            asig.estado = "pagado"
        if (solicitud.estado or "").lower() != "cancelado_con_cobro":
            _agregar_historial(db, solicitud, "finalizado", "Servicio finalizado por pago confirmado")
            if asig:
                asig.estado = "finalizado"
                asig.fecha_finalizacion = local_now_naive()
        if cot and cot.taller and cot.taller.usuario_id:
            _notificar(
                db,
                usuario_id=cot.taller.usuario_id,
                solicitud=solicitud,
                titulo="Pago confirmado",
                mensaje="El cliente confirmó el pago del servicio",
                tipo="pago_confirmado",
            )


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
            Cotizacion.estado.in_(["pendiente", "enviada", "aceptada", "cotizacion_enviada"]),
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

    asig = _resolver_asignacion_cotizacion_estricta(db, cot=cot, solicitud=solicitud)
    if str(cot.solicitud_id or "") != str(solicitud.id):
        raise HTTPException(status_code=409, detail="La cotización no pertenece a la solicitud esperada")
    if cot.taller_id and str(cot.taller_id or "") != str(asig.taller_id or ""):
        raise HTTPException(status_code=409, detail="La cotización no coincide con la asignación seleccionada")
    if cot.cliente_id and str(cot.cliente_id or "") != str(cli.id):
        raise HTTPException(status_code=409, detail="La cotización no pertenece al cliente autenticado")

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

    solicitud = db.query(Solicitud).filter(Solicitud.id == cot.solicitud_id).first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud asociada no encontrada")
    asig = _validar_pago_habilitado(solicitud, cot)

    metodo = (metodo_pago or "").strip().lower()
    if metodo not in {"efectivo"}:
        raise HTTPException(status_code=400, detail="Usa efectivo o el endpoint Stripe Checkout para pagar")

    pago_existente = cot.pago
    es_cobro_visita = (
        (solicitud.estado or "").lower() == "cancelado_con_cobro"
        or "cobro_visita" in ((pago_existente.referencia if pago_existente else "") or "")
    )
    pago = crear_o_actualizar_pago_pendiente(
        db,
        cot=cot,
        solicitud=solicitud,
        monto_total=(float(pago_existente.monto) if es_cobro_visita and pago_existente else None),
        tipo="cobro_visita" if es_cobro_visita else "servicio",
    )
    if (pago.estado or "").lower() in {"pagado", "completado"}:
        return _serializar_pago(pago, cotizacion_id=str(cot.id), mensaje="El pago ya fue registrado")
    pago.comprobante_url = (comprobante_url or "").strip() or None
    _confirmar_pago(
        db,
        pago=pago,
        metodo="efectivo",
        referencia=(referencia or "").strip() or "Pago en efectivo",
        verificado_por=current_user.id,
    )

    db.commit()
    db.refresh(pago)
    return _serializar_pago(
        pago,
        cotizacion_id=str(cot.id),
        mensaje="Pago en efectivo registrado y servicio finalizado",
    )


def crear_stripe_checkout(db: Session, *, pago_id: str, current_user: Usuario) -> dict:
    if current_user.rol not in {"cliente", "conductor"}:
        raise HTTPException(status_code=403, detail="Solo cliente puede iniciar Stripe Checkout")
    secret = os.getenv("STRIPE_SECRET_KEY", "").strip()
    if not secret:
        raise HTTPException(status_code=500, detail="STRIPE_SECRET_KEY no está configurado")

    pago = db.query(Pago).filter(Pago.id == pago_id).first()
    if not pago:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    cot = pago.cotizaciones[0] if pago.cotizaciones else None
    if not cot or not cot.solicitud:
        raise HTTPException(status_code=400, detail="Pago sin cotización asociada")
    cli = db.query(Cliente).filter(Cliente.usuario_id == current_user.id).first()
    if not cli or str(pago.cliente_id or "") != str(cli.id):
        raise HTTPException(status_code=403, detail="No autorizado para este pago")
    _validar_pago_habilitado(cot.solicitud, cot)
    if (pago.estado or "").lower() in {"pagado", "completado"}:
        raise HTTPException(status_code=409, detail="Este pago ya fue confirmado")

    base_url = os.getenv("FRONTEND_URL", "http://localhost:4200").rstrip("/")
    amount_cents = int(round(float(pago.monto) * 100))
    data = {
        "mode": "payment",
        "success_url": f"{base_url}/pagos/gestionar-cotizacion?stripe=success&pago_id={pago.id}",
        "cancel_url": f"{base_url}/pagos/gestionar-cotizacion?stripe=cancel&pago_id={pago.id}",
        "line_items[0][price_data][currency]": os.getenv("STRIPE_CURRENCY", "bob").lower(),
        "line_items[0][price_data][product_data][name]": "Servicio AuxilioSCZ",
        "line_items[0][price_data][unit_amount]": str(amount_cents),
        "line_items[0][quantity]": "1",
        "metadata[pago_id]": str(pago.id),
        "metadata[cotizacion_id]": str(cot.id),
    }
    try:
        with httpx.Client(timeout=20) as client:
            res = client.post(
                "https://api.stripe.com/v1/checkout/sessions",
                data=data,
                headers={"Authorization": f"Bearer {secret}"},
            )
        if res.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Stripe rechazó la sesión: {res.text}")
        payload = res.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"No se pudo crear Stripe Checkout: {exc}") from exc

    pago.metodo = "stripe"
    pago.estado = _estado_pago_compatible(db, "pendiente_verificacion")
    pago.referencia = payload.get("id") or pago.referencia
    pago.comprobante_url = payload.get("url") or pago.comprobante_url
    db.commit()
    return {
        "pago_id": str(pago.id),
        "checkout_url": str(payload.get("url") or ""),
        "stripe_session_id": payload.get("id"),
    }


def _stripe_secret_key() -> str:
    secret = os.getenv("STRIPE_SECRET_KEY", "").strip()
    if not secret:
        raise HTTPException(status_code=500, detail="STRIPE_SECRET_KEY no está configurado")
    return secret


def _stripe_publishable_key() -> str:
    publishable = os.getenv("STRIPE_PUBLISHABLE_KEY", "").strip()
    if not publishable:
        raise HTTPException(status_code=500, detail="STRIPE_PUBLISHABLE_KEY no está configurado")
    return publishable


def crear_stripe_payment_sheet(db: Session, *, pago_id: str, current_user: Usuario) -> dict:
    if current_user.rol not in {"cliente", "conductor"}:
        raise HTTPException(status_code=403, detail="Solo cliente puede iniciar PaymentSheet")

    secret = _stripe_secret_key()
    publishable = _stripe_publishable_key()
    pago = db.query(Pago).filter(Pago.id == pago_id).first()
    if not pago:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    cot_inicial = pago.cotizaciones[0] if pago.cotizaciones else None
    if not cot_inicial or not cot_inicial.solicitud:
        raise HTTPException(status_code=400, detail="Pago sin cotización asociada")

    solicitud = cot_inicial.solicitud
    cot = _cotizacion_aceptada_solicitud(solicitud, db) or cot_inicial
    if (cot.estado or "").strip().lower() != "aceptada":
        raise HTTPException(status_code=400, detail="No existe cotización aceptada para este pago")
    if str(cot.solicitud_id or "") != str(solicitud.id):
        raise HTTPException(status_code=409, detail="La cotización aceptada no pertenece a la solicitud del pago")
    if cot.pago_id and str(cot.pago_id) != str(pago.id):
        pago = cot.pago
        if not pago:
            raise HTTPException(status_code=409, detail="La cotización aceptada referencia un pago inexistente")
    elif not cot.pago_id:
        cot.pago_id = pago.id

    cli = db.query(Cliente).filter(Cliente.usuario_id == current_user.id).first()
    if not cli or str(pago.cliente_id or "") != str(cli.id):
        raise HTTPException(status_code=403, detail="No autorizado para este pago")
    _validar_pago_habilitado(solicitud, cot)
    if (pago.estado or "").lower() in {"pagado", "completado"}:
        raise HTTPException(status_code=409, detail="Este pago ya fue confirmado")

    es_cobro_visita = (
        (solicitud.estado or "").lower() == "cancelado_con_cobro"
        or "cobro_visita" in ((pago.referencia or "").lower())
    )
    monto_base = round(float(pago.monto if es_cobro_visita else cot.monto or 0), 2)
    if monto_base <= 0:
        raise HTTPException(status_code=400, detail="El monto del pago no es válido")
    comision, monto_taller = _calcular_comision(monto_base)
    pago.monto = monto_base
    pago.comision_plataforma = comision
    pago.monto_taller = monto_taller
    pago.cliente_id = cot.cliente_id
    pago.taller_id = cot.taller_id
    pago.incidente_id = cot.incidente_id

    currency = "bob"
    amount_cents = int(round(monto_base * 100))
    if amount_cents <= 0:
        raise HTTPException(status_code=400, detail="El monto del pago no es válido")

    headers = {"Authorization": f"Bearer {secret}"}
    try:
        with httpx.Client(timeout=20) as client:
            customer_res = client.post(
                "https://api.stripe.com/v1/customers",
                data={
                    "name": getattr(current_user, "nombre", None) or "Cliente AuxilioSCZ",
                    "email": getattr(current_user, "email", None) or "",
                    "metadata[usuario_id]": str(current_user.id),
                    "metadata[pago_id]": str(pago.id),
                },
                headers=headers,
            )
            if customer_res.status_code >= 400:
                raise HTTPException(status_code=502, detail=f"Stripe rechazó el cliente: {customer_res.text}")
            customer = customer_res.json()
            customer_id = str(customer.get("id") or "")
            if not customer_id:
                raise HTTPException(status_code=502, detail="Stripe no devolvió customerId")

            ephemeral_res = client.post(
                "https://api.stripe.com/v1/ephemeral_keys",
                data={"customer": customer_id},
                headers={**headers, "Stripe-Version": os.getenv("STRIPE_API_VERSION", "2024-06-20")},
            )
            if ephemeral_res.status_code >= 400:
                raise HTTPException(status_code=502, detail=f"Stripe rechazó ephemeral key: {ephemeral_res.text}")
            ephemeral_key = ephemeral_res.json()
            ephemeral_secret = str(ephemeral_key.get("secret") or "")
            if not ephemeral_secret:
                raise HTTPException(status_code=502, detail="Stripe no devolvió customerEphemeralKeySecret")

            intent_res = client.post(
                "https://api.stripe.com/v1/payment_intents",
                data={
                    "amount": str(amount_cents),
                    "currency": currency,
                    "customer": customer_id,
                    "payment_method_types[0]": "card",
                    "metadata[pago_id]": str(pago.id),
                    "metadata[cotizacion_id]": str(cot.id),
                    "metadata[solicitud_id]": str(cot.solicitud_id),
                    "metadata[monto_bob]": str(monto_base),
                    "metadata[tipo_pago]": "cobro_visita" if es_cobro_visita else "servicio",
                },
                headers=headers,
            )
            if intent_res.status_code >= 400:
                raise HTTPException(status_code=502, detail=f"Stripe rechazó PaymentIntent: {intent_res.text}")
            intent = intent_res.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"No se pudo iniciar PaymentSheet: {exc}") from exc

    client_secret = str(intent.get("client_secret") or "")
    payment_intent_id = str(intent.get("id") or "")
    if not client_secret or not payment_intent_id:
        raise HTTPException(status_code=502, detail="Stripe no devolvió client_secret")

    pago.metodo = "stripe"
    pago.estado = _estado_pago_compatible(db, "pendiente_verificacion")
    pago.referencia = payment_intent_id
    db.commit()
    return {
        "paymentIntentClientSecret": client_secret,
        "customerId": customer_id,
        "customerEphemeralKeySecret": ephemeral_secret,
        "publishableKey": publishable,
        "pago_id": str(pago.id),
    }


def confirmar_stripe_payment_sheet(db: Session, *, pago_id: str, current_user: Usuario) -> dict:
    if current_user.rol not in {"cliente", "conductor"}:
        raise HTTPException(status_code=403, detail="Solo cliente puede confirmar PaymentSheet")

    secret = _stripe_secret_key()
    pago = db.query(Pago).filter(Pago.id == pago_id).first()
    if not pago:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    cot = pago.cotizaciones[0] if pago.cotizaciones else None
    if not cot:
        raise HTTPException(status_code=400, detail="Pago sin cotización asociada")
    cli = db.query(Cliente).filter(Cliente.usuario_id == current_user.id).first()
    if not cli or str(pago.cliente_id or "") != str(cli.id):
        raise HTTPException(status_code=403, detail="No autorizado para este pago")

    if (pago.estado or "").lower() in {"pagado", "completado"}:
        return _serializar_pago(pago, cotizacion_id=str(cot.id), mensaje="El pago ya fue confirmado")

    payment_intent_id = (pago.referencia or "").strip()
    if not payment_intent_id.startswith("pi_"):
        raise HTTPException(status_code=400, detail="El pago no tiene PaymentIntent asociado")

    try:
        with httpx.Client(timeout=20) as client:
            res = client.get(
                f"https://api.stripe.com/v1/payment_intents/{payment_intent_id}",
                headers={"Authorization": f"Bearer {secret}"},
            )
        if res.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Stripe no pudo verificar el pago: {res.text}")
        intent = res.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"No se pudo confirmar PaymentSheet: {exc}") from exc

    if (intent.get("status") or "").lower() != "succeeded":
        raise HTTPException(status_code=409, detail=f"Stripe aún no confirmó el pago: {intent.get('status')}")

    _confirmar_pago(
        db,
        pago=pago,
        metodo="stripe",
        referencia=payment_intent_id,
        verificado_por=current_user.id,
    )
    db.commit()
    db.refresh(pago)
    return _serializar_pago(pago, cotizacion_id=str(cot.id), mensaje="Pago Stripe confirmado")


def _verificar_firma_stripe(raw_body: bytes, signature: str | None) -> None:
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise HTTPException(status_code=500, detail="STRIPE_WEBHOOK_SECRET no está configurado")
    if not signature:
        raise HTTPException(status_code=400, detail="Falta Stripe-Signature")
    parts = dict(part.split("=", 1) for part in signature.split(",") if "=" in part)
    timestamp = parts.get("t")
    expected = parts.get("v1")
    if not timestamp or not expected:
        raise HTTPException(status_code=400, detail="Firma Stripe inválida")
    signed = f"{timestamp}.{raw_body.decode('utf-8')}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(digest, expected):
        raise HTTPException(status_code=400, detail="Firma Stripe inválida")


def procesar_stripe_webhook(db: Session, *, raw_body: bytes, signature: str | None) -> dict:
    _verificar_firma_stripe(raw_body, signature)
    try:
        event = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Payload Stripe inválido") from exc

    if event.get("type") != "checkout.session.completed":
        return {"ok": True, "ignored": True}

    session = ((event.get("data") or {}).get("object") or {})
    metadata = session.get("metadata") or {}
    pago_id = metadata.get("pago_id")
    stripe_session_id = session.get("id")
    if not pago_id and stripe_session_id:
        pago = db.query(Pago).filter(Pago.referencia == stripe_session_id).first()
    else:
        pago = db.query(Pago).filter(Pago.id == pago_id).first()
    if not pago:
        raise HTTPException(status_code=404, detail="Pago Stripe no encontrado")
    if (pago.estado or "").lower() not in {"pagado", "completado"}:
        _confirmar_pago(
            db,
            pago=pago,
            metodo="stripe",
            referencia=stripe_session_id or pago.referencia,
        )
        db.commit()
    return {"ok": True, "pago_id": str(pago.id)}
