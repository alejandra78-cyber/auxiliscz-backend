from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text
from firebase_admin import credentials, initialize_app
import firebase_admin
import os
import json

from .api.routes import websocket
from .packages.admin.routes import router as admin_router
from .packages.asignacion.routes import router as asignacion_router
from .packages.cliente.routes import router as cliente_router
from .packages.emergencia.routes import router as emergencia_router
from .packages.auth.routes import router as auth_router
from .packages.pagos.routes import router as pagos_router
from .packages.taller.routes import router as taller_router
from .core.database import engine, Base


def init_firebase():
    firebase_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
    if not firebase_json:
        raise ValueError("No existe FIREBASE_CREDENTIALS_JSON")

    cred_dict = json.loads(firebase_json)

    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_dict)
        initialize_app(cred)


init_firebase()

Base.metadata.create_all(bind=engine)


def _ensure_incremental_schema() -> None:
    with engine.begin() as conn:
        inspector = inspect(conn)
        tables = set(inspector.get_table_names())

        if "asignaciones" in tables:
            cols_asig = {c["name"] for c in inspector.get_columns("asignaciones")}
            if "servicio" not in cols_asig:
                conn.execute(text("ALTER TABLE asignaciones ADD COLUMN servicio VARCHAR(100)"))

        if "tecnicos" in tables:
            cols_tec = {c["name"] for c in inspector.get_columns("tecnicos")}
            if "usuario_id" not in cols_tec:
                conn.execute(text("ALTER TABLE tecnicos ADD COLUMN usuario_id UUID"))

        if conn.dialect.name == "postgresql":
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

app.include_router(auth_router,        prefix="/api/auth",        tags=["Autenticación"])
app.include_router(cliente_router,     prefix="/api/cliente",     tags=["Cliente"])
app.include_router(cliente_router,     prefix="/api/clientes",    tags=["Cliente (Compat)"])
app.include_router(taller_router,      prefix="/api/taller",      tags=["Taller"])
app.include_router(taller_router,      prefix="/api/talleres",    tags=["Taller (Compat)"])
app.include_router(emergencia_router,  prefix="/api/emergencia",  tags=["Emergencia"])
app.include_router(emergencia_router,  prefix="/api/emergencias", tags=["Emergencia (Compat)"])
app.include_router(asignacion_router,  prefix="/api/asignacion",  tags=["Asignación"])
app.include_router(pagos_router,       prefix="/api/pagos",       tags=["Pagos"])
app.include_router(admin_router,       prefix="/api/admin",       tags=["Admin"])

app.include_router(websocket.router,   prefix="/api/ws",          tags=["WebSocket"])

@app.get("/")
def root():
    return {"status": "ok", "app": "AuxilioSCZ API v2.0"}