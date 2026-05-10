"""POST /extract y GET /extract/{id}."""
import json
import time
from decimal import Decimal
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_api_key, enforce_rate_limit
from app.core.document_loader import DocumentLoader
from app.core.exceptions import (
    DocumentLoadError,
    LLMUpstreamError,
    LLMValidationError,
)
from app.core.extraction_prompts import get_extraction_template, get_system_prompt
from app.core.llm_provider import get_llm_provider
from app.db.models.api_key import ApiKey
from app.db.models.extraction_job import JobStatus
from app.db.repositories.extraction_job import ExtractionJobRepository
from app.db.repositories.extraction_result import ExtractionResultRepository
from app.db.repositories.usage_log import UsageLogRepository
from app.db.session import get_db
from app.schemas.extraction import (
    ExtractionJobResponse,
    ExtractionRequest,
    ExtractionResultResponse,
)
from app.schemas.extraction_outputs import get_output_model


router = APIRouter()

VALID_SCHEMAS = frozenset({"invoice", "cv", "receipt"})


@router.post(
    "/extract",
    response_model=ExtractionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        400: {"description": "Documento inválido o no descargable"},
        422: {"description": "El LLM devolvió JSON que no cumple el schema"},
        502: {"description": "Error upstream del LLM (timeout, red, 5xx)"},
    },
)
async def extract_document(
    body: ExtractionRequest,
    api_key: ApiKey = Depends(get_current_api_key),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(enforce_rate_limit),
) -> ExtractionJobResponse:
    """
    Extrae datos estructurados de un documento.

    El POST espera la respuesta de Gemini y devuelve el status final del job.
    Para v1 no usamos worker async - Gemini Flash suele responder en <5s.

    Status codes:
      - 202 + status=completed       -> extracción exitosa
      - 202 + status=cached          -> cache hit (mismo doc + schema antes)
      - 400                          -> documento inválido (URL/tamaño/formato)
      - 422                          -> LLM devolvió JSON que no cumple el schema
      - 502                          -> LLM upstream falló (timeout/red/5xx)
    """
    if body.schema_type not in VALID_SCHEMAS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"schema_type debe ser uno de: {', '.join(sorted(VALID_SCHEMAS))}",
        )

    # Descargar y hashear documento - DocumentLoadError -> 400
    try:
        document_text, source_hash = await DocumentLoader.load_and_hash(
            str(body.document_url)
        )
    except DocumentLoadError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Cache hit: (tenant, hash, schema) ya extraído antes
    job_repo = ExtractionJobRepository(db)
    cached_job = await job_repo.get_by_hash_and_schema(
        api_key.tenant_id, source_hash, body.schema_type
    )
    if cached_job:
        return ExtractionJobResponse(
            id=cached_job.id,
            status="cached",
            created_at=cached_job.created_at,
        )

    # Crear job nuevo
    job = await job_repo.create(
        tenant_id=api_key.tenant_id,
        api_key_id=api_key.id,
        schema_type=body.schema_type,
        source_hash=source_hash,
        source_url=str(body.document_url),
    )
    await db.commit()

    # Ejecutar extracción. Las excepciones se mapean a HTTP codes pero el job
    # queda en BD como `failed` con error_message para auditoría/billing.
    try:
        await _run_extraction(
            job_id=job.id,
            document_text=document_text,
            schema_type=body.schema_type,
            tenant_id=api_key.tenant_id,
            db=db,
        )
    except LLMValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Output del LLM no cumple el schema: {e}",
        )
    except LLMUpstreamError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM upstream falló: {e}",
        )

    return ExtractionJobResponse(
        id=job.id,
        status=JobStatus.completed.value,
        created_at=job.created_at,
    )


@router.get("/extract/{job_id}", response_model=ExtractionResultResponse)
async def get_extraction_result(
    job_id: UUID,
    api_key: ApiKey = Depends(get_current_api_key),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(enforce_rate_limit),
) -> ExtractionResultResponse:
    """Devuelve el resultado de un job. 404 si no existe o no es del tenant."""
    job_repo = ExtractionJobRepository(db)
    job = await job_repo.get(job_id)

    if job is None or job.tenant_id != api_key.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job no encontrado"
        )

    result_repo = ExtractionResultRepository(db)
    result = await result_repo.get_by_job_id(job_id)

    return ExtractionResultResponse(
        job_id=job.id,
        status=job.status.value,
        data=result.data if result else None,
        error_message=job.error_message,
        input_tokens=job.input_tokens,
        output_tokens=job.output_tokens,
        created_at=job.created_at,
    )


async def _run_extraction(
    *,
    job_id: UUID,
    document_text: str,
    schema_type: str,
    tenant_id: UUID,
    db: AsyncSession,
) -> None:
    """
    Llama LLM, valida output con Pydantic, persiste resultado + usage.
    En cualquier fallo: marca el job como `failed` y re-raise la excepción
    tipada para que el endpoint la traduzca a HTTP code.
    """
    job_repo = ExtractionJobRepository(db)
    result_repo = ExtractionResultRepository(db)
    usage_repo = UsageLogRepository(db)

    start_time = time.time()
    input_tokens = 0
    output_tokens = 0

    await job_repo.update_status(job_id, JobStatus.processing.value)
    await db.commit()

    try:
        llm = get_llm_provider()
        system_prompt = get_system_prompt(schema_type)
        extraction_prompt = get_extraction_template(schema_type).format(
            document_text=document_text
        )

        # 1. Llamada al LLM - puede levantar LLMUpstreamError (502)
        llm_response = await llm.extract(
            document_text=document_text,
            schema_type=schema_type,
            system_prompt=system_prompt,
            extraction_prompt=extraction_prompt,
        )
        input_tokens, output_tokens = llm.get_usage_tokens()

        # 2. Parseo + validación Pydantic - fallos = LLMValidationError (422)
        try:
            raw_data = json.loads(llm_response)
        except json.JSONDecodeError as e:
            raise LLMValidationError(f"JSON inválido del LLM: {e}") from e

        OutputModel = get_output_model(schema_type)
        try:
            validated = OutputModel.model_validate(raw_data)
        except ValidationError as e:
            raise LLMValidationError(f"Schema mismatch: {e.errors()}") from e

        # 3. Persistir resultado validado (JSON-mode -> dates como string)
        validated_dict = validated.model_dump(mode="json", exclude_none=False)
        await result_repo.create(job_id=job_id, extracted_data=validated_dict)

        # 4. Usage log
        cost_usd = _calculate_cost(input_tokens, output_tokens)
        billing_period = datetime.utcnow().strftime("%Y-%m")
        duration_ms = int((time.time() - start_time) * 1000)
        await usage_repo.log_extraction(
            tenant_id=tenant_id,
            job_id=job_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            billing_period=billing_period,
        )

        # 5. Marcar como completed
        await job_repo.update_status(
            job_id,
            JobStatus.completed.value,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_ms=duration_ms,
        )
        await db.commit()

    except (LLMUpstreamError, LLMValidationError) as e:
        # Persistir el fallo para auditoría/billing y re-raise
        await db.rollback()
        await job_repo.update_status(
            job_id,
            JobStatus.failed.value,
            error_message=str(e),
            input_tokens=input_tokens or None,
            output_tokens=output_tokens or None,
            duration_ms=int((time.time() - start_time) * 1000),
        )
        await db.commit()
        raise


def _calculate_cost(input_tokens: int, output_tokens: int) -> Decimal:
    """Costo en USD. Gemini Flash free tier: sin costo hasta 1M tokens/día."""
    return Decimal("0.00")
