# Development Scripts

This directory contains utility scripts for Mantyx development.

## Available Scripts

### setup-dev.sh

**Purpose:** Complete development environment setup

Sets up everything needed for Mantyx development:

- ✅ Checks Python version (3.10+)
- ✅ Creates/verifies virtual environment
- ✅ Installs all dependencies
- ✅ Installs and configures pre-commit hooks
- ✅ Creates development directories
- ✅ Optionally runs pre-commit on all files
- ✅ Verifies setup with test run

**Usage:**

```bash
./scripts/setup-dev.sh
```

**When to use:**

- First time setting up the project
- After pulling major changes
- When environment seems broken
- Setting up on a new machine

### check-env.sh

**Purpose:** Health check for development environment

Verifies that your development environment is properly configured:

- ✅ Python version check
- ✅ Virtual environment exists and works
- ✅ Mantyx package installed
- ✅ Development tools available (pytest, black, ruff, pre-commit)
- ✅ Pre-commit hooks installed
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
