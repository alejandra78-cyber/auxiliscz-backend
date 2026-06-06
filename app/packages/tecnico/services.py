import uuid
import math

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from app.core.time import local_now_naive
from app.core.tenant import assert_same_tenant, tenant_id_from
from app.services.notificaciones import enviar_push_db
from app.models.models import Asignacion, Historial, Notificacion, Solicitud, Tecnico, TrabajoCompletado, Ubicacion, Usuario
from app.packages.pagos.services import _cotizacion_aceptada_solicitud, crear_o_actualizar_pago_pendiente

ESTADOS_COMPARTIR_UBICACION = {
    "tecnico_asignado",
    "en_camino",
    "tecnico_en_lugar",
    "en_diagnostico",
    "diagnostico_completado",
    "en_atencion",
    "cotizacion_emitida",
    "cotizacion_aceptada",
    "en_proceso",
    "trabajo_completado",
}

ACCIONES_ESTADO_TECNICO = {
    "llegue_al_lugar": ("tecnico_en_lugar", "El técnico llegó al lugar de la emergencia"),
    "iniciar_atencion": ("en_proceso", "El técnico inició la atención del servicio"),
    "finalizar_servicio": ("trabajo_completado", "El técnico finalizó la atención del servicio"),
}


def _estado_key(value: str | None) -> str:
    return (value or "").strip().lower().replace(" ", "_")


def _obtener_tecnico_de_usuario(db: Session, current_user: Usuario) -> Tecnico:
    tecnico = db.query(Tecnico).filter(Tecnico.usuario_id == current_user.id).first()
    if not tecnico:
        raise HTTPException(status_code=404, detail="No existe perfil técnico asociado")
    return tecnico


def _codigo_solicitud(solicitud_id: str) -> str:
    return f"SOL-{str(solicitud_id).split('-')[0].upper()}"


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radio = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 2 * radio * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _ultima_ubicacion_tecnico(db: Session, asignacion: Asignacion, tecnico: Tecnico) -> Ubicacion | None:
    row = (
        db.query(Ubicacion)
        .filter(Ubicacion.asignacion_id == asignacion.id, Ubicacion.tecnico_id == tecnico.id)
        .order_by(Ubicacion.registrado_en.desc())
        .first()
    )
    if row:
        return row
    return (
        db.query(Ubicacion)
        .filter(Ubicacion.incidente_id == asignacion.incidente_id, Ubicacion.tecnico_id == tecnico.id)
        .order_by(Ubicacion.registrado_en.desc())
        .first()
    )


def _ultima_ubicacion_cliente(solicitud: Solicitud) -> tuple[float | None, float | None]:
    if solicitud.incidente and solicitud.incidente.latitud is not None and solicitud.incidente.longitud is not None:
        return float(solicitud.incidente.latitud), float(solicitud.incidente.longitud)
    if solicitud.emergencia and solicitud.emergencia.ubicaciones:
        ubicaciones_cliente = [u for u in solicitud.emergencia.ubicaciones if (u.tipo or "cliente") != "tecnico"]
        if ubicaciones_cliente:
            ultima_cli = sorted(
                ubicaciones_cliente,
                key=lambda u: u.registrado_en or local_now_naive(),
            )[-1]
            return float(ultima_cli.latitud), float(ultima_cli.longitud)
    return None, None


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
        .filter(Asignacion.tenant_id == tenant_id_from(tecnico, current_user=current_user))
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
    assert_same_tenant(asignacion, current_user)
    if str(asignacion.tecnico_id or "") != str(tecnico.id):
        raise HTTPException(status_code=403, detail="No autorizado para esta asignación")

    estado = _estado_key(asignacion.estado)
    if estado not in ESTADOS_COMPARTIR_UBICACION:
        raise HTTPException(
            status_code=400,
            detail="Solo puedes compartir ubicación mientras el servicio está activo",
        )

    solicitud = asignacion.solicitud
    if not solicitud or not solicitud.emergencia:
        raise HTTPException(status_code=400, detail="La asignación no está vinculada a una emergencia válida")

    ahora = local_now_naive()
    db.add(
        Ubicacion(
            id=uuid.uuid4(),
            tenant_id=tenant_id_from(asignacion, solicitud, tecnico),
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

    lat_f = float(latitud)
    lng_f = float(longitud)
    tecnico.latitud_actual = lat_f
    tecnico.longitud_actual = lng_f
    tecnico.lat_actual = float(latitud)
    tecnico.lng_actual = float(longitud)
    tecnico.ultima_actualizacion_ubicacion = ahora

    # Avance automático por acción real:
    # - primer envío con técnico asignado => en_camino
    estado_servicio = _estado_key(asignacion.estado)
    if estado_servicio == "tecnico_asignado":
        anterior = asignacion.estado or "tecnico_asignado"
        asignacion.estado = "en_camino"
        if solicitud.incidente:
            solicitud.incidente.estado = "en_camino"
        solicitud.estado = "en_camino"
        db.add(
            Historial(
                id=uuid.uuid4(),
                tenant_id=tenant_id_from(solicitud, asignacion),
                solicitud_id=solicitud.id,
                incidente_id=solicitud.incidente_id,
                estado_anterior=anterior,
                estado_nuevo="en_camino",
                comentario="Cambio automático: técnico inició seguimiento de ubicación",
            )
        )
        estado_servicio = "en_camino"

    lat_cli, lng_cli = _ultima_ubicacion_cliente(solicitud)

    # Si el técnico está cerca del punto de emergencia, marcar llegada automáticamente.
    if estado_servicio == "en_camino":
        if lat_cli is not None and lng_cli is not None:
            distancia = _haversine_km(lat_f, lng_f, lat_cli, lng_cli)
            if distancia <= 0.12:
                anterior = asignacion.estado or "en_camino"
                asignacion.estado = "en_diagnostico"
                if solicitud.incidente:
                    solicitud.incidente.estado = "en_diagnostico"
                solicitud.estado = "en_diagnostico"
                db.add(
                    Historial(
                        id=uuid.uuid4(),
                        tenant_id=tenant_id_from(solicitud, asignacion),
                        solicitud_id=solicitud.id,
                        incidente_id=solicitud.incidente_id,
                        estado_anterior=anterior,
                        estado_nuevo="en_diagnostico",
                        comentario="Cambio automático: técnico llegó al lugar de la emergencia",
                    )
                )
                estado_servicio = "en_diagnostico"

    if estado_servicio in {"en_camino", "en_diagnostico", "en_proceso"}:
        tecnico.estado_operativo = "en_camino" if estado_servicio == "en_camino" else "en_proceso"
        tecnico.disponible = False
        if solicitud.cliente:
            db.add(
                Notificacion(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id_from(solicitud, asignacion),
                    usuario_id=solicitud.cliente.usuario_id,
                    solicitud_id=solicitud.id,
                    incidente_id=solicitud.incidente_id,
                    titulo="Técnico en seguimiento",
                    mensaje=f"El técnico {tecnico.nombre} está compartiendo ubicación en tiempo real.",
                    tipo="seguimiento_tecnico",
                    estado="no_leida",
                )
            )
            enviar_push_db(
                db,
                usuario_id=solicitud.cliente.usuario_id,
                payload={
                    "titulo": "Técnico en seguimiento",
                    "cuerpo": f"El técnico {tecnico.nombre} está compartiendo ubicación en tiempo real.",
                    "tipo": "seguimiento_tecnico",
                    "solicitud_id": solicitud.id,
                    "incidente_id": solicitud.incidente_id or "",
                },
            )

    db.add(tecnico)
    db.commit()
    return {
        "mensaje": "Ubicación enviada correctamente",
        "incidente_id": str(solicitud.id),
        "asignacion_id": str(asignacion.id),
        "tecnico_nombre": tecnico.nombre,
        "estado_servicio": asignacion.estado or "tecnico_asignado",
        "latitud_tecnico": lat_f,
        "longitud_tecnico": lng_f,
        "latitud_cliente": lat_cli,
        "longitud_cliente": lng_cli,
        "ultima_actualizacion": ahora.isoformat(),
    }


def actualizar_estado_desde_tecnico(
    db: Session,
    *,
    current_user: Usuario,
    asignacion_id: str,
    accion: str,
) -> dict:
    if current_user.rol != "tecnico":
        raise HTTPException(status_code=403, detail="Solo técnico puede actualizar este seguimiento")

    accion_key = _estado_key(accion)
    if accion_key not in ACCIONES_ESTADO_TECNICO:
        raise HTTPException(status_code=400, detail="Acción de seguimiento no válida")

    tecnico = _obtener_tecnico_de_usuario(db, current_user)
    asignacion = (
        db.query(Asignacion)
        .options(
        joinedload(Asignacion.solicitud).joinedload(Solicitud.cliente),
        joinedload(Asignacion.solicitud).joinedload(Solicitud.cotizaciones),
        joinedload(Asignacion.solicitud).joinedload(Solicitud.emergencia),
        )
        .filter(Asignacion.id == asignacion_id)
        .first()
    )
    if not asignacion:
        raise HTTPException(status_code=404, detail="Asignación no encontrada")
    assert_same_tenant(asignacion, current_user)
    if str(asignacion.tecnico_id or "") != str(tecnico.id):
        raise HTTPException(status_code=403, detail="No autorizado para esta asignación")

    estado_actual = _estado_key(asignacion.estado)
    if estado_actual in {"pendiente_respuesta", "aceptada_para_cotizar", "cotizacion_enviada", "descartada", "rechazada"}:
        raise HTTPException(status_code=400, detail="El seguimiento aún no está habilitado para esta asignación")

    nuevo_estado, comentario = ACCIONES_ESTADO_TECNICO[accion_key]
    solicitud = asignacion.solicitud
    if not solicitud:
        raise HTTPException(status_code=400, detail="La asignación no tiene solicitud asociada")

    anterior = asignacion.estado or solicitud.estado
    asignacion.estado = nuevo_estado
    solicitud.estado = nuevo_estado
    if solicitud.incidente:
        solicitud.incidente.estado = nuevo_estado
    if solicitud.emergencia:
        solicitud.emergencia.estado = nuevo_estado

    if nuevo_estado in {"tecnico_en_lugar", "en_proceso"}:
        tecnico.estado_operativo = "en_proceso"
        tecnico.disponible = False
    if nuevo_estado == "trabajo_completado":
        cot = _cotizacion_aceptada_solicitud(solicitud, db)
        if not cot:
            resumen = ", ".join(
                f"{str(getattr(c, 'id', ''))}:{getattr(c, 'estado', '')}:{str(getattr(c, 'taller_id', ''))}:{str(getattr(c, 'asignacion_id', ''))}"
                for c in (solicitud.cotizaciones or [])
            ) or "sin cotizaciones"
            raise HTTPException(
                status_code=400,
                detail=f"No existe cotización aceptada para habilitar pago. solicitud_id={solicitud.id}. asignacion_id={asignacion.id}. cotizaciones={resumen}",
            )
        crear_o_actualizar_pago_pendiente(db, cot=cot, solicitud=solicitud)
        tecnico.estado_operativo = "disponible"
        tecnico.disponible = True

    ahora = local_now_naive()
    db.add(
        Historial(
            id=uuid.uuid4(),
            tenant_id=tenant_id_from(solicitud, asignacion),
            solicitud_id=solicitud.id,
            incidente_id=solicitud.incidente_id,
            estado_anterior=anterior,
            estado_nuevo=nuevo_estado,
            comentario=comentario,
        )
    )
    if solicitud.cliente:
        db.add(
            Notificacion(
                id=uuid.uuid4(),
                tenant_id=tenant_id_from(solicitud, asignacion),
                usuario_id=solicitud.cliente.usuario_id,
                solicitud_id=solicitud.id,
                incidente_id=solicitud.incidente_id,
                titulo="Seguimiento actualizado",
                mensaje=comentario,
                tipo="seguimiento_tecnico",
                estado="no_leida",
            )
        )
        enviar_push_db(
            db,
            usuario_id=solicitud.cliente.usuario_id,
            payload={
                "titulo": "Seguimiento actualizado",
                "cuerpo": comentario,
                "tipo": "seguimiento_tecnico",
                "solicitud_id": solicitud.id,
                "incidente_id": solicitud.incidente_id or "",
            },
        )

    db.add(tecnico)
    db.commit()

    ultima_tecnico = _ultima_ubicacion_tecnico(db, asignacion, tecnico)
    lat_tecnico = (
        float(ultima_tecnico.latitud)
        if ultima_tecnico
        else float(tecnico.latitud_actual if tecnico.latitud_actual is not None else tecnico.lat_actual)
        if (tecnico.latitud_actual is not None or tecnico.lat_actual is not None)
        else None
    )
    lng_tecnico = (
        float(ultima_tecnico.longitud)
        if ultima_tecnico
        else float(tecnico.longitud_actual if tecnico.longitud_actual is not None else tecnico.lng_actual)
        if (tecnico.longitud_actual is not None or tecnico.lng_actual is not None)
        else None
    )
    lat_cli, lng_cli = _ultima_ubicacion_cliente(solicitud)
    return {
        "mensaje": comentario,
        "incidente_id": str(solicitud.id),
        "asignacion_id": str(asignacion.id),
        "tecnico_nombre": tecnico.nombre,
        "estado_servicio": nuevo_estado,
        "latitud_tecnico": lat_tecnico,
        "longitud_tecnico": lng_tecnico,
        "latitud_cliente": lat_cli,
        "longitud_cliente": lng_cli,
        "ultima_actualizacion": ahora.isoformat(),
    }


def registrar_trabajo_completado(
    db: Session,
    *,
    current_user: Usuario,
    asignacion_id: str,
    descripcion: str,
    observaciones: str | None,
    evidencias: list[str],
) -> dict:
    if current_user.rol != "tecnico":
        raise HTTPException(status_code=403, detail="Solo técnico puede registrar trabajo completado")

    tecnico = _obtener_tecnico_de_usuario(db, current_user)
    asignacion = (
        db.query(Asignacion)
        .options(
            joinedload(Asignacion.solicitud).joinedload(Solicitud.cliente),
            joinedload(Asignacion.solicitud).joinedload(Solicitud.cotizaciones),
            joinedload(Asignacion.solicitud).joinedload(Solicitud.emergencia),
        )
        .filter(Asignacion.id == asignacion_id)
        .first()
    )
    if not asignacion:
        raise HTTPException(status_code=404, detail="Asignación no encontrada")
    assert_same_tenant(asignacion, current_user)
    if str(asignacion.tecnico_id or "") != str(tecnico.id):
        raise HTTPException(status_code=403, detail="No autorizado para esta asignación")

    solicitud = asignacion.solicitud
    if not solicitud:
        raise HTTPException(status_code=400, detail="La asignación no tiene solicitud")
    estado_actual = _estado_key(asignacion.estado or solicitud.estado)
    if estado_actual not in {"tecnico_en_lugar", "en_diagnostico", "en_atencion", "en_proceso"}:
        raise HTTPException(status_code=400, detail="Solo puedes completar el trabajo después de llegar al lugar")
    cot = _cotizacion_aceptada_solicitud(solicitud, db)
    if not cot:
        resumen = ", ".join(
            f"{str(getattr(c, 'id', ''))}:{getattr(c, 'estado', '')}:{str(getattr(c, 'taller_id', ''))}"
            for c in (solicitud.cotizaciones or [])
        ) or "sin cotizaciones"
        raise HTTPException(
            status_code=400,
            detail=f"No existe cotización aceptada para habilitar pago. solicitud_id={solicitud.id}. cotizaciones={resumen}",
        )

    ahora = local_now_naive()
    evidencia_url = ",".join([e.strip() for e in evidencias if e.strip()]) or None
    trabajo = TrabajoCompletado(
        id=uuid.uuid4(),
        tenant_id=tenant_id_from(solicitud, asignacion),
        solicitud_id=solicitud.id,
        incidente_id=solicitud.incidente_id,
        asignacion_id=asignacion.id,
        taller_id=asignacion.taller_id,
        tecnico_id=tecnico.id,
        descripcion=descripcion.strip(),
        observaciones=(observaciones or "").strip() or None,
        evidencia_url=evidencia_url,
        registrado_por_usuario_id=current_user.id,
        creado_en=ahora,
    )
    db.add(trabajo)

    anterior = asignacion.estado or solicitud.estado
    asignacion.estado = "trabajo_completado"
    asignacion.fecha_finalizacion = ahora
    asignacion.observacion_estado = descripcion.strip()
    solicitud.estado = "trabajo_completado"
    if solicitud.incidente:
        solicitud.incidente.estado = "trabajo_completado"
    if solicitud.emergencia:
        solicitud.emergencia.estado = "trabajo_completado"
    tecnico.estado_operativo = "disponible"
    tecnico.disponible = True

    db.add(
        Historial(
            id=uuid.uuid4(),
            tenant_id=tenant_id_from(solicitud, asignacion),
            solicitud_id=solicitud.id,
            incidente_id=solicitud.incidente_id,
            estado_anterior=anterior,
            estado_nuevo="trabajo_completado",
            comentario=f"Trabajo completado por técnico: {descripcion.strip()}",
        )
    )
    pago = crear_o_actualizar_pago_pendiente(db, cot=cot, solicitud=solicitud)

    if solicitud.cliente:
        db.add(
            Notificacion(
                id=uuid.uuid4(),
                tenant_id=tenant_id_from(solicitud, asignacion),
                usuario_id=solicitud.cliente.usuario_id,
                solicitud_id=solicitud.id,
                incidente_id=solicitud.incidente_id,
                titulo="Servicio completado",
                mensaje="El técnico registró el trabajo completado. Ya puedes realizar el pago.",
                tipo="pago_habilitado",
                estado="no_leida",
            )
        )
        enviar_push_db(
            db,
            usuario_id=solicitud.cliente.usuario_id,
            payload={
                "titulo": "Servicio completado",
                "cuerpo": "El pago ya está habilitado.",
                "tipo": "pago_habilitado",
                "solicitud_id": solicitud.id,
                "incidente_id": solicitud.incidente_id or "",
            },
        )

    db.commit()
    return {
        "mensaje": "Trabajo completado registrado. Pago habilitado para el cliente.",
        "estado_servicio": "trabajo_completado",
        "ultima_actualizacion": ahora.isoformat(),
        "pago_id": str(pago.id),
        "monto_total": float(pago.monto),
        "comision_plataforma": float(pago.comision_plataforma or 0),
        "monto_taller": float(pago.monto_taller or 0),
    }
