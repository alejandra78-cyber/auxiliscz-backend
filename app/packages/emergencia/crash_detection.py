"""
Detección automática de accidentes (Modo Viaje - app móvil).

Endpoint aditivo: POST /api/emergencia/report_accident
- Crea un incidente real tipo "choque" (prioridad alta) reutilizando el
  pipeline existente de reportar_emergencia, que ya dispara la asignación
  automática del taller más cercano en background.
- Envía email a los contactos de emergencia del conductor con un enlace
  de ubicación en Google Maps (vía SMTP, credenciales del .env).
"""
import logging
import os
import smtplib
from datetime import datetime
from email.mime.text import MIMEText

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import Cliente, Vehiculo

from .services import reportar_emergencia

logger = logging.getLogger("auxilioscz.crash_detection")

router = APIRouter()


# ─────────────────────────── Schemas ───────────────────────────

class ContactoEmergenciaIn(BaseModel):
    nombre: str = Field(..., max_length=100)
    telefono: str | None = Field(None, max_length=30)
    email: str | None = Field(None, max_length=150)


class ReportAccidentIn(BaseModel):
    lat: float
    lng: float
    fecha_local: str | None = None
    magnitud: float | None = None  # m/s² detectados por el acelerómetro
    vehiculo_id: str | None = None  # opcional: si no viene, se usa el último del cliente
    contactos: list[ContactoEmergenciaIn] = Field(default_factory=list, max_length=3)


class ReportAccidentOut(BaseModel):
    incidente_id: str
    estado: str
    tipo: str | None = None
    prioridad: int | None = None
    asignacion_id: str | None = None
    contactos_notificados: int = 0
    mensaje: str


# ─────────────────────────── Email a contactos ───────────────────────────

def _enviar_email_smtp(destinatario: str, asunto: str, cuerpo: str) -> bool:
    """Envío por SMTP usando las credenciales SMTP_* del .env."""
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587") or 587)
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    use_tls = (os.getenv("SMTP_USE_TLS", "true").strip().lower() != "false")
    mail_from = os.getenv("MAIL_FROM", user).strip()

    if not host or not user or not password or not destinatario:
        logger.error("SMTP incompleto: host=%s user=%s dest=%s", bool(host), bool(user), bool(destinatario))
        return False

    msg = MIMEText(cuerpo, "plain", "utf-8")
    msg["Subject"] = asunto
    msg["From"] = mail_from
    msg["To"] = destinatario

    try:
        with smtplib.SMTP(host, port, timeout=20) as server:
            if use_tls:
                server.starttls()
            server.login(user, password)
            server.sendmail(mail_from, [destinatario], msg.as_string())
        return True
    except Exception:
        logger.exception("Fallo al enviar email de accidente a %s", destinatario)
        return False


def _notificar_contactos(
    contactos: list[ContactoEmergenciaIn],
    nombre_conductor: str,
    lat: float,
    lng: float,
    fecha: str,
) -> None:
    """Se ejecuta en background: avisa a los contactos de emergencia."""
    link_maps = f"https://www.google.com/maps?q={lat},{lng}"
    for contacto in contactos:
        if not contacto.email:
            continue
        cuerpo = (
            f"Hola {contacto.nombre},\n\n"
            f"AuxilioSCZ detectó un posible ACCIDENTE VEHICULAR de {nombre_conductor} "
            f"y la persona no respondió a la alerta de confirmación.\n\n"
            f"Fecha/hora: {fecha}\n"
            f"Ubicación en el mapa: {link_maps}\n\n"
            f"Ya se notificó a los talleres/asistencia más cercanos. "
            f"Te recomendamos intentar comunicarte con la persona de inmediato.\n\n"
            f"— Sistema de detección de accidentes AuxilioSCZ"
        )
        asunto = f"🚨 Posible accidente de {nombre_conductor} — AuxilioSCZ"

        # Producción (Railway) usa Brevo API; local usa SMTP como respaldo.
        ok = False
        try:
            from app.services.emailer import enviar_email
            ok = enviar_email(contacto.email, asunto, cuerpo)
        except Exception:
            logger.exception("Fallo enviar_email (Brevo) para %s", contacto.email)
        if not ok:
            ok = _enviar_email_smtp(contacto.email, asunto, cuerpo)

        logger.info("Aviso a contacto %s (%s): %s", contacto.nombre, contacto.email, "OK" if ok else "FALLÓ")


# ─────────────────────────── Endpoint ───────────────────────────

@router.post("/report_accident", response_model=ReportAccidentOut)
async def report_accident(
    payload: ReportAccidentIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # 1) Resolver vehículo: el indicado o el más reciente del cliente.
    vehiculo_id = payload.vehiculo_id
    if not vehiculo_id:
        cliente = db.query(Cliente).filter(Cliente.usuario_id == current_user.id).first()
        if cliente:
            vehiculo = (
                db.query(Vehiculo)
                .filter(Vehiculo.cliente_id == cliente.id, Vehiculo.activo.is_(True))
                .order_by(Vehiculo.creado_en.desc())
                .first()
            )
            if vehiculo:
                vehiculo_id = str(vehiculo.id)
    if not vehiculo_id:
        raise HTTPException(
            status_code=400,
            detail="No tienes un vehículo registrado para reportar el accidente automáticamente",
        )

    fecha = payload.fecha_local or datetime.now().isoformat()
    magnitud_txt = f" (impacto detectado: {payload.magnitud:.1f} m/s²)" if payload.magnitud else ""
    descripcion = (
        "REPORTE AUTOMÁTICO por detección de impacto del Modo Viaje. "
        f"El conductor no respondió a la alerta de confirmación en 15 segundos{magnitud_txt}. "
        f"Fecha local del evento: {fecha}."
    )

    # 2) Crear el incidente reutilizando el pipeline real existente
    #    (incluye asignación automática del taller más cercano en background).
    data = await reportar_emergencia(
        db,
        background_tasks=background_tasks,
        current_user=current_user,
        vehiculo_id=vehiculo_id,
        tipo="choque",
        lat=payload.lat,
        lng=payload.lng,
        descripcion=descripcion,
        offline_sync_id=None,
        fecha_local=payload.fecha_local,
        foto=None,
        fotos=None,
        audio=None,
    )

    # 3) Avisar a los contactos de emergencia en background.
    contactos_con_email = [c for c in payload.contactos if c.email]
    if contactos_con_email:
        background_tasks.add_task(
            _notificar_contactos,
            payload.contactos,
            current_user.nombre,
            payload.lat,
            payload.lng,
            fecha,
        )

    return ReportAccidentOut(
        incidente_id=data["incidente_id"],
        estado=data["estado"],
        tipo=data.get("tipo"),
        prioridad=data.get("prioridad"),
        asignacion_id=data.get("asignacion_id"),
        contactos_notificados=len(contactos_con_email),
        mensaje="Accidente reportado automáticamente. Talleres cercanos notificados.",
    )


__all__ = ["router"]
