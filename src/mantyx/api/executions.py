"""
FastAPI routes for executions (runs) and their logs.
"""

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from mantyx.api.schemas import ExecutionResponse
from mantyx.config import get_settings
from mantyx.database import get_db_session
from mantyx.models.execution import Execution, ExecutionStatus

router = APIRouter(prefix="/executions", tags=["executions"])

# Never send more than this much log text in one response.
MAX_LOG_CHUNK_BYTES = 256 * 1024

Stream = Literal["stdout", "stderr"]


def _get_execution(db: Session, execution_id: int) -> Execution:
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="Run not found")
    return execution


def _log_path(execution: Execution, stream: str) -> Path | None:
    raw = execution.stdout_path if stream == "stdout" else execution.stderr_path
    if not raw:
        return None
    path = Path(raw)
    logs_dir = get_settings().logs_dir
    # Only ever serve files from Mantyx's own logs directory.
    try:
        path.resolve().relative_to(logs_dir.resolve())
        return path
    except (ValueError, OSError):
        pass
    # Recorded under an older data directory (e.g. the instance was moved):
    # look for the same file in the current logs directory instead.
    relocated = logs_dir / path.parent.name / path.name
    if path.parent.name and relocated.exists():
        return relocated
    return None


def read_log_chunk(path: Path | None, offset: int, max_bytes: int = MAX_LOG_CHUNK_BYTES) -> dict:
    """Read part of a log file.

    offset < 0 means "the last max_bytes of the file" (initial view). Otherwise
    reading starts at `offset`; if the file shrank (rotated) it restarts at 0.
    """
    if path is None or not path.exists():
        return {"output": "", "offset": 0, "size": 0, "truncated": False, "reset": False}

    size = path.stat().st_size
    reset = False
    if offset < 0:
        start = max(0, size - max_bytes)
    elif offset > size:
        start, reset = 0, True
    else:
        start = offset
    end = min(size, start + max_bytes)

    with path.open("rb") as f:
        f.seek(start)
        data = f.read(end - start)

    text = data.decode("utf-8", errors="replace")
    return {
        "output": text,
        "offset": end,
        "size": size,
        "truncated": start > 0 and offset < 0,
        "reset": reset,
    }


@router.get("", response_model=list[ExecutionResponse])
def list_executions(
    app_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db_session),
):
    """List executions, optionally filtered by app."""
    query = db.query(Execution).order_by(Execution.id.desc())

    if app_id:
        query = query.filter(Execution.app_id == app_id)

    return query.offset(max(offset, 0)).limit(min(max(limit, 1), 500)).all()


@router.get("/{execution_id}", response_model=ExecutionResponse)
def get_execution(
    execution_id: int,
    db: Session = Depends(get_db_session),
):
    """Get a specific execution."""
    return _get_execution(db, execution_id)


@router.get("/{execution_id}/log")
def get_execution_log(
    execution_id: int,
    stream: Stream = "stdout",
    offset: int = -1,
    db: Session = Depends(get_db_session),
):
    """Read a run's output incrementally.

    Call first with offset=-1 for the tail of the log, then keep passing the
    returned `offset` to receive only new output (for live following).
    """
    execution = _get_execution(db, execution_id)
    chunk = read_log_chunk(_log_path(execution, stream), offset)
    chunk["running"] = execution.status in (ExecutionStatus.RUNNING, ExecutionStatus.PENDING)
    return chunk


@router.get("/{execution_id}/log/raw")
def download_execution_log(
    execution_id: int,
    stream: Stream = "stdout",
    db: Session = Depends(get_db_session),
):
    """The full log file as plain text."""
    execution = _get_execution(db, execution_id)
    path = _log_path(execution, stream)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="No log file for this run")
    return FileResponse(
        path,
        media_type="text/plain; charset=utf-8",
        filename=f"run-{execution_id}-{stream}.log",
        content_disposition_type="inline",
    )


@router.post("/{execution_id}/cancel")
def cancel_execution(execution_id: int, db: Session = Depends(get_db_session)):
    """Stop a scheduled app's run that is in progress."""
    from mantyx.core.scheduler import cancel_execution as cancel

    execution = _get_execution(db, execution_id)
    if execution.status not in (ExecutionStatus.RUNNING, ExecutionStatus.PENDING):
        raise HTTPException(status_code=400, detail="This run has already finished")
    if not cancel(execution_id):
        raise HTTPException(
            status_code=400,
            detail="Only scheduled runs can be cancelled; stop always-running apps instead",
        )
    return {"message": "Cancelling run"}


# Backward-compatible endpoints (bounded to the tail of the file).
@router.get("/{execution_id}/stdout")
def get_execution_stdout(execution_id: int, db: Session = Depends(get_db_session)):
    """Get the (tail of the) stdout output of an execution."""
    execution = _get_execution(db, execution_id)
    return {"output": read_log_chunk(_log_path(execution, "stdout"), -1)["output"]}


@router.get("/{execution_id}/stderr")
def get_execution_stderr(execution_id: int, db: Session = Depends(get_db_session)):
    """Get the (tail of the) stderr output of an execution."""
    execution = _get_execution(db, execution_id)
    return {"output": read_log_chunk(_log_path(execution, "stderr"), -1)["output"]}
