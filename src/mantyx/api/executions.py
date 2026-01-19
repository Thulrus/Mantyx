"""
FastAPI routes for executions.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from mantyx.api.schemas import ExecutionResponse
from mantyx.database import get_db_session
from mantyx.models.execution import Execution

router = APIRouter(prefix="/executions", tags=["executions"])


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

    executions = query.offset(offset).limit(limit).all()
    return executions


@router.get("/{execution_id}", response_model=ExecutionResponse)
def get_execution(
    execution_id: int,
    db: Session = Depends(get_db_session),
):
    """Get a specific execution."""
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    return execution


@router.get("/{execution_id}/stdout")
def get_execution_stdout(
    execution_id: int,
    db: Session = Depends(get_db_session),
):
    """Get the stdout output of an execution."""
    from pathlib import Path

    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")

    if not execution.stdout_path:
        return {"output": ""}

    try:
        stdout_path = Path(execution.stdout_path)
        if stdout_path.exists():
            return {"output": stdout_path.read_text()}
        return {"output": ""}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read stdout: {e}")


@router.get("/{execution_id}/stderr")
def get_execution_stderr(
    execution_id: int,
    db: Session = Depends(get_db_session),
):
    """Get the stderr output of an execution."""
    from pathlib import Path

    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")

    if not execution.stderr_path:
        return {"output": ""}

    try:
        stderr_path = Path(execution.stderr_path)
        if stderr_path.exists():
            return {"output": stderr_path.read_text()}
        return {"output": ""}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read stderr: {e}")
