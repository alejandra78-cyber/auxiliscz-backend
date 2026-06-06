import uuid
from collections import defaultdict
from datetime import datetime, time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import (
    Asignacion,
    Auditoria,
    Cotizacion,
    Evaluacion,
    Historial,
    Incidente,
    Pago,
    Rol,
    Solicitud,
    Taller,
    Tenant,
    TrabajoCompletado,
    Usuario,
    UsuarioRol,
)

from .services import estado_paquete_admin

router = APIRouter()


def _only_admin(current_user) -> None:
    if current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="Solo admin")


class UsuarioAdminOut(BaseModel):
    id: str
    nombre: str
    email: EmailStr
    telefono: str | None = None
    estado: str
    rol: str


class UsuarioEstadoIn(BaseModel):
    estado: str


class UsuarioRolIn(BaseModel):
    rol: str


class AdminResumenOut(BaseModel):
    incidentes: dict
    talleres: dict
    servicios_completados: int
    pagos: dict
    comision_total: float
    promedio_calificacion: float
    incidentes_por_tipo: dict
    incidentes_por_estado: dict


class KpiSerieItem(BaseModel):
    label: str
    valor: float | int


class TallerEficienteOut(BaseModel):
    taller_id: str | None = None
    taller: str
    servicios_completados: int
    tiempo_promedio_respuesta_min: float | None = None
    tiempo_promedio_finalizacion_min: float | None = None
    cumplimiento_sla: float


class KpisTenantOut(BaseModel):
    tenant_id: str | None = None
    tenant_nombre: str | None = None
    fecha_inicio: str | None = None
    fecha_fin: str | None = None
    tiempo_promedio_asignacion_min: float | None = None
    tiempo_promedio_llegada_min: float | None = None
    incidentes_por_tipo: list[KpiSerieItem]
    talleres_mas_eficientes: list[TallerEficienteOut]
    zonas_con_mas_incidentes: list[KpiSerieItem]
    casos_cancelados: int
    nivel_cumplimiento_sla: float


def _parse_date_filter(value: str | None, *, end_of_day: bool = False) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        if len(raw) == 10:
            base = datetime.strptime(raw, "%Y-%m-%d")
            return datetime.combine(base.date(), time.max if end_of_day else time.min)
        return datetime.fromisoformat(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Fecha inválida: {value}")


def _minutes_between(start: datetime | None, end: datetime | None) -> float | None:
    if not start or not end or end < start:
        return None
    return round((end - start).total_seconds() / 60, 2)


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _estado_key(value: str | None) -> str:
    return (value or "").strip().lower().replace(" ", "_")


def _taller_tenant_id(db: Session, current_user) -> str | None:
    if getattr(current_user, "tenant_id", None):
        return str(current_user.tenant_id)
    taller = db.query(Taller).filter(Taller.usuario_id == current_user.id).first()
    return str(taller.tenant_id) if taller and taller.tenant_id else None


def _resolve_kpi_tenant(db: Session, current_user, tenant_id: str | None) -> Tenant | None:
    if current_user.rol == "admin":
        if not (tenant_id or "").strip():
            return None
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant no encontrado")
        return tenant
    if current_user.rol == "taller":
        own_tenant_id = _taller_tenant_id(db, current_user)
        if not own_tenant_id:
            raise HTTPException(status_code=403, detail="El taller no tiene tenant asociado")
        if (tenant_id or "").strip() and str(tenant_id) != own_tenant_id:
            raise HTTPException(status_code=403, detail="No puedes consultar KPIs de otro tenant")
        tenant = db.query(Tenant).filter(Tenant.id == own_tenant_id).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant del taller no encontrado")
        return tenant
    raise HTTPException(status_code=403, detail="Solo admin o taller puede consultar KPIs por tenant")


def _report_time(solicitud: Solicitud) -> datetime | None:
    return solicitud.creado_en or (solicitud.incidente.creado_en if solicitud.incidente else None)


def _first_assignment(asignaciones: list[Asignacion]) -> Asignacion | None:
    if not asignaciones:
        return None
    return sorted(
        asignaciones,
        key=lambda a: a.fecha_asignacion or a.fecha_confirmacion or a.asignado_en or datetime.min,
    )[0]


def _assignment_time(asignacion: Asignacion | None) -> datetime | None:
    if not asignacion:
        return None
    return asignacion.fecha_asignacion or asignacion.fecha_confirmacion or asignacion.asignado_en


def _arrival_time(db: Session, solicitud: Solicitud, asignacion: Asignacion | None) -> datetime | None:
    if asignacion and asignacion.fecha_inicio_servicio:
        return asignacion.fecha_inicio_servicio
    row = (
        db.query(Historial)
        .filter(Historial.solicitud_id == solicitud.id)
        .filter(Historial.estado_nuevo.in_(["tecnico_en_lugar", "en_diagnostico", "en_atencion", "en_proceso"]))
        .order_by(Historial.creado_en.asc())
        .first()
    )
    return row.creado_en if row else None


def _completion_time(db: Session, solicitud: Solicitud, asignacion: Asignacion | None) -> datetime | None:
    if asignacion and asignacion.fecha_finalizacion:
        return asignacion.fecha_finalizacion
    trabajo = (
        db.query(TrabajoCompletado)
        .filter(TrabajoCompletado.solicitud_id == solicitud.id)
        .order_by(TrabajoCompletado.creado_en.asc())
        .first()
    )
    if trabajo:
        return trabajo.creado_en
    row = (
        db.query(Historial)
        .filter(Historial.solicitud_id == solicitud.id)
        .filter(Historial.estado_nuevo.in_(["trabajo_completado", "finalizado", "pagado"]))
        .order_by(Historial.creado_en.asc())
        .first()
    )
    return row.creado_en if row else None


def _tipo_incidente(solicitud: Solicitud) -> str:
    raw = solicitud.incidente.tipo if solicitud.incidente and solicitud.incidente.tipo else None
    if not raw and solicitud.emergencia and solicitud.emergencia.tipo:
        raw = solicitud.emergencia.tipo
    key = _estado_key(raw)
    if key in {"bateria", "batería"}:
        return "batería"
    if key in {"llanta", "motor", "choque"}:
        return key
    return "otros"


def _zona_solicitud(solicitud: Solicitud) -> str:
    lat = solicitud.incidente.latitud if solicitud.incidente else None
    lng = solicitud.incidente.longitud if solicitud.incidente else None
    if (lat is None or lng is None) and solicitud.emergencia and solicitud.emergencia.ubicaciones:
        ubicacion = sorted(solicitud.emergencia.ubicaciones, key=lambda u: u.registrado_en or datetime.min)[-1]
        lat, lng = ubicacion.latitud, ubicacion.longitud
    if lat is None or lng is None:
        return "Sin zona registrada"
    return f"{round(float(lat), 2)}, {round(float(lng), 2)}"


@router.get("/estado")
def estado():
    return estado_paquete_admin()


@router.get("/kpis-tenant", response_model=KpisTenantOut)
def consultar_kpis_tenant(
    tenant_id: str | None = None,
    fecha_inicio: str | None = None,
    fecha_fin: str | None = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant = _resolve_kpi_tenant(db, current_user, tenant_id)
    inicio = _parse_date_filter(fecha_inicio)
    fin = _parse_date_filter(fecha_fin, end_of_day=True)
    if inicio and fin and inicio > fin:
        raise HTTPException(status_code=400, detail="fecha_inicio no puede ser mayor a fecha_fin")

    tenant_uuid = tenant.id if tenant else None
    asignaciones_query = db.query(Asignacion)
    if tenant_uuid:
        asignaciones_query = asignaciones_query.filter(Asignacion.tenant_id == tenant_uuid)
    asignaciones_tenant = asignaciones_query.all()
    solicitud_ids = {a.solicitud_id for a in asignaciones_tenant if a.solicitud_id}

    solicitud_query = db.query(Solicitud)
    if tenant_uuid:
        solicitud_query = solicitud_query.filter(or_(Solicitud.tenant_id == tenant_uuid, Solicitud.id.in_(list(solicitud_ids))))
    if inicio:
        solicitud_query = solicitud_query.filter(Solicitud.creado_en >= inicio)
    if fin:
        solicitud_query = solicitud_query.filter(Solicitud.creado_en <= fin)
    solicitudes = solicitud_query.order_by(Solicitud.creado_en.asc()).all()

    asignaciones_por_solicitud: dict[str, list[Asignacion]] = defaultdict(list)
    for asignacion in asignaciones_tenant:
        if tenant_uuid and str(asignacion.tenant_id or "") != str(tenant_uuid):
            continue
        asignaciones_por_solicitud[str(asignacion.solicitud_id)].append(asignacion)

    tiempos_asignacion: list[float] = []
    tiempos_llegada: list[float] = []
    tipos = {"batería": 0, "llanta": 0, "motor": 0, "choque": 0, "otros": 0}
    zonas: dict[str, int] = defaultdict(int)
    cancelados = 0
    sla_total = 0
    sla_ok = 0
    taller_stats: dict[str, dict] = {}
    estados_cancelados = {"cancelado", "cancelada", "cancelado_con_cobro", "rechazado", "rechazada", "no_atendido"}

    for solicitud in solicitudes:
        asignaciones = asignaciones_por_solicitud.get(str(solicitud.id), [])
        if not asignaciones and tenant_uuid:
            asignaciones = [a for a in (solicitud.asignaciones or []) if str(a.tenant_id or "") == str(tenant_uuid)]
        asignacion = _first_assignment(asignaciones)
        report_at = _report_time(solicitud)
        assigned_at = _assignment_time(asignacion)
        arrived_at = _arrival_time(db, solicitud, asignacion)
        completed_at = _completion_time(db, solicitud, asignacion)

        assign_minutes = _minutes_between(report_at, assigned_at)
        if assign_minutes is not None:
            tiempos_asignacion.append(assign_minutes)
        arrival_minutes = _minutes_between(assigned_at, arrived_at)
        if arrival_minutes is not None:
            tiempos_llegada.append(arrival_minutes)

        tipos[_tipo_incidente(solicitud)] += 1
        zonas[_zona_solicitud(solicitud)] += 1
        if _estado_key(solicitud.estado) in estados_cancelados:
            cancelados += 1

        sla_reference = completed_at or arrived_at
        sla_minutes = _minutes_between(report_at, sla_reference)
        if sla_minutes is not None:
            sla_total += 1
            if sla_minutes <= 120:
                sla_ok += 1

        if asignacion and asignacion.taller_id:
            key = str(asignacion.taller_id)
            stats = taller_stats.setdefault(
                key,
                {
                    "taller_id": key,
                    "taller": asignacion.taller.nombre if asignacion.taller else "Taller",
                    "servicios_completados": 0,
                    "respuesta": [],
                    "finalizacion": [],
                    "sla_total": 0,
                    "sla_ok": 0,
                },
            )
            if completed_at or _estado_key(solicitud.estado) in {"trabajo_completado", "finalizado", "pagado", "completado"}:
                stats["servicios_completados"] += 1
            if assign_minutes is not None:
                stats["respuesta"].append(assign_minutes)
            finish_minutes = _minutes_between(report_at, completed_at)
            if finish_minutes is not None:
                stats["finalizacion"].append(finish_minutes)
            if sla_minutes is not None:
                stats["sla_total"] += 1
                if sla_minutes <= 120:
                    stats["sla_ok"] += 1

    talleres = []
    for stats in taller_stats.values():
        total = int(stats["sla_total"] or 0)
        cumplimiento = round((int(stats["sla_ok"] or 0) / total) * 100, 2) if total else 0.0
        talleres.append(
            TallerEficienteOut(
                taller_id=stats["taller_id"],
                taller=stats["taller"],
                servicios_completados=int(stats["servicios_completados"] or 0),
                tiempo_promedio_respuesta_min=_avg(stats["respuesta"]),
                tiempo_promedio_finalizacion_min=_avg(stats["finalizacion"]),
                cumplimiento_sla=cumplimiento,
            )
        )
    talleres.sort(
        key=lambda item: (
            item.tiempo_promedio_respuesta_min if item.tiempo_promedio_respuesta_min is not None else 999999,
            item.tiempo_promedio_finalizacion_min if item.tiempo_promedio_finalizacion_min is not None else 999999,
        )
    )

    return KpisTenantOut(
        tenant_id=str(tenant.id) if tenant else None,
        tenant_nombre=tenant.nombre if tenant else "Todos los tenants",
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        tiempo_promedio_asignacion_min=_avg(tiempos_asignacion),
        tiempo_promedio_llegada_min=_avg(tiempos_llegada),
        incidentes_por_tipo=[KpiSerieItem(label=k, valor=v) for k, v in tipos.items()],
        talleres_mas_eficientes=talleres[:10],
        zonas_con_mas_incidentes=[
            KpiSerieItem(label=k, valor=v)
            for k, v in sorted(zonas.items(), key=lambda item: item[1], reverse=True)[:10]
        ],
        casos_cancelados=cancelados,
        nivel_cumplimiento_sla=round((sla_ok / sla_total) * 100, 2) if sla_total else 0.0,
    )


@router.get("/usuarios/me")
def mi_usuario_admin(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _only_admin(current_user)
    return {
        "id": str(current_user.id),
        "nombre": current_user.nombre,
        "email": current_user.email,
        "telefono": current_user.telefono,
        "rol": current_user.rol,
    }


@router.get("/usuarios", response_model=list[UsuarioAdminOut])
def listar_usuarios_admin(
    rol: str | None = None,
    estado: str | None = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _only_admin(current_user)
    query = db.query(Usuario)
    if (estado or "").strip():
        query = query.filter(Usuario.estado == estado.strip().lower())
    rows = query.order_by(Usuario.creado_en.desc()).all()
    out: list[UsuarioAdminOut] = []
    rol_filter = (rol or "").strip().lower()
    for u in rows:
        urol = u.rol
        if rol_filter and rol_filter != urol:
            continue
        out.append(
            UsuarioAdminOut(
                id=str(u.id),
                nombre=u.nombre,
                email=u.email,
                telefono=u.telefono,
                estado=u.estado or "activo",
                rol=urol,
            )
        )
    return out


@router.patch("/usuarios/{usuario_id}/estado", response_model=UsuarioAdminOut)
def cambiar_estado_usuario(
    usuario_id: str,
    payload: UsuarioEstadoIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _only_admin(current_user)
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    nuevo = (payload.estado or "").strip().lower()
    if nuevo not in {"activo", "inactivo", "bloqueado"}:
        raise HTTPException(status_code=400, detail="Estado no válido")
    usuario.estado = nuevo
    db.add(
        Auditoria(
            id=uuid.uuid4(),
            usuario_id=current_user.id,
            accion="cu26_cambiar_estado_usuario",
            modulo="admin",
            detalle=f"usuario_id={usuario.id}; estado={nuevo}",
        )
    )
    db.commit()
    db.refresh(usuario)
    return UsuarioAdminOut(
        id=str(usuario.id),
        nombre=usuario.nombre,
        email=usuario.email,
        telefono=usuario.telefono,
        estado=usuario.estado or "activo",
        rol=usuario.rol,
    )


@router.patch("/usuarios/{usuario_id}/rol", response_model=UsuarioAdminOut)
def cambiar_rol_usuario(
    usuario_id: str,
    payload: UsuarioRolIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _only_admin(current_user)
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    nuevo_rol = (payload.rol or "").strip().lower()
    if nuevo_rol not in {"admin", "taller", "tecnico", "cliente", "conductor"}:
        raise HTTPException(status_code=400, detail="Rol no válido")
    rol_row = db.query(Rol).filter(Rol.nombre == nuevo_rol).first()
    if not rol_row:
        rol_row = Rol(id=uuid.uuid4(), nombre=nuevo_rol, descripcion=f"Rol {nuevo_rol}")
        db.add(rol_row)
        db.flush()
    db.query(UsuarioRol).filter(UsuarioRol.usuario_id == usuario.id).delete()
    db.add(UsuarioRol(id=uuid.uuid4(), usuario_id=usuario.id, rol_id=rol_row.id))
    db.add(
        Auditoria(
            id=uuid.uuid4(),
            usuario_id=current_user.id,
            accion="cu26_cambiar_rol_usuario",
            modulo="admin",
            detalle=f"usuario_id={usuario.id}; rol={nuevo_rol}",
        )
    )
    db.commit()
    db.refresh(usuario)
    return UsuarioAdminOut(
        id=str(usuario.id),
        nombre=usuario.nombre,
        email=usuario.email,
        telefono=usuario.telefono,
        estado=usuario.estado or "activo",
        rol=usuario.rol,
    )


@router.get("/reportes/resumen", response_model=AdminResumenOut)
def resumen_reportes(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _only_admin(current_user)

    total_incidentes = db.query(Incidente).count()
    hoy = datetime.now().date()
    incidentes_hoy = db.query(Incidente).filter(func.date(Incidente.creado_en) == hoy).count()
    incidentes_mes = (
        db.query(Incidente)
        .filter(func.date_part("year", Incidente.creado_en) == hoy.year)
        .filter(func.date_part("month", Incidente.creado_en) == hoy.month)
        .count()
    )

    talleres_total = db.query(Taller).count()
    talleres_aprobados = db.query(Taller).filter(Taller.estado_aprobacion == "aprobado").count()
    talleres_pendientes = db.query(Taller).filter(Taller.estado_aprobacion == "pendiente").count()

    pagos_rows = db.query(Pago).all()
    pagos_total = len(pagos_rows)
    pagos_pagados = sum(1 for p in pagos_rows if (p.estado or "").lower() == "pagado")
    comision_total = float(sum(float(p.comision_plataforma or 0) for p in pagos_rows))
    ingresos_total = float(sum(float(p.monto or 0) for p in pagos_rows if (p.estado or "").lower() == "pagado"))

    servicios_completados = (
        db.query(Incidente)
        .filter(Incidente.estado.in_(["trabajo_completado", "esperando_pago", "pagado", "finalizado"]))
        .count()
    )

    avg_eval = db.query(func.avg(Evaluacion.estrellas)).scalar()
    promedio_calificacion = float(round(avg_eval or 0, 2))

    por_tipo = defaultdict(int)
    for t, c in db.query(Incidente.tipo, func.count(Incidente.id)).group_by(Incidente.tipo).all():
        por_tipo[str(t or "otro")] = int(c)

    por_estado = defaultdict(int)
    for e, c in db.query(Incidente.estado, func.count(Incidente.id)).group_by(Incidente.estado).all():
        por_estado[str(e or "desconocido")] = int(c)

    return AdminResumenOut(
        incidentes={
            "total": int(total_incidentes),
            "hoy": int(incidentes_hoy),
            "este_mes": int(incidentes_mes),
        },
        talleres={
            "total": int(talleres_total),
            "aprobados": int(talleres_aprobados),
            "pendientes": int(talleres_pendientes),
        },
        servicios_completados=int(servicios_completados),
        pagos={
            "total": int(pagos_total),
            "pagados": int(pagos_pagados),
            "ingresos_total": ingresos_total,
        },
        comision_total=comision_total,
        promedio_calificacion=promedio_calificacion,
        incidentes_por_tipo=dict(por_tipo),
        incidentes_por_estado=dict(por_estado),
    )
