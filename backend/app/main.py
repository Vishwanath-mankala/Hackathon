"""
Main FastAPI application entry point.
"""
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import diagnostics, feed, gate, recon

start_time = datetime.now(timezone.utc)

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
app.include_router(feed.router, prefix="/api")
app.include_router(gate.router, prefix="/api")
app.include_router(recon.router, prefix="/api")
app.include_router(diagnostics.router, prefix="/api")


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

