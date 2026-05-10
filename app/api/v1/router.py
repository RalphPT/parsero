from fastapi import APIRouter

from app.api.v1.endpoints import account, admin, auth, billing, tenants, extraction

router = APIRouter()
router.include_router(admin.router,       prefix="/admin", tags=["admin"])
router.include_router(tenants.router,                      tags=["tenants"])
router.include_router(extraction.router,                   tags=["extraction"])
router.include_router(auth.router,                         tags=["auth"])
router.include_router(billing.router,                      tags=["billing"])
router.include_router(account.router,                      tags=["account"])
