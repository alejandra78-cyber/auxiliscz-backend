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

    if firebase_json:
        # 🔵 Railway (usa variable)
        cred_dict = json.loads(firebase_json)
        cred = credentials.Certificate(cred_dict)
    else:
        # 🟢 Local (usa archivo)
        cred = credentials.Certificate("firebase-credentials.json")

    if not firebase_admin._apps:
        initialize_app(cred)


init_firebase()

Base.metadata.create_all(bind=engine)


def _ensure_incremental_schema() -> None:
    with engine.begin() as conn:
        inspector = inspect(conn)
        tables = set(inspector.get_table_names())

        if "incidentes" not in tables:
            if conn.dialect.name == "postgresql":
                conn.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS incidentes (
                            id UUID PRIMARY KEY,
                            cliente_id UUID NOT NULL REFERENCES clientes(id),
                            vehiculo_id UUID NOT NULL REFERENCES vehiculos(id),
                            estado VARCHAR(50) NOT NULL DEFAULT 'pendiente',
                            prioridad INTEGER NOT NULL DEFAULT 2,
                            tipo VARCHAR(50) NOT NULL DEFAULT 'incierto',
                            descripcion TEXT,
                            canal_origen VARCHAR(20) NOT NULL DEFAULT 'api',
                            creado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
                            actualizado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
                            cerrado_en TIMESTAMP WITHOUT TIME ZONE
                        )
                        """
                    )
                )
            else:
                conn.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS incidentes (
                            id CHAR(36) PRIMARY KEY,
                            cliente_id CHAR(36) NOT NULL REFERENCES clientes(id),
                            vehiculo_id CHAR(36) NOT NULL REFERENCES vehiculos(id),
                            estado VARCHAR(50) NOT NULL DEFAULT 'pendiente',
                            prioridad INTEGER NOT NULL DEFAULT 2,
                            tipo VARCHAR(50) NOT NULL DEFAULT 'incierto',
                            descripcion TEXT,
                            canal_origen VARCHAR(20) NOT NULL DEFAULT 'api',
                            creado_en DATETIME,
                            actualizado_en DATETIME,
                            cerrado_en DATETIME
                        )
                        """
                    )
                )

        if "asignaciones" in tables:
            cols_asig = {c["name"] for c in inspector.get_columns("asignaciones")}
            if "servicio" not in cols_asig:
                conn.execute(text("ALTER TABLE asignaciones ADD COLUMN servicio VARCHAR(100)"))
            if "incidente_id" not in cols_asig:
                conn.execute(
                    text("ALTER TABLE asignaciones ADD COLUMN incidente_id UUID")
                    if conn.dialect.name == "postgresql"
                    else text("ALTER TABLE asignaciones ADD COLUMN incidente_id CHAR(36)")
                )

        if "tecnicos" in tables:
            cols_tec = {c["name"] for c in inspector.get_columns("tecnicos")}
            if "usuario_id" not in cols_tec:
                conn.execute(text("ALTER TABLE tecnicos ADD COLUMN usuario_id UUID"))

        fk_targets = [
            ("solicitudes", "incidente_id"),
            ("emergencias", "incidente_id"),
            ("historial", "incidente_id"),
            ("notificaciones", "incidente_id"),
            ("cotizaciones", "incidente_id"),
            ("mensajes", "incidente_id"),
        ]
        for table_name, col_name in fk_targets:
            if table_name in tables:
                cols = {c["name"] for c in inspector.get_columns(table_name)}
                if col_name not in cols:
                    conn.execute(
                        text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} UUID")
                        if conn.dialect.name == "postgresql"
                        else text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} CHAR(36)")
                    )

        if conn.dialect.name == "postgresql":
            # Backfill mínimo de incidentes faltantes para referencias históricas
            # existentes en solicitudes.incidente_id.
            if "solicitudes" in tables and "incidentes" in tables:
                conn.execute(
                    text(
                        """
                        INSERT INTO incidentes (
                            id, cliente_id, vehiculo_id, estado, prioridad, tipo,
                            descripcion, canal_origen, creado_en, actualizado_en
                        )
                        SELECT
                            s.incidente_id,
                            s.cliente_id,
                            s.vehiculo_id,
                            COALESCE(s.estado, 'pendiente'),
                            COALESCE(s.prioridad, 2),
                            COALESCE(e.tipo, 'incierto'),
                            e.descripcion,
                            'legacy_backfill',
                            COALESCE(s.creado_en, NOW()),
                            COALESCE(s.actualizado_en, COALESCE(s.creado_en, NOW()))
                        FROM solicitudes s
                        LEFT JOIN emergencias e ON e.solicitud_id = s.id
                        WHERE s.incidente_id IS NOT NULL
                          AND NOT EXISTS (
                            SELECT 1 FROM incidentes i WHERE i.id = s.incidente_id
                          )
                        """
                    )
                )

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

            fk_incidente_rules = [
                ("solicitudes", "fk_solicitudes_incidente_id", "incidente_id"),
                ("emergencias", "fk_emergencias_incidente_id", "incidente_id"),
                ("historial", "fk_historial_incidente_id", "incidente_id"),
                ("asignaciones", "fk_asignaciones_incidente_id", "incidente_id"),
                ("notificaciones", "fk_notificaciones_incidente_id", "incidente_id"),
                ("cotizaciones", "fk_cotizaciones_incidente_id", "incidente_id"),
                ("mensajes", "fk_mensajes_incidente_id", "incidente_id"),
            ]
            for table_name, fk_name, col_name in fk_incidente_rules:
                if table_name in tables:
                    conn.execute(
                        text(
                            f"""
                            DO $$
                            BEGIN
                              IF NOT EXISTS (
                                SELECT 1
                                FROM pg_constraint
                                WHERE conname = '{fk_name}'
                              ) THEN
                                ALTER TABLE {table_name}
                                ADD CONSTRAINT {fk_name}
                                FOREIGN KEY ({col_name}) REFERENCES incidentes(id) NOT VALID;
                              END IF;
                            END$$;
                            """
                        )
                    )

            if "solicitudes" in tables:
                conn.execute(
                    text(
                        """
                        UPDATE emergencias e
                        SET incidente_id = s.incidente_id
                        FROM solicitudes s
                        WHERE e.solicitud_id = s.id
                          AND e.incidente_id IS NULL
                          AND s.incidente_id IS NOT NULL
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        UPDATE historial h
                        SET incidente_id = s.incidente_id
                        FROM solicitudes s
                        WHERE h.solicitud_id = s.id
                          AND h.incidente_id IS NULL
                          AND s.incidente_id IS NOT NULL
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        UPDATE asignaciones a
                        SET incidente_id = s.incidente_id
                        FROM solicitudes s
                        WHERE a.solicitud_id = s.id
                          AND a.incidente_id IS NULL
                          AND s.incidente_id IS NOT NULL
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        UPDATE notificaciones n
                        SET incidente_id = s.incidente_id
                        FROM solicitudes s
                        WHERE n.solicitud_id = s.id
                          AND n.incidente_id IS NULL
                          AND s.incidente_id IS NOT NULL
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        UPDATE cotizaciones c
                        SET incidente_id = s.incidente_id
                        FROM solicitudes s
                        WHERE c.solicitud_id = s.id
                          AND c.incidente_id IS NULL
                          AND s.incidente_id IS NOT NULL
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        UPDATE mensajes m
                        SET incidente_id = s.incidente_id
                        FROM solicitudes s
                        WHERE m.solicitud_id = s.id
                          AND m.incidente_id IS NULL
                          AND s.incidente_id IS NOT NULL
                        """
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