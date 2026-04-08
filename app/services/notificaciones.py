async def enviar_push(usuario_id: str, payload: dict):
    """Envío de notificaciones push simulado para ejecución local."""
    # En un entorno real, aquí se enviaría una notificación vía Firebase FCM.
    print(f"[NOTIFICACION] usuario={usuario_id} payload={payload}")
