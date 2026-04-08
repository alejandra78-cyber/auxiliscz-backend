import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Float, Boolean, Integer,
    ForeignKey, DateTime, Text, Enum
)
from sqlalchemy.orm import relationship
from app.core.database import Base, GUID


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    nombre = Column(String(100), nullable=False)
    email = Column(String(150), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    telefono = Column(String(20))
    rol = Column(Enum("conductor", "taller", "admin", name="rol_enum"), default="conductor")
    creado_en = Column(DateTime, default=datetime.utcnow)

    vehiculos = relationship("Vehiculo", back_populates="usuario")
    incidentes = relationship("Incidente", back_populates="usuario")
    taller = relationship("Taller", back_populates="usuario", uselist=False)


class Vehiculo(Base):
    __tablename__ = "vehiculos"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    usuario_id = Column(GUID(), ForeignKey("usuarios.id"), nullable=False)
    placa = Column(String(20), unique=True, nullable=False)
    marca = Column(String(80))
    modelo = Column(String(80))
    anio = Column(Integer)
    color = Column(String(40))

    usuario = relationship("Usuario", back_populates="vehiculos")
    incidentes = relationship("Incidente", back_populates="vehiculo")


class Taller(Base):
    __tablename__ = "talleres"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    usuario_id = Column(GUID(), ForeignKey("usuarios.id"), nullable=False)
    nombre = Column(String(120), nullable=False)
    direccion = Column(String(255))
    latitud = Column(Float)
    longitud = Column(Float)
    servicios = Column(Text)  # JSON list: ["bateria", "llanta", "motor", ...]
    disponible = Column(Boolean, default=True)
    calificacion = Column(Float, default=5.0)

    usuario = relationship("Usuario", back_populates="taller")
    tecnicos = relationship("Tecnico", back_populates="taller")
    incidentes = relationship("Incidente", back_populates="taller")


class Tecnico(Base):
    __tablename__ = "tecnicos"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    taller_id = Column(GUID(), ForeignKey("talleres.id"), nullable=False)
    nombre = Column(String(100), nullable=False)
    disponible = Column(Boolean, default=True)
    lat_actual = Column(Float)
    lng_actual = Column(Float)

    taller = relationship("Taller", back_populates="tecnicos")
    incidentes = relationship("Incidente", back_populates="tecnico")


class Incidente(Base):
    __tablename__ = "incidentes"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    usuario_id = Column(GUID(), ForeignKey("usuarios.id"), nullable=False)
    vehiculo_id = Column(GUID(), ForeignKey("vehiculos.id"))
    taller_id = Column(GUID(), ForeignKey("talleres.id"))
    tecnico_id = Column(GUID(), ForeignKey("tecnicos.id"))

    tipo = Column(Enum(
        "bateria", "llanta", "motor", "choque", "llave", "otro", "incierto",
        name="tipo_incidente_enum"
    ), default="otro")
    descripcion = Column(Text)
    estado = Column(Enum(
        "pendiente", "en_proceso", "atendido", "cancelado",
        name="estado_incidente_enum"
    ), default="pendiente")
    prioridad = Column(Integer, default=2)  # 1=alta, 2=media, 3=baja

    lat_incidente = Column(Float)
    lng_incidente = Column(Float)

    costo_total = Column(Float)
    comision = Column(Float)  # 10% del costo_total

    creado_en = Column(DateTime, default=datetime.utcnow)
    actualizado_en = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    usuario = relationship("Usuario", back_populates="incidentes")
    vehiculo = relationship("Vehiculo", back_populates="incidentes")
    taller = relationship("Taller", back_populates="incidentes")
    tecnico = relationship("Tecnico", back_populates="incidentes")
    evidencias = relationship("Evidencia", back_populates="incidente")
    analisis_ia = relationship("AnalisisIA", back_populates="incidente", uselist=False)
    pagos = relationship("Pago", back_populates="incidente")
    historial = relationship("HistorialEstado", back_populates="incidente")


class Evidencia(Base):
    __tablename__ = "evidencias"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    incidente_id = Column(GUID(), ForeignKey("incidentes.id"), nullable=False)
    tipo = Column(Enum("imagen", "audio", "texto", name="tipo_evidencia_enum"))
    url_archivo = Column(String(500))
    transcripcion = Column(Text)
    subido_en = Column(DateTime, default=datetime.utcnow)

    incidente = relationship("Incidente", back_populates="evidencias")


class AnalisisIA(Base):
    __tablename__ = "analisis_ia"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    incidente_id = Column(GUID(), ForeignKey("incidentes.id"), nullable=False, unique=True)
    clasificacion = Column(String(80))
    prioridad_sugerida = Column(Integer)
    resumen = Column(Text)
    confianza = Column(Float)
    procesado_en = Column(DateTime, default=datetime.utcnow)

    incidente = relationship("Incidente", back_populates="analisis_ia")


class Pago(Base):
    __tablename__ = "pagos"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    incidente_id = Column(GUID(), ForeignKey("incidentes.id"), nullable=False)
    monto = Column(Float, nullable=False)
    comision_plataforma = Column(Float)  # 10%
    estado = Column(Enum("pendiente", "completado", "fallido", name="estado_pago_enum"), default="pendiente")
    metodo = Column(String(50))
    pagado_en = Column(DateTime)

    incidente = relationship("Incidente", back_populates="pagos")


class HistorialEstado(Base):
    __tablename__ = "historial_estados"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    incidente_id = Column(GUID(), ForeignKey("incidentes.id"), nullable=False)
    estado_anterior = Column(String(50))
    estado_nuevo = Column(String(50))
    cambiado_en = Column(DateTime, default=datetime.utcnow)

    incidente = relationship("Incidente", back_populates="historial")
