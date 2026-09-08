"""
Main FastAPI application entry point.
"""
import logging
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import diagnostics, feed, gate, recon, pipeline

logger = logging.getLogger(__name__)

start_time = datetime.now(timezone.utc)


def _log_startup_configuration() -> None:
    """
    Prints which config file was read and which agent stages it wired up.

    Settings are read once at import, so editing .env has no effect until the
    process restarts. Stating the resolved values at startup makes that obvious:
    if a stage you just configured still shows "not configured" here, the file
    was edited after this process began.
    """
    from app.services.agentic_anomaly_service import agentic_anomaly_service

    logger.info("Configuration file: %s", settings.model_config["env_file"])

    roster = agentic_anomaly_service.agent_bridge.get_configured_agents()
    wired = [a for a in roster if a["configured"] and a["auto_dispatch"]]
    missing = [a for a in roster if not a["configured"] and a["auto_dispatch"]]

    for agent in wired:
        logger.info("Agent wired   %-16s -> id %s (%s)", agent["stage_key"], agent["id"], agent["name"])
    for agent in missing:
        logger.warning(
            "Agent MISSING %-16s -> set %s in .env, then restart; this stage will be SKIPPED",
            agent["stage_key"], agent["key"],
        )

    if not settings.crewai_api_key:
        logger.warning("CREWAI_API_KEY is not set — every agent dispatch will be SKIPPED.")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=settings.app_description,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(pipeline.router)
app.include_router(feed.router, prefix="/api")
app.include_router(gate.router, prefix="/api")
app.include_router(recon.router, prefix="/api")
app.include_router(diagnostics.router, prefix="/api")

_log_startup_configuration()


@app.get("/health", tags=["System"])
async def health_check():
    """System liveness and readiness health probe."""
    now = datetime.now(timezone.utc)
    return {
        "status": "healthy",
        "app_name": settings.app_name,
        "version": settings.app_version,
        "uptime_seconds": round((now - start_time).total_seconds(), 2),
        "timestamp": now.isoformat(),
    }


@app.get("/", tags=["System"])
async def root():
    """Root redirect / discovery metadata."""
    return {
        "message": f"Welcome to {settings.app_name}",
        "docs": "/docs",
        "health": "/health",
        "endpoints": {
            "feed": "/api/feed",
            "gate": "/api/gate",
            "recon": "/api/recon",
            "diagnostics": "/api/diagnostics",
        },
    }

