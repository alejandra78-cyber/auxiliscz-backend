from app.models.models import Usuario

ROLES_VALIDOS = {"conductor", "taller", "admin"}

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
    "admin": [
        "gestionar_roles",
        "ver_dashboard",
        "ver_reportes",
        "cambiar_password",
    ],
}

__all__ = ["Usuario", "ROLES_VALIDOS", "PERMISOS_POR_ROL"]
