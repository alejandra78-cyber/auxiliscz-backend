from app.models.models import Usuario

ROLES_VALIDOS = {"conductor", "taller", "tecnico", "admin"}

PERMISOS_POR_ROL = {
    "conductor": [
        "reportar_emergencia",
        "registrar_vehiculo",
        "consultar_mis_incidentes",
        "cambiar_password",
    ],
    "taller": [
        "gestionar_disponibilidad",
        "actualizar_estado_servicio",
        "consultar_historial_atenciones",
        "cambiar_password",
    ],
    "tecnico": [
        "actualizar_mi_ubicacion",
        "consultar_servicios_asignados",
        "registrar_trabajo_completado",
        "cambiar_password",
    ],
    "admin": [
        "gestionar_roles",
        "ver_dashboard",
        "ver_reportes",
        "cambiar_password",
    ],
}

__all__ = ["Usuario", "ROLES_VALIDOS", "PERMISOS_POR_ROL"]
