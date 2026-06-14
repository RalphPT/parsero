# Prompts por schema. Los system prompts traen reglas duras de normalización
# (ISO 4217 para currency, ISO 8601 para fechas, etc.) para que el output sea
# consistente entre llamadas y entre documentos similares.


NORMALIZATION_RULES = """
Normalization rules (apply strictly):
1. Dates: always ISO 8601 format YYYY-MM-DD. Convert any local format
   (DD/MM/YYYY, MM-DD-YY, "31 de enero", etc.) to YYYY-MM-DD.
2. Currency: always use ISO 4217 three-letter code (USD, EUR, PEN, MXN,
   COP, BRL, ARS, CLP, GBP, etc.). Never use symbols ($, €, S/, R$).
   Map common symbols: S/ -> PEN, $ alone -> USD, R$ -> BRL, € -> EUR.
3. Amounts: always numeric (decimal). Never include currency symbols,
   thousands separators or units. "S/ 1,234.56" -> 1234.56.
4. Phone numbers: international format with country code prefix.
   Strip parentheses and dashes. "(+511) 705-9500" -> "+5117059500".
5. Tax IDs / National IDs: digits only, no dashes or spaces.
   "20-347-100-316" -> "20347100316".
6. Emails: lowercase, trimmed.
7. Strings: trim leading/trailing whitespace. Collapse multiple spaces to one.
8. Missing fields: use null. Never invent or guess data not present in
   the document.
"""


INVOICE_SYSTEM_PROMPT = (
    "You are an expert invoice parser. Extract structured data from invoices "
    "and respond with valid JSON only (no markdown, no explanations).\n"
    + NORMALIZATION_RULES
)

INVOICE_EXTRACTION_TEMPLATE = """Extract invoice data from this document.

{document_text}

Return JSON with this exact structure (all fields optional, use null when missing):
{{
  "invoice_number": "string or null",
  "issue_date": "YYYY-MM-DD or null",
  "due_date": "YYYY-MM-DD or null",
  "vendor": {{
    "name": "string or null",
    "email": "string or null",
    "phone": "string or null (international format)",
    "address": "string or null",
    "tax_id": "string or null (digits only)"
  }},
  "customer": {{
    "name": "string or null",
    "email": "string or null",
    "phone": "string or null",
    "address": "string or null",
    "tax_id": "string or null (digits only)"
  }},
  "line_items": [
    {{
      "description": "string or null",
      "quantity": number or null,
      "unit_price": number or null,
      "total": number or null
    }}
  ],
  "subtotal": number or null,
  "tax": number or null,
  "total": number or null,
  "currency": "ISO 4217 code or null (e.g. USD, PEN, EUR, MXN)",
  "payment_terms": "string or null"
}}"""


CV_SYSTEM_PROMPT = (
    "You are an expert CV/resume parser. Extract structured data from resumes "
    "and respond with valid JSON only (no markdown, no explanations).\n"
    + NORMALIZATION_RULES
    + """
Additional CV-specific rules:
- For "present" / "current" / "ongoing" job dates, use null in end_date.
- skills: list of normalized skill names. Capitalize properly (e.g. "Python",
  "JavaScript", "AWS" - not "python" or "PYTHON").
- proficiency in languages: use one of "native", "fluent", "advanced",
  "intermediate", "basic". Map any other phrasing to one of these.
"""
)

CV_EXTRACTION_TEMPLATE = """Extract CV/resume data from this document.

{document_text}

Return JSON with this exact structure (all fields optional, use null when missing):
{{
  "personal": {{
    "full_name": "string or null",
    "email": "string or null (lowercase)",
    "phone": "string or null (international format)",
    "location": "string or null",
    "summary": "string or null"
  }},
  "experience": [
    {{
      "company": "string or null",
      "job_title": "string or null",
      "start_date": "YYYY-MM-DD or null",
      "end_date": "YYYY-MM-DD or null (null if current job)",
      "description": "string or null",
      "achievements": ["string"] or null
    }}
  ],
  "education": [
    {{
      "institution": "string or null",
      "degree": "string or null",
      "field": "string or null",
      "start_date": "YYYY-MM-DD or null",
      "end_date": "YYYY-MM-DD or null",
      "grade": "string or null"
    }}
  ],
  "skills": ["string"] or null,
  "certifications": [
    {{
      "name": "string or null",
      "issuer": "string or null",
      "date": "YYYY-MM-DD or null",
      "credential_id": "string or null"
    }}
  ],
  "languages": [
    {{
      "language": "string or null",
      "proficiency": "native|fluent|advanced|intermediate|basic or null"
    }}
  ]
}}"""


RECEIPT_SYSTEM_PROMPT = (
    "You are an expert receipt parser. Extract structured data from receipts "
    "and respond with valid JSON only (no markdown, no explanations).\n"
    + NORMALIZATION_RULES
    + """
Additional receipt-specific rules:
- transaction_time: 24-hour format HH:MM:SS. If only HH:MM is present, append ":00".
- payment_method: normalize to one of "cash", "credit_card", "debit_card",
  "transfer", "qr", "wallet", "check". Map any other phrasing to one of these.
"""
)

RECEIPT_EXTRACTION_TEMPLATE = """Extract receipt data from this document.

{document_text}

Return JSON with this exact structure (all fields optional, use null when missing):
{{
  "merchant": {{
    "name": "string or null",
    "address": "string or null",
    "phone": "string or null (international format)",
    "tax_id": "string or null (digits only)"
  }},
  "transaction_date": "YYYY-MM-DD or null",
  "transaction_time": "HH:MM:SS (24h) or null",
  "line_items": [
    {{
      "description": "string or null",
      "quantity": number or null,
      "unit_price": number or null,
      "total": number or null
    }}
  ],
  "subtotal": number or null,
  "tax": number or null,
  "total": number or null,
  "currency": "ISO 4217 code or null (e.g. USD, PEN, EUR, MXN)",
  "payment_method": "cash|credit_card|debit_card|transfer|qr|wallet|check or null",
  "transaction_id": "string or null",
  "loyalty_program": "string or null"
}}"""


def get_system_prompt(schema_type: str) -> str:
    prompts = {
        "invoice": INVOICE_SYSTEM_PROMPT,
        "cv": CV_SYSTEM_PROMPT,
        "receipt": RECEIPT_SYSTEM_PROMPT,
    }
    if schema_type not in prompts:
        raise ValueError(f"Unknown schema type: {schema_type}")
    return prompts[schema_type]


def get_extraction_template(schema_type: str) -> str:
    templates = {
        "invoice": INVOICE_EXTRACTION_TEMPLATE,
        "cv": CV_EXTRACTION_TEMPLATE,
        "receipt": RECEIPT_EXTRACTION_TEMPLATE,
    }
    if schema_type not in templates:
        raise ValueError(f"Unknown schema type: {schema_type}")
    return templates[schema_type]
