import uuid
from datetime import datetime
import json
import math

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from app.models.models import (
    Asignacion,
    Emergencia,
    Historial,
    Metrica,
    Notificacion,
    Solicitud,
    SolicitudEvidencia,
    Taller,
    Tecnico,
    Turno,
    Usuario,
)
from app.services.asignacion import listar_candidatos, motor_asignacion
from app.core.time import local_now_naive

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
            joinedload(Solicitud.cliente),
            joinedload(Solicitud.evidencias).joinedload(SolicitudEvidencia.evidencia),
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
            joinedload(Solicitud.cliente),
            joinedload(Solicitud.evidencias).joinedload(SolicitudEvidencia.evidencia),
        )
        .filter(Solicitud.incidente_id == raw_id)
        .first()
    )


def _get_ultimo_asignacion(solicitud: Solicitud) -> Asignacion | None:
    if not solicitud.asignaciones:
        return None
    return sorted(solicitud.asignaciones, key=lambda x: x.asignado_en or x.id)[-1]


def _estado_valido(estado: str) -> str:
    estados = {"pendiente", "aprobada", "rechazada", "asignada", "en_proceso", "completada", "cancelada", "en_evaluacion"}
    s = (estado or "").strip().lower()
    if s not in estados:
        raise HTTPException(status_code=400, detail="Estado no válido")
    return s


def _obtener_taller_de_usuario(db: Session, current_user: Usuario) -> Taller | None:
    if current_user.rol != "taller":
        return None
    return db.query(Taller).filter(Taller.usuario_id == current_user.id).first()


def _guardar_historial(db: Session, solicitud: Solicitud, anterior: str | None, nuevo: str, comentario: str | None = None) -> None:
    db.add(
        Historial(
            id=uuid.uuid4(),
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
    mi_taller = _obtener_taller_de_usuario(db, current_user) if current_user.rol == "taller" else None
    q = db.query(Tecnico).filter(Tecnico.disponible.is_(True))
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
            .filter(Asignacion.tecnico_id == t.id, Asignacion.estado.in_(["asignada", "en_proceso"]))
            .count()
        )
        turno = (
            db.query(Turno)
            .filter(Turno.tecnico_id == t.id, Turno.disponible.is_(True))
            .order_by(Turno.inicio.desc())
            .first()
        )
        especialidad = (turno.especialidad or "").strip().lower() if turno and turno.especialidad else ""
        bonus_especialidad = 1.0 if servicio.replace("_", " ") in especialidad or servicio in especialidad else 0.0
        dist_km = 5.0
        if lat_inc is not None and lng_inc is not None and t.lat_actual is not None and t.lng_actual is not None:
            dist_km = _haversine(lat_inc, lng_inc, float(t.lat_actual), float(t.lng_actual))
        score = (2.5 - min(dist_km, 20) / 10.0) + bonus_especialidad + (2.0 - min(carga, 4) * 0.5)
        item = (score, t, dist_km, carga, especialidad)
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
    q = db.query(Tecnico).filter(Tecnico.disponible.is_(True))
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


async def asignar_taller_automaticamente(
    db: Session,
    *,
    solicitud_id: str,
    lat: float,
    lng: float,
    tipo: str,
    prioridad: int,
):
    solicitud = _resolver_solicitud(db, solicitud_id)
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    taller = await motor_asignacion(db, lat=lat, lng=lng, tipo=tipo, prioridad=prioridad)
    if not taller:
        return None
    db.add(
        Asignacion(
            id=uuid.uuid4(),
            solicitud_id=solicitud.id,
            incidente_id=solicitud.incidente_id,
            taller_id=taller.id,
            tecnico_id=None,
            estado="asignada",
        )
    )
    _guardar_historial(
        db,
        solicitud=solicitud,
        anterior=solicitud.estado,
        nuevo="asignada",
        comentario="Asignación automática",
    )
    db.commit()
    return taller


async def reasignar_taller(
    db: Session,
    *,
    solicitud_id: str,
    lat: float,
    lng: float,
    tipo: str,
    prioridad: int,
):
    solicitud = _resolver_solicitud(db, solicitud_id)
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    candidatos = await listar_candidatos(db, lat=lat, lng=lng, tipo=tipo, prioridad=prioridad)
    if not candidatos:
        return None
    ultima = _get_ultimo_asignacion(solicitud)
    ultimo_taller = str(ultima.taller_id) if ultima and ultima.taller_id else None
    candidato = next((c for c in candidatos if str(c.get("taller_id")) != ultimo_taller), None)
    if not candidato:
        return None
    db.add(
        Asignacion(
            id=uuid.uuid4(),
            solicitud_id=solicitud.id,
            incidente_id=solicitud.incidente_id,
            taller_id=candidato["taller_id"],
            tecnico_id=None,
            estado="asignada",
        )
    )
    _guardar_historial(
        db,
        solicitud=solicitud,
        anterior=solicitud.estado,
        nuevo="asignada",
        comentario="Reasignación automática",
    )
    db.commit()
    return candidato


def listar_solicitudes_servicio(db: Session, *, current_user: Usuario) -> list[Solicitud]:
    if current_user.rol not in {"taller", "admin"}:
        raise HTTPException(status_code=403, detail="Solo taller/admin puede consultar solicitudes")
    q = db.query(Solicitud).options(
        joinedload(Solicitud.emergencia),
        joinedload(Solicitud.emergencia).joinedload(Emergencia.ubicaciones),
        joinedload(Solicitud.cliente),
        joinedload(Solicitud.asignaciones).joinedload(Asignacion.taller),
        joinedload(Solicitud.asignaciones).joinedload(Asignacion.tecnico),
        joinedload(Solicitud.evidencias).joinedload(SolicitudEvidencia.evidencia),
    )
    if current_user.rol == "taller":
        mi_taller = _obtener_taller_de_usuario(db, current_user)
        if not mi_taller:
            raise HTTPException(status_code=403, detail="El usuario taller no tiene perfil de taller")
        q = q.outerjoin(Asignacion).filter((Asignacion.taller_id.is_(None)) | (Asignacion.taller_id == mi_taller.id))
    return q.order_by(Solicitud.creado_en.desc()).all()


def evaluar_solicitud_servicio(
    db: Session,
    *,
    incidente_id: str,
    current_user: Usuario,
    aprobar: bool,
    observacion: str | None,
) -> Solicitud:
    if current_user.rol not in {"taller", "admin"}:
        raise HTTPException(status_code=403, detail="Solo taller/admin puede evaluar solicitudes")
    solicitud = _resolver_solicitud(db, incidente_id)
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if solicitud.estado in {"completada", "cancelada", "rechazada"}:
        raise HTTPException(status_code=400, detail="La solicitud ya fue cerrada")

    estado_anterior = solicitud.estado
    if aprobar:
        if solicitud.estado not in {"pendiente", "en_evaluacion"}:
            raise HTTPException(status_code=400, detail="Solo se puede evaluar una solicitud pendiente")
        nuevo = "aprobada"
    else:
        nuevo = "rechazada"
    _guardar_historial(db, solicitud, estado_anterior, nuevo, observacion)
    if solicitud.cliente:
        _crear_notificacion_evento(
            db,
            solicitud=solicitud,
            usuario_id=solicitud.cliente.usuario_id,
            titulo="Solicitud evaluada",
            mensaje=f"Tu solicitud {codigo_solicitud(solicitud)} fue marcada como {nuevo}",
            tipo="evaluacion",
        )
    if current_user.rol == "taller":
        mi_taller = _obtener_taller_de_usuario(db, current_user)
        if mi_taller:
            _incrementar_metrica_taller(db, taller_id=mi_taller.id, codigo=f"cu15_{nuevo}")
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
    if current_user.rol not in {"taller", "admin"}:
        raise HTTPException(status_code=403, detail="Solo taller/admin puede asignar servicios")
    solicitud = _resolver_solicitud(db, incidente_id)
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if solicitud.estado in {"completada", "cancelada", "rechazada"}:
        raise HTTPException(status_code=400, detail="La solicitud ya fue cerrada")
    if solicitud.estado != "aprobada":
        raise HTTPException(status_code=400, detail="Solo se puede asignar una solicitud aprobada")

    servicio_key = (servicio or "").strip().lower().replace(" ", "_")
    if servicio_key not in CATALOGO_SERVICIOS:
        raise HTTPException(status_code=400, detail="Servicio no válido para asignación")

    taller_asig = taller_id
    if current_user.rol == "taller":
        mi_taller = _obtener_taller_de_usuario(db, current_user)
        if not mi_taller:
            raise HTTPException(status_code=403, detail="El usuario taller no tiene perfil de taller")
        taller_asig = str(mi_taller.id)
    tec = db.query(Tecnico).filter(Tecnico.id == tecnico_id).first()
    if not tec:
        raise HTTPException(status_code=404, detail="Técnico no encontrado")
    if not tec.disponible:
        raise HTTPException(status_code=400, detail="El técnico no está disponible")
    if taller_asig and str(tec.taller_id) != str(taller_asig):
        raise HTTPException(status_code=400, detail="El técnico no pertenece al taller asignado")

    db.add(
        Asignacion(
            id=uuid.uuid4(),
            solicitud_id=solicitud.id,
            incidente_id=solicitud.incidente_id,
            taller_id=taller_asig,
            tecnico_id=tecnico_id,
            servicio=servicio_key,
            estado="asignada",
        )
    )
    tec.disponible = False
    _guardar_historial(
        db,
        solicitud=solicitud,
        anterior=solicitud.estado,
        nuevo="asignada",
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
    costo: float | None = None,
) -> Solicitud:
    if current_user.rol not in {"taller", "admin"}:
        raise HTTPException(status_code=403, detail="Solo taller/admin puede actualizar estado")
    solicitud = _resolver_solicitud(db, incidente_id)
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    if current_user.rol == "taller":
        mi_taller = _obtener_taller_de_usuario(db, current_user)
        ultima = _get_ultimo_asignacion(solicitud)
        if not mi_taller or not ultima or str(ultima.taller_id) != str(mi_taller.id):
            raise HTTPException(status_code=403, detail="No autorizado para actualizar esta solicitud")

    estado_nuevo = _estado_valido(estado)
    if estado_nuevo not in {"asignada", "en_proceso", "completada", "cancelada"}:
        raise HTTPException(status_code=400, detail="Estado no permitido para actualización operativa")
    if solicitud.estado in {"rechazada", "cancelada", "completada"}:
        raise HTTPException(status_code=400, detail="La solicitud ya fue cerrada")

    transiciones_validas = {
        "aprobada": {"asignada", "cancelada"},
        "asignada": {"en_proceso", "cancelada"},
        "en_proceso": {"completada", "cancelada"},
    }
    permitidos = transiciones_validas.get(solicitud.estado, set())
    if estado_nuevo not in permitidos:
        raise HTTPException(status_code=400, detail=f"No se puede pasar de {solicitud.estado} a {estado_nuevo}")

    comentario = observacion or "Actualización de estado"
    if estado_nuevo == "completada" and costo and costo > 0:
        comentario = f"{comentario}. Costo reportado: {costo}"
        ultima = _get_ultimo_asignacion(solicitud)
        if ultima and ultima.tecnico:
            ultima.tecnico.disponible = True
    if estado_nuevo == "cancelada":
        ultima = _get_ultimo_asignacion(solicitud)
        if ultima and ultima.tecnico:
            ultima.tecnico.disponible = True

    _guardar_historial(db, solicitud, solicitud.estado, estado_nuevo, comentario)
    if solicitud.cliente:
        _crear_notificacion_evento(
            db,
            solicitud=solicitud,
            usuario_id=solicitud.cliente.usuario_id,
            titulo="Estado actualizado",
            mensaje=f"Tu solicitud {codigo_solicitud(solicitud)} cambió a {estado_nuevo}",
            tipo="estado_servicio",
        )
    ultima = _get_ultimo_asignacion(solicitud)
    if ultima and ultima.taller_id:
        _incrementar_metrica_taller(db, taller_id=ultima.taller_id, codigo=f"cu17_{estado_nuevo}")
    db.commit()
    db.refresh(solicitud)
    return solicitud
