import re
import uuid

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.models import (
    Asignacion,
    Auditoria,
    Cotizacion,
    Historial,
    Incidente,
    Metrica,
    Pago,
    Solicitud,
    Taller,
    Tecnico,
    Tenant,
    Usuario,
)

_VALID_STATES = {"activo", "inactivo", "suspendido"}


def _slug(value: str) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or f"tenant-{uuid.uuid4().hex[:8]}"


def _unique_slug(db: Session, value: str, *, tenant_id=None) -> str:
    base = _slug(value)
    code = base
    index = 2
    while True:
        query = db.query(Tenant).filter(Tenant.codigo == code)
        if tenant_id is not None:
            query = query.filter(Tenant.id != tenant_id)
        if not query.first():
            return code
        code = f"{base}-{index}"
        index += 1


def _update_by_ids(db: Session, model, ids: set, tenant_id) -> None:
    if not ids:
        return
    db.query(model).filter(model.id.in_(list(ids))).update({model.tenant_id: tenant_id}, synchronize_session=False)


def _taller_de_tenant(db: Session, tenant: Tenant) -> Taller | None:
    if getattr(tenant, "taller_id", None):
        taller = db.query(Taller).filter(Taller.id == tenant.taller_id).first()
        if taller:
            return taller
    return db.query(Taller).filter(Taller.tenant_id == tenant.id).order_by(Taller.creado_en.asc()).first()


def _cascade_taller_tenant(db: Session, taller: Taller, tenant_id) -> None:
    taller.tenant_id = tenant_id
    if taller.usuario:
        taller.usuario.tenant_id = tenant_id

    for tecnico in db.query(Tecnico).filter(Tecnico.taller_id == taller.id).all():
        tecnico.tenant_id = tenant_id
        if tecnico.usuario:
            tecnico.usuario.tenant_id = tenant_id

    asignaciones = db.query(Asignacion).filter(Asignacion.taller_id == taller.id).all()
    solicitud_ids = {a.solicitud_id for a in asignaciones if a.solicitud_id}
    incidente_ids = {a.incidente_id for a in asignaciones if a.incidente_id}
    for asignacion in asignaciones:
        asignacion.tenant_id = tenant_id

    _update_by_ids(db, Solicitud, solicitud_ids, tenant_id)
    _update_by_ids(db, Incidente, incidente_ids, tenant_id)
    _update_by_ids(db, Cotizacion, {c.id for c in db.query(Cotizacion).filter(Cotizacion.taller_id == taller.id).all()}, tenant_id)
    _update_by_ids(db, Pago, {p.id for p in db.query(Pago).filter(Pago.taller_id == taller.id).all()}, tenant_id)
    _update_by_ids(db, Metrica, {m.id for m in db.query(Metrica).filter(Metrica.taller_id == taller.id).all()}, tenant_id)
    _update_by_ids(db, Historial, {h.id for h in db.query(Historial).filter(Historial.solicitud_id.in_(list(solicitud_ids))).all()}, tenant_id)


def tenant_out(db: Session, tenant: Tenant) -> dict:
    taller = _taller_de_tenant(db, tenant)
    admin = taller.usuario if taller and taller.usuario else None
    ultima_actividad = db.query(func.max(Solicitud.actualizado_en)).filter(Solicitud.tenant_id == tenant.id).scalar()
    servicios_completados = (
        db.query(Solicitud)
        .filter(Solicitud.tenant_id == tenant.id)
        .filter(Solicitud.estado.in_(["finalizado", "pagado", "servicio_completado", "completado", "completada"]))
        .count()
    )
    incidentes_atendidos = (
        db.query(Incidente)
        .filter(Incidente.tenant_id == tenant.id)
        .filter(Incidente.estado.in_(["finalizado", "pagado", "servicio_completado", "completado", "completada"]))
        .count()
    )
    tecnicos = db.query(Tecnico).filter(Tecnico.tenant_id == tenant.id).count()
    return {
        "id": str(tenant.id),
        "taller_id": str(taller.id) if taller else None,
        "taller_nombre": taller.nombre if taller else None,
        "taller_estado": taller.estado_aprobacion if taller else None,
        "codigo": tenant.codigo,
        "nombre": tenant.nombre,
        "descripcion": tenant.descripcion,
        "estado": tenant.estado or "activo",
        "contacto_email": tenant.contacto_email,
        "contacto_telefono": tenant.contacto_telefono,
        "usuarios": db.query(Usuario).filter(Usuario.tenant_id == tenant.id).count(),
        "talleres": 1 if taller else 0,
        "tecnicos": tecnicos,
        "incidentes": db.query(Incidente).filter(Incidente.tenant_id == tenant.id).count(),
        "incidentes_atendidos": incidentes_atendidos,
        "servicios_completados": servicios_completados,
        "administrador_principal": admin.nombre if admin else None,
        "creado_en": tenant.creado_en.isoformat() if tenant.creado_en else None,
        "ultima_actividad": ultima_actividad.isoformat() if ultima_actividad else None,
    }


def require_admin(current_user: Usuario) -> None:
    if current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="Solo admin")


def get_tenant(db: Session, tenant_id: str) -> Tenant:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant no encontrado")
    return tenant


def listar_tenants(db: Session) -> list[Tenant]:
    _asegurar_tenants_de_talleres_aprobados(db)
    tenant_ids_con_taller = [row[0] for row in db.query(Taller.tenant_id).filter(Taller.tenant_id.isnot(None)).all()]
    query = db.query(Tenant)
    if tenant_ids_con_taller:
        query = query.filter((Tenant.taller_id.isnot(None)) | (Tenant.id.in_(tenant_ids_con_taller)))
    else:
        query = query.filter(Tenant.taller_id.isnot(None))
    return query.order_by(Tenant.creado_en.desc()).all()


def _asegurar_tenants_de_talleres_aprobados(db: Session) -> None:
    changed = False
    default_tenant_id = "00000000-0000-4000-8000-000000000001"

    def _desvincular_de_tenant_compartido(taller: Taller, tenant: Tenant | None) -> None:
        if tenant and str(getattr(tenant, "taller_id", "") or "") == str(taller.id):
            tenant.taller_id = None
        taller.tenant_id = None
        db.flush()

    for taller in db.query(Taller).filter(Taller.estado_aprobacion == "aprobado").order_by(Taller.creado_en.asc()).all():
        tenant = None
        if taller.tenant_id:
            tenant = db.query(Tenant).filter(Tenant.id == taller.tenant_id).first()

        if not tenant:
            crear_tenant_para_taller(db, taller=taller)
            changed = True
            continue

        talleres_en_mismo_tenant = db.query(Taller).filter(Taller.tenant_id == tenant.id).count()
        es_tenant_default = tenant.codigo == "auxiliscz" or str(tenant.id) == default_tenant_id
        es_tenant_compartido = talleres_en_mismo_tenant > 1
        tenant_es_del_taller = str(getattr(tenant, "taller_id", "") or "") == str(taller.id)
        tenant_es_de_otro_taller = bool(getattr(tenant, "taller_id", None)) and not tenant_es_del_taller

        if tenant_es_del_taller and not es_tenant_compartido and not es_tenant_default:
            _cascade_taller_tenant(db, taller, tenant.id)
            changed = True
            continue

        if not tenant.taller_id and not es_tenant_compartido and not es_tenant_default:
            tenant.taller_id = taller.id
            _cascade_taller_tenant(db, taller, tenant.id)
            changed = True
            continue

        if es_tenant_compartido or es_tenant_default or tenant_es_de_otro_taller:
            # Datos antiguos: varios talleres apuntaban al tenant por defecto.
            # En CU29 cada taller aprobado debe tener su propio tenant.
            _desvincular_de_tenant_compartido(taller, tenant)

        crear_tenant_para_taller(db, taller=taller)
        changed = True
    if changed:
        db.commit()


def crear_tenant_para_taller(db: Session, *, taller: Taller, current_user: Usuario | None = None, solicitud=None, commit: bool = False) -> Tenant:
    if not taller:
        raise HTTPException(status_code=404, detail="Taller no encontrado")

    tenant = None
    if taller.tenant_id:
        tenant = db.query(Tenant).filter(Tenant.id == taller.tenant_id).first()
    if not tenant:
        tenant = db.query(Tenant).filter(Tenant.taller_id == taller.id).first()

    email = None
    telefono = None
    if taller.usuario:
        email = taller.usuario.email
        telefono = taller.usuario.telefono
    if solicitud is not None:
        email = email or getattr(solicitud, "responsable_email", None)
        telefono = telefono or getattr(solicitud, "responsable_telefono", None)

    if tenant:
        tenant.taller_id = taller.id
        tenant.nombre = tenant.nombre or taller.nombre
        tenant.contacto_email = tenant.contacto_email or email
        tenant.contacto_telefono = tenant.contacto_telefono or telefono
        if tenant.estado not in _VALID_STATES:
            tenant.estado = "activo"
    else:
        tenant = Tenant(
            taller_id=taller.id,
            codigo=_unique_slug(db, taller.nombre),
            nombre=taller.nombre,
            descripcion=f"Tenant operativo del taller {taller.nombre}",
            estado="activo",
            contacto_email=email,
            contacto_telefono=telefono,
        )
        db.add(tenant)
        db.flush()

    _cascade_taller_tenant(db, taller, tenant.id)
    if solicitud is not None:
        solicitud.tenant_id = tenant.id

    if current_user is not None:
        db.add(
            Auditoria(
                usuario_id=current_user.id,
                tenant_id=tenant.id,
                accion="cu29_crear_tenant_desde_taller",
                modulo="tenants",
                detalle=f"taller_id={taller.id}; tenant={tenant.codigo}",
            )
        )
    if commit:
        db.commit()
        db.refresh(tenant)
    return tenant


def crear_tenant(db: Session, *, payload, current_user: Usuario) -> Tenant:
    raise HTTPException(
        status_code=400,
        detail="El tenant se crea automáticamente al aprobar un taller en CU27. No se crean tenants manuales.",
    )


def actualizar_tenant(db: Session, *, tenant_id: str, payload, current_user: Usuario) -> Tenant:
    tenant = get_tenant(db, tenant_id)
    taller = _taller_de_tenant(db, tenant)
    if not taller:
        raise HTTPException(status_code=409, detail="Este tenant no tiene taller asociado")
    if payload.codigo is not None:
        tenant.codigo = _unique_slug(db, payload.codigo, tenant_id=tenant.id)
    if payload.nombre is not None:
        tenant.nombre = payload.nombre.strip()
    if payload.descripcion is not None:
        tenant.descripcion = payload.descripcion
    if payload.estado is not None:
        estado = payload.estado.strip().lower()
        if estado not in _VALID_STATES:
            raise HTTPException(status_code=400, detail="Estado de tenant no válido")
        tenant.estado = estado
        if estado == "activo":
            taller.disponible = True
            taller.estado_operativo = "disponible"
        else:
            taller.disponible = False
            taller.estado_operativo = "fuera_de_servicio" if estado == "suspendido" else "inactivo"
    if payload.contacto_email is not None:
        tenant.contacto_email = str(payload.contacto_email) if payload.contacto_email else None
    if payload.contacto_telefono is not None:
        tenant.contacto_telefono = payload.contacto_telefono
    db.add(
        Auditoria(
            usuario_id=current_user.id,
            tenant_id=tenant.id,
            accion="cu29_actualizar_tenant",
            modulo="tenants",
            detalle=f"tenant={tenant.codigo}; taller={taller.nombre}",
        )
    )
    db.commit()
    db.refresh(tenant)
    return tenant


def asignar_usuario(db: Session, *, tenant_id: str, usuario_id: str, current_user: Usuario) -> Tenant:
    raise HTTPException(
        status_code=400,
        detail="Los usuarios internos heredan el tenant desde el taller o tecnico. Los clientes no pertenecen a tenants.",
    )


def asignar_taller(db: Session, *, tenant_id: str, taller_id: str, current_user: Usuario) -> Tenant:
    raise HTTPException(
        status_code=400,
        detail="Un tenant pertenece a un único taller y se crea automáticamente al aprobarlo.",
    )
