"""
StyleSenseAI — FastAPI Application

Main entry point with lifespan management, security middleware,
health checks, and structured logging.
"""

import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.core.logging import (
    generate_request_id,
    get_logger,
    request_id_ctx,
    setup_logging,
)
from app.core.rate_limit import RateLimiter
from app.db.session import close_db
from app.deps import set_rate_limiter

# Import routers
from app.routers import auth, body, consents, me, media, profile, wardrobe

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan — startup and shutdown hooks."""
    setup_logging()
    logger.info("Starting StyleSenseAI API...")

    settings = get_settings()

    # Initialize rate limiter
    redis_client = None
    if not settings.jobs_eager:
        try:
            import redis.asyncio as aioredis
            redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
            await redis_client.ping()
            logger.info("Redis connected for rate limiting")
        except Exception as e:
            logger.warning(f"Redis not available, using in-memory rate limiter: {e}")
            redis_client = None

    limiter = RateLimiter(redis_client)
    set_rate_limiter(limiter)

    logger.info(
        "StyleSenseAI API started",
        extra={
            "env": settings.app_env,
            "llm_provider": settings.llm_provider,
            "storage_provider": settings.storage_provider,
            "classifier_provider": settings.classifier_provider,
        },
    )

    yield

    # Shutdown
    if redis_client:
        await redis_client.close()
    await close_db()
    logger.info("StyleSenseAI API stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="StyleSenseAI",
        description="AI-powered personal styling and wardrobe management",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
    )

    # ── Security Middleware ──

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    # Trusted Hosts (production)
    if settings.is_production:
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=["*.stylesense.ai", "localhost"],
        )

    # ── Request Middleware ──

    @app.middleware("http")
    async def request_middleware(request: Request, call_next):
        """Add request ID, security headers, timing, and logging."""
        # Generate and propagate request ID
        req_id = request.headers.get("X-Request-ID", generate_request_id())
        request_id_ctx.set(req_id)

        start = time.perf_counter()

        # Request size limit (10 MB default, media endpoints have their own)
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > 10 * 1024 * 1024:
            if not request.url.path.startswith(("/media", "/api/v1/media")):
                return JSONResponse(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    content={"detail": "Request body too large."},
                )

        response = await call_next(request)

        # Timing
        duration_ms = (time.perf_counter() - start) * 1000

        # Security headers
        response.headers["X-Request-ID"] = req_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com; "
                "img-src 'self' data: blob:; "
                "frame-ancestors 'none'"
            )

        # Cache control for sensitive endpoints
        if request.url.path.startswith(("/auth", "/me", "/body")):
            response.headers["Cache-Control"] = "no-store"

        # Log request
        logger.info(
            f"{request.method} {request.url.path} → {response.status_code}",
            extra={
                "method": request.method,
                "path": str(request.url.path),
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
            },
        )

        return response

    # ── Routers ──

    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(profile.router, prefix="/api/v1")
    app.include_router(consents.router, prefix="/api/v1")
    app.include_router(me.router, prefix="/api/v1")
    app.include_router(media.router, prefix="/api/v1")
    app.include_router(wardrobe.router, prefix="/api/v1")
    app.include_router(body.router, prefix="/api/v1")

    # ── Health Checks ──

    @app.get("/healthz", tags=["health"])
    async def healthz():
        """Liveness probe — is the process alive?"""
        return {"status": "ok"}

    @app.get("/readyz", tags=["health"])
    async def readyz():
        """Readiness probe — is the service ready to accept traffic?"""
        # TODO: Check DB and Redis connectivity
        return {"status": "ok", "version": "0.1.0"}

    return app


app = create_app()
