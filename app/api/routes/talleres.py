import json
import os
import secrets
import uuid
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.security import get_current_user, get_password_hash
from app.core.time import local_now_naive
from app.packages.auth.services import generar_token_activacion_cuenta
from app.models.models import (
    Asignacion,
    Auditoria,
    Cliente,
    Cotizacion,
    Disponibilidad,
    Emergencia,
    Historial,
    Notificacion,
    Rol,
    SolicitudTaller,
    Solicitud,
    Taller,
    Tecnico,
    Turno,
    Ubicacion,
    Usuario,
    UsuarioRol,
)
from app.services.emailer import enviar_email

router = APIRouter()
ESTADOS_OPERATIVOS_VALIDOS = {"disponible", "ocupado", "cerrado", "fuera_de_servicio"}
ESTADOS_ASIGNACION_ACTIVA = {"asignada", "en_proceso"}


class TallerCreate(BaseModel):
    usuario_id: str | None = None
    nombre: str = Field(..., min_length=3)
    direccion: str | None = None
    latitud: float | None = None
    longitud: float | None = None
    servicios: list[str] = Field(default_factory=list)
    disponible: bool = True
    responsable_nombre: str | None = Field(default=None, min_length=3)
    responsable_email: EmailStr | None = None
    responsable_telefono: str | None = None
    password_temporal: str | None = Field(default=None, min_length=6, max_length=128)


class TallerOut(BaseModel):
    id: UUID
    usuario_id: UUID
    nombre: str
    direccion: str | None = None
    latitud: float | None = None
    longitud: float | None = None
    servicios: list[str]
    disponible: bool
    estado_operativo: str = "disponible"
    capacidad_maxima: int = 1
    radio_cobertura_km: float = 10
    observaciones_operativas: str | None = None
    calificacion: float
    estado_aprobacion: str
    aprobado_por: UUID | None = None
    aprobado_en: str | None = None
    responsable_nombre: str | None = None
    responsable_email: str | None = None
    responsable_telefono: str | None = None

    class Config:
        from_attributes = True


class TecnicoCreate(BaseModel):
    usuario_id: str
    disponible: bool = True


class TecnicoOut(BaseModel):
    id: UUID
    usuario_id: UUID | None = None
    email: str | None = None
    nombre: str
    disponible: bool

    class Config:
        from_attributes = True


class TecnicoCandidatoOut(BaseModel):
    id: UUID
    nombre: str
    email: str


class DisponibilidadIn(BaseModel):
    disponible: bool | None = None
    estado_operativo: str | None = None
    capacidad_maxima: int | None = Field(default=None, ge=1, le=500)
    radio_cobertura_km: float | None = Field(default=None, gt=0, le=500)
    servicios: list[str] | None = None
    latitud: float | None = None
    longitud: float | None = None
    observaciones_operativas: str | None = Field(default=None, max_length=2000)


class TurnoDisponibleOut(BaseModel):
    tecnico_id: UUID
    tecnico_nombre: str
    turno_id: UUID
    nombre: str
    especialidad: str | None = None
    disponible: bool
    inicio: str | None = None
    fin: str | None = None


class DisponibilidadTallerOut(BaseModel):
    taller_id: UUID
    nombre_taller: str
    estado_operativo: str
    disponible: bool
    capacidad_maxima: int
    capacidad_disponible: int
    radio_cobertura_km: float
    servicios: list[str]
    tecnicos_disponibles: int
    tecnicos_totales: int
    direccion: str | None = None
    latitud: float | None = None
    longitud: float | None = None
    observaciones_operativas: str | None = None
    turnos_disponibles: list[TurnoDisponibleOut] = Field(default_factory=list)


class UbicacionTecnicoIn(BaseModel):
    lat: float
    lng: float


class HistorialAtencionOut(BaseModel):
    id: str
    fecha: str
    cliente: str | None = None
    vehiculo: str | None = None
    tipo_incidente: str
    estado_final: str
    tecnico_asignado: str | None = None
    ubicacion: str | None = None
    costo: float | None = None
    pago_monto: float | None = None
    pago_estado: str | None = None


class CompletarServicioIn(BaseModel):
    costo: float = Field(..., gt=0)
    observacion: str | None = None
    evidencia_texto: str | None = None


class ServicioActivoOut(BaseModel):
    incidente_id: str
    codigo_solicitud: str
    estado: str
    tipo_servicio: str | None = None
    tecnico_id: str | None = None
    tecnico_nombre: str | None = None
    cliente: str | None = None


class TallerAprobacionIn(BaseModel):
    comentario: str | None = None


class TallerAprobacionOut(BaseModel):
    taller_id: UUID
    estado_aprobacion: str
    aprobado_por: UUID | None = None
    aprobado_en: str | None = None


class SolicitudAfiliacionPublicIn(BaseModel):
    nombre_taller: str = Field(..., min_length=3)
    responsable_nombre: str = Field(..., min_length=3)
    responsable_email: EmailStr
    responsable_telefono: str = Field(..., min_length=6, max_length=30)
    direccion: str | None = None
    latitud: float | None = None
    longitud: float | None = None
    servicios: list[str] = Field(default_factory=list)
    descripcion: str | None = None


class SolicitudAfiliacionOut(BaseModel):
    id: UUID
    nombre_taller: str
    responsable_nombre: str
    responsable_email: str
    responsable_telefono: str
    direccion: str | None = None
    latitud: float | None = None
    longitud: float | None = None
    servicios: list[str]
    descripcion: str | None = None
    estado: str
    observaciones: str | None = None
    creado_en: str
    revisado_en: str | None = None
    revisado_por: UUID | None = None
    usuario_id: UUID | None = None
    taller_id: UUID | None = None


class SolicitudAfiliacionRevisionIn(BaseModel):
    observaciones: str | None = None


def _parsear_servicios(taller: Taller) -> Taller:
    try:
        taller.servicios = json.loads(taller.servicios or "[]")
    except Exception:
        taller.servicios = []
    return taller


def _to_taller_out(taller: Taller) -> TallerOut:
    parsed = _parsear_servicios(taller)
    aprobado_en = parsed.aprobado_en.isoformat() if getattr(parsed, "aprobado_en", None) else None
    return TallerOut(
        id=parsed.id,
        usuario_id=parsed.usuario_id,
        nombre=parsed.nombre,
        direccion=parsed.direccion,
        latitud=parsed.latitud,
        longitud=parsed.longitud,
        servicios=parsed.servicios,
        disponible=parsed.disponible,
        estado_operativo=getattr(parsed, "estado_operativo", "disponible") or "disponible",
        capacidad_maxima=int(getattr(parsed, "capacidad_maxima", 1) or 1),
        radio_cobertura_km=float(getattr(parsed, "radio_cobertura_km", 10) or 10),
        observaciones_operativas=getattr(parsed, "observaciones_operativas", None),
        calificacion=parsed.calificacion,
        estado_aprobacion=getattr(parsed, "estado_aprobacion", "pendiente") or "pendiente",
        aprobado_por=getattr(parsed, "aprobado_por", None),
        aprobado_en=aprobado_en,
        responsable_nombre=parsed.usuario.nombre if parsed.usuario else None,
        responsable_email=parsed.usuario.email if parsed.usuario else None,
        responsable_telefono=parsed.usuario.telefono if parsed.usuario else None,
    )


def _parse_servicios_raw(servicios: str | list[str] | None) -> list[str]:
    if isinstance(servicios, list):
        return servicios
    if not servicios:
        return []
    try:
        parsed = json.loads(servicios)
        if isinstance(parsed, list):
            return [str(s).strip() for s in parsed if str(s).strip()]
    except Exception:
        pass
    return [s.strip() for s in str(servicios).split(",") if s.strip()]


def _normalizar_servicios(servicios: list[str]) -> list[str]:
    normalizados: list[str] = []
    seen: set[str] = set()
    for s in servicios:
        v = (s or "").strip().lower().replace(" ", "_")
        if not v:
            continue
        if v not in seen:
            seen.add(v)
            normalizados.append(v)
    return normalizados


def _build_disponibilidad_out(db: Session, taller: Taller) -> DisponibilidadTallerOut:
    servicios = _parse_servicios_raw(taller.servicios)
    tecnicos = db.query(Tecnico).filter(Tecnico.taller_id == taller.id).all()
    tecnicos_totales = len(tecnicos)
    tecnicos_disponibles = sum(1 for t in tecnicos if t.disponible)
    carga_activa = (
        db.query(Asignacion)
        .filter(Asignacion.taller_id == taller.id, Asignacion.estado.in_(list(ESTADOS_ASIGNACION_ACTIVA)))
        .count()
    )
    capacidad_maxima = int(getattr(taller, "capacidad_maxima", 1) or 1)
    capacidad_disponible = max(0, capacidad_maxima - carga_activa)

    turnos_disponibles_rows = (
        db.query(Turno, Tecnico)
        .join(Tecnico, Tecnico.id == Turno.tecnico_id)
        .filter(Tecnico.taller_id == taller.id, Turno.disponible.is_(True))
        .order_by(Turno.inicio.desc())
        .limit(20)
        .all()
    )
    turnos_disponibles: list[TurnoDisponibleOut] = []
    for turno, tecnico in turnos_disponibles_rows:
        turnos_disponibles.append(
            TurnoDisponibleOut(
                tecnico_id=tecnico.id,
                tecnico_nombre=tecnico.nombre,
                turno_id=turno.id,
                nombre=turno.nombre,
                especialidad=turno.especialidad,
                disponible=bool(turno.disponible),
                inicio=turno.inicio.isoformat() if turno.inicio else None,
                fin=turno.fin.isoformat() if turno.fin else None,
            )
        )

    return DisponibilidadTallerOut(
        taller_id=taller.id,
        nombre_taller=taller.nombre,
        estado_operativo=(taller.estado_operativo or "disponible"),
        disponible=bool(taller.disponible),
        capacidad_maxima=capacidad_maxima,
        capacidad_disponible=capacidad_disponible,
        radio_cobertura_km=float(getattr(taller, "radio_cobertura_km", 10) or 10),
        servicios=servicios,
        tecnicos_disponibles=tecnicos_disponibles,
        tecnicos_totales=tecnicos_totales,
        direccion=taller.direccion,
        latitud=taller.latitud,
        longitud=taller.longitud,
        observaciones_operativas=taller.observaciones_operativas,
        turnos_disponibles=turnos_disponibles,
    )


def _to_solicitud_afiliacion_out(row: SolicitudTaller) -> SolicitudAfiliacionOut:
    return SolicitudAfiliacionOut(
        id=row.id,
        nombre_taller=row.nombre_taller,
        responsable_nombre=row.responsable_nombre,
        responsable_email=row.responsable_email,
        responsable_telefono=row.responsable_telefono,
        direccion=row.direccion,
        latitud=row.latitud,
        longitud=row.longitud,
        servicios=_parse_servicios_raw(row.servicios),
        descripcion=row.descripcion,
        estado=row.estado,
        observaciones=row.observaciones,
        creado_en=row.creado_en.isoformat() if row.creado_en else local_now_naive().isoformat(),
        revisado_en=row.revisado_en.isoformat() if row.revisado_en else None,
        revisado_por=row.revisado_por,
        usuario_id=row.usuario_id,
        taller_id=row.taller_id,
    )


def _asegurar_rol_taller(db: Session, usuario: Usuario) -> None:
    rol_taller = db.query(Rol).filter(Rol.nombre == "taller").first()
    if not rol_taller:
        rol_taller = Rol(nombre="taller", descripcion="Rol taller")
        db.add(rol_taller)
        db.flush()
    db.query(UsuarioRol).filter(UsuarioRol.usuario_id == usuario.id).delete()
    db.add(UsuarioRol(usuario_id=usuario.id, rol_id=rol_taller.id))
    db.flush()


def _resolve_or_create_taller_user(
    db: Session,
    *,
    usuario_id: str | None,
    responsable_nombre: str | None,
    responsable_email: str | None,
    responsable_telefono: str | None,
    password_temporal: str | None,
) -> tuple[Usuario, bool]:
    if usuario_id:
        usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
        if not usuario:
            raise HTTPException(status_code=404, detail="El usuario indicado no existe")
        _asegurar_rol_taller(db, usuario)
        return usuario, False

    if not responsable_email or not responsable_nombre:
        raise HTTPException(
            status_code=422,
            detail="Debes enviar usuario_id o responsable_email + responsable_nombre",
        )

    email_normalizado = responsable_email.strip().lower()
    usuario = db.query(Usuario).filter(func.lower(Usuario.email) == email_normalizado).first()
    was_created = False
    if not usuario:
        clave_tmp = password_temporal or f"Taller-{secrets.token_urlsafe(10)}"
        usuario = Usuario(
            nombre=responsable_nombre.strip(),
            email=email_normalizado,
            password_hash=get_password_hash(clave_tmp),
            telefono=responsable_telefono,
            estado="pendiente",
        )
        db.add(usuario)
        db.flush()
        was_created = True
    else:
        if responsable_nombre:
            usuario.nombre = responsable_nombre.strip()
        if responsable_telefono:
            usuario.telefono = responsable_telefono
        db.add(usuario)
        db.flush()

    _asegurar_rol_taller(db, usuario)
    return usuario, was_created


def _obtener_taller_de_usuario(db: Session, current_user: Usuario) -> Taller:
    taller = db.query(Taller).filter(Taller.usuario_id == current_user.id).first()
    if not taller:
        raise HTTPException(status_code=404, detail="No existe taller asociado a este usuario")
    return taller


def _resolver_solicitud(db: Session, solicitud_id_o_incidente: str) -> Solicitud | None:
    try:
        raw = uuid.UUID(str(solicitud_id_o_incidente))
    except ValueError:
        return None
    solicitud = db.query(Solicitud).filter(Solicitud.id == raw).first()
    if solicitud:
        return solicitud
    return db.query(Solicitud).filter(Solicitud.incidente_id == raw).first()


def _obtener_tecnico_de_usuario(db: Session, current_user: Usuario) -> Tecnico | None:
    # Flujo actual: técnico vinculado por usuario_id.
    tecnico = db.query(Tecnico).filter(Tecnico.usuario_id == current_user.id).first()
    if tecnico:
        return tecnico
    # Compatibilidad temporal con datos antiguos (antes del vínculo por usuario_id).
    return db.query(Tecnico).filter(Tecnico.nombre == current_user.nombre).first()


@router.post("/solicitudes-afiliacion", response_model=SolicitudAfiliacionOut)
def registrar_solicitud_afiliacion_publica(
    payload: SolicitudAfiliacionPublicIn,
    db: Session = Depends(get_db),
):
    email = payload.responsable_email.strip().lower()
    existe_pendiente = (
        db.query(SolicitudTaller)
        .filter(func.lower(SolicitudTaller.responsable_email) == email)
        .filter(SolicitudTaller.estado == "pendiente")
        .first()
    )
    if existe_pendiente:
        raise HTTPException(
            status_code=409,
            detail="Ya existe una solicitud pendiente para este correo",
        )

    solicitud = SolicitudTaller(
        nombre_taller=payload.nombre_taller.strip(),
        responsable_nombre=payload.responsable_nombre.strip(),
        responsable_email=email,
        responsable_telefono=payload.responsable_telefono.strip(),
        direccion=payload.direccion,
        latitud=payload.latitud,
        longitud=payload.longitud,
        servicios=json.dumps(payload.servicios),
        descripcion=payload.descripcion,
        estado="pendiente",
    )
    db.add(solicitud)
    db.flush()
    db.add(
        Auditoria(
            usuario_id=None,
            accion="solicitud_taller_creada",
            modulo="talleres",
            detalle=f"Solicitud pública creada para {solicitud.responsable_email}",
        )
    )
    db.commit()
    db.refresh(solicitud)
    return _to_solicitud_afiliacion_out(solicitud)


@router.get("/admin/solicitudes-afiliacion", response_model=list[SolicitudAfiliacionOut])
def listar_solicitudes_afiliacion_admin(
    estado: str | None = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede listar solicitudes")
    q = db.query(SolicitudTaller).order_by(SolicitudTaller.creado_en.desc())
    if estado:
        q = q.filter(SolicitudTaller.estado == estado)
    return [_to_solicitud_afiliacion_out(x) for x in q.all()]


@router.get("/admin/solicitudes-afiliacion/{solicitud_id}", response_model=SolicitudAfiliacionOut)
def detalle_solicitud_afiliacion_admin(
    solicitud_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede ver detalle de solicitudes")
    solicitud = db.query(SolicitudTaller).filter(SolicitudTaller.id == solicitud_id).first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    return _to_solicitud_afiliacion_out(solicitud)


@router.patch("/admin/solicitudes-afiliacion/{solicitud_id}/aprobar", response_model=SolicitudAfiliacionOut)
def aprobar_solicitud_afiliacion_admin(
    solicitud_id: str,
    payload: SolicitudAfiliacionRevisionIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede aprobar solicitudes")
    solicitud = db.query(SolicitudTaller).filter(SolicitudTaller.id == solicitud_id).first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if solicitud.estado != "pendiente":
        raise HTTPException(status_code=409, detail="Solo se pueden aprobar solicitudes pendientes")

    usuario, usuario_creado = _resolve_or_create_taller_user(
        db,
        usuario_id=None,
        responsable_nombre=solicitud.responsable_nombre,
        responsable_email=solicitud.responsable_email,
        responsable_telefono=solicitud.responsable_telefono,
        password_temporal=None,
    )

    taller_existente = db.query(Taller).filter(Taller.usuario_id == usuario.id).first()
    if taller_existente:
        taller = taller_existente
        taller.nombre = solicitud.nombre_taller
        taller.direccion = solicitud.direccion
        taller.latitud = solicitud.latitud
        taller.longitud = solicitud.longitud
        taller.servicios = solicitud.servicios
        taller.disponible = True
        taller.estado_operativo = "disponible"
        taller.capacidad_maxima = max(1, int(getattr(taller, "capacidad_maxima", 1) or 1))
        taller.radio_cobertura_km = float(getattr(taller, "radio_cobertura_km", 10) or 10)
        taller.estado_aprobacion = "aprobado"
        taller.aprobado_por = current_user.id
        taller.aprobado_en = local_now_naive()
    else:
        taller = Taller(
            usuario_id=usuario.id,
            nombre=solicitud.nombre_taller,
            direccion=solicitud.direccion,
            latitud=solicitud.latitud,
            longitud=solicitud.longitud,
            servicios=solicitud.servicios,
            disponible=True,
            estado_operativo="disponible",
            capacidad_maxima=1,
            radio_cobertura_km=10,
            estado_aprobacion="aprobado",
            aprobado_por=current_user.id,
            aprobado_en=local_now_naive(),
        )
        db.add(taller)
        db.flush()

    usuario.estado = "pendiente_activacion"
    db.add(usuario)

    solicitud.estado = "aprobado"
    solicitud.revisado_en = local_now_naive()
    solicitud.revisado_por = current_user.id
    solicitud.observaciones = payload.observaciones
    solicitud.usuario_id = usuario.id
    solicitud.taller_id = taller.id
    db.add(solicitud)

    db.add(
        Auditoria(
            usuario_id=current_user.id,
            accion="solicitud_taller_aprobada",
            modulo="talleres",
            detalle=f"Solicitud {solicitud.id} aprobada. Usuario {'creado' if usuario_creado else 'reutilizado'}: {usuario.email}",
        )
    )
    db.add(
        Notificacion(
            id=uuid.uuid4(),
            usuario_id=usuario.id,
            titulo="Afiliación de taller aprobada",
            mensaje=f"Tu taller '{taller.nombre}' fue aprobado. Revisa tu correo para crear contraseña y activar acceso.",
            tipo="onboarding_taller",
            estado="no_leida",
        )
    )
    token_activacion = generar_token_activacion_cuenta(
        db,
        str(usuario.id),
        minutes=60 * 24,
        commit=False,
    )
    frontend_url = os.getenv("FRONTEND_BASE_URL", "http://localhost:4200").rstrip("/")
    query = urlencode({"reset_token": token_activacion, "mode": "activation"})
    activation_url = f"{frontend_url}/recover-password?{query}"
    mail_ok = enviar_email(
        usuario.email,
        "AuxilioSCZ - Taller aprobado, activa tu cuenta",
        (
            f"Hola {usuario.nombre},\n\n"
            f"Tu solicitud para el taller '{taller.nombre}' fue aprobada.\n"
            "Para activar tu cuenta y crear tu contraseña, ingresa al siguiente enlace:\n\n"
            f"{activation_url}\n\n"
            "Este enlace expira en 24 horas.\n"
        ),
    )
    db.add(
        Auditoria(
            usuario_id=current_user.id,
            accion="correo_activacion_taller",
            modulo="talleres",
            detalle=f"Correo de activación {'enviado' if mail_ok else 'no_enviado'} a {usuario.email}",
        )
    )
    db.commit()
    db.refresh(solicitud)
    return _to_solicitud_afiliacion_out(solicitud)


@router.patch("/admin/solicitudes-afiliacion/{solicitud_id}/rechazar", response_model=SolicitudAfiliacionOut)
def rechazar_solicitud_afiliacion_admin(
    solicitud_id: str,
    payload: SolicitudAfiliacionRevisionIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede rechazar solicitudes")
    solicitud = db.query(SolicitudTaller).filter(SolicitudTaller.id == solicitud_id).first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if solicitud.estado != "pendiente":
        raise HTTPException(status_code=409, detail="Solo se pueden rechazar solicitudes pendientes")

    solicitud.estado = "rechazado"
    solicitud.revisado_en = local_now_naive()
    solicitud.revisado_por = current_user.id
    solicitud.observaciones = payload.observaciones
    db.add(solicitud)
    db.add(
        Auditoria(
            usuario_id=current_user.id,
            accion="solicitud_taller_rechazada",
            modulo="talleres",
            detalle=f"Solicitud {solicitud.id} rechazada",
        )
    )
    db.commit()
    db.refresh(solicitud)
    return _to_solicitud_afiliacion_out(solicitud)


@router.post("/", response_model=TallerOut)
def crear_taller(
    datos: TallerCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede crear talleres")

    usuario_taller, usuario_creado = _resolve_or_create_taller_user(
        db,
        usuario_id=datos.usuario_id,
        responsable_nombre=datos.responsable_nombre,
        responsable_email=str(datos.responsable_email) if datos.responsable_email else None,
        responsable_telefono=datos.responsable_telefono,
        password_temporal=datos.password_temporal,
    )

    taller = db.query(Taller).filter(Taller.usuario_id == usuario_taller.id).first()
    if taller:
        taller.nombre = datos.nombre
        taller.direccion = datos.direccion
        taller.latitud = datos.latitud
        taller.longitud = datos.longitud
        taller.servicios = json.dumps(datos.servicios)
        taller.disponible = datos.disponible
        taller.estado_operativo = "disponible" if datos.disponible else "ocupado"
        taller.capacidad_maxima = max(1, int(getattr(taller, "capacidad_maxima", 1) or 1))
        taller.radio_cobertura_km = float(getattr(taller, "radio_cobertura_km", 10) or 10)
        if taller.estado_aprobacion == "rechazado":
            taller.estado_aprobacion = "pendiente"
            taller.aprobado_por = None
            taller.aprobado_en = None
        db.add(
            Auditoria(
                usuario_id=current_user.id,
                accion="taller_actualizado_onboarding",
                modulo="talleres",
                detalle=f"Taller {taller.nombre} actualizado por admin",
            )
        )
    else:
        taller = Taller(
            usuario_id=usuario_taller.id,
            nombre=datos.nombre,
            direccion=datos.direccion,
            latitud=datos.latitud,
            longitud=datos.longitud,
            servicios=json.dumps(datos.servicios),
            disponible=datos.disponible,
            estado_operativo="disponible" if datos.disponible else "ocupado",
            capacidad_maxima=1,
            radio_cobertura_km=10,
            estado_aprobacion="pendiente",
            aprobado_por=None,
            aprobado_en=None,
        )
        db.add(taller)
        db.flush()
        db.add(
            Auditoria(
                usuario_id=current_user.id,
                accion="taller_registrado",
                modulo="talleres",
                detalle=f"Taller {datos.nombre} registrado para {usuario_taller.email}",
            )
        )
        db.add(
            Auditoria(
                usuario_id=current_user.id,
                accion="taller_usuario_resuelto",
                modulo="talleres",
                detalle=f"Usuario {'creado' if usuario_creado else 'reutilizado'} para onboarding de taller: {usuario_taller.email}",
            )
        )
    try:
        db.commit()
        db.refresh(taller)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="No se pudo registrar el taller por datos inválidos")
    return _to_taller_out(taller)


@router.get("/", response_model=list[TallerOut])
def listar_talleres(db: Session = Depends(get_db)):
    talleres = db.query(Taller).options(joinedload(Taller.usuario)).all()
    return [_to_taller_out(taller) for taller in talleres]


@router.get("/admin/onboarding", response_model=list[TallerOut])
def listar_talleres_onboarding(
    estado: str | None = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede listar onboarding de talleres")
    q = db.query(Taller).options(joinedload(Taller.usuario))
    if estado:
        q = q.filter(Taller.estado_aprobacion == estado)
    q = q.order_by(Taller.creado_en.desc())
    return [_to_taller_out(t) for t in q.all()]


@router.patch("/admin/{taller_id}/aprobar", response_model=TallerAprobacionOut)
def aprobar_taller(
    taller_id: str,
    payload: TallerAprobacionIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede aprobar talleres")
    taller = db.query(Taller).filter(Taller.id == taller_id).first()
    if not taller:
        raise HTTPException(status_code=404, detail="Taller no encontrado")
    taller.estado_aprobacion = "aprobado"
    taller.aprobado_por = current_user.id
    taller.aprobado_en = local_now_naive()
    if taller.usuario:
        taller.usuario.estado = "activo"
    db.add(taller)
    db.add(
        Auditoria(
            usuario_id=current_user.id,
            accion="taller_aprobado",
            modulo="talleres",
            detalle=f"Taller {taller.nombre} aprobado. {payload.comentario or ''}".strip(),
        )
    )
    if taller.usuario:
        db.add(
            Notificacion(
                id=uuid.uuid4(),
                usuario_id=taller.usuario.id,
                titulo="Taller aprobado",
                mensaje=f"Tu taller '{taller.nombre}' fue aprobado y ya está habilitado.",
                tipo="onboarding_taller",
                estado="no_leida",
            )
        )
    db.commit()
    db.refresh(taller)
    return TallerAprobacionOut(
        taller_id=taller.id,
        estado_aprobacion=taller.estado_aprobacion,
        aprobado_por=taller.aprobado_por,
        aprobado_en=taller.aprobado_en.isoformat() if taller.aprobado_en else None,
    )


@router.patch("/admin/{taller_id}/rechazar", response_model=TallerAprobacionOut)
def rechazar_taller(
    taller_id: str,
    payload: TallerAprobacionIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede rechazar talleres")
    taller = db.query(Taller).filter(Taller.id == taller_id).first()
    if not taller:
        raise HTTPException(status_code=404, detail="Taller no encontrado")
    taller.estado_aprobacion = "rechazado"
    taller.aprobado_por = current_user.id
    taller.aprobado_en = local_now_naive()
    db.add(taller)
    db.add(
        Auditoria(
            usuario_id=current_user.id,
            accion="taller_rechazado",
            modulo="talleres",
            detalle=f"Taller {taller.nombre} rechazado. {payload.comentario or ''}".strip(),
        )
    )
    if taller.usuario:
        db.add(
            Notificacion(
                id=uuid.uuid4(),
                usuario_id=taller.usuario.id,
                titulo="Taller rechazado",
                mensaje=f"Tu taller '{taller.nombre}' fue rechazado. Revisa observaciones con administración.",
                tipo="onboarding_taller",
                estado="no_leida",
            )
        )
    db.commit()
    db.refresh(taller)
    return TallerAprobacionOut(
        taller_id=taller.id,
        estado_aprobacion=taller.estado_aprobacion,
        aprobado_por=taller.aprobado_por,
        aprobado_en=taller.aprobado_en.isoformat() if taller.aprobado_en else None,
    )


@router.get("/mi-taller", response_model=TallerOut)
def mi_taller(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    if current_user.rol != "taller":
        raise HTTPException(status_code=403, detail="Solo un taller puede consultar esta información")
    return _to_taller_out(_obtener_taller_de_usuario(db, current_user))


@router.get("/mi-taller/disponibilidad", response_model=DisponibilidadTallerOut)
def obtener_disponibilidad_mi_taller(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.rol != "taller":
        raise HTTPException(status_code=403, detail="Solo un taller puede consultar su disponibilidad")
    taller = _obtener_taller_de_usuario(db, current_user)
    return _build_disponibilidad_out(db, taller)


@router.patch("/mi-taller/disponibilidad", response_model=TallerOut)
def cambiar_disponibilidad(
    payload: DisponibilidadIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.rol != "taller":
        raise HTTPException(status_code=403, detail="Solo un taller puede cambiar su disponibilidad")

    taller = _obtener_taller_de_usuario(db, current_user)
    servicios_actuales = _parse_servicios_raw(taller.servicios)
    nuevos_servicios = servicios_actuales

    if payload.estado_operativo is not None:
        estado = payload.estado_operativo.strip().lower()
        if estado not in ESTADOS_OPERATIVOS_VALIDOS:
            raise HTTPException(status_code=400, detail="estado_operativo no válido")
        taller.estado_operativo = estado

    if payload.disponible is not None:
        taller.disponible = bool(payload.disponible)
        if payload.estado_operativo is None:
            taller.estado_operativo = "disponible" if taller.disponible else "ocupado"

    if payload.capacidad_maxima is not None:
        if payload.capacidad_maxima <= 0:
            raise HTTPException(status_code=400, detail="capacidad_maxima debe ser mayor a 0")
        taller.capacidad_maxima = int(payload.capacidad_maxima)

    if payload.radio_cobertura_km is not None:
        if payload.radio_cobertura_km <= 0:
            raise HTTPException(status_code=400, detail="radio_cobertura_km debe ser mayor a 0")
        taller.radio_cobertura_km = float(payload.radio_cobertura_km)

    if payload.servicios is not None:
        nuevos_servicios = _normalizar_servicios(payload.servicios)
        if not nuevos_servicios:
            raise HTTPException(status_code=400, detail="Debes seleccionar al menos un servicio")
        taller.servicios = json.dumps(nuevos_servicios)

    if payload.latitud is not None:
        taller.latitud = payload.latitud
    if payload.longitud is not None:
        taller.longitud = payload.longitud

    if payload.observaciones_operativas is not None:
        taller.observaciones_operativas = payload.observaciones_operativas.strip() or None

    if taller.estado_operativo in {"cerrado", "fuera_de_servicio"}:
        taller.disponible = False

    carga_activa = (
        db.query(Asignacion)
        .filter(Asignacion.taller_id == taller.id, Asignacion.estado.in_(list(ESTADOS_ASIGNACION_ACTIVA)))
        .count()
    )
    if carga_activa >= int(getattr(taller, "capacidad_maxima", 1) or 1):
        taller.estado_operativo = "ocupado"
        taller.disponible = False
    elif taller.estado_operativo in {"disponible", "ocupado"} and taller.disponible:
        taller.estado_operativo = "disponible"

    db.add(
        Auditoria(
            usuario_id=current_user.id,
            accion="cu07_disponibilidad_actualizada",
            modulo="talleres",
            detalle=json.dumps(
                {
                    "taller_id": str(taller.id),
                    "estado_operativo": taller.estado_operativo,
                    "disponible": taller.disponible,
                    "capacidad_maxima": taller.capacidad_maxima,
                    "radio_cobertura_km": taller.radio_cobertura_km,
                    "servicios": nuevos_servicios,
                    "carga_activa": carga_activa,
                },
                ensure_ascii=False,
            ),
        )
    )
    db.add(
        Disponibilidad(
            id=uuid.uuid4(),
            taller_id=taller.id,
            tecnico_id=None,
            estado=taller.estado_operativo,
            desde=local_now_naive(),
            hasta=None,
        )
    )
    db.add(
        Notificacion(
            id=uuid.uuid4(),
            usuario_id=current_user.id,
            solicitud_id=None,
            incidente_id=None,
            titulo="Disponibilidad actualizada",
            mensaje=f"Estado: {taller.estado_operativo}. Capacidad máxima: {taller.capacidad_maxima}.",
            tipo="disponibilidad_taller",
            estado="no_leida",
        )
    )
    db.add(taller)
    db.commit()
    db.refresh(taller)
    return _to_taller_out(taller)


@router.post("/mi-taller/tecnicos", response_model=TecnicoOut)
def registrar_tecnico(
    payload: TecnicoCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.rol != "taller":
        raise HTTPException(status_code=403, detail="Solo un taller puede registrar técnicos")

    taller = _obtener_taller_de_usuario(db, current_user)
    usuario_tecnico = db.query(Usuario).filter(Usuario.id == payload.usuario_id).first()
    if not usuario_tecnico:
        raise HTTPException(status_code=404, detail="El usuario técnico no existe")

    rol_tecnico = db.query(Rol).filter(Rol.nombre == "tecnico").first()
    if not rol_tecnico:
        raise HTTPException(status_code=400, detail="No existe el rol 'tecnico' en el sistema")
    has_tecnico_role = (
        db.query(UsuarioRol)
        .filter(UsuarioRol.usuario_id == usuario_tecnico.id, UsuarioRol.rol_id == rol_tecnico.id)
        .first()
    )
    if not has_tecnico_role:
        raise HTTPException(status_code=400, detail="El usuario seleccionado no tiene rol técnico")

    existe_vinculo = db.query(Tecnico).filter(Tecnico.usuario_id == usuario_tecnico.id).first()
    if existe_vinculo:
        raise HTTPException(status_code=400, detail="Este usuario técnico ya está vinculado a un taller")

    tecnico = Tecnico(
        taller_id=taller.id,
        usuario_id=usuario_tecnico.id,
        nombre=usuario_tecnico.nombre,
        disponible=payload.disponible,
    )
    db.add(tecnico)
    db.commit()
    db.refresh(tecnico)
    return TecnicoOut(
        id=tecnico.id,
        usuario_id=tecnico.usuario_id,
        email=usuario_tecnico.email,
        nombre=tecnico.nombre,
        disponible=tecnico.disponible,
    )


@router.get("/mi-taller/tecnicos", response_model=list[TecnicoOut])
def listar_tecnicos_mi_taller(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.rol != "taller":
        raise HTTPException(status_code=403, detail="Solo un taller puede listar técnicos")
    taller = _obtener_taller_de_usuario(db, current_user)
    rows = db.query(Tecnico).filter(Tecnico.taller_id == taller.id).all()
    out: list[TecnicoOut] = []
    for t in rows:
        out.append(
            TecnicoOut(
                id=t.id,
                usuario_id=t.usuario_id,
                email=t.usuario.email if t.usuario else None,
                nombre=t.nombre,
                disponible=t.disponible,
            )
        )
    return out


@router.get("/mi-taller/tecnicos/candidatos", response_model=list[TecnicoCandidatoOut])
def listar_candidatos_tecnico_mi_taller(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.rol not in {"taller", "admin"}:
        raise HTTPException(status_code=403, detail="Solo taller/admin puede listar candidatos técnicos")

    rol_tecnico = db.query(Rol).filter(Rol.nombre == "tecnico").first()
    if not rol_tecnico:
        return []

    usuarios = (
        db.query(Usuario)
        .join(UsuarioRol, UsuarioRol.usuario_id == Usuario.id)
        .outerjoin(Tecnico, Tecnico.usuario_id == Usuario.id)
        .filter(UsuarioRol.rol_id == rol_tecnico.id)
        .filter(Tecnico.id == None)  # noqa: E711
        .order_by(Usuario.creado_en.desc())
        .all()
    )
    return [TecnicoCandidatoOut(id=u.id, nombre=u.nombre, email=u.email) for u in usuarios]


@router.get("/mi-taller/historial-atenciones", response_model=list[HistorialAtencionOut])
def historial_atenciones_mi_taller(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.rol != "taller":
        raise HTTPException(status_code=403, detail="Solo un taller puede consultar su historial")

    taller = _obtener_taller_de_usuario(db, current_user)
    atenciones = (
        db.query(Solicitud)
        .options(
            joinedload(Solicitud.cliente).joinedload(Cliente.usuario),
            joinedload(Solicitud.vehiculo),
            joinedload(Solicitud.emergencia).joinedload(Emergencia.ubicaciones),
            joinedload(Solicitud.asignaciones).joinedload(Asignacion.tecnico),
            joinedload(Solicitud.asignaciones).joinedload(Asignacion.taller),
            joinedload(Solicitud.cotizaciones).joinedload(Cotizacion.pago),
        )
        .join(Asignacion, Asignacion.solicitud_id == Solicitud.id)
        .filter(Asignacion.taller_id == taller.id)
        .filter(Solicitud.estado.in_(["completada", "cancelada"]))
        .order_by(Solicitud.actualizado_en.desc())
        .all()
    )

    resultado: list[HistorialAtencionOut] = []
    for solicitud in atenciones:
        pago = None
        if solicitud.cotizaciones:
            cot = sorted(
                solicitud.cotizaciones,
                key=lambda c: c.creado_en or solicitud.actualizado_en,
                reverse=True,
            )[0]
            pago = cot.pago

        vehiculo = None
        if solicitud.vehiculo:
            partes = [solicitud.vehiculo.marca, solicitud.vehiculo.modelo, solicitud.vehiculo.placa]
            vehiculo = " ".join([p for p in partes if p]).strip() or None

        ubicacion = None
        if solicitud.emergencia and solicitud.emergencia.ubicaciones:
            last = solicitud.emergencia.ubicaciones[-1]
            ubicacion = f"{last.latitud}, {last.longitud}"

        asig = sorted(solicitud.asignaciones, key=lambda a: a.asignado_en or solicitud.creado_en)[-1] if solicitud.asignaciones else None
        resultado.append(
            HistorialAtencionOut(
                id=str(solicitud.id),
                fecha=solicitud.actualizado_en.isoformat() if solicitud.actualizado_en else solicitud.creado_en.isoformat(),
                cliente=solicitud.cliente.usuario.nombre if solicitud.cliente and solicitud.cliente.usuario else None,
                vehiculo=vehiculo,
                tipo_incidente=solicitud.emergencia.tipo if solicitud.emergencia else "otro",
                estado_final=solicitud.estado,
                tecnico_asignado=asig.tecnico.nombre if asig and asig.tecnico else None,
                ubicacion=ubicacion,
                costo=pago.monto if pago else None,
                pago_monto=pago.monto if pago else None,
                pago_estado=pago.estado if pago else None,
            )
        )
    return resultado


@router.patch("/mi-taller/servicios/{incidente_id}/completar")
def completar_servicio(
    incidente_id: str,
    payload: CompletarServicioIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.rol not in {"taller", "tecnico", "admin"}:
        raise HTTPException(status_code=403, detail="Solo taller/técnico/admin puede completar servicios")
    taller = _obtener_taller_de_usuario(db, current_user) if current_user.rol in {"taller", "admin"} else None
    tecnico = _obtener_tecnico_de_usuario(db, current_user) if current_user.rol == "tecnico" else None
    if current_user.rol == "tecnico" and not tecnico:
        raise HTTPException(status_code=403, detail="No existe perfil técnico asociado a este usuario")
    solicitud = _resolver_solicitud(db, incidente_id)
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    q = db.query(Asignacion).filter(Asignacion.solicitud_id == solicitud.id)
    if current_user.rol in {"taller", "admin"} and taller:
        q = q.filter(Asignacion.taller_id == taller.id)
    if current_user.rol == "tecnico" and tecnico:
        q = q.filter(Asignacion.tecnico_id == tecnico.id)
    asig = q.order_by(Asignacion.asignado_en.desc()).first()
    if not asig:
        raise HTTPException(status_code=403, detail="No autorizado para completar esta solicitud")
    if solicitud.estado != "en_proceso":
        raise HTTPException(
            status_code=400,
            detail="Para completar el trabajo la solicitud debe estar en estado en_proceso",
        )

    estado_anterior = solicitud.estado
    solicitud.estado = "completada"
    if solicitud.emergencia:
        solicitud.emergencia.estado = "completada"
    asig.estado = "completada"
    db.add(
        Cotizacion(
            id=uuid.uuid4(),
            solicitud_id=solicitud.id,
            incidente_id=solicitud.incidente_id,
            monto=payload.costo,
            detalle="Trabajo completado por taller",
            estado="completada",
        )
    )
    db.add(
        Historial(
            id=uuid.uuid4(),
            solicitud_id=solicitud.id,
            incidente_id=solicitud.incidente_id,
            estado_anterior=estado_anterior,
            estado_nuevo=solicitud.estado,
            comentario=payload.observacion or "Trabajo completado por taller",
        )
    )
    if payload.evidencia_texto:
        db.add(
            Historial(
                id=uuid.uuid4(),
                solicitud_id=solicitud.id,
                incidente_id=solicitud.incidente_id,
                estado_anterior=solicitud.estado,
                estado_nuevo=solicitud.estado,
                comentario=f"Evidencia final: {payload.evidencia_texto}",
            )
        )
    if solicitud.cliente:
        db.add(
            Historial(
                id=uuid.uuid4(),
                solicitud_id=solicitud.id,
                incidente_id=solicitud.incidente_id,
                estado_anterior=solicitud.estado,
                estado_nuevo=solicitud.estado,
                comentario="Notificación de completado enviada al cliente",
            )
        )
    db.add(solicitud)
    if solicitud.cliente:
        db.add(
            Notificacion(
                id=uuid.uuid4(),
                usuario_id=solicitud.cliente.usuario_id,
                solicitud_id=solicitud.id,
                incidente_id=solicitud.incidente_id,
                titulo="Servicio completado",
                mensaje=f"Tu solicitud SOL-{str(solicitud.id).split('-')[0].upper()} fue completada",
                tipo="trabajo_completado",
                estado="no_leida",
            )
        )
    db.commit()
    db.refresh(solicitud)
    return {
        "ok": True,
        "incidente_id": str(solicitud.id),
        "estado_anterior": estado_anterior,
        "estado_nuevo": solicitud.estado,
        "costo_total": payload.costo,
        "comision": round(payload.costo * 0.1, 2),
    }


@router.get("/mi-taller/servicios/activos", response_model=list[ServicioActivoOut])
def listar_servicios_activos(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.rol not in {"taller", "tecnico", "admin"}:
        raise HTTPException(status_code=403, detail="Solo taller/técnico/admin puede listar servicios activos")
    taller = _obtener_taller_de_usuario(db, current_user) if current_user.rol in {"taller", "admin"} else None
    tecnico = _obtener_tecnico_de_usuario(db, current_user) if current_user.rol == "tecnico" else None
    if current_user.rol == "tecnico" and not tecnico:
        raise HTTPException(status_code=403, detail="No existe perfil técnico asociado a este usuario")
    rows = (
        db.query(Solicitud)
        .options(
            joinedload(Solicitud.cliente).joinedload(Cliente.usuario),
            joinedload(Solicitud.emergencia),
            joinedload(Solicitud.asignaciones).joinedload(Asignacion.tecnico),
        )
        .join(Asignacion, Asignacion.solicitud_id == Solicitud.id)
        .filter(Solicitud.estado.in_(["asignada", "en_proceso"]))
        .order_by(Solicitud.actualizado_en.desc())
    )
    if current_user.rol in {"taller", "admin"} and taller:
        rows = rows.filter(Asignacion.taller_id == taller.id)
    if current_user.rol == "tecnico" and tecnico:
        rows = rows.filter(Asignacion.tecnico_id == tecnico.id)
    rows = rows.all()
    out: list[ServicioActivoOut] = []
    for s in rows:
        asig = sorted(s.asignaciones, key=lambda a: a.asignado_en or s.creado_en)[-1] if s.asignaciones else None
        out.append(
            ServicioActivoOut(
                incidente_id=str(s.id),
                codigo_solicitud=f"SOL-{str(s.id).split('-')[0].upper()}",
                estado=s.estado,
                tipo_servicio=(asig.servicio if asig else None),
                tecnico_id=(str(asig.tecnico_id) if asig and asig.tecnico_id else None),
                tecnico_nombre=(asig.tecnico.nombre if asig and asig.tecnico else None),
                cliente=(s.cliente.usuario.nombre if s.cliente and s.cliente.usuario else None),
            )
        )
    return out


@router.patch("/tecnicos/mi-ubicacion")
def actualizar_mi_ubicacion_tecnico(
    payload: UbicacionTecnicoIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.rol != "tecnico":
        raise HTTPException(status_code=403, detail="Solo técnico puede reportar su ubicación")

    tecnico = _obtener_tecnico_de_usuario(db, current_user)
    if not tecnico:
        raise HTTPException(status_code=404, detail="No existe perfil técnico asociado a este usuario")

    tecnico.lat_actual = payload.lat
    tecnico.lng_actual = payload.lng
    db.add(tecnico)
    db.commit()
    db.refresh(tecnico)
    return {
        "ok": True,
        "tecnico_id": str(tecnico.id),
        "lat": tecnico.lat_actual,
        "lng": tecnico.lng_actual,
        "mensaje": "Ubicación actualizada",
    }
