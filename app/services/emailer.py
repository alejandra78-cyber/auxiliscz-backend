import os
import smtplib
from email.message import EmailMessage
import logging

logger = logging.getLogger(__name__)


def _smtp_config() -> dict[str, str | int | bool]:
    return {
        "host": os.getenv("SMTP_HOST", "").strip(),
        "port": int(os.getenv("SMTP_PORT", "587")),
        "user": os.getenv("SMTP_USER", "").strip(),
        "password": os.getenv("SMTP_PASSWORD", "").strip(),
        "from_email": os.getenv("MAIL_FROM", "").strip() or os.getenv("SMTP_USER", "").strip(),
        "use_tls": os.getenv("SMTP_USE_TLS", "true").strip().lower() in {"1", "true", "yes"},
    }


def enviar_email(destinatario: str, asunto: str, cuerpo_texto: str) -> bool:
    cfg = _smtp_config()
    if not cfg["host"] or not cfg["from_email"] or not destinatario:
        logger.error(
            "Email no enviado por configuración incompleta. host=%s from=%s destinatario=%s",
            bool(cfg["host"]),
            bool(cfg["from_email"]),
            destinatario,
        )
        return False

    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = str(cfg["from_email"])
    msg["To"] = destinatario
    msg.set_content(cuerpo_texto)

    try:
        with smtplib.SMTP(str(cfg["host"]), int(cfg["port"]), timeout=15) as smtp:
            if bool(cfg["use_tls"]):
                smtp.starttls()
            if cfg["user"] and cfg["password"]:
                smtp.login(str(cfg["user"]), str(cfg["password"]))
            smtp.send_message(msg)
        logger.info("Email enviado correctamente a %s: %s", destinatario, asunto)
        return True
    except smtplib.SMTPAuthenticationError:
        logger.exception("Fallo SMTP auth al enviar email a %s", destinatario)
        return False
    except smtplib.SMTPRecipientsRefused:
        logger.exception("Destinatario rechazado por SMTP: %s", destinatario)
        return False
    except smtplib.SMTPException:
        logger.exception("Fallo SMTP general al enviar email a %s", destinatario)
        return False
    except Exception:
        logger.exception("Fallo inesperado al enviar email a %s", destinatario)
        return False

