# Demo público de la landing. Sin auth. 3 extracciones por IP por día local,
# y solo cuentan las que efectivamente consumen tokens del LLM. Errores 4xx
# del input no descuentan quota.
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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

DEMO_LIMIT_PER_DAY = 3
DEFAULT_TZ = ZoneInfo("UTC")
KEY_TTL_SECONDS = 48 * 3600  # holgado para que el key viejo expire seguro


def _client_ip(request: Request) -> str:
    # Railway está detrás de un proxy, por eso miramos X-Forwarded-For primero.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _client_tz(request: Request) -> ZoneInfo:
    name = request.headers.get("x-timezone")
    if not name:
        return DEFAULT_TZ
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return DEFAULT_TZ


def _today_key(ip: str, tz: ZoneInfo) -> str:
    today = datetime.now(tz).strftime("%Y-%m-%d")
    return f"demo:ip:{ip}:{today}"


async def _consume_quota(redis, redis_key: str) -> int:
    count = await redis.incr(redis_key)
    if count == 1:
        await redis.expire(redis_key, KEY_TTL_SECONDS)
    return count


@router.post("/demo/extract")
async def demo_extract(
    body: ExtractionRequest,
    request: Request,
    redis=Depends(get_redis),
):
    if body.schema_type not in VALID_SCHEMAS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"schema_type debe ser uno de: {', '.join(sorted(VALID_SCHEMAS))}",
        )

    # Chequeamos quota antes de bajar el PDF y llamar al LLM (no incrementamos
    # todavía - solo cuando hayamos confirmado que el LLM efectivamente corrió).
    ip = _client_ip(request)
    tz = _client_tz(request)
    redis_key = _today_key(ip, tz)
    current_raw = await redis.get(redis_key)
    current = int(current_raw) if current_raw else 0
    if current >= DEMO_LIMIT_PER_DAY:
        now = datetime.now(tz)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        retry_after = int((tomorrow - now).total_seconds())
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Límite de {DEMO_LIMIT_PER_DAY} demos alcanzado por hoy. "
                f"Se reinicia a las 00:00 hora local ({tz}). "
                "Para uso continuo crea una cuenta gratis en /signup (10 requests/min)."
            ),
            headers={"Retry-After": str(retry_after)},
        )

    try:
        document_text, _ = await DocumentLoader.load_and_hash(str(body.document_url))
    except DocumentLoadError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

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
        # Mensaje user-friendly ya viene formateado desde llm_provider.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        )

    # Recién aquí descontamos quota: el LLM ya consumió tokens. Si la validación
    # Pydantic falla más abajo igual cuenta - el costo ya se pagó.
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
