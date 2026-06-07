import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    load_dotenv = None

logger = logging.getLogger(__name__)


def _load_env_file(path: Path) -> None:
    if load_dotenv is not None:
        load_dotenv(path, override=False)
        return
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _load_backend_env() -> None:
    backend_env = Path(__file__).resolve().parents[2] / ".env"
    _load_env_file(backend_env)
    if load_dotenv is not None:
        load_dotenv(override=False)


def _normalize_password(host: str, password: str) -> str:
    if "gmail.com" in (host or "").lower():
        return password.replace(" ", "")
    return password


def _smtp_config() -> dict[str, str | int | bool]:
    _load_backend_env()
    host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    password = os.getenv("SMTP_PASSWORD", os.getenv("GMAIL_APP_PASSWORD", "")).strip()
    return {
        "host": host,
        "port": int(os.getenv("SMTP_PORT", "587")),
        "user": os.getenv("SMTP_USER", "").strip(),
        "password": _normalize_password(host, password),
        "from_email": os.getenv("MAIL_FROM", "").strip() or os.getenv("SMTP_USER", "").strip(),
        "use_tls": os.getenv("SMTP_USE_TLS", "true").strip().lower() in {"1", "true", "yes"},
    }


def enviar_email(destinatario: str, asunto: str, cuerpo_texto: str) -> bool:
    cfg = _smtp_config()
    if not cfg["host"] or not cfg["from_email"] or not destinatario or not cfg["user"] or not cfg["password"]:
        logger.error(
            "Email no enviado por configuración SMTP incompleta. host=%s user=%s password=%s from=%s destinatario=%s",
            bool(cfg["host"]),
            bool(cfg["user"]),
            bool(cfg["password"]),
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
        context = ssl.create_default_context()
        if int(cfg["port"]) == 465:
            with smtplib.SMTP_SSL(str(cfg["host"]), int(cfg["port"]), timeout=20, context=context) as smtp:
                smtp.login(str(cfg["user"]), str(cfg["password"]))
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(str(cfg["host"]), int(cfg["port"]), timeout=20) as smtp:
                smtp.ehlo()
                if bool(cfg["use_tls"]):
                    smtp.starttls(context=context)
                    smtp.ehlo()
                smtp.login(str(cfg["user"]), str(cfg["password"]))
                smtp.send_message(msg)
        logger.info("Email enviado correctamente. to=%s subject=%s smtp_host=%s", destinatario, asunto, cfg["host"])
        return True
    except smtplib.SMTPAuthenticationError as exc:
        logger.error(
            "Fallo SMTP auth al enviar email a %s. Gmail requiere contraseña de aplicación, no la contraseña normal. error=%s",
            destinatario,
            exc,
            exc_info=True,
        )
        return False
    except smtplib.SMTPRecipientsRefused as exc:
        logger.error("Destinatario rechazado por SMTP: %s error=%s", destinatario, exc, exc_info=True)
        return False
    except smtplib.SMTPException as exc:
        logger.error("Fallo SMTP general al enviar email a %s error=%s", destinatario, exc, exc_info=True)
        return False
    except Exception as exc:
        logger.error("Fallo inesperado al enviar email a %s error=%s", destinatario, exc, exc_info=True)
        return False

