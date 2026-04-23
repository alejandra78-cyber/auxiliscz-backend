import json
import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import (
    Asignacion,
    Cliente,
    Cotizacion,
    Emergencia,
    Historial,
    Notificacion,
    Rol,
    Solicitud,
    Taller,
    Tecnico,
    Ubicacion,
    Usuario,
    UsuarioRol,
)

router = APIRouter()


class TallerCreate(BaseModel):
    usuario_id: str
    nombre: str = Field(..., min_length=3)
    direccion: str | None = None
    latitud: float | None = None
    longitud: float | None = None
    servicios: list[str] = Field(default_factory=list)
    disponible: bool = True


class TallerOut(BaseModel):
    id: UUID
    nombre: str
    direccion: str | None = None
    latitud: float | None = None
    longitud: float | None = None
    servicios: list[str]
    disponible: bool
    calificacion: float

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
    disponible: bool


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


def _parsear_servicios(taller: Taller) -> Taller:
    try:
        taller.servicios = json.loads(taller.servicios or "[]")
    except Exception:
        taller.servicios = []
    return taller


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


@router.post("/", response_model=TallerOut)
def crear_taller(
    datos: TallerCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede crear talleres")

    usuario_taller = db.query(Usuario).filter(Usuario.id == datos.usuario_id).first()
    if not usuario_taller:
        raise HTTPException(status_code=404, detail="El usuario indicado no existe")
    if usuario_taller.rol != "taller":
        raise HTTPException(status_code=400, detail="El usuario indicado debe tener rol 'taller'")

    taller_existente = db.query(Taller).filter(Taller.usuario_id == datos.usuario_id).first()
    if taller_existente:
        raise HTTPException(status_code=400, detail="El usuario ya tiene un taller registrado")

    taller = Taller(
        usuario_id=datos.usuario_id,
        nombre=datos.nombre,
        direccion=datos.direccion,
        latitud=datos.latitud,
        longitud=datos.longitud,
        servicios=json.dumps(datos.servicios),
        disponible=datos.disponible,
    )
    try:
        db.add(taller)
        db.commit()
        db.refresh(taller)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="No se pudo registrar el taller por datos inválidos")
    return _parsear_servicios(taller)


@router.get("/", response_model=list[TallerOut])
def listar_talleres(db: Session = Depends(get_db)):
    talleres = db.query(Taller).all()
    return [_parsear_servicios(taller) for taller in talleres]


@router.get("/mi-taller", response_model=TallerOut)
def mi_taller(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    if current_user.rol != "taller":
        raise HTTPException(status_code=403, detail="Solo un taller puede consultar esta información")
    return _parsear_servicios(_obtener_taller_de_usuario(db, current_user))


@router.patch("/mi-taller/disponibilidad", response_model=TallerOut)
def cambiar_disponibilidad(
    payload: DisponibilidadIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.rol != "taller":
        raise HTTPException(status_code=403, detail="Solo un taller puede cambiar su disponibilidad")

    taller = _obtener_taller_de_usuario(db, current_user)
    taller.disponible = payload.disponible
    db.add(taller)
    db.commit()
    db.refresh(taller)
    return _parsear_servicios(taller)


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
