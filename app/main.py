from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api.routes import (
    auth, usuarios, incidentes, talleres,
    ia, pagos, notificaciones, dashboard, calificaciones
)
from .api.routes import websocket
from .packages.asignacion_servicio.router import router as asignacion_router
from .packages.emergencias.router import router as emergencias_router
from .packages.ia_incidente.router import router as ia_incidente_router
from .core.database import engine, Base

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="AuxilioSCZ API",
    description="Plataforma inteligente de asistencia vehicular — Santa Cruz, Bolivia",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST
app.include_router(auth.router,           prefix="/api/auth",           tags=["Autenticación"])
app.include_router(usuarios.router,       prefix="/api/usuarios",       tags=["Usuarios"])
app.include_router(incidentes.router,     prefix="/api/incidentes",     tags=["Incidentes"])
app.include_router(talleres.router,       prefix="/api/talleres",       tags=["Talleres"])
app.include_router(ia.router,             prefix="/api/ia",             tags=["IA"])
app.include_router(pagos.router,          prefix="/api/pagos",          tags=["Pagos"])
app.include_router(notificaciones.router, prefix="/api/notificaciones", tags=["Notificaciones"])
app.include_router(calificaciones.router, prefix="/api/calificaciones", tags=["Calificaciones"])
app.include_router(dashboard.router,      prefix="/api/dashboard",      tags=["Dashboard Admin"])
app.include_router(emergencias_router,    prefix="/api/emergencias",    tags=["Paquete 3 - Emergencias"])
app.include_router(ia_incidente_router,   prefix="/api/ia-incidente",   tags=["Paquete 5 - IA Incidente"])
app.include_router(asignacion_router,     prefix="/api/asignacion",     tags=["Paquete 6 - Asignación"])

# WebSockets
app.include_router(websocket.router,      prefix="/api/ws",             tags=["WebSocket"])

@app.get("/")
def root():
    return {"status": "ok", "app": "AuxilioSCZ API v2.0"}
