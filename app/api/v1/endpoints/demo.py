"""Endpoint demo público (sin auth, rate-limited por IP) para la landing page."""
import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError

from app.core.document_loader import DocumentLoader
from app.core.exceptions import (
    DocumentLoadError,
    LLMUpstreamError,
)
from app.core.extraction_prompts import get_extraction_template, get_system_prompt
from app.core.llm_provider import get_llm_provider
from app.schemas.extraction import ExtractionRequest
from app.schemas.extraction_outputs import get_output_model
from app.services.redis_client import get_redis


router = APIRouter()

VALID_SCHEMAS = frozenset({"invoice", "cv", "receipt"})

# Máximo de extracciones que consumen tokens por IP por día
DEMO_LIMIT_PER_DAY = 3
DEMO_TTL_SECONDS = 86400  # 24h


def _client_ip(request: Request) -> str:
    """Extrae IP real del cliente, considerando proxies (Railway)."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _consume_quota(redis, redis_key: str) -> int:
    """Incrementa el contador y le pone TTL si es la primera vez."""
    count = await redis.incr(redis_key)
    if count == 1:
        await redis.expire(redis_key, DEMO_TTL_SECONDS)
    return count


@router.post("/demo/extract")
async def demo_extract(
    body: ExtractionRequest,
    request: Request,
    redis=Depends(get_redis),
):
    """
    Extracción pública sin auth. Máximo 3 extracciones que consumen tokens por
    IP por día. Errores de input (URL inválida, schema desconocido, HTML en lugar
    de PDF) no cuentan. Tampoco fallos upstream del LLM.
    """
    if body.schema_type not in VALID_SCHEMAS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"schema_type debe ser uno de: {', '.join(sorted(VALID_SCHEMAS))}",
        )

    # Verificar quota ANTES de hacer trabajo costoso (sin incrementar todavía)
    ip = _client_ip(request)
    redis_key = f"demo:ip:{ip}"
    current_raw = await redis.get(redis_key)
    current = int(current_raw) if current_raw else 0
    if current >= DEMO_LIMIT_PER_DAY:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Límite de {DEMO_LIMIT_PER_DAY} demos por día alcanzado. "
                "Crea una cuenta gratis en /signup para 10 requests por minuto."
            ),
            headers={"Retry-After": str(DEMO_TTL_SECONDS)},
        )

    # Descargar documento. Si falla, NO consume quota (es error del input).
    try:
        document_text, _ = await DocumentLoader.load_and_hash(str(body.document_url))
    except DocumentLoadError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Llamar al LLM. Si el upstream falla, NO consume quota.
    try:
        llm = get_llm_provider()
        llm_response = await llm.extract(
            document_text=document_text,
            schema_type=body.schema_type,
            system_prompt=get_system_prompt(body.schema_type),
            extraction_prompt=get_extraction_template(body.schema_type).format(
                document_text=document_text
            ),
        )
    except LLMUpstreamError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM upstream falló: {e}",
        )

    # Llegamos al LLM y consumimos tokens. A partir de acá SÍ contamos
    # contra la quota, incluso si la validación Pydantic falla después.
    count = await _consume_quota(redis, redis_key)

    try:
        raw_data = json.loads(llm_response)
        validated = get_output_model(body.schema_type).model_validate(raw_data)
    except (json.JSONDecodeError, ValidationError) as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Output del LLM no cumple el schema: {e}",
        )

    input_tokens, output_tokens = llm.get_usage_tokens()
    return {
        "data": validated.model_dump(mode="json", exclude_none=False),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "demos_remaining": max(0, DEMO_LIMIT_PER_DAY - count),
    }
