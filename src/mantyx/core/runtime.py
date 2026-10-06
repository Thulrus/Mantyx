"""
Process-wide singletons for the running Mantyx server.

There must be exactly one scheduler and one supervisor per process: the
supervisor keeps per-app locks and the set of processes it started, and the
scheduler owns the live job list. API routes, background jobs and the backup
restore all reach them through here instead of constructing their own copies
(which previously left deleted apps' schedules firing, because the copy that
"removed" them had never been started).
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mantyx.core.app_manager import AppManager
    from mantyx.core.scheduler import AppScheduler
    from mantyx.core.supervisor import ProcessSupervisor

_lock = threading.Lock()
_shutting_down = threading.Event()
_scheduler: AppScheduler | None = None
_supervisor: ProcessSupervisor | None = None


def set_runtime(
    scheduler: AppScheduler | None = None, supervisor: ProcessSupervisor | None = None
) -> None:
    """Install the live instances (called at startup and after a backup restore)."""
    global _scheduler, _supervisor
    with _lock:
        if scheduler is not None:
            _scheduler = scheduler
        if supervisor is not None:
            _supervisor = supervisor


def clear_runtime() -> None:
    global _scheduler, _supervisor
    with _lock:
        _scheduler = None
        _supervisor = None


def get_scheduler() -> AppScheduler | None:
    return _scheduler


def get_supervisor() -> ProcessSupervisor:
    """The shared supervisor, created lazily if the server hasn't set one."""
    global _supervisor
    with _lock:
        if _supervisor is None:
            from mantyx.core.supervisor import ProcessSupervisor

            _supervisor = ProcessSupervisor()
        return _supervisor


def get_app_manager() -> AppManager:
    """An AppManager wired to the shared scheduler and supervisor."""
    from mantyx.core.app_manager import AppManager

    return AppManager(supervisor=get_supervisor(), scheduler=get_scheduler())


def mark_shutting_down() -> None:
    """Called as soon as a stop signal arrives, before cleanup starts.

    Under systemd every process in the service receives SIGTERM at once, so
    apps may exit a moment before Mantyx runs its shutdown; this flag keeps
    the crash monitor from treating that as a crash and restarting them.
    """
    _shutting_down.set()


def is_shutting_down() -> bool:
    return _shutting_down.is_set()
