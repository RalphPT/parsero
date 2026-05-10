"""Schemas para los endpoints de billing."""
from typing import Literal
from pydantic import BaseModel


class CheckoutRequest(BaseModel):
    plan: Literal["starter", "pro"]


class CheckoutResponse(BaseModel):
    checkout_url: str


class PortalResponse(BaseModel):
    portal_url: str
