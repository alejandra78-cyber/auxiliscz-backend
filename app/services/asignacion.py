"""
services/asignacion.py
Motor de asignación inteligente — selecciona el taller más adecuado
considerando: distancia, disponibilidad, tipo de servicio y prioridad.
"""
import math
from sqlalchemy.orm import Session
from app.models.models import Asignacion, Taller, Tecnico
import json


RADIO_BUSQUEDA_KM = 15  # Radio máximo de búsqueda en Santa Cruz
ESTADOS_OPERATIVOS_NO_DISPONIBLES = {"cerrado", "fuera_de_servicio"}
ESTADOS_ASIGNACION_ACTIVA = {"asignada", "en_proceso"}

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
    servicios_taller = [str(s).strip().lower().replace(" ", "_") for s in servicios_taller if str(s).strip()]
    servicios_req = SERVICIOS_POR_TIPO.get(tipo, ["general"])

    # Cobertura de servicio: ¿el taller atiende este tipo?
    cubre = any(s in servicios_taller for s in servicios_req)
    puntaje_servicio = 1.0 if cubre else 0.3

    # Distancia: penalización exponencial
    puntaje_distancia = max(0, 1 - (distancia_km / RADIO_BUSQUEDA_KM))

    # Disponibilidad
    estado_operativo = (getattr(taller, "estado_operativo", "disponible") or "disponible").strip().lower()
    if estado_operativo == "ocupado":
        puntaje_disponible = 0.6
    else:
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


def _capacidad_disponible(db: Session, taller: Taller) -> tuple[int, int]:
    capacidad_maxima = int(getattr(taller, "capacidad_maxima", 1) or 1)
    carga = (
        db.query(Asignacion)
        .filter(Asignacion.taller_id == taller.id, Asignacion.estado.in_(list(ESTADOS_ASIGNACION_ACTIVA)))
        .count()
    )
    return max(0, capacidad_maxima - carga), carga


def _es_taller_elegible(db: Session, taller: Taller, tipo: str, distancia_km: float) -> tuple[bool, str]:
    estado_operativo = (getattr(taller, "estado_operativo", "disponible") or "disponible").strip().lower()
    if estado_operativo in ESTADOS_OPERATIVOS_NO_DISPONIBLES:
        return False, f"estado_operativo={estado_operativo}"
    if not taller.disponible and estado_operativo != "ocupado":
        return False, "taller_no_disponible"

    capacidad_disponible, _ = _capacidad_disponible(db, taller)
    if capacidad_disponible <= 0:
        return False, "sin_capacidad_disponible"

    radio_taller = float(getattr(taller, "radio_cobertura_km", 10) or 10)
    radio_efectivo = max(1.0, min(RADIO_BUSQUEDA_KM, radio_taller))
    if distancia_km > radio_efectivo:
        return False, f"fuera_radio({distancia_km:.2f}>{radio_efectivo:.2f})"

    servicios_taller = json.loads(taller.servicios or "[]")
    servicios_taller = [str(s).strip().lower().replace(" ", "_") for s in servicios_taller if str(s).strip()]
    servicios_req = SERVICIOS_POR_TIPO.get(tipo, ["general"])
    cubre = any(s in servicios_taller for s in servicios_req)
    if not cubre:
        return False, "sin_cobertura_servicio"
    return True, "ok"


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
    todos_talleres = db.query(Taller).all()

    candidatos = []
    for taller in todos_talleres:
        if not (taller.latitud and taller.longitud):
            continue
        distancia = haversine(lat, lng, taller.latitud, taller.longitud)
        es_elegible, _ = _es_taller_elegible(db, taller, tipo, distancia)
        if not es_elegible:
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
    todos_talleres = db.query(Taller).all()
    resultado = []

    for taller in todos_talleres:
        if not (taller.latitud and taller.longitud):
            continue
        distancia = haversine(lat, lng, taller.latitud, taller.longitud)
        es_elegible, motivo_exclusion = _es_taller_elegible(db, taller, tipo, distancia)
        if not es_elegible:
            continue
        puntaje = calcular_puntaje(taller, distancia, tipo, prioridad)
        capacidad_disponible, carga = _capacidad_disponible(db, taller)
        resultado.append({
            "taller_id": str(taller.id),
            "nombre": taller.nombre,
            "distancia_km": round(distancia, 2),
            "puntaje": round(puntaje, 3),
            "calificacion": taller.calificacion,
            "disponible": taller.disponible,
            "estado_operativo": getattr(taller, "estado_operativo", "disponible") or "disponible",
            "capacidad_disponible": capacidad_disponible,
            "carga_activa": carga,
            "motivo": (
                f"ok; dist={distancia:.2f}km; capacidad_disponible={capacidad_disponible}; "
                f"estado={(getattr(taller, 'estado_operativo', 'disponible') or 'disponible')}"
            ),
            "motivo_exclusion": motivo_exclusion if motivo_exclusion != "ok" else None,
        })

    resultado.sort(key=lambda x: x["puntaje"], reverse=True)
    return resultado
