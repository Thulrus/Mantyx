# Contributing to Mantyx

Thank you for your interest in contributing to Mantyx! This document provides guidelines for contributing to the project.

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/yourusername/Mantyx.git`
3. Create a virtual environment: `python -m venv .venv`
4. Activate it: `source .venv/bin/activate` (Linux/Mac) or `.venv\Scripts\activate` (Windows)
5. Install development dependencies: `pip install -e ".[dev]"`
6. Install pre-commit hooks: `pre-commit install`

## Development Workflow

### Setting Up Pre-commit Hooks

We use pre-commit hooks to maintain code quality:

```bash
pip install pre-commit
pre-commit install
```

This will automatically run checks before each commit. You can also run manually:

```bash
pre-commit run --all-files
```

### Code Style

- **Python**: We use Black (100 char lines) and isort
- **Type hints**: Required for all function signatures
- **Docstrings**: Use Google-style docstrings for public APIs
- **Naming**: Follow PEP 8 conventions

### Running the Development Server

```bash
# From project root
python -m mantyx
```

Access the web UI at http://localhost:8420

### Database Migrations

When modifying database models:

```bash
# Create migration
alembic revision --autogenerate -m "Description of changes"

# Apply migration
alembic upgrade head
```

### Testing

```bash
# Run tests (when implemented)
pytest

# With coverage
pytest --cov=mantyx
```

## Pull Request Process

1. Create a feature branch: `git checkout -b feature/your-feature-name`
2. Make your changes
3. Ensure pre-commit hooks pass
4. Test your changes thoroughly
5. Commit with clear, descriptive messages
6. Push to your fork
7. Open a Pull Request with a clear description

### PR Requirements

- [ ] Code passes all pre-commit hooks
- [ ] Changes are tested (manual testing at minimum)
- [ ] Documentation updated if needed
- [ ] PR description clearly explains changes
- [ ] No merge conflicts with main branch

## Code Review

- Be respectful and constructive
- Address all review comments
- Update PR based on feedback
- Request re-review after changes

## Project Structure

```
mantyx/
├── src/mantyx/           # Main application code
│   ├── api/              # FastAPI routes
│   ├── core/             # Core business logic
│   ├── models/           # SQLAlchemy models
│   ├── web/              # Web UI static files
│   └── __main__.py       # Entry point
├── examples/             # Example apps
├── tests/                # Test suite (to be implemented)
├── docs/                 # Documentation
└── pyproject.toml        # Project configuration
```

## Common Development Tasks

### Adding a New API Endpoint

1. Create route handler in appropriate file under `src/mantyx/api/`
2. Define Pydantic schemas in `src/mantyx/api/schemas.py`
3. Add business logic to appropriate manager in `src/mantyx/core/`
4. Update OpenAPI documentation if needed

### Adding a New Database Model

1. Create model in `src/mantyx/models/`
2. Add to `src/mantyx/models/__init__.py`
3. Create migration: `alembic revision --autogenerate -m "Add <model>"`
4. Review and apply migration

### Modifying the Web UI

- HTML: `src/mantyx/web/index.html`
- CSS: `src/mantyx/web/static/css/style.css`
- JS: `src/mantyx/web/static/js/main.js`
- Test changes by reloading the browser (static files are served directly)

## Reporting Bugs

Use the GitHub issue tracker with the bug report template. Include:

- Clear description of the bug
- Steps to reproduce
- Expected vs actual behavior
- Environment details
- Relevant logs/error messages

## Feature Requests

Use the GitHub issue tracker with the feature request template. Include:

- Clear description of the feature
- Use case and problem it solves
- Proposed solution
- Any implementation ideas

## Questions?

- Open a GitHub Discussion
- Check existing issues and documentation
- Review the [README.md](README.md) and [prompt.md](prompt.md)

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
