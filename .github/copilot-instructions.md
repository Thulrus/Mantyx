# GitHub Copilot Instructions for Mantyx

## Project Overview

Mantyx is a single-node Python application orchestration framework designed for trusted home servers. It manages multiple independent Python applications with dependency isolation, process supervision, scheduling, and health monitoring.

## Architecture Principles

- **Single-node, non-SaaS**: Internal developer control plane, not multi-tenant
- **Immutable app units**: Apps are versioned, never modified in-place
- **Process isolation**: App code never executes inside orchestrator process
- **Explicit state management**: All state transitions must be clear and reversible
- **Web UI first**: Primary control surface for all operations

## Code Style Guidelines

### Python Style

- Use Black formatter with 100 character line length
- Use isort with Black profile for import sorting
- Type hints are required for all function signatures
- Use SQLAlchemy 2.0 style (mapped_column, Mapped types)
- Async/await for I/O operations where appropriate

### Naming Conventions

- Classes: `PascalCase` (e.g., `AppManager`, `AppScheduler`)
- Functions/methods: `snake_case` (e.g., `create_app_from_zip`, `get_app_status`)
- Constants: `UPPER_SNAKE_CASE` (e.g., `DEFAULT_PORT`, `MAX_RESTARTS`)
- Private methods: prefix with `_` (e.g., `_validate_upload`, `_get_app_dir`)

### Database

- Use SQLAlchemy ORM with context managers: `with get_db() as session:`
- Always commit/refresh within the same session scope
- Never return ORM objects across session boundaries (return dicts or extract values)
- Use proper session lifecycle management to avoid DetachedInstanceError

### API Design

- FastAPI with dependency injection for session management
- Use Pydantic models for request/response validation
- Return proper HTTP status codes (400 for validation, 404 for not found, 500 for server errors)
- All destructive operations require explicit confirmation
- Form data for file uploads, JSON for other operations

### Error Handling

- Catch specific exceptions before generic ones
- Return JSON error responses, never HTML errors
- Log errors with context (app_id, operation, etc.)
- Rollback failed operations when possible

## Key Components

### Core Modules

- `app_manager.py`: App lifecycle (upload, install, delete, update)
- `process_manager.py`: Process supervision for perpetual apps
- `scheduler.py`: APScheduler integration for scheduled apps
- `dependency_manager.py`: Virtual environment and pip management

### Models

- `App`: Application metadata and state
- `AppType`: Enum - PERPETUAL or SCHEDULED
- `AppState`: Enum - UPLOADED, INSTALLED, ENABLED, RUNNING, STOPPED, FAILED, DELETED
- `Schedule`: Cron and interval-based scheduling configuration
- `Execution`: Historical execution records

### API Structure

- `/api/apps/*`: App management endpoints
- `/api/schedules/*`: Schedule management for scheduled apps
- `/api/executions/*`: Execution history and logs
- Web UI served from `/` and `/static/`

## Common Patterns

### Creating Apps

1. Validate upload (file size, structure, no path traversal)
2. Extract to app-specific directory
3. Detect entrypoint (main.py, app.py, etc.)
4. Create database record
5. Return dict with {id, name} to avoid session issues

### Session Management

```python
# Always use context managers
with get_db() as session:
    app = session.query(App).filter(App.id == app_id).first()
    session.commit()
    # Extract values before session closes
    app_id = app.id
    app_name = app.name

# Return simple dicts, not ORM objects
return {"id": app_id, "name": app_name}
```

### State Transitions

- UPLOADED → INSTALLED (after dependency installation)
- INSTALLED → ENABLED (user enables app)
- ENABLED → RUNNING (process starts successfully)
- RUNNING → STOPPED (process stopped cleanly)
- RUNNING → FAILED (process crashed)

## Testing Considerations

- Test apps are in `examples/` directory
- Development data in `dev_data/` (git-ignored)
- Database: SQLite for simplicity, supports other backends
- Use pytest for testing (when implemented)

## Security Notes

- No authentication (trusted home server environment)
- Validate all file uploads for path traversal
- Sandbox app execution (separate processes, virtual envs)
- No privilege escalation
- Apps run as same user as orchestrator

## When Making Changes

1. Consider state consistency (file system + database + process state)
2. Make operations idempotent where possible
3. Provide clear error messages for user-facing operations
4. Update both ZIP and Git upload paths for feature parity
5. Maintain backwards compatibility with existing database schema
6. Test with the hello-world example app

## Common Issues to Avoid

- Don't access ORM object attributes after session closes
- Don't forget to update both upload endpoints (ZIP and Git)
- Don't hardcode paths - use config/settings
- Don't mix sync and async operations incorrectly
- Don't forget to handle deleted apps (is_deleted flag)
- Always clean up temporary files after upload operations
