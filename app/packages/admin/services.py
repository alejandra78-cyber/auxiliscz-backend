from .schemas import AdminDemoOut


def estado_paquete_admin() -> AdminDemoOut:
    return AdminDemoOut(mensaje="Paquete admin listo para siguientes ciclos")
