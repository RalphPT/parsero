"""
Modelos Pydantic para validar el output del LLM.

Cada schema_type tiene su propio modelo. Todos los campos son Optional -
si Gemini no encuentra un campo, devolverá null y eso es OK. Lo que NO es
OK es que devuelva un tipo incorrecto o estructura distinta a la pedida:
en ese caso pydantic lanza ValidationError y el endpoint responde 422.
"""
from typing import Optional
from datetime import date as date_type
from pydantic import BaseModel, ConfigDict


#
# Tipos compartidos
#
class _Strict(BaseModel):
    """
    Base. Validamos tipos pero ignoramos campos extras - los LLMs a veces
    agregan campos auxiliares ('confidence', 'notes'...) y no es razón para
    rechazar la extracción entera. Si los tipos están mal eso sí es 422.
    """
    model_config = ConfigDict(extra="ignore")


#
# Invoice
#
class InvoiceParty(_Strict):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    tax_id: Optional[str] = None


class InvoiceLineItem(_Strict):
    description: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    total: Optional[float] = None


class InvoiceExtraction(_Strict):
    invoice_number: Optional[str] = None
    issue_date: Optional[date_type] = None
    due_date: Optional[date_type] = None
    vendor: Optional[InvoiceParty] = None
    customer: Optional[InvoiceParty] = None
    line_items: Optional[list[InvoiceLineItem]] = None
    subtotal: Optional[float] = None
    tax: Optional[float] = None
    total: Optional[float] = None
    currency: Optional[str] = None
    payment_terms: Optional[str] = None


#
# CV
#
class CVPersonal(_Strict):
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    summary: Optional[str] = None


class CVExperience(_Strict):
    company: Optional[str] = None
    job_title: Optional[str] = None
    start_date: Optional[date_type] = None
    end_date: Optional[date_type] = None
    description: Optional[str] = None
    achievements: Optional[list[str]] = None


class CVEducation(_Strict):
    institution: Optional[str] = None
    degree: Optional[str] = None
    field: Optional[str] = None
    start_date: Optional[date_type] = None
    end_date: Optional[date_type] = None
    grade: Optional[str] = None


class CVCertification(_Strict):
    name: Optional[str] = None
    issuer: Optional[str] = None
    date: Optional[date_type] = None
    credential_id: Optional[str] = None


class CVLanguage(_Strict):
    language: Optional[str] = None
    proficiency: Optional[str] = None


class CVExtraction(_Strict):
    personal: Optional[CVPersonal] = None
    experience: Optional[list[CVExperience]] = None
    education: Optional[list[CVEducation]] = None
    skills: Optional[list[str]] = None
    certifications: Optional[list[CVCertification]] = None
    languages: Optional[list[CVLanguage]] = None


#
# Receipt
#
class ReceiptMerchant(_Strict):
    name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    tax_id: Optional[str] = None


class ReceiptLineItem(_Strict):
    description: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    total: Optional[float] = None


class ReceiptExtraction(_Strict):
    merchant: Optional[ReceiptMerchant] = None
    transaction_date: Optional[date_type] = None
    transaction_time: Optional[str] = None  # HH:MM:SS - no hay tipo time JSON-friendly
    line_items: Optional[list[ReceiptLineItem]] = None
    subtotal: Optional[float] = None
    tax: Optional[float] = None
    total: Optional[float] = None
    currency: Optional[str] = None
    payment_method: Optional[str] = None
    transaction_id: Optional[str] = None
    loyalty_program: Optional[str] = None


#
# Registry: schema_type -> modelo Pydantic
#
SCHEMA_REGISTRY: dict[str, type[_Strict]] = {
    "invoice": InvoiceExtraction,
    "cv": CVExtraction,
    "receipt": ReceiptExtraction,
}


def get_output_model(schema_type: str) -> type[_Strict]:
    """Devuelve el modelo Pydantic para validar el output del LLM."""
    if schema_type not in SCHEMA_REGISTRY:
        raise ValueError(f"schema_type desconocido: {schema_type}")
    return SCHEMA_REGISTRY[schema_type]
