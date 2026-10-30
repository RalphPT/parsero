from uuid import UUID
from decimal import Decimal
from datetime import datetime
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.usage_log import UsageLog


class UsageLogRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def log_extraction(
        self,
        *,
        tenant_id: UUID,
        job_id: UUID,
        input_tokens: int,
        output_tokens: int,
        cost_usd: Decimal,
        billing_period: str,  # YYYY-MM
    ) -> UsageLog:
        usage = UsageLog(
            tenant_id=tenant_id,
            job_id=job_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            billing_period=billing_period,
        )
        self.db.add(usage)
        await self.db.flush()
        return usage

    async def monthly_summary(self, tenant_id: UUID, billing_period: str) -> dict:
        stmt = select(
            func.coalesce(func.sum(UsageLog.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageLog.output_tokens), 0).label("output_tokens"),
            func.count(UsageLog.id).label("extractions_count"),
        ).where(
            UsageLog.tenant_id == tenant_id,
            UsageLog.billing_period == billing_period,
        )
        row = (await self.db.execute(stmt)).one()
        input_tokens = int(row.input_tokens or 0)
        output_tokens = int(row.output_tokens or 0)
        return {
            "billing_period": billing_period,
            "extractions_count": int(row.extractions_count or 0),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
