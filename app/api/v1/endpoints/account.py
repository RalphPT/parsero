"""Endpoints del dashboard: keys + usage del mes. Auth con cookie o JWT."""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user_jwt
from app.db.models.tenant import Tenant
from app.db.models.extraction_job import ExtractionJob
from app.db.repositories.api_key import ApiKeyRepository
from app.db.repositories.extraction_job import ExtractionJobRepository
from app.db.repositories.extraction_result import ExtractionResultRepository
from app.db.repositories.usage_log import UsageLogRepository
from app.db.session import get_db
from app.schemas.account import (
    JobDetailResponse,
    JobListResponse,
    JobSummary,
    UsageSummary,
)
from app.schemas.api_key import (
    ApiKeyCreate,
    ApiKeyCreatedResponse,
    ApiKeyResponse,
    ApiKeyUpdate,
)


router = APIRouter()


@router.get("/account/keys", response_model=list[ApiKeyResponse])
async def list_my_keys(
    tenant: Tenant = Depends(get_current_user_jwt),
    db: AsyncSession = Depends(get_db),
):
    return await ApiKeyRepository(db).list_for_tenant(tenant.id)


@router.post(
    "/account/keys",
    response_model=ApiKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_my_key(
    body: ApiKeyCreate,
    tenant: Tenant = Depends(get_current_user_jwt),
    db: AsyncSession = Depends(get_db),
):
    api_key, raw_key = await ApiKeyRepository(db).create(
        tenant_id=tenant.id, name=body.name, expires_at=body.expires_at
    )
    await db.commit()
    return ApiKeyCreatedResponse(
        id=api_key.id,
        key_prefix=api_key.key_prefix,
        name=api_key.name,
        is_active=api_key.is_active,
        last_used_at=api_key.last_used_at,
        expires_at=api_key.expires_at,
        created_at=api_key.created_at,
        key=raw_key,
    )


@router.patch("/account/keys/{key_id}", response_model=ApiKeyResponse)
async def update_my_key(
    key_id: UUID,
    body: ApiKeyUpdate,
    tenant: Tenant = Depends(get_current_user_jwt),
    db: AsyncSession = Depends(get_db),
):
    """Activa/desactiva una key del propio tenant. 404 si la key no es suya."""
    api_key = await ApiKeyRepository(db).set_active(
        tenant_id=tenant.id, key_id=key_id, is_active=body.is_active
    )
    if api_key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key no encontrada")
    await db.commit()
    return api_key


@router.get("/account/usage", response_model=UsageSummary)
async def my_usage(
    tenant: Tenant = Depends(get_current_user_jwt),
    db: AsyncSession = Depends(get_db),
):
    """Suma de extracciones + tokens del mes actual (formato YYYY-MM)."""
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    return await UsageLogRepository(db).monthly_summary(tenant.id, period)


def _job_summary(job: ExtractionJob) -> JobSummary:
    return JobSummary(
        id=job.id,
        status=job.status.value,
        schema_type=job.schema_type.value,
        source_url=job.source_url,
        input_tokens=job.input_tokens,
        output_tokens=job.output_tokens,
        duration_ms=job.duration_ms,
        error_message=job.error_message,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


@router.get("/account/jobs", response_model=JobListResponse)
async def list_my_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    tenant: Tenant = Depends(get_current_user_jwt),
    db: AsyncSession = Depends(get_db),
):
    jobs, total = await ExtractionJobRepository(db).list_for_tenant(
        tenant.id, limit=limit, offset=offset
    )
    return JobListResponse(
        items=[_job_summary(j) for j in jobs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/account/jobs/{job_id}", response_model=JobDetailResponse)
async def get_my_job(
    job_id: UUID,
    tenant: Tenant = Depends(get_current_user_jwt),
    db: AsyncSession = Depends(get_db),
):
    job = await ExtractionJobRepository(db).get_for_tenant(job_id, tenant.id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job no encontrado")
    result = await ExtractionResultRepository(db).get_by_job_id(job_id)
    return JobDetailResponse(
        **_job_summary(job).model_dump(),
        data=result.data if result else None,
    )
