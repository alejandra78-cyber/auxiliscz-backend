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

        if "solicitudes_taller" not in tables:
            if conn.dialect.name == "postgresql":
                conn.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS solicitudes_taller (
                            id UUID PRIMARY KEY,
                            nombre_taller VARCHAR(120) NOT NULL,
                            responsable_nombre VARCHAR(120) NOT NULL,
                            responsable_email VARCHAR(150) NOT NULL,
                            responsable_telefono VARCHAR(30) NOT NULL,
                            direccion VARCHAR(255),
                            latitud DOUBLE PRECISION,
                            longitud DOUBLE PRECISION,
                            servicios TEXT,
                            descripcion TEXT,
                            estado VARCHAR(20) NOT NULL DEFAULT 'pendiente',
                            observaciones TEXT,
                            creado_en TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                            revisado_en TIMESTAMP WITHOUT TIME ZONE,
                            revisado_por UUID REFERENCES usuarios(id),
                            usuario_id UUID REFERENCES usuarios(id),
                            taller_id UUID REFERENCES talleres(id)
                        )
                        """
                    )
                )
            else:
                conn.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS solicitudes_taller (
                            id CHAR(36) PRIMARY KEY,
                            nombre_taller VARCHAR(120) NOT NULL,
                            responsable_nombre VARCHAR(120) NOT NULL,
                            responsable_email VARCHAR(150) NOT NULL,
                            responsable_telefono VARCHAR(30) NOT NULL,
                            direccion VARCHAR(255),
                            latitud FLOAT,
                            longitud FLOAT,
                            servicios TEXT,
                            descripcion TEXT,
                            estado VARCHAR(20) NOT NULL DEFAULT 'pendiente',
                            observaciones TEXT,
                            creado_en DATETIME,
                            revisado_en DATETIME,
                            revisado_por CHAR(36),
                            usuario_id CHAR(36),
                            taller_id CHAR(36)
                        )
                        """
                    )
                )

        if "password_reset_tokens" not in tables:
            if conn.dialect.name == "postgresql":
                conn.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS password_reset_tokens (
                            id UUID PRIMARY KEY,
                            usuario_id UUID NOT NULL REFERENCES usuarios(id),
                            token_hash VARCHAR(128) NOT NULL UNIQUE,
                            scope VARCHAR(40) NOT NULL DEFAULT 'password_recovery',
                            expires_en TIMESTAMP WITHOUT TIME ZONE NOT NULL,
                            usado_en TIMESTAMP WITHOUT TIME ZONE,
                            creado_en TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
                        )
                        """
                    )
                )
            else:
                conn.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS password_reset_tokens (
                            id CHAR(36) PRIMARY KEY,
                            usuario_id CHAR(36) NOT NULL REFERENCES usuarios(id),
                            token_hash VARCHAR(128) NOT NULL UNIQUE,
                            scope VARCHAR(40) NOT NULL DEFAULT 'password_recovery',
                            expires_en DATETIME NOT NULL,
                            usado_en DATETIME,
                            creado_en DATETIME
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
            if "distancia_km" not in cols_asig:
                conn.execute(text("ALTER TABLE asignaciones ADD COLUMN distancia_km DOUBLE PRECISION"))
            if "puntaje" not in cols_asig:
                conn.execute(text("ALTER TABLE asignaciones ADD COLUMN puntaje DOUBLE PRECISION"))
            if "motivo_asignacion" not in cols_asig:
                conn.execute(text("ALTER TABLE asignaciones ADD COLUMN motivo_asignacion TEXT"))
            if "fecha_respuesta_taller" not in cols_asig:
                conn.execute(
                    text("ALTER TABLE asignaciones ADD COLUMN fecha_respuesta_taller TIMESTAMP WITHOUT TIME ZONE")
                    if conn.dialect.name == "postgresql"
                    else text("ALTER TABLE asignaciones ADD COLUMN fecha_respuesta_taller DATETIME")
                )
            if "fecha_asignacion" not in cols_asig:
                conn.execute(
                    text("ALTER TABLE asignaciones ADD COLUMN fecha_asignacion TIMESTAMP WITHOUT TIME ZONE")
                    if conn.dialect.name == "postgresql"
                    else text("ALTER TABLE asignaciones ADD COLUMN fecha_asignacion DATETIME")
                )
            if "motivo_rechazo" not in cols_asig:
                conn.execute(text("ALTER TABLE asignaciones ADD COLUMN motivo_rechazo TEXT"))
            if "origen_asignacion" not in cols_asig:
                conn.execute(text("ALTER TABLE asignaciones ADD COLUMN origen_asignacion VARCHAR(30)"))
            if "fecha_aceptacion" not in cols_asig:
                conn.execute(
                    text("ALTER TABLE asignaciones ADD COLUMN fecha_aceptacion TIMESTAMP WITHOUT TIME ZONE")
                    if conn.dialect.name == "postgresql"
                    else text("ALTER TABLE asignaciones ADD COLUMN fecha_aceptacion DATETIME")
                )
            if "fecha_inicio_camino" not in cols_asig:
                conn.execute(
                    text("ALTER TABLE asignaciones ADD COLUMN fecha_inicio_camino TIMESTAMP WITHOUT TIME ZONE")
                    if conn.dialect.name == "postgresql"
                    else text("ALTER TABLE asignaciones ADD COLUMN fecha_inicio_camino DATETIME")
                )
            if "fecha_inicio_servicio" not in cols_asig:
                conn.execute(
                    text("ALTER TABLE asignaciones ADD COLUMN fecha_inicio_servicio TIMESTAMP WITHOUT TIME ZONE")
                    if conn.dialect.name == "postgresql"
                    else text("ALTER TABLE asignaciones ADD COLUMN fecha_inicio_servicio DATETIME")
                )
            if "fecha_finalizacion" not in cols_asig:
                conn.execute(
                    text("ALTER TABLE asignaciones ADD COLUMN fecha_finalizacion TIMESTAMP WITHOUT TIME ZONE")
                    if conn.dialect.name == "postgresql"
                    else text("ALTER TABLE asignaciones ADD COLUMN fecha_finalizacion DATETIME")
                )
            if "observacion_estado" not in cols_asig:
                conn.execute(text("ALTER TABLE asignaciones ADD COLUMN observacion_estado TEXT"))
            if "motivo_cancelacion" not in cols_asig:
                conn.execute(text("ALTER TABLE asignaciones ADD COLUMN motivo_cancelacion TEXT"))
            if "cancelado_en" not in cols_asig:
                conn.execute(
                    text("ALTER TABLE asignaciones ADD COLUMN cancelado_en TIMESTAMP WITHOUT TIME ZONE")
                    if conn.dialect.name == "postgresql"
                    else text("ALTER TABLE asignaciones ADD COLUMN cancelado_en DATETIME")
                )

        if "tecnicos" in tables:
            cols_tec = {c["name"] for c in inspector.get_columns("tecnicos")}
            if "usuario_id" not in cols_tec:
                conn.execute(text("ALTER TABLE tecnicos ADD COLUMN usuario_id UUID"))
            if "email" not in cols_tec:
                conn.execute(text("ALTER TABLE tecnicos ADD COLUMN email VARCHAR(150)"))
            if "telefono" not in cols_tec:
                conn.execute(text("ALTER TABLE tecnicos ADD COLUMN telefono VARCHAR(20)"))
            if "especialidad" not in cols_tec:
                conn.execute(text("ALTER TABLE tecnicos ADD COLUMN especialidad VARCHAR(120)"))
            if "estado_operativo" not in cols_tec:
                conn.execute(text("ALTER TABLE tecnicos ADD COLUMN estado_operativo VARCHAR(30) NOT NULL DEFAULT 'disponible'"))
            if "activo" not in cols_tec:
                conn.execute(text("ALTER TABLE tecnicos ADD COLUMN activo BOOLEAN NOT NULL DEFAULT TRUE"))
            if "latitud_actual" not in cols_tec:
                conn.execute(text("ALTER TABLE tecnicos ADD COLUMN latitud_actual DOUBLE PRECISION"))
            if "longitud_actual" not in cols_tec:
                conn.execute(text("ALTER TABLE tecnicos ADD COLUMN longitud_actual DOUBLE PRECISION"))
            if "ultima_actualizacion_ubicacion" not in cols_tec:
                conn.execute(
                    text("ALTER TABLE tecnicos ADD COLUMN ultima_actualizacion_ubicacion TIMESTAMP WITHOUT TIME ZONE")
                    if conn.dialect.name == "postgresql"
                    else text("ALTER TABLE tecnicos ADD COLUMN ultima_actualizacion_ubicacion DATETIME")
                )
            if "creado_en" not in cols_tec:
                conn.execute(
                    text("ALTER TABLE tecnicos ADD COLUMN creado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()")
                    if conn.dialect.name == "postgresql"
                    else text("ALTER TABLE tecnicos ADD COLUMN creado_en DATETIME")
                )
            if "actualizado_en" not in cols_tec:
                conn.execute(
                    text("ALTER TABLE tecnicos ADD COLUMN actualizado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()")
                    if conn.dialect.name == "postgresql"
                    else text("ALTER TABLE tecnicos ADD COLUMN actualizado_en DATETIME")
                )

        if "talleres" in tables:
            cols_taller = {c["name"] for c in inspector.get_columns("talleres")}
            if "estado_aprobacion" not in cols_taller:
                conn.execute(
                    text("ALTER TABLE talleres ADD COLUMN estado_aprobacion VARCHAR(20) NOT NULL DEFAULT 'pendiente'")
                )
            if "aprobado_por" not in cols_taller:
                conn.execute(
                    text("ALTER TABLE talleres ADD COLUMN aprobado_por UUID")
                    if conn.dialect.name == "postgresql"
                    else text("ALTER TABLE talleres ADD COLUMN aprobado_por CHAR(36)")
                )
            if "aprobado_en" not in cols_taller:
                conn.execute(
                    text("ALTER TABLE talleres ADD COLUMN aprobado_en TIMESTAMP WITHOUT TIME ZONE")
                    if conn.dialect.name == "postgresql"
                    else text("ALTER TABLE talleres ADD COLUMN aprobado_en DATETIME")
                )
            if "creado_en" not in cols_taller:
                conn.execute(
                    text("ALTER TABLE talleres ADD COLUMN creado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()")
                    if conn.dialect.name == "postgresql"
                    else text("ALTER TABLE talleres ADD COLUMN creado_en DATETIME")
                )
            if "actualizado_en" not in cols_taller:
                conn.execute(
                    text("ALTER TABLE talleres ADD COLUMN actualizado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()")
                    if conn.dialect.name == "postgresql"
                    else text("ALTER TABLE talleres ADD COLUMN actualizado_en DATETIME")
                )
            if "estado_operativo" not in cols_taller:
                conn.execute(
                    text("ALTER TABLE talleres ADD COLUMN estado_operativo VARCHAR(30) NOT NULL DEFAULT 'disponible'")
                )
            if "capacidad_maxima" not in cols_taller:
                conn.execute(text("ALTER TABLE talleres ADD COLUMN capacidad_maxima INTEGER NOT NULL DEFAULT 1"))
            if "radio_cobertura_km" not in cols_taller:
                conn.execute(text("ALTER TABLE talleres ADD COLUMN radio_cobertura_km DOUBLE PRECISION NOT NULL DEFAULT 10"))
            if "observaciones_operativas" not in cols_taller:
                conn.execute(text("ALTER TABLE talleres ADD COLUMN observaciones_operativas TEXT"))

        if "vehiculos" in tables:
            cols_vehiculos = {c["name"] for c in inspector.get_columns("vehiculos")}
            if "cliente_id" not in cols_vehiculos:
                conn.execute(
                    text("ALTER TABLE vehiculos ADD COLUMN cliente_id UUID")
                    if conn.dialect.name == "postgresql"
                    else text("ALTER TABLE vehiculos ADD COLUMN cliente_id CHAR(36)")
                )
            if "tipo" not in cols_vehiculos:
                conn.execute(text("ALTER TABLE vehiculos ADD COLUMN tipo VARCHAR(40)"))
            if "observacion" not in cols_vehiculos:
                conn.execute(text("ALTER TABLE vehiculos ADD COLUMN observacion TEXT"))
            if "activo" not in cols_vehiculos:
                conn.execute(text("ALTER TABLE vehiculos ADD COLUMN activo BOOLEAN NOT NULL DEFAULT TRUE"))
            if "creado_en" not in cols_vehiculos:
                conn.execute(
                    text("ALTER TABLE vehiculos ADD COLUMN creado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()")
                    if conn.dialect.name == "postgresql"
                    else text("ALTER TABLE vehiculos ADD COLUMN creado_en DATETIME")
                )
            if "actualizado_en" not in cols_vehiculos:
                conn.execute(
                    text("ALTER TABLE vehiculos ADD COLUMN actualizado_en TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()")
                    if conn.dialect.name == "postgresql"
                    else text("ALTER TABLE vehiculos ADD COLUMN actualizado_en DATETIME")
                )

            if conn.dialect.name == "postgresql":
                conn.execute(
                    text(
                        """
                        UPDATE vehiculos v
                        SET cliente_id = c.id
                        FROM clientes c
                        WHERE c.usuario_id = v.usuario_id
                          AND v.cliente_id IS NULL
                        """
                    )
                )

        if "incidentes" in tables:
            cols_inc = {c["name"] for c in inspector.get_columns("incidentes")}
            if "latitud" not in cols_inc:
                conn.execute(text("ALTER TABLE incidentes ADD COLUMN latitud DOUBLE PRECISION"))
            if "longitud" not in cols_inc:
                conn.execute(text("ALTER TABLE incidentes ADD COLUMN longitud DOUBLE PRECISION"))
            if "direccion_referencia" not in cols_inc:
                conn.execute(text("ALTER TABLE incidentes ADD COLUMN direccion_referencia VARCHAR(255)"))
            if "resumen_ia" not in cols_inc:
                conn.execute(text("ALTER TABLE incidentes ADD COLUMN resumen_ia TEXT"))
            if "confianza_ia" not in cols_inc:
                conn.execute(text("ALTER TABLE incidentes ADD COLUMN confianza_ia DOUBLE PRECISION"))
            if "transcripcion_audio" not in cols_inc:
                conn.execute(text("ALTER TABLE incidentes ADD COLUMN transcripcion_audio TEXT"))
            if "analisis_imagen" not in cols_inc:
                conn.execute(text("ALTER TABLE incidentes ADD COLUMN analisis_imagen TEXT"))
            if "ia_estado" not in cols_inc:
                conn.execute(text("ALTER TABLE incidentes ADD COLUMN ia_estado VARCHAR(30) DEFAULT 'pendiente'"))
            if "motivo_cancelacion" not in cols_inc:
                conn.execute(text("ALTER TABLE incidentes ADD COLUMN motivo_cancelacion TEXT"))
            if "cancelado_en" not in cols_inc:
                conn.execute(
                    text("ALTER TABLE incidentes ADD COLUMN cancelado_en TIMESTAMP WITHOUT TIME ZONE")
                    if conn.dialect.name == "postgresql"
                    else text("ALTER TABLE incidentes ADD COLUMN cancelado_en DATETIME")
                )
            if "cancelado_por" not in cols_inc:
                conn.execute(
                    text("ALTER TABLE incidentes ADD COLUMN cancelado_por UUID")
                    if conn.dialect.name == "postgresql"
                    else text("ALTER TABLE incidentes ADD COLUMN cancelado_por CHAR(36)")
                )

        if "evidencias" in tables:
            cols_ev = {c["name"] for c in inspector.get_columns("evidencias")}
            if "incidente_id" not in cols_ev:
                conn.execute(
                    text("ALTER TABLE evidencias ADD COLUMN incidente_id UUID")
                    if conn.dialect.name == "postgresql"
                    else text("ALTER TABLE evidencias ADD COLUMN incidente_id CHAR(36)")
                )
            if "contenido_texto" not in cols_ev:
                conn.execute(text("ALTER TABLE evidencias ADD COLUMN contenido_texto TEXT"))
            if "metadata_json" not in cols_ev:
                conn.execute(text("ALTER TABLE evidencias ADD COLUMN metadata_json TEXT"))

            if conn.dialect.name == "postgresql":
                conn.execute(
                    text(
                        """
                        DO $$
                        BEGIN
                          IF NOT EXISTS (
                            SELECT 1
                            FROM pg_constraint
                            WHERE conname = 'fk_evidencias_incidente_id'
                          ) THEN
                            ALTER TABLE evidencias
                            ADD CONSTRAINT fk_evidencias_incidente_id
                            FOREIGN KEY (incidente_id) REFERENCES incidentes(id) NOT VALID;
                          END IF;
                        END$$;
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        UPDATE vehiculos
                        SET activo = COALESCE(activo, TRUE),
                            creado_en = COALESCE(creado_en, NOW()),
                            actualizado_en = COALESCE(actualizado_en, NOW())
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
                            WHERE conname = 'fk_vehiculos_cliente_id'
                          ) THEN
                            ALTER TABLE vehiculos
                            ADD CONSTRAINT fk_vehiculos_cliente_id
                            FOREIGN KEY (cliente_id) REFERENCES clientes(id) NOT VALID;
                          END IF;
                        END$$;
                        """
                    )
                )

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
                    """
                    CREATE INDEX IF NOT EXISTS ix_solicitudes_taller_estado_creado_en
                    ON solicitudes_taller(estado, creado_en DESC)
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_solicitudes_taller_email
                    ON solicitudes_taller(lower(responsable_email))
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_password_reset_tokens_usuario_scope
                    ON password_reset_tokens(usuario_id, scope)
                    """
                )
            )
            conn.execute(
                text(
                    """
                    DO $$
                    BEGIN
                      IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name='talleres' AND column_name='aprobado_por'
                      ) AND NOT EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conname = 'fk_talleres_aprobado_por'
                      ) THEN
                        ALTER TABLE talleres
                        ADD CONSTRAINT fk_talleres_aprobado_por
                        FOREIGN KEY (aprobado_por) REFERENCES usuarios(id) NOT VALID;
                      END IF;
                    END$$;
                    """
                )
            )
            conn.execute(
                text(
                    """
                    DO $$
                    BEGIN
                      IF NOT EXISTS (
                        SELECT 1 FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE c.relkind = 'i'
                          AND c.relname = 'ux_talleres_usuario_id'
                          AND n.nspname = 'public'
                      ) AND NOT EXISTS (
                        SELECT usuario_id
                        FROM talleres
                        WHERE usuario_id IS NOT NULL
                        GROUP BY usuario_id
                        HAVING COUNT(*) > 1
                      ) THEN
                        CREATE UNIQUE INDEX ux_talleres_usuario_id ON talleres(usuario_id);
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
app.include_router(asignacion_router,  prefix="/api/asignaciones", tags=["Asignación (Compat)"])
app.include_router(pagos_router,       prefix="/api/pagos",       tags=["Pagos"])
app.include_router(admin_router,       prefix="/api/admin",       tags=["Admin"])

app.include_router(websocket.router,   prefix="/api/ws",          tags=["WebSocket"])

@app.get("/")
def root():
    return {"status": "ok", "app": "AuxilioSCZ API v2.0"}
