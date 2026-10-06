"""
In-memory task tracking for long-running operations.

Lets API endpoints kick off slow work (venv creation, pip installs, git
clones) in a background thread while the frontend polls for live progress
instead of staring at a frozen spinner.

Tasks can be tied to an app so the UI can show "Installing…" on that app and
the API can refuse to start a second conflicting operation on it. They can
also declare named steps, which the UI renders as a checklist.
"""

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# Finished tasks are kept around this long so a client can still collect the
# result (and a reloaded page can still show what happened), then dropped.
FINISHED_TASK_TTL_SECONDS = 3600


class TaskStatus(str, Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class TaskStep:
    key: str
    label: str
    status: StepStatus = StepStatus.PENDING


@dataclass
class Task:
    id: str
    name: str
    app_id: int | None = None
    status: TaskStatus = TaskStatus.RUNNING
    logs: list[str] = field(default_factory=list)
    steps: list[TaskStep] = field(default_factory=list)
    error: str | None = None
    result: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class TaskConflictError(RuntimeError):
    """Raised when an app already has an operation in progress."""


class TaskManager:
    """Tracks progress of background operations so clients can poll for updates."""

    def __init__(self):
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()

    def create(
        self,
        name: str,
        app_id: int | None = None,
        steps: list[tuple[str, str]] | None = None,
    ) -> Task:
        """Register a new task.

        If app_id is given and that app already has a running task, raises
        TaskConflictError so two operations never fight over the same app.
        """
        task = Task(
            id=str(uuid.uuid4()),
            name=name,
            app_id=app_id,
            steps=[TaskStep(key, label) for key, label in (steps or [])],
        )
        with self._lock:
            self._prune_locked()
            if app_id is not None:
                for existing in self._tasks.values():
                    if existing.app_id == app_id and existing.status == TaskStatus.RUNNING:
                        raise TaskConflictError(
                            f"Another operation is already in progress for this app "
                            f"({existing.name}). Wait for it to finish."
                        )
            self._tasks[task.id] = task
        return task

    def get(self, task_id: str) -> Task | None:
        with self._lock:
            return self._tasks.get(task_id)

    def active_for_app(self, app_id: int) -> Task | None:
        with self._lock:
            for task in self._tasks.values():
                if task.app_id == app_id and task.status == TaskStatus.RUNNING:
                    return task
        return None

    def active_by_app(self) -> dict[int, Task]:
        with self._lock:
            return {
                t.app_id: t
                for t in self._tasks.values()
                if t.app_id is not None and t.status == TaskStatus.RUNNING
            }

    def set_app(self, task_id: str, app_id: int) -> None:
        """Associate a task with an app once the app exists (e.g. after upload)."""
        task = self.get(task_id)
        if task:
            with task.lock:
                task.app_id = app_id

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

    def step(self, task_id: str, key: str, status: StepStatus | str) -> None:
        """Update one step's status. Starting a step finishes the previous running one."""
        task = self.get(task_id)
        if not task:
            return
        status = StepStatus(status)
        with task.lock:
            for step in task.steps:
                if step.key == key:
                    step.status = status
                    if status == StepStatus.RUNNING:
                        task.logs.append(f"── {step.label} ──")
                elif status == StepStatus.RUNNING and step.status == StepStatus.RUNNING:
                    step.status = StepStatus.DONE

    def complete(self, task_id: str, result: dict[str, Any] | None = None) -> None:
        task = self.get(task_id)
        if not task:
            return
        with task.lock:
            for step in task.steps:
                if step.status == StepStatus.RUNNING:
                    step.status = StepStatus.DONE
            task.status = TaskStatus.SUCCESS
            task.result = result
            task.finished_at = time.time()

    def fail(self, task_id: str, error: str) -> None:
        task = self.get(task_id)
        if not task:
            return
        with task.lock:
            for step in task.steps:
                if step.status == StepStatus.RUNNING:
                    step.status = StepStatus.FAILED
            task.status = TaskStatus.FAILED
            task.error = error
            task.logs.append(f"ERROR: {error}")
            task.finished_at = time.time()

    def to_dict(self, task_id: str, since: int = 0) -> dict[str, Any] | None:
        task = self.get(task_id)
        if not task:
            return None
        with task.lock:
            return {
                "task_id": task.id,
                "name": task.name,
                "app_id": task.app_id,
                "status": task.status.value,
                "logs": task.logs[since:],
                "log_count": len(task.logs),
                "steps": [
                    {"key": s.key, "label": s.label, "status": s.status.value} for s in task.steps
                ],
                "error": task.error,
                "result": task.result,
            }

    def _prune_locked(self) -> None:
        cutoff = time.time() - FINISHED_TASK_TTL_SECONDS
        stale = [
            tid
            for tid, t in self._tasks.items()
            if t.finished_at is not None and t.finished_at < cutoff
        ]
        for tid in stale:
            del self._tasks[tid]


def run_task_in_background(task_id: str, work: Callable[[], None], on_error=None) -> None:
    """Run `work` on a daemon thread, marking the task failed on unhandled errors."""

    def _runner():
        try:
            work()
        except Exception as e:  # noqa: BLE001 - surfaced to the user via the task
            if on_error:
                on_error(e)
            task_manager.fail(task_id, str(e))

    threading.Thread(target=_runner, daemon=True, name=f"task-{task_id[:8]}").start()


# Single process-wide instance; tasks are ephemeral and don't need persistence.
task_manager = TaskManager()
