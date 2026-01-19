# Pre-commit Setup Guide

This project uses [pre-commit](https://pre-commit.com/) hooks to automatically check code quality before commits.

## Installation

### 1. Install pre-commit (if not already installed)

```bash
pip install pre-commit
```

Or if using the project virtual environment:

```bash
.venv/bin/pip install pre-commit
```

### 2. Install the git hooks

```bash
pre-commit install
```

This will configure git to run the hooks automatically before each commit.

## Usage

### Automatic (Recommended)

Once installed, pre-commit will run automatically when you try to commit:

```bash
git add .
git commit -m "Your commit message"
# Pre-commit hooks will run automatically
```

If any hooks fail, the commit will be blocked and files may be auto-fixed. Review the changes and commit again.

### Manual

Run all hooks on all files:

```bash
pre-commit run --all-files
```

Run specific hook:

```bash
pre-commit run black --all-files
pre-commit run ruff --all-files
```

Run hooks on staged files only:

```bash
pre-commit run
```

## Configured Hooks

### Code Quality

- **trailing-whitespace**: Removes trailing whitespace
- **end-of-file-fixer**: Ensures files end with a newline
- **black**: Code formatter (100 char line length)
- **isort**: Import sorter (Black-compatible)
- **ruff**: Fast Python linter (replaces flake8)
- **ruff-format**: Additional formatting via Ruff

### File Checks

- **check-yaml**: Validates YAML syntax
- **check-toml**: Validates TOML syntax
- **check-json**: Validates JSON syntax
- **check-added-large-files**: Prevents large files (>500KB)
- **check-merge-conflict**: Detects merge conflict markers
- **check-case-conflict**: Prevents case-conflicting filenames
- **mixed-line-ending**: Ensures consistent line endings (LF)
- **detect-private-key**: Prevents committing private keys

### Security

- **bandit**: Security linter for Python code

### Documentation

- **markdownlint**: Markdown linter and formatter

## Ignoring Specific Errors

### Ruff

Current ignores (in `pyproject.toml`):

- `E501`: Line too long (handled by formatter)
- `B008`: Function calls in defaults (required for FastAPI Depends pattern)

To add more ignores, edit `pyproject.toml`:

```toml
[tool.ruff.lint]
ignore = [
    "E501",
    "B008",
    "YOUR_CODE_HERE",
]
```

### Markdownlint

Configured in `.markdownlintrc` to allow:

- Long lines (MD013)
- Inline HTML (MD033)
- Code blocks without language (MD040)
- Duplicate headings in siblings (MD024)

## Updating Hooks

Update all hooks to latest versions:

```bash
pre-commit autoupdate
```

## Skipping Hooks (Emergency Only)

To skip pre-commit hooks for a single commit (not recommended):

```bash
git commit --no-verify -m "Emergency commit"
```

## Troubleshooting

### Hooks not running

```bash
# Reinstall hooks
pre-commit uninstall
pre-commit install
```

### Cache issues

```bash
# Clear pre-commit cache
pre-commit clean
```

### Hook taking too long

You can temporarily disable specific hooks in `.pre-commit-config.yaml` by commenting them out:

```yaml
# - repo: https://github.com/PyCQA/bandit
#   rev: 1.7.7
#   hooks:
#     - id: bandit
```

## CI/CD Integration

These same checks run in GitHub Actions CI/CD. Commits that pass pre-commit locally will pass CI checks.

## More Information

- [Pre-commit documentation](https://pre-commit.com/)
- [Ruff documentation](https://docs.astral.sh/ruff/)
- [Black documentation](https://black.readthedocs.io/)
