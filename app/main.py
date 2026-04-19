from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api.routes import (
    auth, usuarios, incidentes, talleres,
    ia, pagos, notificaciones, dashboard, calificaciones
)
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


def _ensure_incremental_schema() -> None:
    # Cambios incrementales sin migración destructiva.
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE IF EXISTS asignaciones ADD COLUMN IF NOT EXISTS servicio VARCHAR(100)"))
        conn.execute(text("ALTER TABLE IF EXISTS tecnicos ADD COLUMN IF NOT EXISTS usuario_id UUID"))
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                  IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'fk_tecnicos_usuario_id'
                  ) THEN
                    ALTER TABLE tecnicos
                    ADD CONSTRAINT fk_tecnicos_usuario_id
                    FOREIGN KEY (usuario_id) REFERENCES usuarios(id);
                  END IF;
                END$$;
                """
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_tecnicos_usuario_id ON tecnicos(usuario_id) WHERE usuario_id IS NOT NULL"
            )
        )


_ensure_incremental_schema()

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
        "https://auxiliscz-web-speu.onrender.com",
    ],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
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

# WebSockets
app.include_router(websocket.router,      prefix="/api/ws",             tags=["WebSocket"])

@app.get("/")
def root():
    return {"status": "ok", "app": "AuxilioSCZ API v2.0"}
