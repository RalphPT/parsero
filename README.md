# Parsero

API que toma un PDF (factura, CV, recibo) y devuelve un JSON estructurado.
Por debajo le pega a Gemini Flash con prompts y un schema Pydantic por cada
tipo de documento. Cache por SHA-256 para no pagar dos veces la misma
extracción.

Demo en vivo: https://parsero-production.up.railway.app

## Stack

- FastAPI 0.115 (Python 3.12, todo async)
- Postgres 16 + SQLAlchemy 2.0 con asyncpg
- Redis 7 para rate limit y throttling de `last_used_at`
- Gemini 2.5 Flash como LLM principal (free tier mientras dure)
- Resend para emails transaccionales
- Lemon Squeezy para checkout y subscripciones
- Alembic para migraciones
- Deploy en Railway (Postgres + Redis + app, todo en el mismo proyecto)

## Levantarlo en local

Necesitas Python 3.12 y Docker.

```bash
# 1. Postgres + Redis
docker compose up -d

# 2. Variables de entorno
cp .env.example .env
# editar .env y poner como mínimo:
#   - SECRET_KEY (python -c "import secrets; print(secrets.token_urlsafe(48))")
#   - GEMINI_API_KEY (gratis en https://aistudio.google.com/app/apikey)

# 3. Dependencias
python -m venv .venv
.venv\Scripts\activate          # Windows; en Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt

# 4. Migraciones
alembic upgrade head

# 5. Servidor
uvicorn app.main:app --reload --port 8000
```

Si todo va bien: `http://localhost:8000` muestra la landing y `http://localhost:8000/docs` el Swagger con todos los endpoints.

## Cómo se usa la API

Crear cuenta en `/signup`, verificar el email, copiar la API key del dashboard
y mandar requests:

```bash
curl -X POST http://localhost:8000/api/v1/extract \
  -H "Authorization: Bearer psr_xxx" \
  -H "Content-Type: application/json" \
  -d '{"document_url": "https://example.com/factura.pdf", "schema_type": "invoice"}'
```

Respuesta (cuando termina, ~5 segundos):

```json
{
  "id": "uuid-del-job",
  "status": "completed",
  "created_at": "2026-05-09T..."
}
```

Para traer la data extraída se hace `GET /api/v1/extract/{id}` con el mismo
Bearer.

Schemas soportados: `invoice`, `cv`, `receipt`. Los modelos Pydantic con la
estructura exacta de cada uno están en `app/schemas/extraction_outputs.py`.

## Estructura

```
app/
  api/
    v1/endpoints/      → admin, auth, billing, extraction, account, tenants
    webhooks.py        → handler del webhook de Lemon Squeezy
    dependencies.py    → auth (API key + JWT), rate limit, admin token
  core/                → config, jwt, passwords, llm provider, prompts, etc.
  db/
    models/            → tenant, api_key, extraction_job, result, usage_log
    repositories/      → queries por modelo
  schemas/             → pydantic in/out
  services/            → email, lemonsqueezy, redis
  web/
    routes.py          → páginas HTML (server-rendered con Jinja2)
    templates/         → landing, dashboard, login, signup, etc.
alembic/               → migraciones
tests/                 → smoke tests por fase (no son pytest, se corren con -m)
```

## Tests

No hay suite de unit tests todavía. Sí hay smoke tests end-to-end por cada
fase del proyecto. Necesitan Postgres y Redis levantados.

```bash
python -m tests.smoke_phase2     # auth + rate limiting
python -m tests.smoke_phase3     # extracción real con Gemini
python -m tests.smoke_phase5_1   # auth pública (signup, login, JWT)
python -m tests.smoke_phase5_2   # billing con Lemon Squeezy (mockeado)
python -m tests.smoke_phase5_3   # landing + dashboard
```

`smoke_phase3` consume tu cuota de Gemini real. El de `5_2` no toca nada
externo, todo está mockeado y firma webhooks localmente con HMAC.

## Decisiones que vale la pena explicar

**Por qué Gemini y no Claude/GPT.** Free tier generoso. Para una v1 con
poco tráfico la diferencia de calidad no compensa el costo. Si en algún
momento aparece tier premium, el provider está abstraído en
`app/core/llm_provider.py` y migrar es cambiar una clase.

**Por qué Lemon Squeezy y no Stripe.** Stripe no opera en Perú y no
quería abrir LLC en Delaware. Lemon Squeezy es Merchant of Record:
ellos cobran, manejan IVA y depositan neto. Comisión más alta (~5%)
pero cero burocracia.

**API keys vs JWT.** Las dos coexisten. `psr_xxx` (API key) para
clientes que llaman a `/extract` desde código. JWT con cookie HttpOnly
para el browser navegando el dashboard. La dependencia
`get_current_user_jwt` acepta ambos.

**Cache key.** `(tenant_id, document_hash, schema_type)`. Schema
distinto = extracción distinta. Sin esto, pedir un mismo PDF como
`invoice` y luego como `receipt` devolvería el mismo JSON erróneo.

**`completed_at` y status.** Cada job pasa por `pending → processing →
completed | failed | cached`. Persistir el status incluso en errores
sirve para auditoría y para no cobrar tokens dos veces si el cliente
reintenta.

## Estado actual

v0.1 corriendo en producción. Faltan:

- Aprobar KYC de Lemon Squeezy (1-3 días) para activar cobros reales
- Comprar dominio custom y configurarlo en Railway + Resend
- Verificar dominio propio en Resend (sin eso, solo se pueden mandar
  emails al email de la cuenta de Resend)
- Workers async (Celery) si en algún momento aparecen documentos que
  tarden mucho. Hoy con Gemini Flash y PDFs chicos, los 5 segundos
  bloqueando el request van bien.

## Variables de entorno

Mira `.env.example` para la lista completa. Las críticas:

- `DATABASE_URL`, `REDIS_URL`
- `SECRET_KEY` (firma JWTs y compara con `X-Admin-Token`)
- `GEMINI_API_KEY`
- `RESEND_API_KEY`, `EMAIL_FROM`, `PUBLIC_BASE_URL`
- `LEMONSQUEEZY_*` (API key, webhook secret, store id, variant ids)

En Railway, `DATABASE_URL` y `REDIS_URL` se inyectan referenciando los
servicios con `${{Postgres.DATABASE_URL}}` y `${{Redis.REDIS_URL}}`.
El código en `app/db/session.py` traduce `postgresql://` a
`postgresql+asyncpg://` automáticamente porque Railway usa el formato
psycopg2 por default.
