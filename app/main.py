from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .core.database import Base, engine

# ROUTERS NUEVOS
from .packages.auth.routes import router as auth_router
from .packages.cliente.routes import router as cliente_router
from .packages.emergencia.routes import router as emergencia_router
from .packages.pagos.routes import router as pagos_router
from .packages.taller.routes import router as taller_router

# ROUTERS EXISTENTES
from .api.routes import usuarios, solicitudes, talleres, ia, websocket

Base.metadata.create_all(bind=engine)

app = FastAPI(title="AuxilioSCZ API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔹 AUTH
app.include_router(auth_router, prefix="/api/auth")

# 🔹 CLIENTE
app.include_router(cliente_router, prefix="/api/cliente")
app.include_router(cliente_router, prefix="/api/clientes")  # compat móvil

# 🔹 EMERGENCIA
app.include_router(emergencia_router, prefix="/api/emergencia")
app.include_router(emergencia_router, prefix="/api/emergencias")  # compat móvil

# 🔹 PAGOS
app.include_router(pagos_router, prefix="/api/pagos")

# 🔹 TALLER
app.include_router(taller_router, prefix="/api/taller")

# 🔹 EXISTENTES
app.include_router(usuarios.router, prefix="/api/usuarios")
app.include_router(solicitudes.router, prefix="/api/solicitudes")
app.include_router(talleres.router, prefix="/api/talleres")
app.include_router(ia.router, prefix="/api/ia")

# 🔹 WEBSOCKET
app.include_router(websocket.router, prefix="/api/ws")


@app.get("/")
def root():
    return {"status": "ok"}