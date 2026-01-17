"""
Main FastAPI application.
"""

import signal
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from mantyx.api import apps, executions, schedules
from mantyx.config import get_settings
from mantyx.core.app_manager import AppManager
from mantyx.core.scheduler import AppScheduler
from mantyx.core.supervisor import ProcessSupervisor
from mantyx.database import init_db
from mantyx.logging import get_logger

logger = get_logger("main")

# Global instances
scheduler: AppScheduler | None = None
supervisor: ProcessSupervisor | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown."""
    global scheduler, supervisor

    # Startup
    logger.info("Starting Mantyx...")

    settings = get_settings()
    settings.ensure_directories()

    # Initialize database
    init_db()
    logger.info("Database initialized")

    # Start scheduler
    scheduler = AppScheduler()
    scheduler.start()
    logger.info("Scheduler started")

    # Start supervisor
    supervisor = ProcessSupervisor()
    logger.info("Supervisor initialized")

    # Register signal handlers
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        if scheduler:
            scheduler.stop()
        if supervisor:
            supervisor.cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info("Mantyx started successfully")

    yield

    # Shutdown
    logger.info("Shutting down Mantyx...")

    if scheduler:
        scheduler.stop()

    if supervisor:
        supervisor.cleanup()

    logger.info("Mantyx shut down")


# Create FastAPI app
app = FastAPI(
    title="Mantyx",
    description="Python Application Orchestration Framework",
    version="0.1.0",
    lifespan=lifespan,
)

# Include routers
app.include_router(apps.router, prefix="/api")
app.include_router(executions.router, prefix="/api")
app.include_router(schedules.router, prefix="/api")

# Serve static files (web UI)
static_dir = Path(__file__).parent / "web" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main web interface."""
    template_path = Path(__file__).parent / "web" / "index.html"
    if template_path.exists():
        return template_path.read_text()
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Mantyx</title>
    </head>
    <body>
        <h1>Mantyx - Python App Orchestration</h1>
        <p>Web interface not yet configured. Access the API at <a href="/docs">/docs</a></p>
    </body>
    </html>
    """


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "scheduler_running":
        scheduler._scheduler.running if scheduler else False,
    }


@app.get("/api/system/info")
async def system_info():
    """Get system information."""
    settings = get_settings()
    return {
        "timezone": settings.timezone,
        "version": "0.1.0",
    }


def run():
    """Run the application."""
    import uvicorn

    settings = get_settings()

    # Exclude dev_data directory from file watching to prevent reloads
    # when apps install dependencies or create virtual environments
    reload_excludes = ["dev_data/*"] if settings.debug else None

    uvicorn.run(
        "mantyx.app:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        reload_excludes=reload_excludes,
        log_level="info" if not settings.debug else "debug",
    )


if __name__ == "__main__":
    run()
