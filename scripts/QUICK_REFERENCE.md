# Development Environment Quick Reference

## First Time Setup

```bash
./scripts/setup-dev.sh
```

## Daily Development

### Check Environment Health

```bash
./scripts/check-env.sh
```

### Start Development Server

```bash
make run
# or
python -m mantyx.cli run
```

### Run Tests

```bash
make test
# or
pytest -v
```

### Code Quality

```bash
# Format code
make format

# Run linter
make lint

# Run pre-commit hooks
make pre-commit
# or
pre-commit run --all-files
```

## VS Code Tasks

Access via `Ctrl+Shift+P` → "Tasks: Run Task":

- **Mantyx: Setup Development Environment** - Full environment setup
- **Mantyx: Check Environment** - Health check
- **Mantyx: Run Development Server** - Start server
- **Mantyx: Run Tests** - Execute test suite
- **Mantyx: Run Pre-commit** - Check code quality
- **Mantyx: Format Code** - Auto-format with Black

## Make Targets

```bash
make help          # Show all available targets
make dev           # Install dev dependencies + pre-commit
make run           # Run Mantyx server
make test          # Run tests
make test-cov      # Run tests with coverage
make format        # Format code (black + isort)
make lint          # Run linters (ruff + mypy)
make pre-commit    # Run pre-commit hooks
make clean         # Clean temporary files
```

## Directory Structure

```
Mantyx/
├── scripts/           # Development scripts
│   ├── setup-dev.sh   # Environment setup
│   └── check-env.sh   # Health check
├── src/mantyx/        # Main source code
├── tests/             # Test files
├── examples/          # Example apps
└── dev_data/          # Development data (gitignored)
```

## Troubleshooting

### Environment Issues

```bash
# Check what's wrong
./scripts/check-env.sh

# Reset environment
rm -rf .venv
./scripts/setup-dev.sh
```

### Pre-commit Issues

```bash
# Reinstall hooks
pre-commit uninstall
pre-commit install

# Update hooks to latest
pre-commit autoupdate
```

### Test Issues

```bash
# Run with verbose output
pytest -vv

# Run specific test
pytest tests/test_models.py::test_app_creation
```

## Useful Commands

```bash
# Activate virtual environment
source .venv/bin/activate

# Deactivate virtual environment
deactivate

# View server logs
tail -f dev_data/logs/mantyx.log

# Clear development data
make clean
rm -rf dev_data

# Check Python version
python --version
```

## Configuration Files

- `.pre-commit-config.yaml` - Pre-commit hook configuration
- `pyproject.toml` - Project metadata, ruff, black, pytest config
- `.markdownlintrc` - Markdown linting rules
- `.vscode/tasks.json` - VS Code task definitions

## Getting Help

- Run `make help` for available make targets
- Check [CONTRIBUTING.md](../CONTRIBUTING.md) for contribution guidelines
- Read [scripts/README.md](README.md) for script documentation
- See [.github/PRE_COMMIT_GUIDE.md](../.github/PRE_COMMIT_GUIDE.md) for pre-commit details
