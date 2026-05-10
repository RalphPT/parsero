"""
Re-exporta todos los modelos para que Alembic los descubra automáticamente
al importar `app.db.models` en su `env.py`.
"""
from app.db.models.tenant            import Tenant, TenantPlan
from app.db.models.api_key           import ApiKey
from app.db.models.extraction_job    import ExtractionJob, JobStatus, SchemaType
from app.db.models.extraction_result import ExtractionResult
from app.db.models.usage_log         import UsageLog

__all__ = [
    "Tenant", "TenantPlan",
    "ApiKey",
    "ExtractionJob", "JobStatus", "SchemaType",
    "ExtractionResult",
    "UsageLog",
]
