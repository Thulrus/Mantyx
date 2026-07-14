"""
In-memory task tracking for long-running operations.

Lets API endpoints kick off slow work (venv creation, pip installs, git
clones) in a background thread while the frontend polls for live progress
instead of staring at a frozen spinner.
"""

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class Task:
    id: str
    name: str
    status: TaskStatus = TaskStatus.RUNNING
    logs: list[str] = field(default_factory=list)
    error: str | None = None
    result: dict[str, Any] | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class TaskManager:
    """Tracks progress of background operations so clients can poll for updates."""

    def __init__(self):
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()

    def create(self, name: str) -> Task:
        task = Task(id=str(uuid.uuid4()), name=name)
        with self._lock:
            self._tasks[task.id] = task
        return task

    def get(self, task_id: str) -> Task | None:
        with self._lock:
            return self._tasks.get(task_id)

    def log(self, task_id: str, message: str) -> None:
        task = self.get(task_id)
        if not task:
            return
        with task.lock:
            task.logs.append(message)

    def logger_for(self, task_id: str) -> Callable[[str], None]:
        """A callback suitable for passing into log-emitting operations."""

        def _log(message: str) -> None:
            self.log(task_id, message)

        return _log

    def complete(self, task_id: str, result: dict[str, Any] | None = None) -> None:
        task = self.get(task_id)
        if not task:
            return
        with task.lock:
            task.status = TaskStatus.SUCCESS
            task.result = result

    def fail(self, task_id: str, error: str) -> None:
        task = self.get(task_id)
        if not task:
            return
        with task.lock:
            task.status = TaskStatus.FAILED
            task.error = error
            task.logs.append(f"ERROR: {error}")

    def to_dict(self, task_id: str, since: int = 0) -> dict[str, Any] | None:
        task = self.get(task_id)
        if not task:
            return None
        with task.lock:
            return {
                "task_id": task.id,
                "name": task.name,
                "status": task.status.value,
                "logs": task.logs[since:],
                "log_count": len(task.logs),
                "error": task.error,
                "result": task.result,
            }


# Single process-wide instance; tasks are ephemeral and don't need persistence.
task_manager = TaskManager()
