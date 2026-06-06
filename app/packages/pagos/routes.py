from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user

from .schemas import (
    CotizacionCreateIn,
    CotizacionDecisionIn,
    CotizacionDecisionOut,
    CotizacionOut,
    PagoOut,
    PagoProcesarIn,
    StripeCheckoutOut,
    StripePaymentSheetOut,
)
from .services import (
    confirmar_stripe_payment_sheet,
    cotizacion_out,
    crear_stripe_checkout,
    crear_stripe_payment_sheet,
    estado_paquete_pagos,
    generar_cotizacion_taller,
    listar_cotizaciones_taller,
    obtener_cotizacion_cliente,
    procesar_pago_cliente,
    procesar_stripe_webhook,
    responder_cotizacion_cliente,
)

router = APIRouter()


@router.get("/estado")
def estado():
    return estado_paquete_pagos()


@router.post("/taller/cotizaciones", response_model=CotizacionOut)
def generar_cotizacion(
    payload: CotizacionCreateIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    cot = generar_cotizacion_taller(
        db,
        current_user=current_user,
        incidente_id=payload.incidente_id,
        monto_total=payload.monto_total,
        tiempo_estimado=payload.tiempo_estimado,
        detalle=payload.detalle,
        observaciones=payload.observaciones,
        validez_hasta=payload.validez_hasta,
    )
    return cotizacion_out(cot)


@router.get("/cliente/cotizaciones/{cotizacion_id}", response_model=CotizacionOut)
def ver_cotizacion_cliente(
    cotizacion_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    cot = obtener_cotizacion_cliente(
        db,
        cotizacion_id=cotizacion_id,
        current_user=current_user,
    )
    return cotizacion_out(cot)


@router.get("/taller/cotizaciones", response_model=list[CotizacionOut])
def listar_cotizaciones_taller_endpoint(
    estado: str | None = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    rows = listar_cotizaciones_taller(
        db,
        estado=estado,
        current_user=current_user,
    )
    return [cotizacion_out(c) for c in rows]


@router.post("/cliente/cotizaciones/{cotizacion_id}/aceptar", response_model=CotizacionDecisionOut)
def aceptar_cotizacion_cliente(
    cotizacion_id: str,
    payload: CotizacionDecisionIn | None = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return responder_cotizacion_cliente(
        db,
        cotizacion_id=cotizacion_id,
        current_user=current_user,
        aceptar=True,
        observaciones=payload.observaciones if payload else None,
    )


@router.post("/cliente/cotizaciones/{cotizacion_id}/rechazar", response_model=CotizacionDecisionOut)
def rechazar_cotizacion_cliente(
    cotizacion_id: str,
    payload: CotizacionDecisionIn | None = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return responder_cotizacion_cliente(
        db,
        cotizacion_id=cotizacion_id,
        current_user=current_user,
        aceptar=False,
        observaciones=payload.observaciones if payload else None,
    )


@router.post("/cliente/pagos/procesar", response_model=PagoOut)
def procesar_pago_endpoint(
    payload: PagoProcesarIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return procesar_pago_cliente(
        db,
        current_user=current_user,
        cotizacion_id=payload.cotizacion_id,
        metodo_pago=payload.metodo_pago,
        comprobante_url=payload.comprobante_url,
        referencia=payload.referencia,
    )


@router.post("/{pago_id}/stripe-checkout", response_model=StripeCheckoutOut)
def crear_stripe_checkout_endpoint(
    pago_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return crear_stripe_checkout(db, pago_id=pago_id, current_user=current_user)


@router.post("/{pago_id}/stripe-payment-sheet", response_model=StripePaymentSheetOut)
def crear_stripe_payment_sheet_endpoint(
    pago_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return crear_stripe_payment_sheet(db, pago_id=pago_id, current_user=current_user)


@router.post("/{pago_id}/stripe-payment-sheet/confirmar", response_model=PagoOut)
def confirmar_stripe_payment_sheet_endpoint(
    pago_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return confirmar_stripe_payment_sheet(db, pago_id=pago_id, current_user=current_user)


@router.post("/stripe/webhook")
async def stripe_webhook_endpoint(request: Request, db: Session = Depends(get_db)):
    raw_body = await request.body()
    signature = request.headers.get("stripe-signature")
    return procesar_stripe_webhook(db, raw_body=raw_body, signature=signature)
