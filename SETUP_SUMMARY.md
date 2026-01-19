# Development Environment Setup - Summary

## What Was Created

### 1. Setup Script (`scripts/setup-dev.sh`)

Comprehensive environment setup script that:

- ✅ Validates Python 3.10+ installation
- ✅ Creates/verifies virtual environment
- ✅ Installs all dependencies (including dev tools)
- ✅ Installs and configures pre-commit hooks
- ✅ Creates development directory structure
- ✅ Optionally runs pre-commit on all files
- ✅ Runs tests to verify setup
- ✅ Provides clear success/error messages with next steps

**Usage:** `./scripts/setup-dev.sh`

### 2. Environment Check Script (`scripts/check-env.sh`)

Health check script that verifies:

- ✅ Python version (3.10+)
- ✅ Virtual environment exists and works
- ✅ Mantyx package installed
- ✅ Development tools available (pytest, black, ruff, pre-commit)
- ✅ Pre-commit hooks installed in git
- ✅ Development directories present
- ✅ Configuration files exist
- ✅ Tests discoverable
- ✅ Core modules import correctly

**Usage:** `./scripts/check-env.sh`

**Exit Codes:**

- `0` = All checks passed (healthy environment)
- `1` = Some checks failed (issues need fixing)

### 3. VS Code Tasks

Added to `.vscode/tasks.json`:

- **Mantyx: Setup Development Environment** - Runs `setup-dev.sh`
  - Can run on folder open (currently configured)

- **Mantyx: Check Environment** - Runs `check-env.sh`
  - Quick health check before starting work

- **Mantyx: Run Pre-commit** - Runs `pre-commit run --all-files`
  - Check code quality without committing

Access via: `Ctrl+Shift+P` → "Tasks: Run Task"

### 4. Documentation

- `scripts/README.md` - Detailed script documentation
- `scripts/QUICK_REFERENCE.md` - Developer quick reference
- Updated `CONTRIBUTING.md` - Added setup instructions

## Integration with Existing Tools

### Makefile

The scripts complement existing Make targets:

```bash
make dev          # Similar to setup-dev.sh but less verbose
make help         # Show all targets
make pre-commit   # Run pre-commit hooks
```

### Pre-commit Hooks

Setup script ensures pre-commit is:

1. Installed as a Python package
2. Configured in `.pre-commit-config.yaml`
3. Installed as git hooks via `pre-commit install`

## Workflow

### For New Contributors

```bash
# 1. Clone repo
git clone https://github.com/Thulrus/Mantyx.git
cd Mantyx

# 2. Run setup (one command!)
./scripts/setup-dev.sh

# 3. Start developing
make run
```

### For Existing Developers

```bash
# Check environment health
./scripts/check-env.sh

# If issues, re-run setup
./scripts/setup-dev.sh
```

### Daily Development

```bash
# Check environment
./scripts/check-env.sh

# Make changes...

# Check quality before commit
make pre-commit
# or just commit (hooks run automatically)

# Run tests
make test
```

## Benefits

1. **Consistent Setup** - Everyone uses the same setup process
2. **Early Problem Detection** - Health check catches issues before they cause problems
3. **Pre-commit Integration** - Ensures code quality checks happen before push
4. **Clear Feedback** - Colored output shows exactly what's working/broken
5. **VS Code Integration** - One-click access to common tasks
6. **Documentation** - Clear guides for all skill levels

## Files Created/Modified

**New Files:**

- `scripts/setup-dev.sh` - Setup script
- `scripts/check-env.sh` - Health check script
- `scripts/README.md` - Script documentation
- `scripts/QUICK_REFERENCE.md` - Developer quick reference

**Modified Files:**

- `.vscode/tasks.json` - Added setup and check tasks
- `CONTRIBUTING.md` - Added setup instructions

**Existing Files (Leverage):**

- `Makefile` - Already has `dev` target
- `.pre-commit-config.yaml` - Pre-commit configuration
- `pyproject.toml` - Dependency and tool config

## Next Steps for Users

1. **Run Setup:**

   ```bash
   ./scripts/setup-dev.sh
   ```

2. **Verify Health:**

   ```bash
   ./scripts/check-env.sh
   ```

3. **Start Developing:**

   ```bash
   make run
   ```

4. **Before First Commit:**
   - Pre-commit hooks will run automatically
   - Or run manually: `make pre-commit`

## Maintenance

### Updating Dependencies

When `pyproject.toml` changes:

```bash
pip install -e ".[dev]"
# or re-run
./scripts/setup-dev.sh
```

### Updating Pre-commit Hooks

```bash
pre-commit autoupdate
```

### Adding New Checks

Edit `scripts/check-env.sh` to add new validation checks as the project evolves.

## Troubleshooting

All common issues have fixes in the scripts:

- Missing Python → Clear error message with version requirement
- No venv → Script creates it
- Dependencies missing → Script installs them
- Pre-commit not working → Script reinstalls
- Directories missing → Script creates them

The `check-env.sh` script diagnoses issues and suggests fixes.
