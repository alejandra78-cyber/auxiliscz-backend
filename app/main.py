from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api.routes import calificaciones, ia, incidentes, usuarios
from .api.routes import websocket
from .packages.admin.routes import router as admin_router
from .packages.asignacion.routes import router as asignacion_router
from .packages.cliente.routes import router as cliente_router
from .packages.emergencia.routes import router as emergencia_router
from .packages.auth.routes import router as auth_router
from .packages.pagos.routes import router as pagos_router
from .packages.taller.routes import router as taller_router
from .core.database import engine, Base

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="AuxilioSCZ API",
    description="Plataforma inteligente de asistencia vehicular — Santa Cruz, Bolivia",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",
        "http://127.0.0.1:4200",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST
app.include_router(auth_router,           prefix="/api/auth",           tags=["Autenticación"])
app.include_router(cliente_router,        prefix="/api/cliente",        tags=["Cliente"])
app.include_router(cliente_router,        prefix="/api/clientes",       tags=["Cliente (Compat)"])
app.include_router(taller_router,         prefix="/api/taller",         tags=["Taller"])
app.include_router(taller_router,         prefix="/api/talleres",       tags=["Taller (Compat)"])
app.include_router(emergencia_router,     prefix="/api/emergencia",     tags=["Emergencia"])
app.include_router(emergencia_router,     prefix="/api/emergencias",    tags=["Emergencia (Compat)"])
app.include_router(asignacion_router,     prefix="/api/asignacion",     tags=["Asignación"])
app.include_router(pagos_router,          prefix="/api/pagos",          tags=["Pagos"])
app.include_router(admin_router,          prefix="/api/admin",          tags=["Admin"])

# Compatibilidad de rutas legacy aún usadas por componentes existentes.
app.include_router(usuarios.router,       prefix="/api/usuarios",       tags=["Usuarios (Legacy)"])
app.include_router(incidentes.router,     prefix="/api/incidentes",     tags=["Incidentes (Legacy)"])
app.include_router(ia.router,             prefix="/api/ia",             tags=["IA (Legacy)"])
app.include_router(calificaciones.router, prefix="/api/calificaciones", tags=["Calificaciones (Legacy)"])

# WebSockets
app.include_router(websocket.router,      prefix="/api/ws",             tags=["WebSocket"])

@app.get("/")
def root():
    return {"status": "ok", "app": "AuxilioSCZ API v2.0"}
