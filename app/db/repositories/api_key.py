from typing import Optional
from uuid import UUID
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.api_key import ApiKey
from app.core.security import generate_api_key


class ApiKeyRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        *,
        tenant_id: UUID,
        name: Optional[str] = None,
        expires_at: Optional[datetime] = None,
    ) -> tuple[ApiKey, str]:
        """
        Crea una API key. Devuelve `(modelo, clave_en_claro)`.

        La clave_en_claro NO se persiste en BD - solo se entrega al cliente
        UNA VEZ en la respuesta del create. Después solo queda el SHA-256.
        """
        raw_key, key_hash, key_prefix = generate_api_key()
        api_key = ApiKey(
            tenant_id=tenant_id,
            key_hash=key_hash,
            key_prefix=key_prefix,
            name=name,
            expires_at=expires_at,
        )
        self.db.add(api_key)
        await self.db.flush()
        return api_key, raw_key

    async def get_by_hash(self, key_hash: str) -> Optional[ApiKey]:
        stmt = select(ApiKey).where(ApiKey.key_hash == key_hash)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_tenant(self, tenant_id: UUID) -> list[ApiKey]:
        stmt = (
            select(ApiKey)
            .where(ApiKey.tenant_id == tenant_id)
            .order_by(ApiKey.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def set_active(
        self, *, tenant_id: UUID, key_id: UUID, is_active: bool
    ) -> Optional[ApiKey]:
        """
        Activa/desactiva una key. Devuelve None si la key no existe o no
        pertenece al tenant indicado (para evitar enumerar keys de otros).
        """
        stmt = select(ApiKey).where(
            ApiKey.id == key_id, ApiKey.tenant_id == tenant_id
        )
        result = await self.db.execute(stmt)
        api_key = result.scalar_one_or_none()
        if api_key is None:
            return None
        api_key.is_active = is_active
        await self.db.flush()
        return api_key
