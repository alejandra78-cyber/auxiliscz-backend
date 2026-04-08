"""
app/api/routes/calificaciones.py
Sistema de calificaciones y reseñas conductor → taller.
Afecta el puntaje del motor de asignación en tiempo real.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel, Field
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import Incidente, Taller
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, ForeignKey, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base

router = APIRouter()


# ── Modelo de calificación ────────────────────────────────────
class Calificacion(Base):
    __tablename__ = "calificaciones"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incidente_id = Column(UUID(as_uuid=True), ForeignKey("incidentes.id"), nullable=False, unique=True)
    taller_id = Column(UUID(as_uuid=True), ForeignKey("talleres.id"), nullable=False)
    usuario_id = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"), nullable=False)
    estrellas = Column(Integer, nullable=False)   # 1-5
    comentario = Column(Text)
    creado_en = Column(DateTime, default=datetime.utcnow)


# ── Schemas ───────────────────────────────────────────────────
class CalificacionCreate(BaseModel):
    incidente_id: str
    estrellas: int = Field(..., ge=1, le=5)
    comentario: str = None


class CalificacionOut(BaseModel):
    id: str
    estrellas: int
    comentario: str = None
    creado_en: datetime

    class Config:
        from_attributes = True


# ── Endpoints ─────────────────────────────────────────────────
@router.post("/")
def crear_calificacion(
    datos: CalificacionCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    incidente = db.query(Incidente).filter(Incidente.id == datos.incidente_id).first()
    if not incidente:
        raise HTTPException(404, "Incidente no encontrado")
    if str(incidente.usuario_id) != str(current_user.id):
        raise HTTPException(403, "Solo el conductor puede calificar este servicio")
    if incidente.estado != "atendido":
        raise HTTPException(400, "Solo se puede calificar un servicio completado")

    # Verificar que no haya calificación previa
    existente = db.query(Calificacion).filter(
        Calificacion.incidente_id == datos.incidente_id
    ).first()
    if existente:
        raise HTTPException(400, "Este servicio ya fue calificado")

    cal = Calificacion(
        incidente_id=datos.incidente_id,
        taller_id=incidente.taller_id,
        usuario_id=current_user.id,
        estrellas=datos.estrellas,
        comentario=datos.comentario
    )
    db.add(cal)

    # Actualizar calificación promedio del taller
    _actualizar_promedio_taller(db, str(incidente.taller_id))

    db.commit()
    return {"ok": True, "mensaje": "Calificación registrada"}


def _actualizar_promedio_taller(db: Session, taller_id: str):
    """Recalcula el promedio de estrellas del taller y lo guarda."""
    resultado = db.query(func.avg(Calificacion.estrellas)).filter(
        Calificacion.taller_id == taller_id
    ).scalar()
    taller = db.query(Taller).filter(Taller.id == taller_id).first()
    if taller and resultado:
        taller.calificacion = round(float(resultado), 2)
        db.flush()


@router.get("/taller/{taller_id}")
def reseñas_del_taller(taller_id: str, db: Session = Depends(get_db)):
    """Retorna las últimas 20 reseñas de un taller."""
    reseñas = (
        db.query(Calificacion)
        .filter(Calificacion.taller_id == taller_id)
        .order_by(Calificacion.creado_en.desc())
        .limit(20)
        .all()
    )
    taller = db.query(Taller).filter(Taller.id == taller_id).first()
    return {
        "taller": taller.nombre if taller else "",
        "calificacion_promedio": taller.calificacion if taller else 0,
        "total_reseñas": len(reseñas),
        "reseñas": reseñas
    }


@router.get("/mis-calificaciones")
def mis_calificaciones(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return db.query(Calificacion).filter(
        Calificacion.usuario_id == current_user.id
    ).order_by(Calificacion.creado_en.desc()).all()
