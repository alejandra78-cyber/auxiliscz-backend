"""
app/api/routes/websocket.py
WebSocket para:
  - Chat en tiempo real conductor ↔ taller
  - Rastreo GPS del técnico en tiempo real
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import Asignacion, Solicitud, Tecnico
from typing import Dict, List
import json, asyncio
from datetime import datetime

router = APIRouter()

# ── Gestor de conexiones activas ──────────────────────────────
class ConnectionManager:
    def __init__(self):
        # { incidente_id: [ws1, ws2, ...] }
        self.chats: Dict[str, List[WebSocket]] = {}
        # { tecnico_id: [ws_conductor, ...] }
        self.tracking: Dict[str, List[WebSocket]] = {}

    async def connect_chat(self, ws: WebSocket, incidente_id: str):
        await ws.accept()
        self.chats.setdefault(incidente_id, []).append(ws)

    async def connect_tracking(self, ws: WebSocket, incidente_id: str):
        await ws.accept()
        self.tracking.setdefault(incidente_id, []).append(ws)

    def disconnect_chat(self, ws: WebSocket, incidente_id: str):
        if incidente_id in self.chats:
            self.chats[incidente_id] = [c for c in self.chats[incidente_id] if c != ws]

    def disconnect_tracking(self, ws: WebSocket, incidente_id: str):
        if incidente_id in self.tracking:
            self.tracking[incidente_id] = [c for c in self.tracking[incidente_id] if c != ws]

    async def broadcast_chat(self, incidente_id: str, mensaje: dict):
        for ws in self.chats.get(incidente_id, []):
            try:
                await ws.send_json(mensaje)
            except Exception:
                pass

    async def broadcast_tracking(self, incidente_id: str, datos: dict):
        for ws in self.tracking.get(incidente_id, []):
            try:
                await ws.send_json(datos)
            except Exception:
                pass


manager = ConnectionManager()


# ── Chat conductor ↔ taller ───────────────────────────────────
@router.websocket("/chat/{incidente_id}")
async def chat_endpoint(websocket: WebSocket, incidente_id: str):
    """
    Conexión WebSocket para el chat de una solicitud.
    Ambas partes (conductor y taller) se conectan al mismo canal.
    Mensajes: { "autor": "conductor|taller", "texto": "...", "tipo": "texto|imagen" }
    """
    await manager.connect_chat(websocket, incidente_id)
    try:
        while True:
            data = await websocket.receive_text()
            mensaje = json.loads(data)
            mensaje["timestamp"] = datetime.utcnow().isoformat()
            await manager.broadcast_chat(incidente_id, mensaje)
    except WebSocketDisconnect:
        manager.disconnect_chat(websocket, incidente_id)


# ── Rastreo GPS del técnico ───────────────────────────────────
@router.websocket("/tracking/{incidente_id}")
async def tracking_endpoint(websocket: WebSocket, incidente_id: str, db: Session = Depends(get_db)):
    """
    El técnico envía su ubicación GPS periódicamente.
    El conductor recibe actualizaciones en tiempo real.
    Mensajes del técnico: { "lat": float, "lng": float, "rol": "tecnico" }
    Mensajes al conductor: { "lat": float, "lng": float, "eta_minutos": int }
    """
    await manager.connect_tracking(websocket, incidente_id)
    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)

            if payload.get("rol") == "tecnico":
                # Actualizar posición del técnico en DB
                solicitud = db.query(Solicitud).filter(Solicitud.id == incidente_id).first()
                if not solicitud:
                    solicitud = db.query(Solicitud).filter(Solicitud.incidente_id == incidente_id).first()
                asig = None
                if solicitud:
                    asig = (
                        db.query(Asignacion)
                        .filter(Asignacion.solicitud_id == solicitud.id, Asignacion.tecnico_id.isnot(None))
                        .order_by(Asignacion.asignado_en.desc())
                        .first()
                    )
                if asig and asig.tecnico_id:
                    tecnico = db.query(Tecnico).filter(Tecnico.id == asig.tecnico_id).first()
                    if tecnico:
                        tecnico.lat_actual = payload["lat"]
                        tecnico.lng_actual = payload["lng"]
                        db.commit()

                # Calcular ETA aproximado (simplificado)
                eta = _calcular_eta(payload.get("lat"), payload.get("lng"), incidente_id, db)

                await manager.broadcast_tracking(incidente_id, {
                    "tipo": "ubicacion_tecnico",
                    "lat": payload["lat"],
                    "lng": payload["lng"],
                    "eta_minutos": eta,
                    "timestamp": datetime.utcnow().isoformat()
                })
    except WebSocketDisconnect:
        manager.disconnect_tracking(websocket, incidente_id)


def _calcular_eta(lat_tec: float, lng_tec: float, incidente_id: str, db: Session) -> int:
    """ETA simple basado en distancia (asume 30 km/h promedio en ciudad)."""
    import math
    solicitud = db.query(Solicitud).filter(Solicitud.id == incidente_id).first()
    if not solicitud:
        solicitud = db.query(Solicitud).filter(Solicitud.incidente_id == incidente_id).first()
    if not solicitud or not solicitud.emergencia or not solicitud.emergencia.ubicaciones or not lat_tec:
        return 0
    ubicacion_ref = solicitud.emergencia.ubicaciones[-1]
    R = 6371
    d_lat = math.radians(ubicacion_ref.latitud - lat_tec)
    d_lng = math.radians(ubicacion_ref.longitud - lng_tec)
    a = math.sin(d_lat/2)**2 + math.cos(math.radians(lat_tec)) * math.cos(math.radians(ubicacion_ref.latitud)) * math.sin(d_lng/2)**2
    distancia_km = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return max(1, round(distancia_km / 30 * 60))  # minutos a 30 km/h
