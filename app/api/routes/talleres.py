import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import Incidente, Taller, Tecnico, Usuario

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
    id: str
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
    nombre: str = Field(..., min_length=3)
    disponible: bool = True


class TecnicoOut(BaseModel):
    id: str
    nombre: str
    disponible: bool

    class Config:
        from_attributes = True


class DisponibilidadIn(BaseModel):
    disponible: bool


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


@router.post("/", response_model=TallerOut)
def crear_taller(
    datos: TallerCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede crear talleres")

    taller = Taller(
        usuario_id=datos.usuario_id,
        nombre=datos.nombre,
        direccion=datos.direccion,
        latitud=datos.latitud,
        longitud=datos.longitud,
        servicios=json.dumps(datos.servicios),
        disponible=datos.disponible,
    )
    db.add(taller)
    db.commit()
    db.refresh(taller)
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
    tecnico = Tecnico(
        taller_id=taller.id,
        nombre=payload.nombre,
        disponible=payload.disponible,
    )
    db.add(tecnico)
    db.commit()
    db.refresh(tecnico)
    return tecnico


@router.get("/mi-taller/tecnicos", response_model=list[TecnicoOut])
def listar_tecnicos_mi_taller(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.rol != "taller":
        raise HTTPException(status_code=403, detail="Solo un taller puede listar técnicos")

    taller = _obtener_taller_de_usuario(db, current_user)
    return db.query(Tecnico).filter(Tecnico.taller_id == taller.id).all()


@router.get("/mi-taller/historial-atenciones", response_model=list[HistorialAtencionOut])
def historial_atenciones_mi_taller(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.rol != "taller":
        raise HTTPException(status_code=403, detail="Solo un taller puede consultar su historial")

    taller = _obtener_taller_de_usuario(db, current_user)
    atenciones = (
        db.query(Incidente)
        .options(
            joinedload(Incidente.usuario),
            joinedload(Incidente.vehiculo),
            joinedload(Incidente.tecnico),
            joinedload(Incidente.pagos),
        )
        .filter(Incidente.taller_id == taller.id)
        .filter(Incidente.estado.in_(["atendido", "cancelado"]))
        .order_by(Incidente.actualizado_en.desc())
        .all()
    )

    resultado: list[HistorialAtencionOut] = []
    for incidente in atenciones:
        pago = None
        if incidente.pagos:
            pago = sorted(
                incidente.pagos,
                key=lambda p: p.pagado_en or incidente.actualizado_en,
                reverse=True,
            )[0]

        vehiculo = None
        if incidente.vehiculo:
            partes = [incidente.vehiculo.marca, incidente.vehiculo.modelo, incidente.vehiculo.placa]
            vehiculo = " ".join([p for p in partes if p]).strip() or None

        ubicacion = None
        if incidente.lat_incidente is not None and incidente.lng_incidente is not None:
            ubicacion = f"{incidente.lat_incidente}, {incidente.lng_incidente}"

        resultado.append(
            HistorialAtencionOut(
                id=str(incidente.id),
                fecha=incidente.actualizado_en.isoformat() if incidente.actualizado_en else incidente.creado_en.isoformat(),
                cliente=incidente.usuario.nombre if incidente.usuario else None,
                vehiculo=vehiculo,
                tipo_incidente=incidente.tipo,
                estado_final=incidente.estado,
                tecnico_asignado=incidente.tecnico.nombre if incidente.tecnico else None,
                ubicacion=ubicacion,
                costo=incidente.costo_total,
                pago_monto=pago.monto if pago else None,
                pago_estado=pago.estado if pago else None,
            )
        )
    return resultado
