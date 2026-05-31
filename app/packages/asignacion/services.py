import uuid
from datetime import datetime, time
import json
import math
import asyncio

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from app.models.models import (
    Asignacion,
    Auditoria,
    Cliente,
    Emergencia,
    Historial,
    Metrica,
    Notificacion,
    Servicio,
    Solicitud,
    SolicitudEvidencia,
    Taller,
    TecnicoEspecialidad,
    Tecnico,
    Turno,
    Usuario,
)
from app.services.asignacion import listar_candidatos
from app.core.time import local_now_naive
from app.core.tenant import assert_same_tenant, stamp_tenant, tenant_id_from

from .schemas import AsignacionDemoOut


def estado_paquete_asignacion() -> AsignacionDemoOut:
    return AsignacionDemoOut(mensaje="Paquete asignacion listo")


CATALOGO_SERVICIOS = {
    "grua": {"codigo": "grua", "nombre": "Grúa", "descripcion": "Traslado del vehículo al taller"},
    "cambio_llanta": {
        "codigo": "cambio_llanta",
        "nombre": "Cambio de llanta",
        "descripcion": "Reemplazo de llanta dañada por repuesto",
    },
    "paso_corriente": {
        "codigo": "paso_corriente",
        "nombre": "Paso de corriente",
        "descripcion": "Asistencia para encendido por batería descargada",
    },
    "combustible": {
        "codigo": "combustible",
        "nombre": "Combustible",
        "descripcion": "Entrega de combustible de emergencia",
    },
    "diagnostico": {
        "codigo": "diagnostico",
        "nombre": "Diagnóstico",
        "descripcion": "Revisión técnica inicial del problema",
    },
    "otro": {"codigo": "otro", "nombre": "Otro", "descripcion": "Servicio no categorizado"},
}

ESTADOS_CU17_VALIDOS = {
    "buscando_talleres",
    "esperando_respuestas",
    "esperando_cotizaciones",
    "cotizaciones_recibidas",
    "taller_confirmado",
    "pendiente_respuesta",
    "aceptada_para_cotizar",
    "cotizacion_enviada",
    "confirmada",
    "descartada",
    "aceptada",
    "tecnico_asignado",
    "en_camino",
    "en_diagnostico",
    "diagnostico_completado",
    "cotizacion_emitida",
    "cotizacion_aceptada",
    "en_proceso",
    "atendido",
    "finalizado",
    "cancelado",
    # Compatibilidad legado
    "asignada",
    "completada",
    "cancelada",
}

TRANSICIONES_CU17: dict[str, set[str]] = {
    "pendiente_respuesta": {"aceptada"},
    "aceptada": {"tecnico_asignado", "cancelado"},
    "tecnico_asignado": {"en_camino", "cancelado"},
    # Compatibilidad: permite ir directo a en_proceso o pasar por diagnóstico.
    "en_camino": {"en_diagnostico", "en_proceso", "cancelado"},
    "en_diagnostico": {"diagnostico_completado", "cancelado"},
    "diagnostico_completado": {"cotizacion_emitida", "cotizacion_aceptada", "en_proceso", "cancelado"},
    "cotizacion_emitida": {"cotizacion_aceptada", "cancelado"},
    "cotizacion_aceptada": {"en_proceso", "cancelado"},
    "en_proceso": {"atendido", "cancelado"},
    "atendido": {"finalizado"},
    "finalizado": set(),
    "cancelado": set(),
}

ESTADOS_ASIGNACION_ACTIVA_CU17 = {
    "confirmada",
    "aceptada",
    "tecnico_asignado",
    "en_camino",
    "en_diagnostico",
    "diagnostico_completado",
    "cotizacion_emitida",
    "cotizacion_aceptada",
    "en_proceso",
}


def codigo_solicitud(solicitud: Solicitud) -> str:
    ref = str(solicitud.id).split("-")[0].upper()
    return f"SOL-{ref}"


def _resolver_solicitud(db: Session, solicitud_id_o_incidente: str) -> Solicitud | None:
    try:
        raw_id = uuid.UUID(str(solicitud_id_o_incidente))
    except ValueError:
        return None
    solicitud = (
        db.query(Solicitud)
        .options(
            joinedload(Solicitud.emergencia),
            joinedload(Solicitud.emergencia).joinedload(Emergencia.ubicaciones),
            joinedload(Solicitud.asignaciones).joinedload(Asignacion.taller),
            joinedload(Solicitud.asignaciones).joinedload(Asignacion.tecnico),
            joinedload(Solicitud.cliente).joinedload(Cliente.usuario),
            joinedload(Solicitud.evidencias).joinedload(SolicitudEvidencia.evidencia),
            joinedload(Solicitud.incidente),
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
            joinedload(Solicitud.emergencia).joinedload(Emergencia.ubicaciones),
            joinedload(Solicitud.asignaciones).joinedload(Asignacion.taller),
            joinedload(Solicitud.asignaciones).joinedload(Asignacion.tecnico),
            joinedload(Solicitud.cliente).joinedload(Cliente.usuario),
            joinedload(Solicitud.evidencias).joinedload(SolicitudEvidencia.evidencia),
            joinedload(Solicitud.incidente),
        )
        .filter(Solicitud.incidente_id == raw_id)
        .first()
    )


def _get_ultimo_asignacion(solicitud: Solicitud) -> Asignacion | None:
    if not solicitud.asignaciones:
        return None
    return sorted(
        solicitud.asignaciones,
        key=lambda x: (x.fecha_asignacion or x.asignado_en or datetime.min),
    )[-1]


def _get_ultima_asignacion_taller(solicitud: Solicitud, taller_id: str) -> Asignacion | None:
    candidatas = [a for a in (solicitud.asignaciones or []) if a.taller_id and str(a.taller_id) == str(taller_id)]
    if not candidatas:
        return None
    return sorted(candidatas, key=lambda x: (x.fecha_asignacion or x.asignado_en or datetime.min), reverse=True)[0]


def _get_ubicacion_incidente(solicitud: Solicitud) -> tuple[float | None, float | None]:
    if solicitud.emergencia and solicitud.emergencia.ubicaciones:
        last = sorted(solicitud.emergencia.ubicaciones, key=lambda u: u.registrado_en or datetime.min)[-1]
        return last.latitud, last.longitud
    return None, None


def _tipo_prioridad_para_asignacion(solicitud: Solicitud) -> tuple[str, int]:
    tipo = (
        (solicitud.incidente.tipo if solicitud.incidente and solicitud.incidente.tipo else None)
        or (solicitud.emergencia.tipo if solicitud.emergencia and solicitud.emergencia.tipo else None)
        or "otro"
    )
    prioridad = (
        int(solicitud.incidente.prioridad) if solicitud.incidente and solicitud.incidente.prioridad is not None
        else int(solicitud.prioridad or 2)
    )
    return str(tipo).strip().lower(), max(1, min(prioridad, 3))


def _obtener_candidatos_para_solicitud(db: Session, solicitud: Solicitud) -> list[dict]:
    lat, lng = _get_ubicacion_incidente(solicitud)
    if lat is None or lng is None:
        raise HTTPException(status_code=400, detail="La solicitud no tiene ubicación para asignación")
    tipo, prioridad = _tipo_prioridad_para_asignacion(solicitud)
    return asyncio.run(
        listar_candidatos(
            db,
            lat=lat,
            lng=lng,
            tipo=tipo,
            prioridad=prioridad,
            tenant_id=tenant_id_from(solicitud),
        )
    )


def _marcar_sin_taller_disponible(db: Session, solicitud: Solicitud, comentario: str) -> None:
    anterior = solicitud.estado
    _guardar_historial(
        db,
        solicitud=solicitud,
        anterior=anterior,
        nuevo="sin_taller_disponible",
        comentario=comentario,
    )
    if solicitud.cliente:
        _crear_notificacion_evento(
            db,
            solicitud=solicitud,
            usuario_id=solicitud.cliente.usuario_id,
            titulo="Sin taller disponible",
            mensaje=f"No se encontró taller disponible para {codigo_solicitud(solicitud)}",
            tipo="sin_taller_disponible",
        )


def _parse_fecha_iso(fecha: str | None, *, end_of_day: bool = False) -> datetime | None:
    if not fecha:
        return None
    raw = fecha.strip()
    if not raw:
        return None
    try:
        if len(raw) == 10:
            base = datetime.strptime(raw, "%Y-%m-%d")
            if end_of_day:
                return datetime.combine(base.date(), time.max)
            return datetime.combine(base.date(), time.min)
        return datetime.fromisoformat(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Fecha inválida: {fecha}")


def _estado_valido(estado: str) -> str:
    s = _normalizar_estado_servicio(estado)
    if s not in ESTADOS_CU17_VALIDOS and s not in {
        "pendiente",
        "aprobada",
        "aceptado",
        "rechazada",
        "en_evaluacion",
        "sin_taller_disponible",
    }:
        raise HTTPException(status_code=400, detail="Estado no válido")
    return s


def _normalizar_estado_servicio(estado: str | None) -> str:
    s = (estado or "").strip().lower()
    aliases = {
        "asignada": "tecnico_asignado",
        "completada": "finalizado",
        "cancelada": "cancelado",
    }
    return aliases.get(s, s)


def _obtener_taller_de_usuario(db: Session, current_user: Usuario) -> Taller | None:
    if current_user.rol != "taller":
        return None
    return db.query(Taller).filter(Taller.usuario_id == current_user.id).first()


def _obtener_tecnico_de_usuario(db: Session, current_user: Usuario) -> Tecnico | None:
    tecnico = db.query(Tecnico).filter(Tecnico.usuario_id == current_user.id).first()
    if tecnico:
        return tecnico
    return db.query(Tecnico).filter(Tecnico.nombre == current_user.nombre).first()


def _guardar_historial(db: Session, solicitud: Solicitud, anterior: str | None, nuevo: str, comentario: str | None = None) -> None:
    db.add(
        Historial(
            id=uuid.uuid4(),
            tenant_id=tenant_id_from(solicitud),
            solicitud_id=solicitud.id,
            incidente_id=solicitud.incidente_id,
            estado_anterior=anterior,
            estado_nuevo=nuevo,
            comentario=comentario,
        )
    )
    solicitud.estado = nuevo
    if solicitud.incidente:
        solicitud.incidente.estado = nuevo
    if solicitud.emergencia:
        solicitud.emergencia.estado = nuevo


def _crear_notificacion_evento(
    db: Session,
    *,
    solicitud: Solicitud,
    usuario_id,
    titulo: str,
    mensaje: str,
    tipo: str,
) -> None:
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


def _incrementar_metrica_taller(db: Session, *, taller_id, codigo: str, delta: float = 1.0) -> None:
    periodo = local_now_naive().strftime("%Y-%m")
    taller = db.query(Taller).filter(Taller.id == taller_id).first()
    row = (
        db.query(Metrica)
        .filter(Metrica.taller_id == taller_id, Metrica.codigo == codigo, Metrica.periodo == periodo)
        .first()
    )
    if row:
        row.valor = float(row.valor or 0) + delta
    else:
        db.add(
            Metrica(
                id=uuid.uuid4(),
                tenant_id=tenant_id_from(taller),
                taller_id=taller_id,
                codigo=codigo,
                valor=delta,
                periodo=periodo,
            )
        )


def _get_resumen_ia(solicitud: Solicitud) -> str | None:
    evidencias = solicitud.evidencias or []
    for link in reversed(evidencias):
        ev = getattr(link, "evidencia", None)
        if ev and ev.tipo == "resumen_ia" and ev.transcripcion:
            return ev.transcripcion
    return None


def _map_tipo_a_servicio(tipo: str | None) -> str:
    t = (tipo or "otro").strip().lower()
    mapping = {
        "llanta": "cambio_llanta",
        "bateria": "paso_corriente",
        "motor": "diagnostico",
        "choque": "grua",
        "llave": "otro",
        "otro": "otro",
        "incierto": "diagnostico",
    }
    return mapping.get(t, "otro")


def _servicio_canonico(codigo: str | None) -> str:
    c = (codigo or "").strip().lower().replace(" ", "_")
    alias = {
        "cambio_llanta": "llanta",
        "paso_corriente": "bateria",
        "combustible": "auxilio_de_combustible",
        "diagnostico": "diagnostico_electrico",
        "grua": "remolque",
    }
    return alias.get(c, c)


def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def sugerir_asignacion_inteligente(db: Session, *, incidente_id: str, current_user: Usuario) -> dict:
    if current_user.rol not in {"taller", "admin"}:
        raise HTTPException(status_code=403, detail="Solo taller/admin puede solicitar sugerencias IA")
    solicitud = _resolver_solicitud(db, incidente_id)
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if solicitud.estado != "aprobada":
        raise HTTPException(status_code=400, detail="La solicitud debe estar aprobada para sugerir asignación")

    servicio = _map_tipo_a_servicio(solicitud.emergencia.tipo if solicitud.emergencia else None)
    servicio_canonico = _servicio_canonico(servicio)
    mi_taller = _obtener_taller_de_usuario(db, current_user) if current_user.rol == "taller" else None
    q = (
        db.query(Tecnico)
        .filter(Tecnico.activo.is_(True), Tecnico.disponible.is_(True), Tecnico.estado_operativo == "disponible")
    )
    if mi_taller:
        q = q.filter(Tecnico.taller_id == mi_taller.id)
    tecnicos = q.all()
    if not tecnicos:
        return {
            "solicitud_id": str(solicitud.id),
            "codigo_solicitud": codigo_solicitud(solicitud),
            "servicio_sugerido": servicio,
            "motivo": "No hay técnicos disponibles para sugerencia",
        }

    lat_inc = None
    lng_inc = None
    if solicitud.emergencia and solicitud.emergencia.ubicaciones:
        last = sorted(solicitud.emergencia.ubicaciones, key=lambda u: u.registrado_en or datetime.min)[-1]
        lat_inc, lng_inc = last.latitud, last.longitud

    best = None
    for t in tecnicos:
        carga = (
            db.query(Asignacion)
            .filter(Asignacion.tecnico_id == t.id, Asignacion.estado.in_(list(ESTADOS_ASIGNACION_ACTIVA_CU17)))
            .count()
        )
        turno = (
            db.query(Turno)
            .filter(Turno.tecnico_id == t.id, Turno.disponible.is_(True))
            .order_by(Turno.inicio.desc())
            .first()
        )
        especialidad_turno = (turno.especialidad or "").strip().lower() if turno and turno.especialidad else ""
        tiene_relacion_especialidad = (
            db.query(TecnicoEspecialidad)
            .join(Servicio, Servicio.id == TecnicoEspecialidad.servicio_id)
            .filter(TecnicoEspecialidad.tecnico_id == t.id, Servicio.codigo == servicio_canonico, Servicio.activo.is_(True))
            .first()
            is not None
        )
        bonus_especialidad = 1.0 if (tiene_relacion_especialidad or servicio_canonico in especialidad_turno) else 0.0
        dist_km = 5.0
        lat_t = t.latitud_actual if t.latitud_actual is not None else t.lat_actual
        lng_t = t.longitud_actual if t.longitud_actual is not None else t.lng_actual
        if lat_inc is not None and lng_inc is not None and lat_t is not None and lng_t is not None:
            dist_km = _haversine(lat_inc, lng_inc, float(lat_t), float(lng_t))
        score = (2.5 - min(dist_km, 20) / 10.0) + bonus_especialidad + (2.0 - min(carga, 4) * 0.5)
        item = (score, t, dist_km, carga, especialidad_turno)
        if best is None or score > best[0]:
            best = item

    if not best:
        return {
            "solicitud_id": str(solicitud.id),
            "codigo_solicitud": codigo_solicitud(solicitud),
            "servicio_sugerido": servicio,
            "motivo": "No se pudo calcular sugerencia",
        }

    score, tsel, dist_km, carga, especialidad = best
    return {
        "solicitud_id": str(solicitud.id),
        "codigo_solicitud": codigo_solicitud(solicitud),
        "tecnico_id": str(tsel.id),
        "tecnico_nombre": tsel.nombre,
        "taller_id": str(tsel.taller_id),
        "taller_nombre": tsel.taller.nombre if tsel.taller else None,
        "servicio_sugerido": servicio,
        "puntaje": round(float(score), 3),
        "motivo": f"Distancia~{dist_km:.1f}km, carga={carga}, especialidad='{especialidad or 'general'}'",
    }


def listar_servicios_catalogo() -> list[dict]:
    return list(CATALOGO_SERVICIOS.values())


def listar_tecnicos_disponibles(
    db: Session,
    *,
    current_user: Usuario,
    solicitud_id: str | None = None,
) -> list[Tecnico]:
    q = (
        db.query(Tecnico)
        .filter(Tecnico.activo.is_(True), Tecnico.disponible.is_(True), Tecnico.estado_operativo == "disponible")
    )
    if current_user.rol == "taller":
        mi_taller = _obtener_taller_de_usuario(db, current_user)
        if not mi_taller:
            raise HTTPException(status_code=403, detail="El usuario taller no tiene perfil de taller")
        q = q.filter(Tecnico.taller_id == mi_taller.id)
    elif current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="Solo taller/admin puede consultar técnicos disponibles")

    if solicitud_id:
        solicitud = _resolver_solicitud(db, solicitud_id)
        if not solicitud:
            raise HTTPException(status_code=404, detail="Solicitud no encontrada")
        ultima = _get_ultimo_asignacion(solicitud)
        if ultima and ultima.taller_id:
            q = q.filter(Tecnico.taller_id == ultima.taller_id)
    return q.order_by(Tecnico.nombre.asc()).all()


async def buscar_talleres_candidatos_cercanos(
    db: Session,
    *,
    lat: float,
    lng: float,
    tipo: str,
    prioridad: int,
) -> list[dict]:
    return await listar_candidatos(db, lat=lat, lng=lng, tipo=tipo, prioridad=prioridad)


def listar_candidatos_para_solicitud(
    db: Session,
    *,
    incidente_id: str,
    current_user: Usuario,
) -> list[dict]:
    if current_user.rol not in {"taller", "admin"}:
        raise HTTPException(status_code=403, detail="Solo taller/admin puede consultar candidatos")
    solicitud = _resolver_solicitud(db, incidente_id)
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    return _obtener_candidatos_para_solicitud(db, solicitud)


async def asignar_taller_automaticamente(
    db: Session,
    *,
    solicitud_id: str,
    lat: float | None = None,
    lng: float | None = None,
    tipo: str | None = None,
    prioridad: int | None = None,
):
    solicitud = _resolver_solicitud(db, solicitud_id)
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if solicitud.estado in {"cancelada", "cancelado", "completada", "finalizado"}:
        raise HTTPException(status_code=400, detail="La solicitud ya está cerrada")

    existentes_candidatas = [
        a
        for a in (solicitud.asignaciones or [])
        if (a.estado or "").lower()
        in {"pendiente_respuesta", "aceptada_para_cotizar", "cotizacion_enviada", "confirmada"}
    ]
    if existentes_candidatas:
        raise HTTPException(status_code=400, detail="La solicitud ya tiene candidatos activos")

    if lat is None or lng is None:
        lat_calc, lng_calc = _get_ubicacion_incidente(solicitud)
    else:
        lat_calc, lng_calc = lat, lng
    tipo_calc, prioridad_calc = _tipo_prioridad_para_asignacion(solicitud)
    if tipo:
        tipo_calc = str(tipo).strip().lower()
    if prioridad is not None:
        prioridad_calc = int(prioridad)
    if lat_calc is None or lng_calc is None:
        raise HTTPException(status_code=400, detail="No se puede asignar sin ubicación de incidente")

    candidatos = await listar_candidatos(
        db,
        lat=float(lat_calc),
        lng=float(lng_calc),
        tipo=tipo_calc,
        prioridad=prioridad_calc,
        tenant_id=None,
    )
    if not candidatos:
        _marcar_sin_taller_disponible(db, solicitud, "No hay talleres candidatos para asignación automática")
        db.commit()
        return None
    talleres_creados: list[Taller] = []
    for candidato in candidatos[:3]:
        taller_id = candidato.get("taller_id")
        if not taller_id:
            continue
        taller = None
        try:
            taller_uuid = uuid.UUID(str(taller_id))
            taller = db.query(Taller).filter(Taller.id == taller_uuid).first()
        except Exception:
            taller = None
        if not taller:
            taller = next((t for t in db.query(Taller).all() if str(t.id) == str(taller_id)), None)
        if not taller:
            continue
        talleres_creados.append(taller)
        db.add(
            Asignacion(
                id=uuid.uuid4(),
                tenant_id=getattr(taller, "tenant_id", None),
                solicitud_id=solicitud.id,
                incidente_id=solicitud.incidente_id,
                taller_id=taller.id,
                tecnico_id=None,
                fecha_asignacion=local_now_naive(),
                distancia_km=float(candidato.get("distancia_km", 0) or 0),
                puntaje=float(candidato.get("puntaje", 0) or 0),
                motivo_asignacion=str(candidato.get("motivo") or "Candidato automático para cotizar"),
                origen_asignacion="automatica",
                tipo_asignacion="candidata",
                es_definitiva=False,
                estado="pendiente_respuesta",
            )
        )
        if taller.usuario_id:
            _crear_notificacion_evento(
                db,
                solicitud=solicitud,
                usuario_id=taller.usuario_id,
                titulo="Nueva solicitud para cotizar",
                mensaje=f"Recibiste {codigo_solicitud(solicitud)} para decidir si participas y cotizas",
                tipo="solicitud_candidata",
            )
    if not talleres_creados:
        _marcar_sin_taller_disponible(db, solicitud, "No se pudo resolver ningún taller candidato")
        db.commit()
        return None
    _guardar_historial(
        db,
        solicitud=solicitud,
        anterior=solicitud.estado,
        nuevo="esperando_respuestas",
        comentario=f"Solicitud enviada a {len(talleres_creados)} taller(es) candidato(s)",
    )
    db.add(
        Auditoria(
            id=uuid.uuid4(),
            usuario_id=None,
            accion="cu16_candidatos_automaticos",
            modulo="asignacion",
            detalle=f"Solicitud {solicitud.id} enviada a {len(talleres_creados)} candidato(s)",
        )
    )
    for taller in talleres_creados:
        _incrementar_metrica_taller(db, taller_id=taller.id, codigo="cu16_candidatos")
    db.commit()
    return talleres_creados[0]


async def reasignar_taller(
    db: Session,
    *,
    solicitud_id: str,
    lat: float | None = None,
    lng: float | None = None,
    tipo: str | None = None,
    prioridad: int | None = None,
):
    solicitud = _resolver_solicitud(db, solicitud_id)
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if lat is None or lng is None:
        lat_calc, lng_calc = _get_ubicacion_incidente(solicitud)
    else:
        lat_calc, lng_calc = lat, lng
    tipo_calc, prioridad_calc = _tipo_prioridad_para_asignacion(solicitud)
    if tipo:
        tipo_calc = str(tipo).strip().lower()
    if prioridad is not None:
        prioridad_calc = int(prioridad)
    if lat_calc is None or lng_calc is None:
        _marcar_sin_taller_disponible(db, solicitud, "Reasignación fallida: solicitud sin ubicación")
        db.commit()
        return None

    candidatos = await listar_candidatos(
        db,
        lat=float(lat_calc),
        lng=float(lng_calc),
        tipo=tipo_calc,
        prioridad=prioridad_calc,
        tenant_id=None,
    )
    if not candidatos:
        _marcar_sin_taller_disponible(db, solicitud, "No hay candidatos para reasignación")
        db.commit()
        return None
    ultima = _get_ultimo_asignacion(solicitud)
    ultimo_taller = str(ultima.taller_id) if ultima and ultima.taller_id else None
    candidato = next((c for c in candidatos if str(c.get("taller_id")) != ultimo_taller), None)
    if not candidato:
        # Si no existe alternativo, reutilizamos el mejor candidato disponible.
        # Evita dejar la solicitud sin asignar cuando solo hay 1 taller elegible.
        candidato = candidatos[0]
    nuevo_taller = None
    try:
        nuevo_taller_uuid = uuid.UUID(str(candidato["taller_id"]))
        nuevo_taller = db.query(Taller).filter(Taller.id == nuevo_taller_uuid).first()
    except Exception:
        nuevo_taller = None
    if not nuevo_taller:
        nuevo_taller = next((t for t in db.query(Taller).all() if str(t.id) == str(candidato["taller_id"])), None)
    if not nuevo_taller:
        _marcar_sin_taller_disponible(
            db,
            solicitud,
            f"No se pudo resolver el taller de reasignación ({candidato.get('taller_id')})",
        )
        db.commit()
        return None
    tenant_asignacion = getattr(nuevo_taller, "tenant_id", None)
    solicitud.tenant_id = tenant_asignacion
    if solicitud.incidente:
        solicitud.incidente.tenant_id = tenant_asignacion
    if solicitud.emergencia:
        solicitud.emergencia.tenant_id = tenant_asignacion
    db.add(
        Asignacion(
            id=uuid.uuid4(),
            tenant_id=tenant_asignacion,
            solicitud_id=solicitud.id,
            incidente_id=solicitud.incidente_id,
            taller_id=nuevo_taller.id,
            tecnico_id=None,
            fecha_asignacion=local_now_naive(),
            distancia_km=float(candidato.get("distancia_km", 0) or 0),
            puntaje=float(candidato.get("puntaje", 0) or 0),
            motivo_asignacion=str(candidato.get("motivo") or "Reasignación automática por motor"),
            origen_asignacion="reasignacion",
            estado="pendiente_respuesta",
        )
    )
    _guardar_historial(
        db,
        solicitud=solicitud,
        anterior=solicitud.estado,
        nuevo="asignada",
        comentario="Reasignación automática",
    )
    if nuevo_taller and nuevo_taller.usuario_id:
        _crear_notificacion_evento(
            db,
            solicitud=solicitud,
            usuario_id=nuevo_taller.usuario_id,
            titulo="Nueva solicitud reasignada",
            mensaje=f"Se te reasignó {codigo_solicitud(solicitud)} para evaluación",
            tipo="reasignacion",
        )
    db.add(
        Auditoria(
            id=uuid.uuid4(),
            usuario_id=None,
            accion="cu16_reasignacion_automatica",
            modulo="asignacion",
            detalle=f"Solicitud {solicitud.id} reasignada al taller {candidato.get('taller_id')}",
        )
    )
    db.commit()
    return candidato


def listar_solicitudes_servicio(
    db: Session,
    *,
    current_user: Usuario,
    estado: str | None = None,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    taller_id: str | None = None,
) -> list[Solicitud]:
    if current_user.rol not in {"taller", "admin", "tecnico"}:
        raise HTTPException(status_code=403, detail="Solo taller/admin/tecnico puede consultar solicitudes")
    fecha_desde_dt = _parse_fecha_iso(fecha_desde, end_of_day=False)
    fecha_hasta_dt = _parse_fecha_iso(fecha_hasta, end_of_day=True)
    if fecha_desde_dt and fecha_hasta_dt and fecha_desde_dt > fecha_hasta_dt:
        raise HTTPException(status_code=400, detail="fecha_desde no puede ser mayor a fecha_hasta")
    estado_norm = (estado or "").strip().lower() or None
    if estado_norm:
        estado_norm = _normalizar_estado_servicio(estado_norm)
    if estado_norm and estado_norm not in {
        "pendiente",
        "buscando_talleres",
        "esperando_respuestas",
        "esperando_cotizaciones",
        "cotizaciones_recibidas",
        "taller_confirmado",
        "en_evaluacion",
        "aprobada",
        "rechazada",
        "pendiente_respuesta",
        "aceptada_para_cotizar",
        "cotizacion_enviada",
        "confirmada",
        "descartada",
        "aceptada",
        "tecnico_asignado",
        "en_camino",
        "en_diagnostico",
        "diagnostico_completado",
        "cotizacion_emitida",
        "cotizacion_aceptada",
        "en_proceso",
        "atendido",
        "finalizado",
        "cancelado",
        "sin_taller_disponible",
    }:
        raise HTTPException(status_code=400, detail="Filtro de estado inválido")

    q = db.query(Solicitud).options(
        joinedload(Solicitud.emergencia),
        joinedload(Solicitud.emergencia).joinedload(Emergencia.ubicaciones),
        joinedload(Solicitud.cliente).joinedload(Cliente.usuario),
        joinedload(Solicitud.asignaciones).joinedload(Asignacion.taller),
        joinedload(Solicitud.asignaciones).joinedload(Asignacion.tecnico),
        joinedload(Solicitud.evidencias).joinedload(SolicitudEvidencia.evidencia),
        joinedload(Solicitud.incidente),
    )
    if current_user.rol == "taller":
        mi_taller = _obtener_taller_de_usuario(db, current_user)
        if not mi_taller:
            raise HTTPException(status_code=403, detail="El usuario taller no tiene perfil de taller")
        q = q.join(Asignacion, Asignacion.solicitud_id == Solicitud.id).filter(Asignacion.taller_id == mi_taller.id)
    elif current_user.rol == "tecnico":
        mi_tecnico = _obtener_tecnico_de_usuario(db, current_user)
        if not mi_tecnico:
            raise HTTPException(status_code=403, detail="No existe perfil técnico asociado a este usuario")
        q = q.join(Asignacion, Asignacion.solicitud_id == Solicitud.id).filter(Asignacion.tecnico_id == mi_tecnico.id)
    elif current_user.rol == "admin" and taller_id:
        q = q.join(Asignacion, Asignacion.solicitud_id == Solicitud.id).filter(Asignacion.taller_id == taller_id)
    if estado_norm:
        q = q.filter(Solicitud.estado == estado_norm)
    if fecha_desde_dt:
        q = q.filter(Solicitud.creado_en >= fecha_desde_dt)
    if fecha_hasta_dt:
        q = q.filter(Solicitud.creado_en <= fecha_hasta_dt)
    rows = q.order_by(Solicitud.creado_en.desc()).all()
    dedup: dict[str, Solicitud] = {}
    for row in rows:
        key = str(row.id)
        if key not in dedup:
            dedup[key] = row
    return list(dedup.values())


def obtener_detalle_solicitud_servicio(
    db: Session,
    *,
    incidente_id: str,
    current_user: Usuario,
) -> Solicitud:
    if current_user.rol not in {"taller", "admin", "tecnico"}:
        raise HTTPException(status_code=403, detail="Solo taller/admin/tecnico puede consultar detalle de solicitudes")
    solicitud = _resolver_solicitud(db, incidente_id)
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if current_user.rol == "taller":
        mi_taller = _obtener_taller_de_usuario(db, current_user)
        if not mi_taller:
            raise HTTPException(status_code=403, detail="El usuario taller no tiene perfil de taller")
        asignacion_taller = next((a for a in solicitud.asignaciones if str(a.taller_id) == str(mi_taller.id)), None)
        if not asignacion_taller:
            raise HTTPException(status_code=403, detail="No autorizado para consultar esta solicitud")
    elif current_user.rol == "tecnico":
        mi_tecnico = _obtener_tecnico_de_usuario(db, current_user)
        if not mi_tecnico:
            raise HTTPException(status_code=403, detail="No existe perfil técnico asociado a este usuario")
        asignacion_tecnico = next((a for a in solicitud.asignaciones if str(a.tecnico_id or "") == str(mi_tecnico.id)), None)
        if not asignacion_tecnico:
            raise HTTPException(status_code=403, detail="No autorizado para consultar esta solicitud")
    return solicitud


def evaluar_solicitud_servicio(
    db: Session,
    *,
    incidente_id: str,
    current_user: Usuario,
    aprobar: bool,
    observacion: str | None,
) -> Solicitud:
    if current_user.rol != "taller":
        raise HTTPException(status_code=403, detail="Solo taller puede evaluar solicitudes")
    solicitud = _resolver_solicitud(db, incidente_id)
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if solicitud.estado in {"completada", "finalizado", "cancelada", "cancelado", "rechazada"}:
        raise HTTPException(status_code=400, detail="La solicitud ya fue cerrada")

    # Flujo CU15 para actor Taller: evaluar SOLO solicitudes asignadas a su taller.
    mi_taller = _obtener_taller_de_usuario(db, current_user)
    if not mi_taller:
        raise HTTPException(status_code=403, detail="El usuario taller no tiene perfil de taller")

    asig_actual = _get_ultima_asignacion_taller(solicitud, str(mi_taller.id))
    if not asig_actual:
        raise HTTPException(status_code=403, detail="No autorizado: la solicitud no pertenece a este taller")

    if (asig_actual.estado or "").lower() not in {"pendiente_respuesta", "asignada"}:
        raise HTTPException(status_code=400, detail="La asignación no está pendiente de evaluación")

    estado_anterior = solicitud.estado
    asig_actual.fecha_respuesta_taller = local_now_naive()

    if aprobar:
            # Validaciones operativas de CU07
            estado_operativo = (mi_taller.estado_operativo or "disponible").lower()
            if estado_operativo in {"cerrado", "fuera_de_servicio"} or not mi_taller.disponible:
                raise HTTPException(status_code=400, detail="El taller no está disponible para aceptar solicitudes")

            capacidad_max = int(getattr(mi_taller, "capacidad_maxima", 1) or 1)
            carga_activa = (
                db.query(Asignacion)
                .filter(
                    Asignacion.taller_id == mi_taller.id,
                    Asignacion.estado.in_(list(ESTADOS_ASIGNACION_ACTIVA_CU17)),
                )
                .count()
            )
            if carga_activa >= capacidad_max:
                raise HTTPException(status_code=400, detail="El taller no tiene capacidad disponible")

            asig_actual.estado = "aceptada_para_cotizar"
            asig_actual.motivo_rechazo = None
            asig_actual.fecha_aceptacion = local_now_naive()
            nuevo = "esperando_cotizaciones"
            _guardar_historial(
                db,
                solicitud,
                estado_anterior,
                nuevo,
                observacion or f"Taller {mi_taller.nombre} aceptó participar y puede cotizar",
            )
            db.add(
                Auditoria(
                    id=uuid.uuid4(),
                    usuario_id=current_user.id,
                    accion="cu15_aceptar_solicitud",
                    modulo="asignacion",
                    detalle=f"Solicitud {solicitud.id} aceptada por taller {mi_taller.id}",
                )
            )
            if solicitud.cliente:
                _crear_notificacion_evento(
                    db,
                    solicitud=solicitud,
                    usuario_id=solicitud.cliente.usuario_id,
                    titulo="Solicitud aceptada",
                    mensaje=f"Un taller aceptó revisar tu solicitud {codigo_solicitud(solicitud)} y preparará una cotización",
                    tipo="evaluacion_aceptada",
                )
            _incrementar_metrica_taller(db, taller_id=mi_taller.id, codigo="cu15_aceptada")
    else:
            asig_actual.estado = "rechazada"
            asig_actual.motivo_rechazo = observacion or "Rechazada por taller"
            db.add(
                Auditoria(
                    id=uuid.uuid4(),
                    usuario_id=current_user.id,
                    accion="cu15_rechazar_solicitud",
                    modulo="asignacion",
                    detalle=f"Solicitud {solicitud.id} rechazada por taller {mi_taller.id}. Motivo: {asig_actual.motivo_rechazo}",
                )
            )

            restantes = [
                a
                for a in (solicitud.asignaciones or [])
                if (a.estado or "").lower() in {"pendiente_respuesta", "aceptada_para_cotizar", "cotizacion_enviada"}
            ]
            nuevo = "esperando_respuestas" if restantes else "cancelada"
            _guardar_historial(
                db,
                solicitud,
                estado_anterior,
                nuevo,
                (
                    f"Taller {mi_taller.nombre} rechazó participar"
                    if restantes
                    else "Todos los talleres candidatos rechazaron la solicitud"
                ),
            )
            if solicitud.cliente:
                _crear_notificacion_evento(
                    db,
                    solicitud=solicitud,
                    usuario_id=solicitud.cliente.usuario_id,
                    titulo="Respuesta de taller",
                    mensaje=(
                        "Un taller rechazó participar; seguimos esperando otras respuestas"
                        if restantes
                        else "No hay talleres disponibles para esta solicitud"
                    ),
                    tipo="evaluacion_rechazada",
                )
            _incrementar_metrica_taller(db, taller_id=mi_taller.id, codigo="cu15_rechazada")

    db.commit()
    db.refresh(solicitud)
    return solicitud


def asignar_servicio(
    db: Session,
    *,
    incidente_id: str,
    current_user: Usuario,
    tecnico_id: str,
    servicio: str,
    taller_id: str | None,
    observacion: str | None,
) -> Solicitud:
    if current_user.rol != "taller":
        raise HTTPException(status_code=403, detail="Solo taller puede asignar servicios")
    solicitud = _resolver_solicitud(db, incidente_id)
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if solicitud.estado in {"completada", "finalizado", "cancelada", "cancelado", "rechazada"}:
        raise HTTPException(status_code=400, detail="La solicitud ya fue cerrada")
    if solicitud.estado not in {"taller_confirmado", "tecnico_asignado", "en_camino", "en_proceso"}:
        raise HTTPException(status_code=400, detail="Solo se puede asignar técnico cuando el cliente confirmó un taller")

    servicio_key = (servicio or "").strip().lower().replace(" ", "_")
    if servicio_key not in CATALOGO_SERVICIOS:
        raise HTTPException(status_code=400, detail="Servicio no válido para asignación")

    taller_asig = taller_id
    mi_taller = _obtener_taller_de_usuario(db, current_user)
    if not mi_taller:
        raise HTTPException(status_code=403, detail="El usuario taller no tiene perfil de taller")
    taller_asig = str(mi_taller.id)

    asig_actual = _get_ultima_asignacion_taller(solicitud, taller_asig)
    if not asig_actual:
        raise HTTPException(status_code=403, detail="La solicitud no tiene asignación activa para este taller")
    if _normalizar_estado_servicio(asig_actual.estado) not in {"confirmada", "tecnico_asignado", "en_camino", "en_proceso"}:
        raise HTTPException(status_code=400, detail="La asignación debe estar confirmada para asignar técnico")

    tec = db.query(Tecnico).filter(Tecnico.id == tecnico_id).first()
    if not tec:
        raise HTTPException(status_code=404, detail="Técnico no encontrado")
    if (not tec.activo) or (not tec.disponible) or (tec.estado_operativo != "disponible"):
        raise HTTPException(status_code=400, detail="El técnico no está disponible")
    if taller_asig and str(tec.taller_id) != str(taller_asig):
        raise HTTPException(status_code=400, detail="El técnico no pertenece al taller asignado")
    servicio_canonico = _servicio_canonico(servicio_key)
    tiene_especialidad = (
        db.query(TecnicoEspecialidad)
        .join(Servicio, Servicio.id == TecnicoEspecialidad.servicio_id)
        .filter(TecnicoEspecialidad.tecnico_id == tec.id, Servicio.codigo == servicio_canonico, Servicio.activo.is_(True))
        .first()
        is not None
    )
    if not tiene_especialidad:
        raise HTTPException(status_code=400, detail="El técnico no tiene especialidad para el servicio seleccionado")

    asig_actual.tecnico_id = tec.id
    asig_actual.servicio = servicio_key
    asig_actual.estado = "tecnico_asignado"
    asig_actual.fecha_asignacion = asig_actual.fecha_asignacion or local_now_naive()
    asig_actual.origen_asignacion = asig_actual.origen_asignacion or "manual"
    tec.disponible = False
    tec.estado_operativo = "ocupado"
    _guardar_historial(
        db,
        solicitud=solicitud,
        anterior=solicitud.estado,
        nuevo="tecnico_asignado",
        comentario=observacion or f"Asignación manual de servicio: {CATALOGO_SERVICIOS[servicio_key]['nombre']}",
    )
    if solicitud.cliente:
        _crear_notificacion_evento(
            db,
            solicitud=solicitud,
            usuario_id=solicitud.cliente.usuario_id,
            titulo="Servicio asignado",
            mensaje=f"Tu solicitud {codigo_solicitud(solicitud)} fue asignada a {tec.nombre}",
            tipo="asignacion",
        )
    if taller_asig:
        _incrementar_metrica_taller(db, taller_id=taller_asig, codigo="cu16_asignaciones")
    db.commit()
    db.refresh(solicitud)
    return solicitud


def actualizar_estado_servicio(
    db: Session,
    *,
    incidente_id: str,
    current_user: Usuario,
    estado: str,
    observacion: str | None = None,
    tecnico_id: str | None = None,
) -> Solicitud:
    if current_user.rol not in {"taller", "tecnico"}:
        raise HTTPException(status_code=403, detail="Solo taller/técnico puede actualizar estado")
    solicitud = _resolver_solicitud(db, incidente_id)
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if solicitud.estado in {"rechazada", "cancelada", "cancelado", "completada", "finalizado"}:
        raise HTTPException(status_code=400, detail="La solicitud ya fue cerrada")

    asig_actual = None
    mi_taller = None
    mi_tecnico = None
    if current_user.rol == "taller":
        mi_taller = _obtener_taller_de_usuario(db, current_user)
        if not mi_taller:
            raise HTTPException(status_code=403, detail="El usuario taller no tiene perfil de taller")
        asig_actual = _get_ultima_asignacion_taller(solicitud, str(mi_taller.id))
    else:
        mi_tecnico = _obtener_tecnico_de_usuario(db, current_user)
        if not mi_tecnico:
            raise HTTPException(status_code=403, detail="No existe perfil técnico asociado a este usuario")
        asig_actual = (
            db.query(Asignacion)
            .filter(Asignacion.solicitud_id == solicitud.id, Asignacion.tecnico_id == mi_tecnico.id)
            .order_by(Asignacion.fecha_asignacion.desc().nullslast(), Asignacion.asignado_en.desc().nullslast())
            .first()
        )
        mi_taller = mi_tecnico.taller

    if not asig_actual or not mi_taller or str(asig_actual.taller_id) != str(mi_taller.id):
        raise HTTPException(status_code=403, detail="No autorizado para actualizar esta solicitud")

    estado_actual = _normalizar_estado_servicio(asig_actual.estado or solicitud.estado)
    estado_nuevo = _estado_valido(estado)
    estado_nuevo = _normalizar_estado_servicio(estado_nuevo)

    if estado_actual not in TRANSICIONES_CU17:
        raise HTTPException(status_code=400, detail=f"Estado actual no gestionable por CU17: {estado_actual}")
    permitidos = TRANSICIONES_CU17.get(estado_actual, set())
    if estado_nuevo not in permitidos:
        raise HTTPException(status_code=400, detail=f"No se puede pasar de {estado_actual} a {estado_nuevo}")

    if estado_actual == "pendiente_respuesta":
        raise HTTPException(status_code=400, detail="Primero debes aceptar la solicitud en CU15")

    if estado_nuevo == "tecnico_asignado":
        tecnico_obj = None
        tecnico_destino = tecnico_id or (str(mi_tecnico.id) if mi_tecnico else None) or (str(asig_actual.tecnico_id) if asig_actual.tecnico_id else None)
        if not tecnico_destino:
            raise HTTPException(status_code=400, detail="Para tecnico_asignado debes enviar tecnico_id")
        tecnico_obj = db.query(Tecnico).filter(Tecnico.id == tecnico_destino).first()
        if not tecnico_obj:
            raise HTTPException(status_code=404, detail="Técnico no encontrado")
        if str(tecnico_obj.taller_id) != str(mi_taller.id):
            raise HTTPException(status_code=400, detail="El técnico no pertenece al taller")
        if (
            (not tecnico_obj.activo)
            or (not tecnico_obj.disponible)
            or (tecnico_obj.estado_operativo != "disponible")
        ) and str(asig_actual.tecnico_id or "") != str(tecnico_obj.id):
            raise HTTPException(status_code=400, detail="El técnico no está disponible")
        asig_actual.tecnico_id = tecnico_obj.id
        tecnico_obj.disponible = False
        tecnico_obj.estado_operativo = "ocupado"

    if estado_nuevo in {"en_camino", "en_diagnostico", "en_proceso"} and not asig_actual.tecnico_id:
        raise HTTPException(status_code=400, detail=f"Para {estado_nuevo} debes tener técnico asignado")

    ahora = local_now_naive()
    if estado_nuevo == "en_camino":
        asig_actual.fecha_inicio_camino = asig_actual.fecha_inicio_camino or ahora
        if asig_actual.tecnico:
            asig_actual.tecnico.estado_operativo = "en_camino"
            asig_actual.tecnico.disponible = False
    if estado_nuevo == "en_diagnostico":
        asig_actual.fecha_inicio_servicio = asig_actual.fecha_inicio_servicio or ahora
        if asig_actual.tecnico:
            asig_actual.tecnico.estado_operativo = "en_proceso"
            asig_actual.tecnico.disponible = False
    if estado_nuevo == "en_proceso":
        asig_actual.fecha_inicio_servicio = asig_actual.fecha_inicio_servicio or ahora
        if asig_actual.tecnico:
            asig_actual.tecnico.estado_operativo = "en_proceso"
            asig_actual.tecnico.disponible = False
    if estado_nuevo in {"finalizado", "cancelado"}:
        asig_actual.fecha_finalizacion = asig_actual.fecha_finalizacion or ahora

    asig_actual.estado = estado_nuevo
    if observacion:
        asig_actual.observacion_estado = observacion.strip()

    if asig_actual.tecnico and estado_nuevo in {"atendido", "finalizado", "cancelado"}:
        asig_actual.tecnico.disponible = True
        asig_actual.tecnico.estado_operativo = "disponible"

    comentario = observacion or "Actualización de estado del servicio"
    _guardar_historial(db, solicitud, solicitud.estado, estado_nuevo, comentario)

    db.add(
        Auditoria(
            id=uuid.uuid4(),
            usuario_id=current_user.id,
            accion="cu17_actualizar_estado",
            modulo="asignacion",
            detalle=(
                f"Solicitud {solicitud.id} estado {estado_actual}->{estado_nuevo}; "
                f"taller={mi_taller.id}; tecnico={asig_actual.tecnico_id or 'n/a'}"
            ),
        )
    )

    if solicitud.cliente:
        _crear_notificacion_evento(
            db,
            solicitud=solicitud,
            usuario_id=solicitud.cliente.usuario_id,
            titulo="Estado del servicio actualizado",
            mensaje=f"Tu solicitud {codigo_solicitud(solicitud)} cambió a {estado_nuevo}",
            tipo="estado_servicio",
        )
    if estado_nuevo == "en_camino" and solicitud.cliente:
        _crear_notificacion_evento(
            db,
            solicitud=solicitud,
            usuario_id=solicitud.cliente.usuario_id,
            titulo="Técnico en camino",
            mensaje=f"El técnico ya va en camino para {codigo_solicitud(solicitud)}",
            tipo="tecnico_en_camino",
        )

    if asig_actual.taller_id:
        _incrementar_metrica_taller(db, taller_id=asig_actual.taller_id, codigo=f"cu17_{estado_nuevo}")

    db.commit()
    db.refresh(solicitud)
    return solicitud


ACCIONES_OPERATIVAS_CU17 = {
    "aceptar_solicitud",
    "rechazar_solicitud",
    "asignar_tecnico",
    "iniciar_ruta",
    "llegue_al_lugar",
    "completar_diagnostico",
    "iniciar_atencion",
    "generar_cotizacion",
    "finalizar_servicio",
}


def ejecutar_accion_operativa_servicio(
    db: Session,
    *,
    incidente_id: str,
    current_user: Usuario,
    accion: str,
    observacion: str | None = None,
    tecnico_id: str | None = None,
    servicio: str | None = None,
) -> Solicitud:
    a = (accion or "").strip().lower()
    if a not in ACCIONES_OPERATIVAS_CU17:
        raise HTTPException(status_code=400, detail="Acción operativa no válida")

    if a == "aceptar_solicitud":
        return evaluar_solicitud_servicio(
            db,
            incidente_id=incidente_id,
            current_user=current_user,
            aprobar=True,
            observacion=observacion,
        )

    if a == "rechazar_solicitud":
        return evaluar_solicitud_servicio(
            db,
            incidente_id=incidente_id,
            current_user=current_user,
            aprobar=False,
            observacion=observacion or "Rechazo operativo desde CU17",
        )

    if a == "asignar_tecnico":
        if not tecnico_id:
            raise HTTPException(status_code=400, detail="Para asignar técnico debes seleccionar un técnico")
        servicio_final = (servicio or "").strip().lower().replace(" ", "_") or "diagnostico"
        return asignar_servicio(
            db,
            incidente_id=incidente_id,
            current_user=current_user,
            tecnico_id=tecnico_id,
            servicio=servicio_final,
            taller_id=None,
            observacion=observacion or "Asignación operativa de técnico",
        )

    if a == "iniciar_ruta":
        return actualizar_estado_servicio(
            db,
            incidente_id=incidente_id,
            current_user=current_user,
            estado="en_camino",
            observacion=observacion or "Técnico en ruta",
            tecnico_id=tecnico_id,
        )

    if a == "llegue_al_lugar":
        return actualizar_estado_servicio(
            db,
            incidente_id=incidente_id,
            current_user=current_user,
            estado="en_diagnostico",
            observacion=observacion or "Técnico llegó al lugar",
            tecnico_id=tecnico_id,
        )

    if a == "completar_diagnostico":
        return actualizar_estado_servicio(
            db,
            incidente_id=incidente_id,
            current_user=current_user,
            estado="diagnostico_completado",
            observacion=observacion or "Diagnóstico completado",
            tecnico_id=tecnico_id,
        )

    if a == "iniciar_atencion":
        return actualizar_estado_servicio(
            db,
            incidente_id=incidente_id,
            current_user=current_user,
            estado="en_proceso",
            observacion=observacion or "Atención iniciada",
            tecnico_id=tecnico_id,
        )

    if a == "generar_cotizacion":
        return actualizar_estado_servicio(
            db,
            incidente_id=incidente_id,
            current_user=current_user,
            estado="diagnostico_completado",
            observacion=observacion or "Diagnóstico completado, listo para cotización",
            tecnico_id=tecnico_id,
        )

    # finalizar_servicio
    return actualizar_estado_servicio(
        db,
        incidente_id=incidente_id,
        current_user=current_user,
        estado="atendido",
        observacion=observacion or "Servicio finalizado operativamente",
        tecnico_id=tecnico_id,
    )
