import logging
import os
from pathlib import Path

import httpx

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
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _load_backend_env() -> None:
    backend_env = Path(__file__).resolve().parents[2] / ".env"
    _load_env_file(backend_env)
    if load_dotenv is not None:
        load_dotenv(override=False)


def enviar_email(destinatario: str, asunto: str, cuerpo_texto: str) -> bool:
    _load_backend_env()

    brevo_api_key = os.getenv("BREVO_API_KEY", "").strip()
    from_email = os.getenv("MAIL_FROM", "").strip()
    from_name = os.getenv("MAIL_FROM_NAME", "AuxilioSCZ").strip()

    if not brevo_api_key or not from_email or not destinatario:
        logger.error(
            "Email no enviado por configuración Brevo incompleta. api_key=%s from=%s destinatario=%s",
            bool(brevo_api_key),
            bool(from_email),
            destinatario,
        )
        return False

    payload = {
        "sender": {
            "name": from_name,
            "email": from_email,
        },
        "to": [
            {
                "email": destinatario,
            }
        ],
        "subject": asunto,
        "textContent": cuerpo_texto,
    }

    try:
        response = httpx.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={
                "accept": "application/json",
                "api-key": brevo_api_key,
                "content-type": "application/json",
            },
            json=payload,
            timeout=20,
        )

        if response.status_code >= 400:
            logger.error(
                "Brevo API rechazó el email. status=%s body=%s",
                response.status_code,
                response.text,
            )
            return False

        logger.info("Email enviado correctamente por Brevo API. to=%s subject=%s", destinatario, asunto)
        return True

    except Exception as exc:
        logger.error(
            "Fallo inesperado al enviar email por Brevo API a %s error=%s",
            destinatario,
            exc,
            exc_info=True,
        )
        return False