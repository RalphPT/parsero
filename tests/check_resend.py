r"""
Validación manual de la integración con Resend.

Manda 3 emails reales (verify, welcome, reset) a tu cuenta para confirmar
que la API key funciona y que los templates se ven bien en Gmail.

Uso:
    .\.venv\Scripts\python.exe -m tests.check_resend perccatrejorafael@gmail.com

NOTA: con el sandbox `onboarding@resend.dev` solo puedes mandar al email con
el que te registraste en Resend. Cuando verifiques tu propio dominio, podrás
mandar a cualquiera.
"""
import asyncio
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.core.config import get_settings
from app.services.email_service import EmailService


async def main() -> int:
    if len(sys.argv) != 2:
        print("Uso: python -m tests.check_resend <email-destino>")
        return 1

    to = sys.argv[1]
    settings = get_settings()

    if not settings.resend_api_key:
        print("[FAIL] RESEND_API_KEY no está configurada en .env")
        return 1

    print(f"\n>>> Enviando emails de prueba a {to}\n")
    print(f"    EMAIL_FROM: {settings.email_from}")
    print(f"    PUBLIC_BASE_URL: {settings.public_base_url}")
    print(f"    API key: re_...{settings.resend_api_key[-4:]}\n")

    svc = EmailService()
    if not svc.is_live:
        print("[FAIL] EmailService dice que no está en modo live")
        return 1

    fake_token = "demo.token.no-funcional-para-verificar-realmente"
    fake_api_key = "psr_DemoKey1234567890ABCDEF"

    try:
        print("  enviando verify-email...")
        await svc.send_verification_email(to=to, token=fake_token)
        print("  [OK] verify-email enviado")

        print("  enviando welcome con api_key...")
        await svc.send_welcome_email(to=to, api_key=fake_api_key)
        print("  [OK] welcome enviado")

        print("  enviando password-reset...")
        await svc.send_password_reset_email(to=to, token=fake_token)
        print("  [OK] password-reset enviado")
    except Exception as e:
        print(f"\n[FAIL] Error enviando: {type(e).__name__}: {e}")
        return 1

    print(f"\n[OK] Los 3 emails fueron aceptados por Resend.")
    print(f"     Revisa tu inbox en {to} (puede demorar 30-60s).")
    print(f"     Si no llegan, revisa la carpeta de Spam y el dashboard de Resend -> Logs.\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
