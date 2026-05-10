"""
Excepciones tipadas del dominio. Permiten al endpoint mapear fallos a HTTP
codes correctos sin acoplarse a httpx/pydantic/google-generativeai.
"""


class DocumentLoadError(ValueError):
    """Documento inválido o no descargable. -> HTTP 400."""


class LLMUpstreamError(RuntimeError):
    """Falló la llamada al LLM (timeout, red, 5xx). -> HTTP 502."""


class LLMValidationError(ValueError):
    """LLM devolvió JSON pero no cumple el schema esperado. -> HTTP 422."""
