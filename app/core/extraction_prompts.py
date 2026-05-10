"""Extraction prompts for different document schemas."""

INVOICE_SYSTEM_PROMPT = """You are an expert invoice parser. Extract structured data from invoices.
Always respond with valid JSON only, no markdown or extra text.
Use null for missing fields."""

INVOICE_EXTRACTION_TEMPLATE = """Extract invoice data from this document and return JSON:

{document_text}

Return JSON with this structure (all fields optional):
{{
  "invoice_number": string | null,
  "issue_date": string (YYYY-MM-DD) | null,
  "due_date": string (YYYY-MM-DD) | null,
  "vendor": {{
    "name": string | null,
    "email": string | null,
    "phone": string | null,
    "address": string | null,
    "tax_id": string | null
  }},
  "customer": {{
    "name": string | null,
    "email": string | null,
    "address": string | null,
    "tax_id": string | null
  }},
  "line_items": [
    {{
      "description": string | null,
      "quantity": number | null,
      "unit_price": number | null,
      "total": number | null
    }}
  ],
  "subtotal": number | null,
  "tax": number | null,
  "total": number | null,
  "currency": string | null,
  "payment_terms": string | null
}}"""


CV_SYSTEM_PROMPT = """You are an expert CV/resume parser. Extract structured data from CVs.
Always respond with valid JSON only, no markdown or extra text.
Use null for missing fields."""

CV_EXTRACTION_TEMPLATE = """Extract CV data from this document and return JSON:

{document_text}

Return JSON with this structure (all fields optional):
{{
  "personal": {{
    "full_name": string | null,
    "email": string | null,
    "phone": string | null,
    "location": string | null,
    "summary": string | null
  }},
  "experience": [
    {{
      "company": string | null,
      "job_title": string | null,
      "start_date": string (YYYY-MM-DD) | null,
      "end_date": string (YYYY-MM-DD) | null,
      "description": string | null,
      "achievements": [string] | null
    }}
  ],
  "education": [
    {{
      "institution": string | null,
      "degree": string | null,
      "field": string | null,
      "start_date": string (YYYY-MM-DD) | null,
      "end_date": string (YYYY-MM-DD) | null,
      "grade": string | null
    }}
  ],
  "skills": [string] | null,
  "certifications": [
    {{
      "name": string | null,
      "issuer": string | null,
      "date": string (YYYY-MM-DD) | null,
      "credential_id": string | null
    }}
  ],
  "languages": [
    {{
      "language": string | null,
      "proficiency": string | null
    }}
  ]
}}"""


RECEIPT_SYSTEM_PROMPT = """You are an expert receipt parser. Extract structured data from receipts.
Always respond with valid JSON only, no markdown or extra text.
Use null for missing fields."""

RECEIPT_EXTRACTION_TEMPLATE = """Extract receipt data from this document and return JSON:

{document_text}

Return JSON with this structure (all fields optional):
{{
  "merchant": {{
    "name": string | null,
    "address": string | null,
    "phone": string | null,
    "tax_id": string | null
  }},
  "transaction_date": string (YYYY-MM-DD) | null,
  "transaction_time": string (HH:MM:SS) | null,
  "line_items": [
    {{
      "description": string | null,
      "quantity": number | null,
      "unit_price": number | null,
      "total": number | null
    }}
  ],
  "subtotal": number | null,
  "tax": number | null,
  "total": number | null,
  "currency": string | null,
  "payment_method": string | null,
  "transaction_id": string | null,
  "loyalty_program": string | null
}}"""


def get_system_prompt(schema_type: str) -> str:
    """Get system prompt for schema type."""
    prompts = {
        "invoice": INVOICE_SYSTEM_PROMPT,
        "cv": CV_SYSTEM_PROMPT,
        "receipt": RECEIPT_SYSTEM_PROMPT,
    }
    if schema_type not in prompts:
        raise ValueError(f"Unknown schema type: {schema_type}")
    return prompts[schema_type]


def get_extraction_template(schema_type: str) -> str:
    """Get extraction prompt template for schema type."""
    templates = {
        "invoice": INVOICE_EXTRACTION_TEMPLATE,
        "cv": CV_EXTRACTION_TEMPLATE,
        "receipt": RECEIPT_EXTRACTION_TEMPLATE,
    }
    if schema_type not in templates:
        raise ValueError(f"Unknown schema type: {schema_type}")
    return templates[schema_type]
