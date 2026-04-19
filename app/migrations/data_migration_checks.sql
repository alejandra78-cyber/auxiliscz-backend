-- Validaciones previas/posteriores para migración de datos viejo->nuevo

-- 1) Usuarios sin rol válido en esquema antiguo
SELECT id, email, rol
FROM usuarios
WHERE lower(coalesce(rol, '')) NOT IN ('conductor', 'cliente', 'user', 'taller', 'admin', 'administrador');

-- 2) Incidentes sin vehículo asociado (afecta creación de solicitud)
SELECT id, usuario_id, vehiculo_id
FROM incidentes
WHERE vehiculo_id IS NULL;

-- 3) Incidentes sin solicitud nueva (después de migración)
SELECT i.id AS incidente_id
FROM incidentes i
LEFT JOIN solicitudes s ON s.incidente_id = i.id
WHERE s.id IS NULL;

-- 4) Solicitudes sin emergencia (después de migración)
SELECT s.id AS solicitud_id
FROM solicitudes s
LEFT JOIN emergencias e ON e.solicitud_id = s.id
WHERE e.id IS NULL;

-- 5) Pagos sin cotización enlazada
SELECT p.id AS pago_id
FROM pagos p
LEFT JOIN cotizaciones c ON c.pago_id = p.id
WHERE c.id IS NULL;

-- 6) Conteos resumen
SELECT 'usuarios' tabla, count(*) total FROM usuarios
UNION ALL SELECT 'roles', count(*) FROM roles
UNION ALL SELECT 'usuarios_roles', count(*) FROM usuarios_roles
UNION ALL SELECT 'clientes', count(*) FROM clientes
UNION ALL SELECT 'solicitudes', count(*) FROM solicitudes
UNION ALL SELECT 'emergencias', count(*) FROM emergencias
UNION ALL SELECT 'ubicaciones', count(*) FROM ubicaciones
UNION ALL SELECT 'asignaciones', count(*) FROM asignaciones
UNION ALL SELECT 'mensajes', count(*) FROM mensajes
UNION ALL SELECT 'notificaciones', count(*) FROM notificaciones
UNION ALL SELECT 'cotizaciones', count(*) FROM cotizaciones
UNION ALL SELECT 'comisiones', count(*) FROM comisiones
UNION ALL SELECT 'metricas', count(*) FROM metricas
UNION ALL SELECT 'auditorias', count(*) FROM auditorias;
