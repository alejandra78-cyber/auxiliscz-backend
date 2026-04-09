from pydantic import BaseModel


class PrioridadOut(BaseModel):
    tipo: str
    prioridad: int


class FichaResumenOut(BaseModel):
    resumen: str

