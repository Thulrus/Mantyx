"""
Main FastAPI application.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from mantyx import __version__
from mantyx.api import apps, backup, executions, schedules, settings
from mantyx.config import get_settings, get_system_timezone
from mantyx.core import runtime
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
    """Lifespan context manager for startup and shutdown.

    Shutdown relies on uvicorn's own SIGINT/SIGTERM handling, which lets this
    function's cleanup run. (A previous custom signal handler stopped the
    event loop directly, which skipped cleanup entirely.)
    """
    global scheduler, supervisor

    logger.info(f"Starting Mantyx {__version__}...")

    settings = get_settings()
    settings.ensure_directories()

    # Initialize database (also adds columns missing from older installs)
    init_db()
    logger.info("Database initialized")

    supervisor = ProcessSupervisor()
    scheduler = AppScheduler()
    runtime.set_runtime(scheduler=scheduler, supervisor=supervisor)

    # Close run records interrupted by the last shutdown, then bring back every
    # always-running app that was running (or adopt it if it survived).
    await run_in_threadpool(supervisor.reconcile_on_startup)
    await run_in_threadpool(supervisor.adopt_running_apps)

    scheduler.start()
    logger.info("Mantyx started successfully")

    yield

    logger.info("Shutting down Mantyx...")
    current_scheduler = runtime.get_scheduler()
    current_supervisor = runtime.get_supervisor()
    if current_scheduler:
        current_scheduler.stop()
    if current_supervisor:
        await run_in_threadpool(current_supervisor.shutdown)
    runtime.clear_runtime()
    logger.info("Mantyx shut down")


# Create FastAPI app
app = FastAPI(
    title="Mantyx",
    description="Python Application Orchestration Framework",
    version=__version__,
    lifespan=lifespan,
)

# Include routers
app.include_router(apps.router, prefix="/api")
app.include_router(executions.router, prefix="/api")
app.include_router(schedules.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(backup.router, prefix="/api")

# Serve static files (web UI)
static_dir = Path(__file__).parent / "web" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main web interface."""
    template_path = Path(__file__).parent / "web" / "index.html"
    if template_path.exists():
        # Cache-bust static assets on every Mantyx version so browsers never
        # keep running old JavaScript against a new API after a deploy.
        return HTMLResponse(
            template_path.read_text().replace("__MANTYX_VERSION__", _asset_version()),
            headers={"Cache-Control": "no-cache"},
        )
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


def _asset_version() -> str:
    """Changes whenever the bundled web assets change."""
    static = Path(__file__).parent / "web" / "static"
    newest = 0.0
    for path in static.rglob("*"):
        if path.is_file():
            newest = max(newest, path.stat().st_mtime)
    return f"{__version__}-{int(newest)}"


@app.get("/health")
async def health():
    """Health check endpoint."""
    current = runtime.get_scheduler()
    return {
        "status": "healthy",
        "scheduler_running": bool(current and current.running),
    }


@app.get("/api/system/info")
async def system_info():
    """Get system information."""
    from mantyx.core.scheduler import get_effective_timezone

    current = runtime.get_scheduler()
    return {
        "version": __version__,
        "timezone": current.timezone if current else get_effective_timezone(),
        "detected_timezone": get_system_timezone(),
        "scheduler_running": bool(current and current.running),
    }


def run():
    """Run the application."""
    import uvicorn

    settings = get_settings()

    if settings.debug:
        # Exclude dev_data directory from file watching to prevent reloads
        # when apps install dependencies or create virtual environments
        uvicorn.run(
            "mantyx.app:app",
            host=settings.host,
            port=settings.port,
            reload=True,
            reload_excludes=["dev_data/*"],
            log_level="debug",
        )
        return

    class _Server(uvicorn.Server):
        def handle_exit(self, sig, frame):
            runtime.mark_shutting_down()
            super().handle_exit(sig, frame)

    config = uvicorn.Config(
        "mantyx.app:app", host=settings.host, port=settings.port, log_level="info"
    )
    _Server(config).run()


if __name__ == "__main__":
    run()
