"""Banner Engine - FastAPI application entry point."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.session import ServerSessionMiddleware

from app.core.exceptions import (
    AssetUploadError,
    GenerationError,
    TemplateNotFoundError,
    ValidationError,
    XMLParseError,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger("banner_engine")

# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------
CORS_ORIGINS: list[str] = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8000").split(",")
SESSION_SECRET_KEY: str = os.getenv("SESSION_SECRET_KEY", "banner-engine-dev-secret-change-me")

# ---------------------------------------------------------------------------
# Router imports (try/except so the app can start even if router modules
# have not been created yet)
# ---------------------------------------------------------------------------
_routers = []

try:
    from app.routers import pages

    _routers.append(pages.router)
except (ImportError, AttributeError) as exc:
    logger.warning("Could not import pages router: %s", exc)

try:
    from app.routers import templates

    _routers.append(templates.router)
except (ImportError, AttributeError) as exc:
    logger.warning("Could not import templates router: %s", exc)

try:
    from app.routers import slots

    _routers.append(slots.router)
except (ImportError, AttributeError) as exc:
    logger.warning("Could not import slots router: %s", exc)

try:
    from app.routers import preview

    _routers.append(preview.router)
except (ImportError, AttributeError) as exc:
    logger.warning("Could not import preview router: %s", exc)

try:
    from app.routers import generate

    _routers.append(generate.router)
except (ImportError, AttributeError) as exc:
    logger.warning("Could not import generate router: %s", exc)

try:
    from app.routers import assets

    _routers.append(assets.router)
except (ImportError, AttributeError) as exc:
    logger.warning("Could not import assets router: %s", exc)

try:
    from app.routers import image_generate
    _routers.append(image_generate.router)
except (ImportError, AttributeError) as exc:
    logger.warning("Could not import image_generate router: %s", exc)


# ---------------------------------------------------------------------------
# Startup / shutdown logic
# ---------------------------------------------------------------------------
def _load_xml_templates(app_instance: FastAPI) -> None:
    """Load XML templates at startup and attach services to app.state."""
    try:
        from app.services.template_service import TemplateService  # noqa: WPS433
        from app.core.svg_renderer import SvgRenderer  # noqa: WPS433

        service = TemplateService()
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        service.load_templates_from_directory(base_dir)
        app_instance.state.template_service = service

        renderer = SvgRenderer()
        app_instance.state.svg_renderer = renderer

        # Initialize image generation services
        from app.services.nano_banana_client import NanoBananaClient
        from app.services.image_generation_service import ImageGenerationService

        api_key = os.getenv("GOOGLE_AI_API_KEY", "")
        nano_client = NanoBananaClient(api_key=api_key)
        app_instance.state.nano_banana_client = nano_client
        app_instance.state.image_generation_service = ImageGenerationService(nano_client)

        logger.info(
            "XML templates loaded successfully (%d templates)",
            len(service.get_all_templates()),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load XML templates at startup: %s", exc)
        # Ensure state attributes exist even on failure
        from app.services.template_service import TemplateService
        from app.core.svg_renderer import SvgRenderer
        app_instance.state.template_service = TemplateService()
        app_instance.state.svg_renderer = SvgRenderer()
        from app.services.nano_banana_client import NanoBananaClient
        from app.services.image_generation_service import ImageGenerationService
        nano_client = NanoBananaClient(api_key="")
        app_instance.state.nano_banana_client = nano_client
        app_instance.state.image_generation_service = ImageGenerationService(nano_client)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown events."""
    _load_xml_templates(app)
    yield


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Banner Engine",
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(ServerSessionMiddleware)

# ---------------------------------------------------------------------------
# Static files & templates
# ---------------------------------------------------------------------------
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

os.makedirs("app/templates", exist_ok=True)
templates = Jinja2Templates(directory="app/templates")

# ---------------------------------------------------------------------------
# Include routers
# ---------------------------------------------------------------------------
for router in _routers:
    app.include_router(router)

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/health", tags=["health"])
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "version": "1.0.0"}



# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """Handle 404 Not Found errors."""
    return JSONResponse(
        status_code=404,
        content={"detail": "The requested resource was not found."},
    )


@app.exception_handler(422)
async def validation_error_handler(request: Request, exc):
    """Handle 422 Unprocessable Entity errors."""
    detail = "Validation error. Please check your input."
    if hasattr(exc, "errors"):
        detail = str(exc.errors()) if callable(exc.errors) else str(exc.errors)
    elif hasattr(exc, "detail"):
        detail = str(exc.detail)
    logger.warning("422 error on %s: %s", request.url.path, detail)
    return JSONResponse(
        status_code=422,
        content={"detail": detail},
    )


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    """Handle 500 Internal Server errors."""
    logger.exception("Internal server error")
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred."},
    )


@app.exception_handler(TemplateNotFoundError)
async def template_not_found_handler(request: Request, exc: TemplateNotFoundError):
    """Handle TemplateNotFoundError."""
    return JSONResponse(
        status_code=404,
        content={"detail": exc.message},
    )


@app.exception_handler(ValidationError)
async def custom_validation_error_handler(request: Request, exc: ValidationError):
    """Handle custom ValidationError."""
    return JSONResponse(
        status_code=422,
        content={"detail": exc.message, "errors": exc.errors},
    )


@app.exception_handler(XMLParseError)
async def xml_parse_error_handler(request: Request, exc: XMLParseError):
    """Handle XMLParseError."""
    return JSONResponse(
        status_code=400,
        content={"detail": exc.message},
    )


@app.exception_handler(GenerationError)
async def generation_error_handler(request: Request, exc: GenerationError):
    """Handle GenerationError."""
    return JSONResponse(
        status_code=500,
        content={"detail": exc.message},
    )


@app.exception_handler(AssetUploadError)
async def asset_upload_error_handler(request: Request, exc: AssetUploadError):
    """Handle AssetUploadError."""
    return JSONResponse(
        status_code=422,
        content={"detail": exc.message},
    )
