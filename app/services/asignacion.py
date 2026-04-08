"""
services/asignacion.py
Motor de asignación inteligente — selecciona el taller más adecuado
considerando: distancia, disponibilidad, tipo de servicio y prioridad.
"""
import math
from sqlalchemy.orm import Session
from app.models.models import Taller, Tecnico
import json


RADIO_BUSQUEDA_KM = 15  # Radio máximo de búsqueda en Santa Cruz

SERVICIOS_POR_TIPO = {
    "bateria": ["bateria", "electrico", "general"],
    "llanta":  ["llanta", "goma", "neumatico", "general"],
    "motor":   ["motor", "mecanica", "general"],
    "choque":  ["grua", "remolque", "carroceria"],
    "llave":   ["cerrajeria", "llave", "general"],
    "otro":    ["general"],
    "incierto": ["general"],
}


def haversine(lat1, lng1, lat2, lng2) -> float:
    """Distancia en km entre dos puntos GPS."""
    R = 6371
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = (math.sin(d_lat/2)**2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(d_lng/2)**2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def calcular_puntaje(taller: Taller, distancia_km: float, tipo: str, prioridad: int) -> float:
    """
    Puntaje más alto = mejor candidato.
    Factores:
      - Distancia     (peso 40%): penaliza lejanía
      - Disponibilidad(peso 30%): taller abierto y con técnicos libres
      - Servicio      (peso 20%): cubre el tipo de problema
      - Calificación  (peso 10%): historial de calidad
    """
    servicios_taller = json.loads(taller.servicios or "[]")
    servicios_req = SERVICIOS_POR_TIPO.get(tipo, ["general"])

    # Cobertura de servicio: ¿el taller atiende este tipo?
    cubre = any(s in servicios_taller for s in servicios_req)
    puntaje_servicio = 1.0 if cubre else 0.3

    # Distancia: penalización exponencial
    puntaje_distancia = max(0, 1 - (distancia_km / RADIO_BUSQUEDA_KM))

    # Disponibilidad
    puntaje_disponible = 1.0 if taller.disponible else 0.0

    # Calificación normalizada (1-5 → 0-1)
    puntaje_cal = (taller.calificacion or 5.0) / 5.0

    # Bonus por prioridad alta: urgencia reduce el umbral de distancia
    bonus_urgencia = 0.2 if prioridad == 1 and distancia_km < 5 else 0

    puntaje_total = (
        puntaje_distancia  * 0.40 +
        puntaje_disponible * 0.30 +
        puntaje_servicio   * 0.20 +
        puntaje_cal        * 0.10 +
        bonus_urgencia
    )
    return puntaje_total


async def motor_asignacion(
    db: Session,
    lat: float,
    lng: float,
    tipo: str,
    prioridad: int
) -> Taller | None:
    """
    Retorna el taller más adecuado para el incidente.
    Si no hay ninguno disponible en el radio, retorna None.
    """
    todos_talleres = db.query(Taller).filter(Taller.disponible == True).all()

    candidatos = []
    for taller in todos_talleres:
        if not (taller.latitud and taller.longitud):
            continue
        distancia = haversine(lat, lng, taller.latitud, taller.longitud)
        if distancia > RADIO_BUSQUEDA_KM:
            continue
        puntaje = calcular_puntaje(taller, distancia, tipo, prioridad)
        candidatos.append((puntaje, distancia, taller))

    if not candidatos:
        return None

    # Ordenar por puntaje descendente
    candidatos.sort(key=lambda x: x[0], reverse=True)
    puntaje_ganador, distancia_ganadora, taller_ganador = candidatos[0]

    return taller_ganador


async def listar_candidatos(db: Session, lat: float, lng: float, tipo: str, prioridad: int) -> list:
    """
    Retorna lista de talleres candidatos con su puntaje y distancia.
    Útil para mostrar opciones al conductor.
    """
    todos_talleres = db.query(Taller).filter(Taller.disponible == True).all()
    resultado = []

    for taller in todos_talleres:
        if not (taller.latitud and taller.longitud):
            continue
        distancia = haversine(lat, lng, taller.latitud, taller.longitud)
        if distancia > RADIO_BUSQUEDA_KM:
            continue
        puntaje = calcular_puntaje(taller, distancia, tipo, prioridad)
        resultado.append({
            "taller_id": str(taller.id),
            "nombre": taller.nombre,
            "distancia_km": round(distancia, 2),
            "puntaje": round(puntaje, 3),
            "calificacion": taller.calificacion,
            "disponible": taller.disponible
        })

    resultado.sort(key=lambda x: x["puntaje"], reverse=True)
    return resultado
