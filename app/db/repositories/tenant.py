from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.tenant import Tenant, TenantPlan


class TenantRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        *,
        name: str,
        email: str,
        plan: TenantPlan = TenantPlan.free,
        password_hash: Optional[str] = None,
        is_active: bool = True,
    ) -> Tenant:
        tenant = Tenant(
            name=name,
            email=email,
            plan=plan,
            password_hash=password_hash,
            is_active=is_active,
        )
        self.db.add(tenant)
        await self.db.flush()  # popula id y timestamps
        return tenant

    async def get(self, tenant_id: UUID) -> Optional[Tenant]:
        return await self.db.get(Tenant, tenant_id)

    async def get_by_email(self, email: str) -> Optional[Tenant]:
        stmt = select(Tenant).where(Tenant.email == email)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Tenant]:
        stmt = select(Tenant).order_by(Tenant.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def mark_email_verified(self, tenant: Tenant) -> Tenant:
        """Setea email_verified_at=ahora y is_active=True."""
        tenant.email_verified_at = datetime.now(timezone.utc)
        tenant.is_active = True
        await self.db.flush()
        return tenant

    async def update_password(self, tenant: Tenant, password_hash: str) -> Tenant:
        tenant.password_hash = password_hash
        await self.db.flush()
        return tenant
