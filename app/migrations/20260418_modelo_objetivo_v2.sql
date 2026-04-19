-- Migración incremental del esquema objetivo (sin eliminar tablas existentes)
-- Fecha: 2026-04-18
-- Compatibilidad: PostgreSQL

CREATE TABLE IF NOT EXISTS roles (
  id uuid PRIMARY KEY,
  nombre varchar(60) UNIQUE NOT NULL,
  descripcion varchar(255)
);

CREATE TABLE IF NOT EXISTS permisos (
  id uuid PRIMARY KEY,
  codigo varchar(80) UNIQUE NOT NULL,
  descripcion varchar(255)
);

CREATE TABLE IF NOT EXISTS usuarios_roles (
  id uuid PRIMARY KEY,
  usuario_id uuid NOT NULL REFERENCES usuarios(id),
  rol_id uuid NOT NULL REFERENCES roles(id),
  asignado_en timestamp without time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS roles_permisos (
  id uuid PRIMARY KEY,
  rol_id uuid NOT NULL REFERENCES roles(id),
  permiso_id uuid NOT NULL REFERENCES permisos(id),
  asignado_en timestamp without time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS clientes (
  id uuid PRIMARY KEY,
  usuario_id uuid UNIQUE NOT NULL REFERENCES usuarios(id),
  direccion varchar(255),
  creado_en timestamp without time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS solicitudes (
  id uuid PRIMARY KEY,
  incidente_id uuid UNIQUE REFERENCES incidentes(id),
  cliente_id uuid NOT NULL REFERENCES clientes(id),
  vehiculo_id uuid NOT NULL REFERENCES vehiculos(id),
  estado varchar(50) DEFAULT 'pendiente',
  prioridad integer DEFAULT 2,
  creado_en timestamp without time zone DEFAULT now(),
  actualizado_en timestamp without time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS emergencias (
  id uuid PRIMARY KEY,
  solicitud_id uuid UNIQUE NOT NULL REFERENCES solicitudes(id),
  tipo varchar(50) DEFAULT 'otro',
  descripcion text,
  estado varchar(50) DEFAULT 'pendiente',
  prioridad integer DEFAULT 2,
  creado_en timestamp without time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ubicaciones (
  id uuid PRIMARY KEY,
  emergencia_id uuid NOT NULL REFERENCES emergencias(id),
  latitud double precision NOT NULL,
  longitud double precision NOT NULL,
  fuente varchar(40) DEFAULT 'gps',
  registrado_en timestamp without time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS asignaciones (
  id uuid PRIMARY KEY,
  solicitud_id uuid NOT NULL REFERENCES solicitudes(id),
  taller_id uuid REFERENCES talleres(id),
  tecnico_id uuid REFERENCES tecnicos(id),
  estado varchar(50) DEFAULT 'asignada',
  asignado_en timestamp without time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS disponibilidades (
  id uuid PRIMARY KEY,
  taller_id uuid NOT NULL REFERENCES talleres(id),
  tecnico_id uuid REFERENCES tecnicos(id),
  estado varchar(40) DEFAULT 'disponible',
  desde timestamp without time zone DEFAULT now(),
  hasta timestamp without time zone
);

CREATE TABLE IF NOT EXISTS turnos (
  id uuid PRIMARY KEY,
  tecnico_id uuid NOT NULL REFERENCES tecnicos(id),
  nombre varchar(120) NOT NULL,
  especialidad varchar(120),
  disponible boolean DEFAULT true,
  inicio timestamp without time zone DEFAULT now(),
  fin timestamp without time zone
);

CREATE TABLE IF NOT EXISTS evaluaciones (
  id uuid PRIMARY KEY,
  solicitud_id uuid NOT NULL REFERENCES solicitudes(id),
  estrellas integer NOT NULL,
  comentario text,
  creado_en timestamp without time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cotizaciones (
  id uuid PRIMARY KEY,
  solicitud_id uuid NOT NULL REFERENCES solicitudes(id),
  pago_id uuid UNIQUE REFERENCES pagos(id),
  monto double precision NOT NULL,
  detalle text,
  estado varchar(50) DEFAULT 'pendiente',
  creado_en timestamp without time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS comisiones (
  id uuid PRIMARY KEY,
  pago_id uuid UNIQUE NOT NULL REFERENCES pagos(id),
  porcentaje double precision NOT NULL DEFAULT 10.0,
  monto double precision,
  creado_en timestamp without time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS historial (
  id uuid PRIMARY KEY,
  solicitud_id uuid NOT NULL REFERENCES solicitudes(id),
  estado_anterior varchar(50),
  estado_nuevo varchar(50) NOT NULL,
  comentario text,
  creado_en timestamp without time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS solicitudes_evidencias (
  id uuid PRIMARY KEY,
  solicitud_id uuid NOT NULL REFERENCES solicitudes(id),
  evidencia_id uuid NOT NULL REFERENCES evidencias(id),
  creado_en timestamp without time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS notificaciones (
  id uuid PRIMARY KEY,
  usuario_id uuid NOT NULL REFERENCES usuarios(id),
  solicitud_id uuid REFERENCES solicitudes(id),
  titulo varchar(150) NOT NULL,
  mensaje text NOT NULL,
  tipo varchar(60) DEFAULT 'sistema',
  estado varchar(40) DEFAULT 'no_leida',
  creada_en timestamp without time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mensajes (
  id uuid PRIMARY KEY,
  solicitud_id uuid NOT NULL REFERENCES solicitudes(id),
  usuario_id uuid NOT NULL REFERENCES usuarios(id),
  contenido text NOT NULL,
  creado_en timestamp without time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS metricas (
  id uuid PRIMARY KEY,
  taller_id uuid NOT NULL REFERENCES talleres(id),
  codigo varchar(80) NOT NULL,
  valor double precision NOT NULL DEFAULT 0,
  periodo varchar(50),
  creado_en timestamp without time zone DEFAULT now()
);

CREATE TABLE IF NOT EXISTS auditorias (
  id uuid PRIMARY KEY,
  usuario_id uuid REFERENCES usuarios(id),
  accion varchar(120) NOT NULL,
  modulo varchar(80) NOT NULL,
  detalle text,
  fecha timestamp without time zone DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_solicitudes_cliente ON solicitudes(cliente_id);
CREATE INDEX IF NOT EXISTS idx_solicitudes_incidente ON solicitudes(incidente_id);
CREATE INDEX IF NOT EXISTS idx_emergencias_solicitud ON emergencias(solicitud_id);
CREATE INDEX IF NOT EXISTS idx_asignaciones_solicitud ON asignaciones(solicitud_id);
CREATE INDEX IF NOT EXISTS idx_mensajes_solicitud ON mensajes(solicitud_id);
CREATE INDEX IF NOT EXISTS idx_notificaciones_usuario ON notificaciones(usuario_id);
CREATE INDEX IF NOT EXISTS idx_historial_solicitud ON historial(solicitud_id);
