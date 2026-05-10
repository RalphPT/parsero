"""Cliente de Resend. Sin RESEND_API_KEY, los emails van a stdout (modo dev)."""
import logging
from typing import Optional

import resend

from app.core.config import get_settings


logger = logging.getLogger(__name__)


class EmailService:
    def __init__(self):
        settings = get_settings()
        self._from = settings.email_from
        self._api_key = settings.resend_api_key
        self._base_url = settings.public_base_url
        if self._api_key:
            resend.api_key = self._api_key

    @property
    def is_live(self) -> bool:
        """True si vamos a mandar emails reales; False si solo loguea."""
        return bool(self._api_key)

    async def send_verification_email(self, *, to: str, token: str) -> None:
        verify_url = f"{self._base_url}/verify-email?token={token}"
        subject = "Verifica tu email en Parsero"
        html = f"""
            <h2>Bienvenido a Parsero</h2>
            <p>Haz click para verificar tu cuenta:</p>
            <p><a href="{verify_url}">Verificar email</a></p>
            <p>O copia este link: {verify_url}</p>
            <p>Este link vence en 24 horas.</p>
        """
        await self._send(to=to, subject=subject, html=html)

    async def send_password_reset_email(self, *, to: str, token: str) -> None:
        reset_url = f"{self._base_url}/reset-password?token={token}"
        subject = "Restablece tu contraseña en Parsero"
        html = f"""
            <h2>Restablecer contraseña</h2>
            <p>Haz click para definir una nueva contraseña:</p>
            <p><a href="{reset_url}">Cambiar contraseña</a></p>
            <p>Si no fuiste tú, ignora este email.</p>
            <p>Este link vence en 1 hora.</p>
        """
        await self._send(to=to, subject=subject, html=html)

    async def send_welcome_email(self, *, to: str, api_key: str) -> None:
        subject = "Tu cuenta de Parsero está activa"
        html = f"""
            <h2>Cuenta activada</h2>
            <p>Tu primera API key:</p>
            <pre>{api_key}</pre>
            <p><strong>Guárdala bien</strong>, no se vuelve a mostrar.</p>
        """
        await self._send(to=to, subject=subject, html=html)

    async def _send(self, *, to: str, subject: str, html: str) -> None:
        if not self.is_live:
            logger.info("[email-mock] To=%s | Subject=%s\n%s", to, subject, html)
            print(f"\n[email-mock] To={to}\nSubject={subject}\n{html}\n")
            return
        try:
            resend.Emails.send({
                "from": self._from,
                "to": to,
                "subject": subject,
                "html": html,
            })
        except Exception as e:
            logger.error("Resend send falló: %s", e)
            raise


# Singleton - se construye una sola vez y se reusa
_email_service: Optional[EmailService] = None


def get_email_service() -> EmailService:
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service
