"""
services/asignacion.py
Motor de asignación inteligente — selecciona el taller más adecuado
considerando: distancia, disponibilidad, tipo de servicio y prioridad.
"""
import math
import unicodedata
from sqlalchemy.orm import Session
from app.models.models import Asignacion, Taller, Tecnico
import json


RADIO_BUSQUEDA_KM = 15  # Radio máximo de búsqueda en Santa Cruz
ESTADOS_OPERATIVOS_NO_DISPONIBLES = {"cerrado", "fuera_de_servicio", "ocupado"}
ESTADOS_ASIGNACION_ACTIVA = {"pendiente_respuesta", "aceptada", "asignada", "en_proceso"}

SERVICIOS_POR_TIPO = {
    "bateria": ["bateria", "electrico", "general"],
    "llanta":  ["llanta", "goma", "neumatico", "general"],
    "motor":   ["motor", "mecanica", "general"],
    "choque":  ["choque", "grua", "remolque", "carroceria", "general"],
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


def _normalizar_tipo(tipo: str | None) -> str:
    t = (tipo or "otro").strip().lower().replace(" ", "_")
    return t if t in SERVICIOS_POR_TIPO else "otro"

def _normalizar_servicio(raw: str | None) -> str:
    s = (raw or "").strip().lower()
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.replace("/", "_").replace("-", "_").replace(" ", "_")
    while "__" in s:
        s = s.replace("__", "_")
    alias = {
        "cambio_de_llanta": "llanta",
        "cambio_llanta": "llanta",
        "remolque_grua": "remolque",
        "remolque__grua": "remolque",
        "grua": "remolque",
        "arranque_de_emergencia": "bateria",
        "auxilio_de_combustible": "combustible",
        "diagnostico_electrico": "electrico",
        "cerrajeria_automotriz": "cerrajeria",
        "mecanica_rapida": "mecanica",
    }
    return alias.get(s, s)


def _servicios_taller(taller: Taller) -> list[str]:
    raw = taller.servicios
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [_normalizar_servicio(str(s)) for s in parsed if _normalizar_servicio(str(s))]
    except Exception:
        pass
    # Compatibilidad: soporta formato legado "a,b,c"
    return [_normalizar_servicio(s) for s in str(raw).split(",") if _normalizar_servicio(s)]


def _servicio_compatible(taller: Taller, tipo: str) -> bool:
    servicios_taller = _servicios_taller(taller)
    if not servicios_taller:
        return False
    # Si IA no puede clasificar con precisión, no bloqueamos por servicio exacto.
    if _normalizar_tipo(tipo) in {"otro", "incierto"}:
        return True
    tipo_norm = _normalizar_servicio(_normalizar_tipo(tipo))
    servicios_req = [_normalizar_servicio(s) for s in SERVICIOS_POR_TIPO.get(_normalizar_tipo(tipo), ["general"])]
    if tipo_norm and tipo_norm not in servicios_req:
        servicios_req.append(tipo_norm)
    return any(s in servicios_taller for s in servicios_req)


def _tecnicos_disponibles(db: Session, taller: Taller) -> int:
    return (
        db.query(Tecnico)
        .filter(
            Tecnico.taller_id == taller.id,
            Tecnico.activo.is_(True),
            Tecnico.disponible.is_(True),
            Tecnico.estado_operativo.in_(["disponible"]),
        )
        .count()
    )


def calcular_puntaje(taller: Taller, distancia_km: float, tipo: str, prioridad: int) -> float:
    """
    Puntaje más alto = mejor candidato.
    Factores:
      - Distancia     (peso 40%): penaliza lejanía
      - Disponibilidad(peso 30%): taller abierto y con técnicos libres
      - Servicio      (peso 20%): cubre el tipo de problema
      - Calificación  (peso 10%): historial de calidad
    """
    tipo_norm = _normalizar_tipo(tipo)
    cubre = _servicio_compatible(taller, tipo_norm)
    puntaje_servicio = 1.0 if cubre else 0.0

    # Distancia: penalización exponencial
    puntaje_distancia = max(0, 1 - (distancia_km / RADIO_BUSQUEDA_KM))

    # Disponibilidad
    estado_operativo = (getattr(taller, "estado_operativo", "disponible") or "disponible").strip().lower()
    puntaje_disponible = 1.0 if (taller.disponible and estado_operativo == "disponible") else 0.0

    # Calificación normalizada (1-5 → 0-1)
    puntaje_cal = (taller.calificacion or 5.0) / 5.0

    # Bonus por prioridad alta: favorece cercanía fuerte
    bonus_urgencia = 0.25 if prioridad == 1 and distancia_km < 5 else 0.0

    puntaje_total = (
        puntaje_servicio   * 0.40 +
        puntaje_disponible * 0.25 +
        puntaje_distancia  * 0.20 +
        puntaje_cal        * 0.15 +
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


def _es_taller_elegible(
    db: Session,
    taller: Taller,
    tipo: str,
    distancia_km: float,
    *,
    exigir_aprobado: bool = True,
) -> tuple[bool, str]:
    estado_aprobacion = (getattr(taller, "estado_aprobacion", "pendiente") or "pendiente").strip().lower()
    if exigir_aprobado and estado_aprobacion != "aprobado":
        return False, "taller_no_aprobado"

    estado_operativo = (getattr(taller, "estado_operativo", "disponible") or "disponible").strip().lower()
    if estado_operativo in ESTADOS_OPERATIVOS_NO_DISPONIBLES:
        return False, f"estado_operativo={estado_operativo}"
    if not taller.disponible:
        return False, "taller_no_disponible"

    capacidad_disponible, _ = _capacidad_disponible(db, taller)
    if capacidad_disponible <= 0:
        return False, "sin_capacidad_disponible"

    radio_taller = float(getattr(taller, "radio_cobertura_km", 10) or 10)
    radio_efectivo = max(1.0, min(RADIO_BUSQUEDA_KM, radio_taller))
    if distancia_km > radio_efectivo:
        return False, f"fuera_radio({distancia_km:.2f}>{radio_efectivo:.2f})"

    if not _servicio_compatible(taller, tipo):
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
    tipo = _normalizar_tipo(tipo)
    prioridad = int(prioridad or 2)
    todos_talleres = db.query(Taller).all()

    def _candidatos(exigir_aprobado: bool) -> list[tuple[float, float, Taller]]:
        rows: list[tuple[float, float, Taller]] = []
        for taller in todos_talleres:
            if not (taller.latitud and taller.longitud):
                continue
            distancia = haversine(lat, lng, taller.latitud, taller.longitud)
            es_elegible, _ = _es_taller_elegible(db, taller, tipo, distancia, exigir_aprobado=exigir_aprobado)
            if not es_elegible:
                continue
            puntaje = calcular_puntaje(taller, distancia, tipo, prioridad)
            if _tecnicos_disponibles(db, taller) <= 0:
                puntaje -= 0.15
            rows.append((puntaje, distancia, taller))
        return rows

    candidatos = _candidatos(exigir_aprobado=True)
    if not candidatos:
        # Fallback operativo: permite asignación en ambientes donde aún no se aprobó el taller
        candidatos = _candidatos(exigir_aprobado=False)

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
    tipo = _normalizar_tipo(tipo)
    prioridad = int(prioridad or 2)
    todos_talleres = db.query(Taller).all()
    resultado = []

    def _append_candidatos(*, exigir_aprobado: bool) -> None:
        for taller in todos_talleres:
            if not (taller.latitud and taller.longitud):
                continue
            distancia = haversine(lat, lng, taller.latitud, taller.longitud)
            es_elegible, motivo_exclusion = _es_taller_elegible(
                db,
                taller,
                tipo,
                distancia,
                exigir_aprobado=exigir_aprobado,
            )
            if not es_elegible:
                continue
            puntaje = calcular_puntaje(taller, distancia, tipo, prioridad)
            capacidad_disponible, carga = _capacidad_disponible(db, taller)
            tecnicos_disponibles = _tecnicos_disponibles(db, taller)
            if tecnicos_disponibles <= 0:
                puntaje -= 0.15
            estado_aprobacion = (getattr(taller, "estado_aprobacion", "pendiente") or "pendiente").strip().lower()
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
                "tecnicos_disponibles": tecnicos_disponibles,
                "motivo": (
                    f"tipo={tipo}; prioridad={prioridad}; dist={distancia:.2f}km; "
                    f"capacidad_disponible={capacidad_disponible}; tecnicos_disponibles={tecnicos_disponibles}; "
                    f"estado={(getattr(taller, 'estado_operativo', 'disponible') or 'disponible')}; "
                    f"aprobacion={estado_aprobacion}"
                ),
                "motivo_exclusion": motivo_exclusion if motivo_exclusion != "ok" else None,
            })

    _append_candidatos(exigir_aprobado=True)
    if not resultado:
        # Fallback operativo: evita dejar solicitudes sin asignar en ambientes de pruebas
        _append_candidatos(exigir_aprobado=False)

    resultado.sort(key=lambda x: x["puntaje"], reverse=True)
    return resultado
