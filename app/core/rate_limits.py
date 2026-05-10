"""
Rate limits por plan. Centralizado para que sea fácil ajustar valores
sin tocar la lógica del limiter.
"""
from app.db.models.tenant import TenantPlan

# Requests por minuto permitidos por plan. 0 = ilimitado.
RATE_LIMITS_PER_MINUTE: dict[TenantPlan, int] = {
    TenantPlan.free:       10,
    TenantPlan.starter:    100,
    TenantPlan.pro:        500,
    TenantPlan.enterprise: 0,
}
