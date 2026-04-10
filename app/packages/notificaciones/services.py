from .schemas import NotificacionesDemoOut


def estado_paquete_notificaciones() -> NotificacionesDemoOut:
    return NotificacionesDemoOut(mensaje="Paquete notificaciones listo para siguientes ciclos")
