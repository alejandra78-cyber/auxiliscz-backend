import json
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.models import (
    Asignacion,
    Cliente,
    Comision,
    Cotizacion,
    Disponibilidad,
    Emergencia,
    Evidencia,
    Historial,
    HistorialEstado,
    Incidente,
    Mensaje,
    Metrica,
    Notificacion,
    Pago,
    Permiso,
    Rol,
    RolPermiso,
    Solicitud,
    SolicitudEvidencia,
    Tecnico,
    Taller,
    Turno,
    Ubicacion,
    Usuario,
    UsuarioRol,
    Vehiculo,
)


def normalize_role(raw: str | None) -> tuple[str, bool]:
    value = (raw or "").strip().lower()
    mapping = {
        "conductor": "conductor",
        "cliente": "conductor",
        "user": "conductor",
        "taller": "taller",
        "admin": "admin",
        "administrador": "admin",
    }
    if value in mapping:
        return mapping[value], False
    return "conductor", True


def get_or_create_role(db: Session, nombre: str, descripcion: str) -> Rol:
    rol = db.query(Rol).filter(func.lower(Rol.nombre) == nombre.lower()).first()
    if rol:
        return rol
    rol = Rol(id=uuid.uuid4(), nombre=nombre, descripcion=descripcion)
    db.add(rol)
    db.flush()
    return rol


def get_or_create_permiso(db: Session, codigo: str, descripcion: str) -> Permiso:
    permiso = db.query(Permiso).filter(Permiso.codigo == codigo).first()
    if permiso:
        return permiso
    permiso = Permiso(id=uuid.uuid4(), codigo=codigo, descripcion=descripcion)
    db.add(permiso)
    db.flush()
    return permiso


def ensure_rol_permiso(db: Session, rol_id, permiso_id) -> None:
    exists = (
        db.query(RolPermiso)
        .filter(RolPermiso.rol_id == rol_id, RolPermiso.permiso_id == permiso_id)
        .first()
    )
    if not exists:
        db.add(RolPermiso(id=uuid.uuid4(), rol_id=rol_id, permiso_id=permiso_id))


def ensure_usuario_rol(db: Session, usuario_id, rol_id) -> None:
    exists = (
        db.query(UsuarioRol)
        .filter(UsuarioRol.usuario_id == usuario_id, UsuarioRol.rol_id == rol_id)
        .first()
    )
    if not exists:
        db.add(UsuarioRol(id=uuid.uuid4(), usuario_id=usuario_id, rol_id=rol_id))


def ensure_cliente(db: Session, usuario_id):
    cliente = db.query(Cliente).filter(Cliente.usuario_id == usuario_id).first()
    if cliente:
        return cliente
    cliente = Cliente(id=uuid.uuid4(), usuario_id=usuario_id)
    db.add(cliente)
    db.flush()
    return cliente


def build_role_permissions(db: Session, report: dict) -> dict[str, Rol]:
    roles = {
        "admin": get_or_create_role(db, "admin", "Administrador del sistema"),
        "taller": get_or_create_role(db, "taller", "Usuario de taller"),
        "conductor": get_or_create_role(db, "conductor", "Cliente conductor"),
    }

    permisos_catalog = {
        "auth.login": "Iniciar sesión",
        "auth.roles.manage": "Gestionar roles y permisos",
        "taller.manage": "Gestionar taller y técnicos",
        "vehiculo.create": "Registrar vehículos",
        "emergencia.report": "Reportar emergencia",
        "solicitud.track": "Consultar estado de solicitud",
        "solicitud.assign": "Asignar y actualizar servicio",
        "chat.use": "Usar comunicación de solicitud",
        "pago.manage": "Gestionar pagos y cotizaciones",
    }

    permisos = {}
    for codigo, descripcion in permisos_catalog.items():
        permisos[codigo] = get_or_create_permiso(db, codigo, descripcion)

    grants = {
        "admin": list(permisos_catalog.keys()),
        "taller": ["auth.login", "taller.manage", "solicitud.assign", "chat.use", "pago.manage"],
        "conductor": ["auth.login", "vehiculo.create", "emergencia.report", "solicitud.track", "chat.use"],
    }

    for rol_name, codes in grants.items():
        for code in codes:
            ensure_rol_permiso(db, roles[rol_name].id, permisos[code].id)

    report["migrated"]["roles_seeded"] = len(roles)
    report["migrated"]["permisos_seeded"] = len(permisos_catalog)
    return roles


def migrate_users_to_roles(db: Session, roles: dict[str, Rol], report: dict) -> None:
    users = db.query(Usuario).all()
    for user in users:
        normalized, was_conflict = normalize_role(user.rol)
        if was_conflict:
            report["conflicts"]["invalid_roles"].append(
                {"usuario_id": str(user.id), "email": user.email, "rol_original": user.rol}
            )
        ensure_usuario_rol(db, user.id, roles[normalized].id)
    report["migrated"]["usuarios_roles"] = (
        db.query(UsuarioRol).count()
    )


def migrate_clientes(db: Session, report: dict) -> None:
    users = db.query(Usuario).all()
    created = 0
    for user in users:
        has_car = db.query(Vehiculo.id).filter(Vehiculo.usuario_id == user.id).first() is not None
        has_incident = db.query(Incidente.id).filter(Incidente.usuario_id == user.id).first() is not None
        role_normalized, _ = normalize_role(user.rol)
        if role_normalized == "conductor" or has_car or has_incident:
            existing = db.query(Cliente).filter(Cliente.usuario_id == user.id).first()
            if not existing:
                ensure_cliente(db, user.id)
                created += 1
    report["migrated"]["clientes_created"] = created


def migrate_solicitudes_core(db: Session, report: dict) -> dict:
    incidents = db.query(Incidente).all()
    solicitud_by_incidente = {}
    created = 0

    for inc in incidents:
        solicitud = db.query(Solicitud).filter(Solicitud.incidente_id == inc.id).first()
        if solicitud:
            solicitud_by_incidente[str(inc.id)] = solicitud
            continue

        vehiculo_id = inc.vehiculo_id
        if vehiculo_id is None:
            fallback = (
                db.query(Vehiculo)
                .filter(Vehiculo.usuario_id == inc.usuario_id)
                .order_by(Vehiculo.id.asc())
                .first()
            )
            if fallback:
                vehiculo_id = fallback.id
            else:
                report["conflicts"]["incidentes_sin_vehiculo"].append(str(inc.id))
                continue

        cliente = ensure_cliente(db, inc.usuario_id)
        solicitud = Solicitud(
            id=uuid.uuid4(),
            incidente_id=inc.id,
            cliente_id=cliente.id,
            vehiculo_id=vehiculo_id,
            estado=str(inc.estado),
            prioridad=inc.prioridad or 2,
            creado_en=inc.creado_en,
            actualizado_en=inc.actualizado_en,
        )
        db.add(solicitud)
        db.flush()
        solicitud_by_incidente[str(inc.id)] = solicitud
        created += 1

    report["migrated"]["solicitudes_created"] = created
    return solicitud_by_incidente


def migrate_emergencias_ubicaciones(db: Session, solicitud_by_incidente: dict, report: dict) -> None:
    created_emergencias = 0
    created_ubicaciones = 0

    for inc_id, solicitud in solicitud_by_incidente.items():
        inc = db.query(Incidente).filter(Incidente.id == uuid.UUID(inc_id)).first()
        if not inc:
            continue

        emergencia = db.query(Emergencia).filter(Emergencia.solicitud_id == solicitud.id).first()
        if not emergencia:
            emergencia = Emergencia(
                id=uuid.uuid4(),
                solicitud_id=solicitud.id,
                tipo=str(inc.tipo) if inc.tipo else "otro",
                descripcion=inc.descripcion,
                estado=str(inc.estado),
                prioridad=inc.prioridad or 2,
                creado_en=inc.creado_en,
            )
            db.add(emergencia)
            db.flush()
            created_emergencias += 1

        if inc.lat_incidente is not None and inc.lng_incidente is not None:
            exists = (
                db.query(Ubicacion)
                .filter(
                    Ubicacion.emergencia_id == emergencia.id,
                    Ubicacion.latitud == inc.lat_incidente,
                    Ubicacion.longitud == inc.lng_incidente,
                )
                .first()
            )
            if not exists:
                db.add(
                    Ubicacion(
                        id=uuid.uuid4(),
                        emergencia_id=emergencia.id,
                        latitud=inc.lat_incidente,
                        longitud=inc.lng_incidente,
                        fuente="migracion_incidente",
                        registrado_en=inc.creado_en,
                    )
                )
                created_ubicaciones += 1

    report["migrated"]["emergencias_created"] = created_emergencias
    report["migrated"]["ubicaciones_created"] = created_ubicaciones


def migrate_historial(db: Session, solicitud_by_incidente: dict, report: dict) -> None:
    created = 0
    rows = db.query(HistorialEstado).all()
    for row in rows:
        solicitud = solicitud_by_incidente.get(str(row.incidente_id))
        if not solicitud:
            report["conflicts"]["historial_sin_solicitud"].append(str(row.id))
            continue
        exists = (
            db.query(Historial)
            .filter(
                Historial.solicitud_id == solicitud.id,
                Historial.estado_anterior == row.estado_anterior,
                Historial.estado_nuevo == row.estado_nuevo,
                Historial.creado_en == row.cambiado_en,
            )
            .first()
        )
        if exists:
            continue
        db.add(
            Historial(
                id=uuid.uuid4(),
                solicitud_id=solicitud.id,
                estado_anterior=row.estado_anterior,
                estado_nuevo=row.estado_nuevo or "pendiente",
                comentario="Migrado desde historial_estados",
                creado_en=row.cambiado_en,
            )
        )
        created += 1
    report["migrated"]["historial_created"] = created


def migrate_evidencias(db: Session, solicitud_by_incidente: dict, report: dict) -> None:
    created_links = 0
    evs = db.query(Evidencia).all()
    for ev in evs:
        solicitud = solicitud_by_incidente.get(str(ev.incidente_id))
        if not solicitud:
            continue
        exists = (
            db.query(SolicitudEvidencia)
            .filter(
                SolicitudEvidencia.solicitud_id == solicitud.id,
                SolicitudEvidencia.evidencia_id == ev.id,
            )
            .first()
        )
        if exists:
            continue
        db.add(
            SolicitudEvidencia(
                id=uuid.uuid4(),
                solicitud_id=solicitud.id,
                evidencia_id=ev.id,
                creado_en=ev.subido_en,
            )
        )
        created_links += 1
    report["migrated"]["solicitudes_evidencias_created"] = created_links


def parse_chat_message(raw: str) -> tuple[str, str]:
    texto = raw or ""
    autor_rol = "conductor"
    if texto.startswith("[CHAT]"):
        try:
            prefix, contenido = texto.split("] ", 1)
            if "[rol=" in prefix:
                autor_rol = prefix.split("[rol=")[1].replace("]", "").strip()
            return autor_rol, contenido.strip()
        except Exception:
            return autor_rol, texto.replace("[CHAT]", "").strip()
    return autor_rol, texto.strip()


def migrate_chat_notificaciones(db: Session, solicitud_by_incidente: dict, report: dict) -> None:
    created_messages = 0
    created_notifications = 0

    chat_rows = (
        db.query(Evidencia, Incidente)
        .join(Incidente, Incidente.id == Evidencia.incidente_id)
        .filter(Evidencia.tipo == "texto")
        .all()
    )

    for ev, inc in chat_rows:
        if not ev.transcripcion or "[CHAT]" not in ev.transcripcion:
            continue
        solicitud = solicitud_by_incidente.get(str(inc.id))
        if not solicitud:
            continue
        autor_rol, contenido = parse_chat_message(ev.transcripcion)
        if not contenido:
            continue

        if autor_rol == "taller" and inc.taller:
            usuario_id = inc.taller.usuario_id
        else:
            usuario_id = inc.usuario_id

        exists_msg = (
            db.query(Mensaje)
            .filter(
                Mensaje.solicitud_id == solicitud.id,
                Mensaje.usuario_id == usuario_id,
                Mensaje.contenido == contenido,
                Mensaje.creado_en == ev.subido_en,
            )
            .first()
        )
        if not exists_msg:
            db.add(
                Mensaje(
                    id=uuid.uuid4(),
                    solicitud_id=solicitud.id,
                    usuario_id=usuario_id,
                    contenido=contenido,
                    creado_en=ev.subido_en,
                )
            )
            created_messages += 1

        destino = None
        if autor_rol == "taller":
            destino = inc.usuario_id
        elif inc.taller:
            destino = inc.taller.usuario_id
        if destino:
            exists_not = (
                db.query(Notificacion)
                .filter(
                    Notificacion.usuario_id == destino,
                    Notificacion.solicitud_id == solicitud.id,
                    Notificacion.tipo == "chat",
                    Notificacion.mensaje == contenido[:250],
                )
                .first()
            )
            if not exists_not:
                db.add(
                    Notificacion(
                        id=uuid.uuid4(),
                        usuario_id=destino,
                        solicitud_id=solicitud.id,
                        titulo="Mensaje migrado",
                        mensaje=contenido[:250],
                        tipo="chat",
                        estado="no_leida",
                        creada_en=ev.subido_en or datetime.utcnow(),
                    )
                )
                created_notifications += 1

    report["migrated"]["mensajes_created"] = created_messages
    report["migrated"]["notificaciones_created"] = created_notifications


def migrate_asignaciones_disponibilidad_turnos(db: Session, solicitud_by_incidente: dict, report: dict) -> None:
    created_asig = 0
    created_disp = 0
    created_turnos = 0

    incidentes = db.query(Incidente).all()
    for inc in incidentes:
        solicitud = solicitud_by_incidente.get(str(inc.id))
        if not solicitud:
            continue
        if inc.taller_id is None and inc.tecnico_id is None:
            continue
        exists = (
            db.query(Asignacion)
            .filter(
                Asignacion.solicitud_id == solicitud.id,
                Asignacion.taller_id == inc.taller_id,
                Asignacion.tecnico_id == inc.tecnico_id,
            )
            .first()
        )
        if not exists:
            db.add(
                Asignacion(
                    id=uuid.uuid4(),
                    solicitud_id=solicitud.id,
                    taller_id=inc.taller_id,
                    tecnico_id=inc.tecnico_id,
                    estado="asignada" if str(inc.estado) != "cancelado" else "cancelada",
                    asignado_en=inc.actualizado_en or inc.creado_en,
                )
            )
            created_asig += 1

    talleres = db.query(Taller).all()
    for t in talleres:
        exists = (
            db.query(Disponibilidad)
            .filter(Disponibilidad.taller_id == t.id, Disponibilidad.tecnico_id.is_(None))
            .first()
        )
        if not exists:
            db.add(
                Disponibilidad(
                    id=uuid.uuid4(),
                    taller_id=t.id,
                    tecnico_id=None,
                    estado="disponible" if t.disponible else "no_disponible",
                    desde=datetime.utcnow(),
                )
            )
            created_disp += 1

    tecnicos = db.query(Tecnico).all()
    for tec in tecnicos:
        exists_disp = (
            db.query(Disponibilidad)
            .filter(Disponibilidad.taller_id == tec.taller_id, Disponibilidad.tecnico_id == tec.id)
            .first()
        )
        if not exists_disp:
            db.add(
                Disponibilidad(
                    id=uuid.uuid4(),
                    taller_id=tec.taller_id,
                    tecnico_id=tec.id,
                    estado="disponible" if tec.disponible else "no_disponible",
                    desde=datetime.utcnow(),
                )
            )
            created_disp += 1

        exists_turno = db.query(Turno).filter(Turno.tecnico_id == tec.id).first()
        if not exists_turno:
            db.add(
                Turno(
                    id=uuid.uuid4(),
                    tecnico_id=tec.id,
                    nombre=f"Turno base {tec.nombre}",
                    especialidad="general",
                    disponible=tec.disponible,
                    inicio=datetime.utcnow(),
                )
            )
            created_turnos += 1

    report["migrated"]["asignaciones_created"] = created_asig
    report["migrated"]["disponibilidades_created"] = created_disp
    report["migrated"]["turnos_created"] = created_turnos


def migrate_pagos_cotizaciones_comisiones(db: Session, solicitud_by_incidente: dict, report: dict) -> None:
    created_cot = 0
    created_com = 0

    pagos = db.query(Pago).all()
    for pago in pagos:
        solicitud = solicitud_by_incidente.get(str(pago.incidente_id))
        if not solicitud:
            report["conflicts"]["pagos_sin_solicitud"].append(str(pago.id))
            continue

        cot = db.query(Cotizacion).filter(Cotizacion.pago_id == pago.id).first()
        if not cot:
            cot = Cotizacion(
                id=uuid.uuid4(),
                solicitud_id=solicitud.id,
                pago_id=pago.id,
                monto=pago.monto,
                detalle=f"Migrada desde pago {pago.id}",
                estado="completada" if str(pago.estado) == "completado" else "pendiente",
                creado_en=pago.pagado_en or datetime.utcnow(),
            )
            db.add(cot)
            created_cot += 1

        com = db.query(Comision).filter(Comision.pago_id == pago.id).first()
        if not com:
            base_pct = pago.comision_plataforma
            pct = 10.0
            monto = None
            if base_pct is not None and pago.monto:
                monto = base_pct
                try:
                    pct = round((base_pct / pago.monto) * 100, 2) if pago.monto > 0 else 10.0
                except Exception:
                    pct = 10.0
            db.add(
                Comision(
                    id=uuid.uuid4(),
                    pago_id=pago.id,
                    porcentaje=pct,
                    monto=monto,
                    creado_en=pago.pagado_en or datetime.utcnow(),
                )
            )
            created_com += 1

    report["migrated"]["cotizaciones_created"] = created_cot
    report["migrated"]["comisiones_created"] = created_com


def migrate_metricas(db: Session, report: dict) -> None:
    created = 0
    talleres = db.query(Taller).all()
    for t in talleres:
        total_servicios = (
            db.query(func.count(Incidente.id))
            .filter(Incidente.taller_id == t.id, Incidente.estado == "atendido")
            .scalar()
            or 0
        )
        ingresos = (
            db.query(func.coalesce(func.sum(Incidente.costo_total), 0.0))
            .filter(Incidente.taller_id == t.id, Incidente.estado == "atendido")
            .scalar()
            or 0.0
        )
        for code, value in {
            "servicios_atendidos": float(total_servicios),
            "ingresos_totales": float(ingresos),
        }.items():
            exists = (
                db.query(Metrica)
                .filter(Metrica.taller_id == t.id, Metrica.codigo == code, Metrica.periodo == "historico")
                .first()
            )
            if not exists:
                db.add(
                    Metrica(
                        id=uuid.uuid4(),
                        taller_id=t.id,
                        codigo=code,
                        valor=value,
                        periodo="historico",
                        creado_en=datetime.utcnow(),
                    )
                )
                created += 1
    report["migrated"]["metricas_created"] = created


def run_migration() -> dict:
    db = SessionLocal()
    report = {
        "started_at": datetime.utcnow().isoformat(),
        "migrated": defaultdict(int),
        "conflicts": {
            "invalid_roles": [],
            "incidentes_sin_vehiculo": [],
            "historial_sin_solicitud": [],
            "pagos_sin_solicitud": [],
        },
        "notes": [
            "Migración progresiva: no elimina ni altera tablas antiguas.",
            "La migración es idempotente: evita duplicados por checks previos.",
        ],
    }

    try:
        roles = build_role_permissions(db, report)
        migrate_users_to_roles(db, roles, report)
        migrate_clientes(db, report)

        solicitud_by_incidente = migrate_solicitudes_core(db, report)
        migrate_emergencias_ubicaciones(db, solicitud_by_incidente, report)
        migrate_historial(db, solicitud_by_incidente, report)
        migrate_evidencias(db, solicitud_by_incidente, report)
        migrate_chat_notificaciones(db, solicitud_by_incidente, report)
        migrate_asignaciones_disponibilidad_turnos(db, solicitud_by_incidente, report)
        migrate_pagos_cotizaciones_comisiones(db, solicitud_by_incidente, report)
        migrate_metricas(db, report)

        db.commit()
        report["status"] = "ok"
    except Exception as exc:
        db.rollback()
        report["status"] = "error"
        report["error"] = str(exc)
        raise
    finally:
        report["finished_at"] = datetime.utcnow().isoformat()
        db.close()

    report["migrated"] = dict(report["migrated"])
    return report


def save_report(report: dict) -> Path:
    out_dir = Path(__file__).resolve().parent / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"data_migration_report_{stamp}.json"
    out_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_file


if __name__ == "__main__":
    result = run_migration()
    path = save_report(result)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"Reporte guardado en: {path}")
