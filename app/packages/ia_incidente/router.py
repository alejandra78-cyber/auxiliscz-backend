from fastapi import APIRouter, File, UploadFile

from .schemas import FichaResumenOut, PrioridadOut
from .service import (
    analizar_imagen_para_danos,
    asignar_nivel_prioridad,
    clasificar_incidente_por_imagenes,
    transcribir_audio_a_texto,
)

router = APIRouter()


@router.post("/transcribir-audio")
async def transcribir_audio_endpoint(audio: UploadFile = File(...)):
    contenido = await audio.read()
    texto = await transcribir_audio_a_texto(contenido)
    return {"texto": texto}


@router.post("/clasificar-imagen")
async def clasificar_imagen_endpoint(imagen: UploadFile = File(...)):
    contenido = await imagen.read()
    resultado = await clasificar_incidente_por_imagenes(contenido)
    return resultado


@router.post("/analizar-danos")
async def analizar_danos_endpoint(imagen: UploadFile = File(...)):
    contenido = await imagen.read()
    return await analizar_imagen_para_danos(contenido)


@router.get("/prioridad/{tipo_incidente}", response_model=PrioridadOut)
def prioridad_endpoint(tipo_incidente: str):
    return PrioridadOut(tipo=tipo_incidente, prioridad=asignar_nivel_prioridad(tipo_incidente))


@router.get("/ficha-demo", response_model=FichaResumenOut)
def ficha_demo_endpoint():
    return FichaResumenOut(resumen="Ficha resumen generada por IA.")

