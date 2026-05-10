from typing import Literal, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ─── App ──────────────────────────────────────
    app_name: str = "Parsero"
    app_version: str = "0.1.0"
    app_env: str = "development"
    app_debug: bool = False

    # ─── Base de datos ────────────────────────────
    database_url: str

    # ─── Redis ────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ─── LLM provider ─────────────────────────────
    # Cuál se usa en Fase 3. La key correspondiente debe estar seteada.
    llm_provider: Literal["gemini", "anthropic", "ollama"] = "gemini"
    llm_max_tokens: int = 2048

    # ─── Gemini (default en dev — free tier) ──────
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-2.5-flash"

    # ─── Anthropic (tier premium / opcional) ──────
    anthropic_api_key: Optional[str] = None
    claude_model: str = "claude-sonnet-4-6"

    # ─── Seguridad ────────────────────────────────
    secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_session_ttl_hours: int = 24 * 7        # 7 días
    jwt_email_verify_ttl_hours: int = 24       # 1 día
    jwt_password_reset_ttl_hours: int = 1      # 1 hora

    # ─── Resend (email transaccional) ─────────────
    resend_api_key: Optional[str] = None
    email_from: str = "Parsero <noreply@parsero.dev>"  # ajustar cuando haya dominio
    public_base_url: str = "http://localhost:8000"     # base para los links en emails

    # ─── Lemon Squeezy (billing, Fase 5.2) ────────
    lemonsqueezy_api_key: Optional[str] = None
    lemonsqueezy_webhook_secret: Optional[str] = None
    lemonsqueezy_store_id: Optional[str] = None
    lemonsqueezy_variant_starter: Optional[str] = None
    lemonsqueezy_variant_pro: Optional[str] = None

    # ─── Rate limiting ────────────────────────────
    rate_limit_per_minute: int = 100

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    """
    Singleton de settings — se cachea en el primer llamado.
    Usar como dependencia en FastAPI: Depends(get_settings)
    """
    return Settings()
