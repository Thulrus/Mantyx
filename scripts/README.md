# Development Scripts

This directory contains utility scripts for Mantyx development.

## Available Scripts

### setup-dev.sh

**Purpose:** Set up the development environment, or repair it if anything is wrong

Runs automatically when the folder is opened in VS Code (task "Mantyx: Setup
Development Environment") and is safe to run any time:

- ✅ Checks Python version (3.10+)
- ✅ Checks `.venv` health and **rebuilds it automatically** if it's broken
- ✅ Installs all dependencies
- ✅ Installs pre-commit hooks (rewriting a stale git hook if needed)
- ✅ Creates development directories
- ✅ Verifies setup with a test run

A `.venv` counts as broken when:

- `bin/python` points at a Python that no longer exists, or at a different
  version than the venv was built for (e.g. after an OS upgrade from 3.12 to 3.14)
- the venv or project directory was moved, so `bin/pip` and other console
  scripts point at the old location
- pip doesn't work inside it

**Usage:**

```bash
./scripts/setup-dev.sh               # set up / repair
./scripts/setup-dev.sh --recreate    # rebuild .venv from scratch regardless
./scripts/setup-dev.sh --all-hooks   # also run every pre-commit hook on all files
PYTHON=python3.12 ./scripts/setup-dev.sh --recreate   # build with a specific Python
```

The VS Code task "Mantyx: Rebuild Development Environment (from scratch)" runs
it with `--recreate`.

**When to use:**

- First time setting up the project
- After pulling major changes
- When environment seems broken (including after an OS Python upgrade)
- Setting up on a new machine

### check-env.sh

**Purpose:** Health check for development environment

Verifies that your development environment is properly configured:

- ✅ Python version check
- ✅ Virtual environment is healthy (same checks setup-dev.sh uses)
- ✅ Mantyx package installed
- ✅ Development tools available (pytest, black, ruff, pre-commit)
- ✅ Pre-commit hooks installed and pointing at this venv
- ✅ Development directories present
- ✅ Configuration files exist
- ✅ Tests discoverable
- ✅ Core modules import correctly

**Usage:**

```bash
./scripts/check-env.sh
```

**When to use:**

- Before starting development work
- Troubleshooting environment issues
- After dependency updates
- In CI/CD pipelines

**Exit codes:**

- `0` - All checks passed
- `1` - Some checks failed

## VS Code Integration

These scripts are integrated as VS Code tasks. Run them via:

1. **Command Palette** (`Ctrl+Shift+P` or `Cmd+Shift+P`)
2. Type: "Tasks: Run Task"
3. Select:
   - "Mantyx: Setup Development Environment"
   - "Mantyx: Check Environment"

Or use the keyboard shortcut for tasks: `Ctrl+Shift+B` (or `Cmd+Shift+B`)

## Automation

### First-time Setup

The setup script can be run automatically when opening the workspace by uncommenting the `runOptions` in `.vscode/tasks.json`:

```jsonc
"runOptions": {
    "runOn": "folderOpen"
}
```

### Pre-commit Integration

Both scripts ensure pre-commit hooks are properly installed and configured. The setup script will:

1. Install pre-commit package
2. Run `pre-commit install` to add git hooks
3. Optionally run all hooks on existing files

## Troubleshooting

### Permission denied

Make scripts executable:

```bash
chmod +x scripts/*.sh
```

### Python not found

Ensure Python 3.10+ is installed and in your PATH:

```bash
python3 --version
```

### Virtual environment issues

Delete and recreate:

```bash
rm -rf .venv
./scripts/setup-dev.sh
```

### Pre-commit not working

Reinstall hooks:

```bash
pre-commit uninstall
pre-commit install
```

## Alternative: Using Make

You can also use Make targets for similar functionality:

```bash
make dev          # Install dev dependencies + pre-commit
make help         # Show all available targets
```

The scripts provide more detailed output and checks than Make targets.
