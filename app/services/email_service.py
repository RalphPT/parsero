# Resend para emails transaccionales. Si RESEND_API_KEY no está seteado,
# los emails salen por stdout - útil para dev local sin tocar Resend.
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
        return bool(self._api_key)

    async def send_verification_email(self, *, to: str, token: str) -> None:
        verify_url = f"{self._base_url}/verify-email?token={token}"
        subject = "Confirma tu email en Parsero"
        html = f"""
            <h2>Casi listo</h2>
            <p>Un click más y activamos tu cuenta:</p>
            <p><a href="{verify_url}">Confirmar email</a></p>
            <p>Si el botón no funciona, pega este link en el navegador:<br>{verify_url}</p>
            <p>El link vence en 24 horas.</p>
        """
        await self._send(to=to, subject=subject, html=html)

    async def send_password_reset_email(self, *, to: str, token: str) -> None:
        reset_url = f"{self._base_url}/reset-password?token={token}"
        subject = "Cambiar tu contraseña en Parsero"
        html = f"""
            <h2>Nueva contraseña</h2>
            <p>Haz click para definirla:</p>
            <p><a href="{reset_url}">Cambiar contraseña</a></p>
            <p>Si no pediste esto, ignora el email. Si lo ves repetido, avísanos.</p>
            <p>El link vence en 1 hora.</p>
        """
        await self._send(to=to, subject=subject, html=html)

    async def send_welcome_email(self, *, to: str, api_key: str) -> None:
        subject = "Tu cuenta de Parsero está lista"
        html = f"""
            <h2>Bienvenido</h2>
            <p>Aquí está tu primera API key. Cópiala y guárdala en un lugar seguro
            (un password manager está bien) - no se vuelve a mostrar.</p>
            <pre>{api_key}</pre>
            <p>Para usarla:<br>
            <code>Authorization: Bearer {api_key[:12]}...</code></p>
            <p>Cualquier duda, responde este mail.</p>
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


_email_service: Optional[EmailService] = None


def get_email_service() -> EmailService:
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service
