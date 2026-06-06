from fastapi import HTTPException
from datetime import datetime
import math

from sqlalchemy import or_
from sqlalchemy.orm import Session

import uuid

from app.core.tenant import assert_same_tenant, tenant_id_from
from app.models.models import Asignacion, Cliente, Cotizacion, Evaluacion, Pago, Solicitud, TrabajoCompletado, Ubicacion, Usuario
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
    "taller_confirmado",
    "confirmada",
    "cotizacion_aceptada",
    "tecnico_asignado",
    "en_camino",
    "tecnico_en_lugar",
    "en_diagnostico",
    "en_atencion",
    "en_proceso",
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


ESTADOS_ASIGNACION_DEFINITIVA = {
    "confirmada",
    "tecnico_asignado",
    "en_camino",
    "tecnico_en_lugar",
    "en_diagnostico",
    "diagnostico_completado",
    "cotizacion_aceptada",
    "en_proceso",
    "trabajo_completado",
    "esperando_pago",
    "pagado",
    "finalizado",
}

ESTADOS_TRACKING_PERMITIDOS_CLIENTE = {
    "confirmada",
    "tecnico_asignado",
    "en_camino",
    "tecnico_en_lugar",
    "en_diagnostico",
    "diagnostico_completado",
    "en_atencion",
    "en_proceso",
    "trabajo_completado",
    "finalizado",
}

VELOCIDAD_PROMEDIO_KMH = 30.0


def _orden_asignacion_cliente(asignacion: Asignacion):
    estado = _estado_key(asignacion.estado)
    prioridad_estado = {
        "finalizado": 9,
        "pagado": 8,
        "esperando_pago": 7,
        "trabajo_completado": 6,
        "en_proceso": 5,
        "en_diagnostico": 4,
        "tecnico_en_lugar": 4,
        "en_camino": 3,
        "tecnico_asignado": 2,
        "confirmada": 1,
    }.get(estado, 0)
    return (
        1 if getattr(asignacion, "es_definitiva", False) else 0,
        prioridad_estado,
        getattr(asignacion, "fecha_confirmacion", None)
        or getattr(asignacion, "fecha_asignacion", None)
        or getattr(asignacion, "asignado_en", None)
        or getattr(asignacion, "creado_en", None)
        or datetime.min,
        str(asignacion.id),
    )


def _cotizacion_aceptada_cliente(solicitud: Solicitud, db: Session | None = None) -> Cotizacion | None:
    cotizaciones = _cotizaciones_solicitud(solicitud, db)
    aceptadas = [
        c
        for c in cotizaciones
        if _estado_key(c.estado) == "aceptada" and str(c.solicitud_id or "") == str(solicitud.id)
    ]
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

    estado_solicitud = _estado_key(solicitud.estado)
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

    asignaciones = [
        a
        for a in (solicitud.asignaciones or [])
        if a.taller_id
        and (
            getattr(a, "es_definitiva", False)
            or _estado_key(a.estado) in ESTADOS_ASIGNACION_DEFINITIVA
        )
    ]
    if not asignaciones:
        return None

    asig = sorted(asignaciones, key=_orden_asignacion_cliente)[-1]
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

    ahora = datetime.now()
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
        if _estado_key(otra.estado) in {"pendiente", "emitida", "enviada", "cotizacion_enviada", "aceptada"}:
            otra.estado = "rechazada"
            otra.actualizado_en = ahora
    db.flush()
    return candidata


def _asignacion_definitiva_cliente(solicitud: Solicitud, db: Session | None = None) -> Asignacion | None:
    cotizacion_aceptada = _cotizacion_aceptada_cliente(solicitud, db)
    asig_cotizacion = None
    if cotizacion_aceptada and cotizacion_aceptada.asignacion_id:
        asig_cotizacion = next(
            (
                a
                for a in (solicitud.asignaciones or [])
                if str(a.id) == str(cotizacion_aceptada.asignacion_id)
            ),
            None,
        )
    if cotizacion_aceptada and cotizacion_aceptada.taller_id:
        asignaciones_taller_cotizado = [
            a
            for a in (solicitud.asignaciones or [])
            if str(a.taller_id or "") == str(cotizacion_aceptada.taller_id)
            and (
                getattr(a, "es_definitiva", False)
                or _estado_key(a.estado) not in {"descartada", "rechazada", "cancelada", "cancelado"}
            )
        ]
        if asignaciones_taller_cotizado:
            return sorted(asignaciones_taller_cotizado, key=_orden_asignacion_cliente)[-1]
    if asig_cotizacion:
        return asig_cotizacion

    asignaciones = [
        a
        for a in (solicitud.asignaciones or [])
        if getattr(a, "es_definitiva", False) or _estado_key(a.estado) in ESTADOS_ASIGNACION_DEFINITIVA
    ]
    if not asignaciones:
        return None
    return sorted(asignaciones, key=_orden_asignacion_cliente)[-1]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radio_tierra = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return 2 * radio_tierra * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _estado_visible_tracking(estado: str | None, distancia_km: float | None = None) -> str:
    key = _estado_key(estado)
    if key == "finalizado":
        return "Servicio finalizado"
    if key in {"tecnico_en_lugar", "en_diagnostico", "diagnostico_completado"}:
        return "El técnico llegó al lugar"
    if key in {"en_atencion", "en_proceso", "trabajo_completado"}:
        return "Servicio en atención"
    if distancia_km is not None:
        if distancia_km < 0.1:
            return "El técnico está llegando"
        if distancia_km <= 0.5:
            return "El técnico está cerca"
    if key in {"en_camino", "tecnico_asignado", "confirmada"}:
        return "Técnico en camino"
    return "Seguimiento del técnico"


def _mensaje_tracking(estado: str | None, distancia_km: float | None = None) -> str:
    key = _estado_key(estado)
    if key in {"tecnico_en_lugar", "en_diagnostico", "diagnostico_completado"}:
        return "El técnico llegó al lugar de la emergencia."
    if key in {"en_atencion", "en_proceso", "trabajo_completado"}:
        return "El servicio está siendo atendido."
    if distancia_km is not None:
        if distancia_km < 0.1:
            return "El técnico está llegando a tu ubicación."
        if distancia_km <= 0.5:
            return "El técnico está muy cerca de tu ubicación."
    return "El técnico se está acercando a tu ubicación."


def _hora_corta(value) -> str | None:
    if not value:
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%H:%M")
    except Exception:
        return str(value)


def _tracking_response(
    *,
    solicitud: Solicitud,
    asignacion: Asignacion | None,
    tecnico_nombre: str | None,
    lat_tecnico: float | None,
    lng_tecnico: float | None,
    lat_cliente: float | None,
    lng_cliente: float | None,
    ultima_actualizacion,
    mensaje_fallback: str | None = None,
) -> dict:
    estado = str(asignacion.estado if asignacion and asignacion.estado else solicitud.estado)
    distancia = None
    eta = None
    if lat_tecnico is not None and lng_tecnico is not None and lat_cliente is not None and lng_cliente is not None:
        distancia = round(_haversine_km(float(lat_tecnico), float(lng_tecnico), float(lat_cliente), float(lng_cliente)), 2)
        eta = max(1, round((distancia / VELOCIDAD_PROMEDIO_KMH) * 60))
    estado_visible = _estado_visible_tracking(estado, distancia)
    mensaje = mensaje_fallback or _mensaje_tracking(estado, distancia)
    ultima = _hora_corta(ultima_actualizacion)
    return {
        "incidente_id": str(solicitud.id),
        "codigo_solicitud": _codigo_solicitud(solicitud),
        "tecnico": {
            "nombre": tecnico_nombre,
            "latitud": lat_tecnico,
            "longitud": lng_tecnico,
        },
        "cliente": {
            "latitud": lat_cliente,
            "longitud": lng_cliente,
        },
        "estado": estado,
        "estado_visible": estado_visible,
        "distancia_restante_km": distancia,
        "tiempo_estimado_llegada_min": eta,
        "tecnico_nombre": tecnico_nombre,
        "estado_servicio": estado,
        "latitud_tecnico": lat_tecnico,
        "longitud_tecnico": lng_tecnico,
        "latitud_cliente": lat_cliente,
        "longitud_cliente": lng_cliente,
        "ultima_actualizacion": ultima,
        "mensaje": mensaje,
    }


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

    es_dueno = bool(solicitud.cliente and str(solicitud.cliente.usuario_id) == str(current_user.id))
    if current_user.rol != "admin" and not es_dueno:
        assert_same_tenant(solicitud, current_user)
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
    asignacion = _asignacion_definitiva_cliente(solicitud, db)
    if not solicitud.asignaciones or not asignacion or not asignacion.tecnico:
        return _tracking_response(
            solicitud=solicitud,
            asignacion=asignacion,
            tecnico_nombre=None,
            lat_tecnico=None,
            lng_tecnico=None,
            lat_cliente=None,
            lng_cliente=None,
            ultima_actualizacion=None,
            mensaje_fallback="Aún no hay técnico asignado.",
        )

    estado_servicio = _estado_key(asignacion.estado or solicitud.estado)
    if estado_servicio not in ESTADOS_TRACKING_PERMITIDOS_CLIENTE:
        return _tracking_response(
            solicitud=solicitud,
            asignacion=asignacion,
            tecnico_nombre=asignacion.tecnico.nombre,
            lat_tecnico=None,
            lng_tecnico=None,
            lat_cliente=None,
            lng_cliente=None,
            ultima_actualizacion=None,
            mensaje_fallback="El seguimiento estará disponible cuando el taller confirme un técnico.",
        )

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

    return _tracking_response(
        solicitud=solicitud,
        asignacion=asignacion,
        tecnico_nombre=asignacion.tecnico.nombre,
        lat_tecnico=ultima_ubicacion.latitud if ultima_ubicacion else None,
        lng_tecnico=ultima_ubicacion.longitud if ultima_ubicacion else None,
        lat_cliente=lat_cliente,
        lng_cliente=lng_cliente,
        ultima_actualizacion=ultima_ubicacion.registrado_en if ultima_ubicacion else None,
        mensaje_fallback=None if ultima_ubicacion else "El técnico aún no inició el seguimiento.",
    )


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


def _resolver_acciones_disponibles(solicitud: Solicitud, db: Session | None = None) -> dict:
    estado_key = _estado_key(solicitud.estado)
    tiene_tecnico = False
    asignacion_definitiva = _asignacion_definitiva_cliente(solicitud, db)
    if asignacion_definitiva:
        tiene_tecnico = asignacion_definitiva.tecnico_id is not None

    cotizaciones = _cotizaciones_solicitud(solicitud, db)
    cotizacion = _cotizacion_aceptada_cliente(solicitud, db)
    pago = cotizacion.pago if cotizacion and cotizacion.pago else None
    hay_cotizaciones_responder = any(_estado_key(c.estado) in {"emitida", "pendiente", "enviada"} for c in cotizaciones)

    puede_ver_cotizacion = cotizacion is not None
    puede_responder_cotizacion = hay_cotizaciones_responder
    puede_pagar = bool(
        cotizacion
        and estado_key in {"trabajo_completado", "esperando_pago", "cancelado_con_cobro", "finalizado"}
        and (pago is None or _estado_key(pago.estado) in {"pendiente", "pendiente_pago", "pendiente_verificacion"})
    )
    pago_pagado = bool(pago and _estado_key(pago.estado) in {"pagado", "completado"})
    puede_evaluar = estado_key in {"servicio_completado", "pagado"} or (estado_key == "finalizado" and pago_pagado)
    motivo_pago_no_disponible = None
    if estado_key in {"trabajo_completado", "esperando_pago", "cancelado_con_cobro", "finalizado"} and not puede_pagar:
        if not cotizacion:
            resumen = ", ".join(
                f"{getattr(c.taller, 'nombre', 'sin_taller')}:{c.estado}"
                for c in cotizaciones
            ) or "sin cotizaciones registradas"
            motivo_pago_no_disponible = (
                f"No se encontró cotización aceptada para la solicitud {solicitud.id}. "
                f"Cotizaciones actuales: {resumen}"
            )
        elif not asignacion_definitiva or not getattr(asignacion_definitiva, "es_definitiva", False):
            motivo_pago_no_disponible = "No existe asignación confirmada para habilitar el pago."
        elif not asignacion_definitiva.tecnico_id:
            motivo_pago_no_disponible = "No existe técnico asignado en la asignación confirmada."
        elif not pago:
            motivo_pago_no_disponible = "El pago pendiente aún no fue creado para la cotización aceptada."
        else:
            motivo_pago_no_disponible = "El pago no está disponible en el estado actual."

    return {
        "puede_cancelar": estado_key in CANCELABLE_STATES,
        "puede_ver_tecnico": tiene_tecnico
        and estado_key
        in {
            "tecnico_asignado",
            "en_camino",
            "tecnico_en_lugar",
            "en_diagnostico",
            "diagnostico_completado",
            "cotizacion_emitida",
            "cotizacion_aceptada",
            "en_atencion",
            "en_proceso",
        },
        "puede_ver_cotizacion": puede_ver_cotizacion,
        "puede_responder_cotizacion": puede_responder_cotizacion,
        "puede_pagar": puede_pagar,
        "motivo_pago_no_disponible": motivo_pago_no_disponible,
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


def _serializar_taller_tecnico(solicitud: Solicitud, db: Session | None = None) -> tuple[dict | None, dict | None]:
    asig = _asignacion_definitiva_cliente(solicitud, db)
    cotizacion_aceptada = _cotizacion_aceptada_cliente(solicitud, db)
    taller = None
    tecnico = None
    if cotizacion_aceptada and cotizacion_aceptada.taller:
        taller = {
            "id": str(cotizacion_aceptada.taller.id),
            "nombre": cotizacion_aceptada.taller.nombre,
            "estado": solicitud.estado,
        }
    elif asig and asig.taller:
        taller = {
            "id": str(asig.taller.id),
            "nombre": asig.taller.nombre,
            # Para cliente mostramos el estado global del servicio, no un estado técnico legado de asignación.
            "estado": solicitud.estado,
        }
    if asig and asig.tecnico:
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


def _serializar_cotizacion_pago(solicitud: Solicitud, db: Session | None = None) -> tuple[dict | None, dict | None]:
    cotizacion = _cotizacion_aceptada_cliente(solicitud, db)
    if not cotizacion:
        return None, None
    cot = {
        "id": str(cotizacion.id),
        "solicitud_id": str(cotizacion.solicitud_id) if cotizacion.solicitud_id else None,
        "taller_id": str(cotizacion.taller_id) if cotizacion.taller_id else None,
        "monto": cotizacion.monto,
        "tiempo_estimado": getattr(cotizacion, "tiempo_estimado", None),
        "estado": cotizacion.estado,
        "detalle": cotizacion.detalle,
        "observaciones": cotizacion.observaciones,
        "taller_nombre": cotizacion.taller.nombre if cotizacion.taller else None,
        "taller_calificacion": cotizacion.taller.calificacion if cotizacion.taller else None,
        "validez_hasta": cotizacion.validez_hasta.isoformat() if cotizacion.validez_hasta else None,
        "fecha_respuesta_cliente": (
            cotizacion.fecha_respuesta_cliente.isoformat() if cotizacion.fecha_respuesta_cliente else None
        ),
        "creado_en": cotizacion.creado_en.isoformat() if cotizacion.creado_en else None,
    }
    pago: Pago | None = cotizacion.pago
    if (
        db is not None
        and not pago
        and _estado_key(cotizacion.estado) == "aceptada"
        and _estado_key(solicitud.estado) in {"trabajo_completado", "esperando_pago", "cancelado_con_cobro", "finalizado"}
    ):
        from app.packages.pagos.services import crear_o_actualizar_pago_pendiente

        es_cobro_visita = _estado_key(solicitud.estado) == "cancelado_con_cobro"
        pago = crear_o_actualizar_pago_pendiente(
            db,
            cot=cotizacion,
            solicitud=solicitud,
            monto_total=(round(float(cotizacion.monto) * 0.30, 2) if es_cobro_visita else None),
            tipo=("cobro_visita" if es_cobro_visita else "servicio"),
        )
        db.commit()
        db.refresh(pago)
    if not pago:
        return cot, None
    return cot, {
        "id": str(pago.id),
        "estado": pago.estado,
        "monto": pago.monto,
        "comision_plataforma": pago.comision_plataforma,
        "monto_taller": pago.monto_taller,
        "metodo": pago.metodo,
        "referencia": pago.referencia,
        "stripe_checkout_url": pago.comprobante_url if (pago.metodo or "").lower() == "stripe" else None,
        "pagado_en": pago.pagado_en.isoformat() if pago.pagado_en else None,
    }


def _serializar_cotizaciones_disponibles(solicitud: Solicitud, db: Session | None = None) -> list[dict]:
    rows = []
    for cot in sorted(_cotizaciones_solicitud(solicitud, db), key=lambda c: c.creado_en or c.fecha_emision):
        if _estado_key(cot.estado) not in {"pendiente", "emitida", "enviada", "cotizacion_enviada", "aceptada"}:
            continue
        rows.append(
            {
                "id": str(cot.id),
                "solicitud_id": str(cot.solicitud_id) if cot.solicitud_id else None,
                "taller_id": str(cot.taller_id) if cot.taller_id else None,
                "monto": cot.monto,
                "tiempo_estimado": getattr(cot, "tiempo_estimado", None),
                "estado": cot.estado,
                "detalle": cot.detalle,
                "observaciones": cot.observaciones,
                "taller_nombre": cot.taller.nombre if cot.taller else None,
                "taller_calificacion": cot.taller.calificacion if cot.taller else None,
                "fecha_emision": cot.fecha_emision.isoformat() if cot.fecha_emision else None,
            }
        )
    return rows


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


def _tipo_prioridad_actual(solicitud: Solicitud) -> tuple[str | None, int | None]:
    tipo = None
    prioridad = None
    if solicitud.incidente:
        if solicitud.incidente.tipo:
            tipo = str(solicitud.incidente.tipo)
        if solicitud.incidente.prioridad is not None:
            prioridad = int(solicitud.incidente.prioridad)
    if not tipo and solicitud.emergencia and solicitud.emergencia.tipo:
        tipo = str(solicitud.emergencia.tipo)
    if prioridad is None:
        prioridad = int(solicitud.prioridad) if solicitud.prioridad is not None else None
    return tipo, prioridad


def listar_solicitudes_cliente(db: Session, *, current_user: Usuario) -> list[dict]:
    _validar_identidad_cliente(current_user)
    solicitudes = listar_solicitudes_para_seguimiento(db, current_user=current_user)
    rows: list[dict] = []
    for s in solicitudes:
        tipo, prioridad = _tipo_prioridad_actual(s)
        rows.append(
            {
                "incidente_id": str(s.id),
                "codigo_solicitud": _codigo_solicitud(s),
                "estado": str(s.estado),
                "prioridad": prioridad,
                "tipo": tipo,
                "fecha_reporte": s.creado_en.isoformat() if s.creado_en else None,
                "vehiculo": _serializar_vehiculo(s),
                "acciones_disponibles": _resolver_acciones_disponibles(s, db),
            }
        )
    return rows


def obtener_detalle_solicitud_cliente(db: Session, *, incidente_id: str, current_user: Usuario) -> dict:
    solicitud = consultar_estado_solicitud_cliente(db, incidente_id=incidente_id, current_user=current_user)
    tipo, prioridad = _tipo_prioridad_actual(solicitud)
    taller, tecnico = _serializar_taller_tecnico(solicitud, db)
    ubicacion = _serializar_ubicacion(solicitud)
    cotizacion, pago = _serializar_cotizacion_pago(solicitud, db)
    acciones = _resolver_acciones_disponibles(solicitud, db)
    cotizaciones_disponibles = _serializar_cotizaciones_disponibles(solicitud, db)
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
        "prioridad": prioridad,
        "tipo_problema": tipo,
        "fecha_reporte": solicitud.creado_en.isoformat() if solicitud.creado_en else None,
        "fecha_actualizacion": solicitud.actualizado_en.isoformat() if solicitud.actualizado_en else None,
        "resumen_ia": _resolver_resumen_ia(solicitud),
        "vehiculo": _serializar_vehiculo(solicitud),
        "ubicacion": ubicacion,
        "taller_asignado": taller,
        "tecnico_asignado": tecnico,
        "historial": historial,
        "cotizacion_actual": cotizacion,
        "cotizaciones_disponibles": cotizaciones_disponibles,
        "pago_actual": pago,
        "acciones_disponibles": acciones,
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
    _, pago = _serializar_cotizacion_pago(solicitud, db)
    estado_key = _estado_key(solicitud.estado)
    return {
        "incidente_id": str(solicitud.id),
        "estado": str(solicitud.estado),
        "pago_actual": pago,
        "requiere_pago": estado_key == "cancelado_con_cobro" and pago is not None,
        "mensaje": (
            "Solicitud cancelada con cobro por visita. Debes procesar el pago pendiente."
            if estado_key == "cancelado_con_cobro"
            else "Solicitud cancelada correctamente"
        ),
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
        tenant_id=tenant_id_from(solicitud),
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
        tipo, _prioridad = _tipo_prioridad_actual(s)
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
                "tipo_problema": tipo,
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
