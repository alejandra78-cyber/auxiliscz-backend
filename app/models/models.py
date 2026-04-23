import uuid

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base, GUID
from app.core.time import local_now_naive


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    nombre = Column(String(100), nullable=False)
    email = Column(String(150), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    telefono = Column(String(20))
    estado = Column(String(30), default="activo")
    creado_en = Column(DateTime, default=local_now_naive)

    vehiculos = relationship("Vehiculo", back_populates="usuario")
    taller = relationship("Taller", back_populates="usuario", uselist=False, foreign_keys="Taller.usuario_id")
    cliente = relationship("Cliente", back_populates="usuario", uselist=False)
    tecnico = relationship("Tecnico", back_populates="usuario", uselist=False)
    usuario_roles = relationship("UsuarioRol", back_populates="usuario")
    notificaciones = relationship("Notificacion", back_populates="usuario")
    auditorias = relationship("Auditoria", back_populates="usuario")
    mensajes = relationship("Mensaje", back_populates="usuario")
    password_reset_tokens = relationship("PasswordResetToken", back_populates="usuario")

    @property
    def rol(self) -> str:
        if self.usuario_roles:
            return self.usuario_roles[0].rol.nombre if self.usuario_roles[0].rol else "conductor"
        return "conductor"


class Rol(Base):
    __tablename__ = "roles"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    nombre = Column(String(60), unique=True, nullable=False)
    descripcion = Column(String(255))

    usuarios = relationship("UsuarioRol", back_populates="rol")
    permisos = relationship("RolPermiso", back_populates="rol")


class Permiso(Base):
    __tablename__ = "permisos"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    codigo = Column(String(80), unique=True, nullable=False)
    descripcion = Column(String(255))

    roles = relationship("RolPermiso", back_populates="permiso")


class UsuarioRol(Base):
    __tablename__ = "usuarios_roles"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    usuario_id = Column(GUID(), ForeignKey("usuarios.id"), nullable=False)
    rol_id = Column(GUID(), ForeignKey("roles.id"), nullable=False)
    asignado_en = Column(DateTime, default=local_now_naive)

    usuario = relationship("Usuario", back_populates="usuario_roles")
    rol = relationship("Rol", back_populates="usuarios")


class RolPermiso(Base):
    __tablename__ = "roles_permisos"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    rol_id = Column(GUID(), ForeignKey("roles.id"), nullable=False)
    permiso_id = Column(GUID(), ForeignKey("permisos.id"), nullable=False)
    asignado_en = Column(DateTime, default=local_now_naive)

    rol = relationship("Rol", back_populates="permisos")
    permiso = relationship("Permiso", back_populates="roles")


class Cliente(Base):
    __tablename__ = "clientes"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    usuario_id = Column(GUID(), ForeignKey("usuarios.id"), unique=True, nullable=False)
    direccion = Column(String(255))
    creado_en = Column(DateTime, default=local_now_naive)

    usuario = relationship("Usuario", back_populates="cliente")
    solicitudes = relationship("Solicitud", back_populates="cliente")
    incidentes = relationship("Incidente", back_populates="cliente")


class SolicitudTaller(Base):
    __tablename__ = "solicitudes_taller"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    nombre_taller = Column(String(120), nullable=False)
    responsable_nombre = Column(String(120), nullable=False)
    responsable_email = Column(String(150), nullable=False, index=True)
    responsable_telefono = Column(String(30), nullable=False)
    direccion = Column(String(255))
    latitud = Column(Float)
    longitud = Column(Float)
    servicios = Column(Text)
    descripcion = Column(Text)
    estado = Column(String(20), default="pendiente", nullable=False)
    observaciones = Column(Text)
    creado_en = Column(DateTime, default=local_now_naive, nullable=False)
    revisado_en = Column(DateTime)
    revisado_por = Column(GUID(), ForeignKey("usuarios.id"), nullable=True)
    usuario_id = Column(GUID(), ForeignKey("usuarios.id"), nullable=True)
    taller_id = Column(GUID(), ForeignKey("talleres.id"), nullable=True)

    revisor = relationship("Usuario", foreign_keys=[revisado_por])
    usuario = relationship("Usuario", foreign_keys=[usuario_id])
    taller = relationship("Taller", foreign_keys=[taller_id])


class Taller(Base):
    __tablename__ = "talleres"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    usuario_id = Column(GUID(), ForeignKey("usuarios.id"), nullable=False)
    nombre = Column(String(120), nullable=False)
    direccion = Column(String(255))
    latitud = Column(Float)
    longitud = Column(Float)
    servicios = Column(Text)
    disponible = Column(Boolean, default=True)
    calificacion = Column(Float, default=5.0)
    estado_aprobacion = Column(String(20), default="pendiente", nullable=False)
    aprobado_por = Column(GUID(), ForeignKey("usuarios.id"), nullable=True)
    aprobado_en = Column(DateTime)
    creado_en = Column(DateTime, default=local_now_naive)
    actualizado_en = Column(DateTime, default=local_now_naive, onupdate=local_now_naive)

    usuario = relationship("Usuario", back_populates="taller", foreign_keys=[usuario_id])
    aprobador = relationship("Usuario", foreign_keys=[aprobado_por])
    tecnicos = relationship("Tecnico", back_populates="taller")
    disponibilidades = relationship("Disponibilidad", back_populates="taller")
    metricas = relationship("Metrica", back_populates="taller")
    asignaciones = relationship("Asignacion", back_populates="taller")


class Tecnico(Base):
    __tablename__ = "tecnicos"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    taller_id = Column(GUID(), ForeignKey("talleres.id"), nullable=False)
    usuario_id = Column(GUID(), ForeignKey("usuarios.id"), unique=True, nullable=True)
    nombre = Column(String(100), nullable=False)
    disponible = Column(Boolean, default=True)
    lat_actual = Column(Float)
    lng_actual = Column(Float)

    taller = relationship("Taller", back_populates="tecnicos")
    usuario = relationship("Usuario", back_populates="tecnico")
    turnos = relationship("Turno", back_populates="tecnico")
    asignaciones = relationship("Asignacion", back_populates="tecnico")
    disponibilidades = relationship("Disponibilidad", back_populates="tecnico")


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


class Incidente(Base):
    __tablename__ = "incidentes"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    cliente_id = Column(GUID(), ForeignKey("clientes.id"), nullable=False)
    vehiculo_id = Column(GUID(), ForeignKey("vehiculos.id"), nullable=False)
    estado = Column(String(50), default="pendiente", nullable=False)
    prioridad = Column(Integer, default=2, nullable=False)
    tipo = Column(String(50), default="incierto", nullable=False)
    descripcion = Column(Text)
    canal_origen = Column(String(20), default="api", nullable=False)
    creado_en = Column(DateTime, default=local_now_naive)
    actualizado_en = Column(DateTime, default=local_now_naive, onupdate=local_now_naive)
    cerrado_en = Column(DateTime)

    cliente = relationship("Cliente", back_populates="incidentes")
    vehiculo = relationship("Vehiculo", back_populates="incidentes")
    solicitudes = relationship("Solicitud", back_populates="incidente")
    emergencias = relationship("Emergencia", back_populates="incidente")
    asignaciones = relationship("Asignacion", back_populates="incidente")
    cotizaciones = relationship("Cotizacion", back_populates="incidente")
    historial = relationship("Historial", back_populates="incidente")
    notificaciones = relationship("Notificacion", back_populates="incidente")
    mensajes = relationship("Mensaje", back_populates="incidente")


class Solicitud(Base):
    __tablename__ = "solicitudes"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    incidente_id = Column(GUID(), ForeignKey("incidentes.id"), nullable=True, unique=True)
    cliente_id = Column(GUID(), ForeignKey("clientes.id"), nullable=False)
    vehiculo_id = Column(GUID(), ForeignKey("vehiculos.id"), nullable=False)
    estado = Column(String(50), default="pendiente")
    prioridad = Column(Integer, default=2)
    creado_en = Column(DateTime, default=local_now_naive)
    actualizado_en = Column(DateTime, default=local_now_naive, onupdate=local_now_naive)

    cliente = relationship("Cliente", back_populates="solicitudes")
    vehiculo = relationship("Vehiculo")
    incidente = relationship("Incidente", back_populates="solicitudes")
    emergencia = relationship("Emergencia", back_populates="solicitud", uselist=False)
    asignaciones = relationship("Asignacion", back_populates="solicitud")
    cotizaciones = relationship("Cotizacion", back_populates="solicitud")
    evaluaciones = relationship("Evaluacion", back_populates="solicitud")
    historial = relationship("Historial", back_populates="solicitud")
    evidencias = relationship("SolicitudEvidencia", back_populates="solicitud")
    notificaciones = relationship("Notificacion", back_populates="solicitud")
    mensajes = relationship("Mensaje", back_populates="solicitud")


class Emergencia(Base):
    __tablename__ = "emergencias"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    solicitud_id = Column(GUID(), ForeignKey("solicitudes.id"), unique=True, nullable=False)
    incidente_id = Column(GUID(), ForeignKey("incidentes.id"), nullable=True)
    tipo = Column(String(50), default="otro")
    descripcion = Column(Text)
    estado = Column(String(50), default="pendiente")
    prioridad = Column(Integer, default=2)
    creado_en = Column(DateTime, default=local_now_naive)

    solicitud = relationship("Solicitud", back_populates="emergencia")
    incidente = relationship("Incidente", back_populates="emergencias")
    ubicaciones = relationship("Ubicacion", back_populates="emergencia")


class Ubicacion(Base):
    __tablename__ = "ubicaciones"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    emergencia_id = Column(GUID(), ForeignKey("emergencias.id"), nullable=False)
    latitud = Column(Float, nullable=False)
    longitud = Column(Float, nullable=False)
    fuente = Column(String(40), default="gps")
    registrado_en = Column(DateTime, default=local_now_naive)

    emergencia = relationship("Emergencia", back_populates="ubicaciones")


class Asignacion(Base):
    __tablename__ = "asignaciones"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    solicitud_id = Column(GUID(), ForeignKey("solicitudes.id"), nullable=False)
    incidente_id = Column(GUID(), ForeignKey("incidentes.id"), nullable=True)
    taller_id = Column(GUID(), ForeignKey("talleres.id"), nullable=True)
    tecnico_id = Column(GUID(), ForeignKey("tecnicos.id"), nullable=True)
    servicio = Column(String(100))
    estado = Column(String(50), default="asignada")
    asignado_en = Column(DateTime, default=local_now_naive)

    solicitud = relationship("Solicitud", back_populates="asignaciones")
    incidente = relationship("Incidente", back_populates="asignaciones")
    taller = relationship("Taller", back_populates="asignaciones")
    tecnico = relationship("Tecnico", back_populates="asignaciones")


class Disponibilidad(Base):
    __tablename__ = "disponibilidades"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    taller_id = Column(GUID(), ForeignKey("talleres.id"), nullable=False)
    tecnico_id = Column(GUID(), ForeignKey("tecnicos.id"), nullable=True)
    estado = Column(String(40), default="disponible")
    desde = Column(DateTime, default=local_now_naive)
    hasta = Column(DateTime)

    taller = relationship("Taller", back_populates="disponibilidades")
    tecnico = relationship("Tecnico", back_populates="disponibilidades")


class Turno(Base):
    __tablename__ = "turnos"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    tecnico_id = Column(GUID(), ForeignKey("tecnicos.id"), nullable=False)
    nombre = Column(String(120), nullable=False)
    especialidad = Column(String(120))
    disponible = Column(Boolean, default=True)
    inicio = Column(DateTime, default=local_now_naive)
    fin = Column(DateTime)

    tecnico = relationship("Tecnico", back_populates="turnos")


class Evaluacion(Base):
    __tablename__ = "evaluaciones"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    solicitud_id = Column(GUID(), ForeignKey("solicitudes.id"), nullable=False)
    estrellas = Column(Integer, nullable=False)
    comentario = Column(Text)
    creado_en = Column(DateTime, default=local_now_naive)

    solicitud = relationship("Solicitud", back_populates="evaluaciones")


class Pago(Base):
    __tablename__ = "pagos"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    monto = Column(Float, nullable=False)
    estado = Column(String(50), default="pendiente")
    metodo = Column(String(50))
    pagado_en = Column(DateTime)
    comision_plataforma = Column(Float)

    cotizaciones = relationship("Cotizacion", back_populates="pago")
    comision_detalle = relationship("Comision", back_populates="pago", uselist=False)


class Cotizacion(Base):
    __tablename__ = "cotizaciones"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    solicitud_id = Column(GUID(), ForeignKey("solicitudes.id"), nullable=False)
    incidente_id = Column(GUID(), ForeignKey("incidentes.id"), nullable=True)
    pago_id = Column(GUID(), ForeignKey("pagos.id"), unique=True, nullable=True)
    monto = Column(Float, nullable=False)
    detalle = Column(Text)
    estado = Column(String(50), default="pendiente")
    creado_en = Column(DateTime, default=local_now_naive)

    solicitud = relationship("Solicitud", back_populates="cotizaciones")
    incidente = relationship("Incidente", back_populates="cotizaciones")
    pago = relationship("Pago", back_populates="cotizaciones")


class Comision(Base):
    __tablename__ = "comisiones"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    pago_id = Column(GUID(), ForeignKey("pagos.id"), unique=True, nullable=False)
    porcentaje = Column(Float, nullable=False, default=10.0)
    monto = Column(Float, nullable=True)
    creado_en = Column(DateTime, default=local_now_naive)

    pago = relationship("Pago", back_populates="comision_detalle")


class Historial(Base):
    __tablename__ = "historial"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    solicitud_id = Column(GUID(), ForeignKey("solicitudes.id"), nullable=False)
    incidente_id = Column(GUID(), ForeignKey("incidentes.id"), nullable=True)
    estado_anterior = Column(String(50))
    estado_nuevo = Column(String(50), nullable=False)
    comentario = Column(Text)
    creado_en = Column(DateTime, default=local_now_naive)

    solicitud = relationship("Solicitud", back_populates="historial")
    incidente = relationship("Incidente", back_populates="historial")


class Evidencia(Base):
    __tablename__ = "evidencias"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    tipo = Column(String(20), nullable=False)
    url_archivo = Column(String(500))
    transcripcion = Column(Text)
    subido_en = Column(DateTime, default=local_now_naive)

    solicitudes = relationship("SolicitudEvidencia", back_populates="evidencia")


class SolicitudEvidencia(Base):
    __tablename__ = "solicitudes_evidencias"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    solicitud_id = Column(GUID(), ForeignKey("solicitudes.id"), nullable=False)
    evidencia_id = Column(GUID(), ForeignKey("evidencias.id"), nullable=False)
    creado_en = Column(DateTime, default=local_now_naive)

    solicitud = relationship("Solicitud", back_populates="evidencias")
    evidencia = relationship("Evidencia", back_populates="solicitudes")


class Notificacion(Base):
    __tablename__ = "notificaciones"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    usuario_id = Column(GUID(), ForeignKey("usuarios.id"), nullable=False)
    solicitud_id = Column(GUID(), ForeignKey("solicitudes.id"), nullable=True)
    incidente_id = Column(GUID(), ForeignKey("incidentes.id"), nullable=True)
    titulo = Column(String(150), nullable=False)
    mensaje = Column(Text, nullable=False)
    tipo = Column(String(60), default="sistema")
    estado = Column(String(40), default="no_leida")
    creada_en = Column(DateTime, default=local_now_naive)

    usuario = relationship("Usuario", back_populates="notificaciones")
    solicitud = relationship("Solicitud", back_populates="notificaciones")
    incidente = relationship("Incidente", back_populates="notificaciones")


class Mensaje(Base):
    __tablename__ = "mensajes"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    solicitud_id = Column(GUID(), ForeignKey("solicitudes.id"), nullable=False)
    incidente_id = Column(GUID(), ForeignKey("incidentes.id"), nullable=True)
    usuario_id = Column(GUID(), ForeignKey("usuarios.id"), nullable=False)
    contenido = Column(Text, nullable=False)
    creado_en = Column(DateTime, default=local_now_naive)

    solicitud = relationship("Solicitud", back_populates="mensajes")
    incidente = relationship("Incidente", back_populates="mensajes")
    usuario = relationship("Usuario", back_populates="mensajes")


class Metrica(Base):
    __tablename__ = "metricas"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    taller_id = Column(GUID(), ForeignKey("talleres.id"), nullable=False)
    codigo = Column(String(80), nullable=False)
    valor = Column(Float, nullable=False, default=0)
    periodo = Column(String(50))
    creado_en = Column(DateTime, default=local_now_naive)

    taller = relationship("Taller", back_populates="metricas")


class Auditoria(Base):
    __tablename__ = "auditorias"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    usuario_id = Column(GUID(), ForeignKey("usuarios.id"), nullable=True)
    accion = Column(String(120), nullable=False)
    modulo = Column(String(80), nullable=False)
    detalle = Column(Text)
    fecha = Column(DateTime, default=local_now_naive)

    usuario = relationship("Usuario", back_populates="auditorias")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    usuario_id = Column(GUID(), ForeignKey("usuarios.id"), nullable=False, index=True)
    token_hash = Column(String(128), nullable=False, unique=True, index=True)
    scope = Column(String(40), nullable=False, default="password_recovery")
    expires_en = Column(DateTime, nullable=False)
    usado_en = Column(DateTime)
    creado_en = Column(DateTime, default=local_now_naive, nullable=False)

    usuario = relationship("Usuario", back_populates="password_reset_tokens")
