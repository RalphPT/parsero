"""Schemas para los endpoints /account/* del dashboard."""
from pydantic import BaseModel


class UsageSummary(BaseModel):
    """Resumen de consumo del billing period actual (mes)."""
    billing_period: str  # YYYY-MM
    extractions_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
