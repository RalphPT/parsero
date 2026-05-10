"""LLM provider abstraction layer."""
import logging
from abc import ABC, abstractmethod

import google.generativeai as genai

from app.core.config import get_settings
from app.core.exceptions import LLMUpstreamError


logger = logging.getLogger(__name__)
LLM_TIMEOUT_SECONDS = 60


class LLMProvider(ABC):
    """Abstract base for LLM providers."""

    @abstractmethod
    async def extract(
        self,
        document_text: str,
        schema_type: str,
        system_prompt: str,
        extraction_prompt: str,
    ) -> str:
        """Llama al LLM y devuelve el JSON crudo (string)."""
        ...

    @abstractmethod
    def get_usage_tokens(self) -> tuple[int, int]:
        """Tokens (input, output) de la última llamada."""
        ...


class GeminiProvider(LLMProvider):
    """Google Gemini Flash provider."""

    def __init__(self):
        settings = get_settings()
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY no configurado en .env")
        genai.configure(api_key=settings.gemini_api_key)
        self._model_name = settings.gemini_model
        self._max_tokens = settings.llm_max_tokens
        self._input_tokens = 0
        self._output_tokens = 0

    async def extract(
        self,
        document_text: str,
        schema_type: str,
        system_prompt: str,
        extraction_prompt: str,
    ) -> str:
        """
        Llama a Gemini con timeout explícito y JSON mode.
        Cualquier excepción del SDK se traduce a LLMUpstreamError -> 502.
        """
        try:
            model = genai.GenerativeModel(
                model_name=self._model_name,
                system_instruction=system_prompt,
                generation_config={
                    "response_mime_type": "application/json",
                    "max_output_tokens": self._max_tokens,
                    "temperature": 0.1,
                },
            )
            response = await model.generate_content_async(
                extraction_prompt,
                request_options={"timeout": LLM_TIMEOUT_SECONDS},
            )
            if response.usage_metadata:
                self._input_tokens = response.usage_metadata.prompt_token_count
                self._output_tokens = response.usage_metadata.candidates_token_count

            # Detectar si Gemini cortó la respuesta por límite de tokens
            if response.candidates:
                finish = response.candidates[0].finish_reason
                # finish_reason 2 = MAX_TOKENS en la SDK de google-generativeai
                if str(finish) in ("FinishReason.MAX_TOKENS", "MAX_TOKENS", "2"):
                    logger.warning(
                        "Gemini truncó respuesta por MAX_TOKENS (limite=%d, output=%d)",
                        self._max_tokens, self._output_tokens,
                    )
                    raise LLMUpstreamError(
                        "No pudimos procesar este documento completamente. "
                        "Intenta de nuevo o prueba con un PDF más simple."
                    )
            return response.text
        except LLMUpstreamError:
            raise
        except Exception as e:
            logger.error("Gemini API error: %s: %s", type(e).__name__, e)
            raise LLMUpstreamError(
                "El servicio de IA no está respondiendo. Intenta de nuevo en unos segundos."
            ) from e

    def get_usage_tokens(self) -> tuple[int, int]:
        return self._input_tokens, self._output_tokens


def get_llm_provider() -> LLMProvider:
    """Construye el provider según settings.llm_provider."""
    settings = get_settings()
    if settings.llm_provider == "gemini":
        return GeminiProvider()
    raise ValueError(f"LLM provider no soportado todavía: {settings.llm_provider}")
