from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.api.v1.router import router as api_v1_router
from app.api.webhooks import router as webhooks_router
from app.web.routes import router as web_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup y shutdown de la aplicación."""
    print(f"[startup] {settings.app_name} v{settings.app_version} [{settings.app_env}]")
    yield
    print("[shutdown] bye")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.app_debug,
    lifespan=lifespan,
    docs_url="/swagger",
    redoc_url="/redoc",
    description=(
        "API SaaS para extraer datos estructurados de documentos (facturas, "
        "CVs, recibos) usando IA.\n\n"
        "**Auth**:\n"
        "- Endpoints `/extract`, `/me*`: header `Authorization: Bearer psr_...`\n"
        "- Endpoints `/admin/*`: header `X-Admin-Token` (uso interno)\n"
        "- Endpoints `/account/*` y `/billing/*`: cookie de sesión o JWT\n\n"
        "Para conseguir tu API key, [crea una cuenta](/signup) gratis."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if not settings.is_production else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_v1_router, prefix="/api/v1")
app.include_router(webhooks_router, prefix="/webhooks", tags=["webhooks"])
app.include_router(web_router, include_in_schema=False)  # HTML routes — fuera del OpenAPI


@app.get("/health", tags=["system"])
async def health_check():
    """Endpoint de salud para Railway y load balancers."""
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "env": settings.app_env,
    }
