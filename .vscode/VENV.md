# Virtual Environment Setup

## Overview

This project uses a Python virtual environment (`.venv`) to isolate dependencies from the system Python installation.

## Status

✅ Virtual environment is set up and configured  
✅ All dependencies installed  
✅ VS Code configured to use `.venv`  
✅ Tasks and debug configurations updated

## Using the Virtual Environment

### Automatic Activation

VS Code will automatically use the `.venv` interpreter when:

- Running tasks (Ctrl+Shift+B)
- Debugging (F5)
- Using the integrated terminal (if `python.terminal.activateEnvironment` is enabled)

### Manual Activation

If you need to activate the venv manually in a terminal:

```bash
# Linux/macOS
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

### Running Commands

#### With VS Code Tasks (Recommended)

- **Run Server**: Press `Ctrl+Shift+B` or select "Mantyx: Run Development Server"
- **Run Tests**: `Ctrl+Shift+T` or "Mantyx: Run Tests"
- **Debug**: Press `F5` to start debugging

#### Direct Command Execution

```bash
# Using absolute path (works from any directory)
/home/geoff/Ghowe/Documents/Mantyx/.venv/bin/python -m mantyx.cli run

# Using workspace variable (works in VS Code tasks)
${workspaceFolder}/.venv/bin/python -m mantyx.cli run

# After activating venv (works in terminal)
python -m mantyx.cli run
```

## Installed Packages

### Core Dependencies

- fastapi>=0.109.0 - Web framework
- uvicorn>=0.27.0 - ASGI server
- sqlalchemy>=2.0.0 - ORM
- alembic>=1.13.0 - Database migrations
- apscheduler>=3.10.0 - Job scheduling
- pydantic>=2.5.0 - Data validation
- pydantic-settings>=2.1.0 - Settings management
- python-multipart>=0.0.6 - File uploads
- aiofiles>=23.2.0 - Async file operations
- psutil>=5.9.0 - Process management
- pyyaml>=6.0.0 - YAML parsing
- gitpython>=3.1.0 - Git integration
- jinja2>=3.1.0 - Templating
- httpx>=0.26.0 - HTTP client

### Development Dependencies

- pytest>=7.4.0 - Testing framework
- pytest-asyncio>=0.23.0 - Async test support
- pytest-cov>=4.1.0 - Coverage reporting
- black>=23.12.0 - Code formatting
- ruff>=0.1.0 - Linting
- mypy>=1.8.0 - Type checking

## Managing Dependencies

### Installing Additional Packages

```bash
.venv/bin/pip install package-name
```

### Updating pyproject.toml

After installing new packages, add them to `pyproject.toml`:

```toml
[project]
dependencies = [
    "new-package>=1.0.0",
]
```

### Reinstalling All Dependencies

```bash
.venv/bin/pip install -e .[dev]
```

Or use the VS Code task: "Mantyx: Install Dev Dependencies"

## Troubleshooting

### "ModuleNotFoundError: No module named 'mantyx'"

**Solution**: The package needs to be installed in editable mode:

```bash
.venv/bin/pip install -e .[dev]
```

Or use the task: "Mantyx: Install Dev Dependencies"

### VS Code Not Using .venv

**Solution**:

1. Open Command Palette (Ctrl+Shift+P)
2. Type "Python: Select Interpreter"
3. Choose `.venv/bin/python`

### Packages Installing to System Python

**Solution**: Always use `.venv/bin/pip` instead of just `pip`, or ensure venv is activated first.

### Tasks Failing with "Command not found"

**Solution**: All tasks are configured to use absolute paths to venv executables. If you see this error:

1. Check that `.venv` exists: `ls -la .venv/bin/`
2. Reinstall dependencies: `.venv/bin/pip install -e .[dev]`

## VS Code Configuration

### settings.json

- Python interpreter: `${workspaceFolder}/.venv/bin/python`
- Auto-activation enabled for terminals
- File exclusions: `.venv` hidden from explorer

### tasks.json

All tasks use absolute paths:

- `${workspaceFolder}/.venv/bin/python`
- `${workspaceFolder}/.venv/bin/pip`
- `${workspaceFolder}/.venv/bin/pytest`
- `${workspaceFolder}/.venv/bin/black`
- `${workspaceFolder}/.venv/bin/ruff`
- `${workspaceFolder}/.venv/bin/mypy`

### launch.json

All debug configurations specify:

```json
"python": "${workspaceFolder}/.venv/bin/python"
```

## Best Practices

1. **Never commit .venv** - It's in `.gitignore`
2. **Always use venv pip** - Prevents system pollution
3. **Use VS Code tasks** - Ensures correct environment
4. **Update pyproject.toml** - Keep dependencies documented
5. **Reinstall after pulling** - Run "Mantyx: Install Dev Dependencies" after git pull

## Quick Commands

```bash
# Create new venv (already done)
python3 -m venv .venv

# Install dependencies
.venv/bin/pip install -e .[dev]

# Activate for manual use
source .venv/bin/activate

# Deactivate
deactivate

# List installed packages
.venv/bin/pip list

# Check Python version
.venv/bin/python --version

# Run mantyx
.venv/bin/python -m mantyx.cli run
```
