# Mantyx VS Code Tasks

This document describes all available VS Code tasks for the Mantyx project.

## Running Tasks

- Press `Ctrl+Shift+B` (or `Cmd+Shift+B` on Mac) to run the default build task
- Press `Ctrl+Shift+P` and type "Run Task" to see all available tasks
- Press `F5` to start debugging with the default configuration

---

## Development Tasks

### 🚀 Mantyx: Run Development Server (Default Build)

Starts the Mantyx server in development mode with debug enabled.

- **Shortcut**: `Ctrl+Shift+B`
- **Environment**: Development mode, local data directory
- **Port**: 8420
- **Auto-reload**: Enabled

### 🔧 Mantyx: Check Configuration

Displays current Mantyx configuration without starting the server.

### 🌐 Mantyx: Open Web Interface

Opens the Mantyx web interface in your default browser.

- **URL**: <http://localhost:8420>

### 📖 Mantyx: Open API Docs

Opens the interactive API documentation.

- **URL**: <http://localhost:8420/docs>

### 🏥 Mantyx: Test API Health

Checks if the Mantyx API is responding.

- **Endpoint**: /health

---

## Installation Tasks

### � Mantyx: Create Virtual Environment

Creates a new `.venv` virtual environment for the project.

```bash
python3 -m venv .venv
```

**Note**: Run this first when setting up a new clone or if .venv doesn't exist.

### 🔄 Mantyx: Recreate Virtual Environment

Deletes and recreates the virtual environment from scratch.

```bash
rm -rf .venv && python3 -m venv .venv
```

**Warning**: You'll need to reinstall dependencies after this.

### 📦 Mantyx: Install Dependencies

Installs Mantyx in editable mode with all runtime dependencies.

```bash
.venv/bin/pip install -e .
```

### 🛠️ Mantyx: Install Dev Dependencies

Installs Mantyx with development dependencies (pytest, black, ruff, mypy).

```bash
.venv/bin/pip install -e .[dev]
```

### ⚡ Mantyx: Setup Development Environment

Composite task that:

1. Creates virtual environment (if needed)
2. Installs all dev dependencies
3. Cleans dev data directory

**Use this for first-time setup or fresh environment!**

---

## Code Quality Tasks

### 🎨 Mantyx: Format Code (Black)

Formats all Python code using Black formatter.

- **Line length**: 100 characters

### 🔍 Mantyx: Lint Code (Ruff)

Runs Ruff linter on the codebase.

### 🔬 Mantyx: Type Check (MyPy)

Runs MyPy type checker on the source code.

### ✅ Mantyx: Full Quality Check

Composite task that runs:

1. Black formatter
2. Ruff linter
3. MyPy type checker
4. All tests

---

## Testing Tasks

### 🧪 Mantyx: Run Tests (Default Test)

Runs all tests with pytest.

- **Shortcut**: `Ctrl+Shift+T` (when in test file)

### 📊 Mantyx: Run Tests with Coverage

Runs tests and generates coverage report.

- **Output**: HTML coverage report + terminal output

---

## Example Apps

### 📦 Mantyx: Package Hello World Example

Creates a ZIP file of the hello-world example app.

- **Output**: `hello-world.zip`

### 📦 Mantyx: Package Scheduled Report Example

Creates a ZIP file of the scheduled-report example app.

- **Output**: `scheduled-report.zip`

---

## Production Tasks

### 🚀 Mantyx: Run Production Server

Starts Mantyx in production mode (debug disabled).

- **Data directory**: /srv/mantyx
- **Debug**: Disabled

### 📦 Mantyx: Build Distribution

Creates distribution packages (wheel and source).

```bash
python -m build
```

### 🔧 Mantyx: Install Systemd Service

Installs Mantyx as a systemd service (requires sudo).

- **Service file**: /etc/systemd/system/mantyx.service

### 📊 Mantyx: View Service Status

Shows systemd service status.

### 📜 Mantyx: View Service Logs

Follows systemd journal logs for Mantyx service.

---

## Utility Tasks

### 🧹 Mantyx: Clean Dev Data

Removes the development data directory.

- **Warning**: This will delete all dev apps, logs, and database!

### 📋 Mantyx: View Dev Logs

Lists all log files in the development logs directory.

### 📡 Mantyx: List Apps (API)

Fetches and displays all apps via the API.

---

## Composite Tasks

### 🚀 Mantyx: Quick Start

Complete setup and launch:

1. Setup development environment
2. Start development server
3. Open web interface

---

## Debug Configurations

### 🐛 Mantyx: Run Server (Debug)

Debugs the Mantyx server with breakpoint support.

- **Shortcut**: `F5`
- **Just My Code**: Disabled (debug into libraries)

### 🐛 Mantyx: Run Server (Production Mode)

Debugs in production mode configuration.

### 🐛 Python: Current File

Debugs the currently open Python file.

### 🐛 Mantyx: Test App Manager

Debugs specific test file.

### 🐛 Mantyx: Run Example Hello World

Debugs the hello-world example app.

### 🐛 Mantyx: Run Example Scheduled Report

Debugs the scheduled-report example app.

---

## Quick Reference

| Task           | Shortcut       | Purpose                          |
| -------------- | -------------- | -------------------------------- |
| Run Dev Server | `Ctrl+Shift+B` | Start development server         |
| Debug Server   | `F5`           | Debug with breakpoints           |
| Run Tests      | -              | Execute all tests                |
| Format Code    | -              | Format with Black                |
| Open Web UI    | -              | Launch browser to localhost:8420 |

---

## Environment Variables

Tasks automatically set these environment variables:

```bash
MANTYX_BASE_DIR=./dev_data  # Development data directory
MANTYX_DEBUG=true           # Enable debug mode
MANTYX_PORT=8420            # Server port
```

Override in `.vscode/settings.json` or create `.env` file for persistent settings.

---

## Tips

1. **First Time Setup**: Run "Mantyx: Quick Start" to set everything up
2. **Development Loop**: Use "Mantyx: Full Quality Check" before commits
3. **Testing Apps**: Package examples and upload via web interface
4. **Debugging**: Use F5 to debug with breakpoints in VS Code
5. **Production**: Use systemd tasks for production deployment

---

**For more information, see:**

- [README.md](../README.md) - Full documentation
- [QUICKSTART.md](../QUICKSTART.md) - Getting started guide
- [IMPLEMENTATION.md](../IMPLEMENTATION.md) - Technical details
