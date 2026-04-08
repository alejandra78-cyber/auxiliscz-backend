import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import Taller

router = APIRouter()


class TallerCreate(BaseModel):
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


@router.post("/", response_model=TallerOut)
def crear_taller(
    datos: TallerCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    if current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede crear talleres")

    taller = Taller(
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
    return taller


@router.get("/", response_model=list[TallerOut])
def listar_talleres(db: Session = Depends(get_db)):
    talleres = db.query(Taller).all()
    for taller in talleres:
        try:
            taller.servicios = json.loads(taller.servicios or "[]")
        except Exception:
            taller.servicios = []
    return talleres
