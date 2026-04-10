from .schemas import PagosDemoOut


def estado_paquete_pagos() -> PagosDemoOut:
    return PagosDemoOut(mensaje="Paquete pagos listo para siguientes ciclos")
