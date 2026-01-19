# Testing Guide

This directory contains tests for the Mantyx application orchestration framework.

## Running Tests

### Run all tests

```bash
pytest
```

### Run with coverage

```bash
pytest --cov=mantyx --cov-report=term-missing
```

### Run specific test file

```bash
pytest tests/test_models.py
```

### Run specific test

```bash
pytest tests/test_models.py::test_app_creation
```

## Test Structure

- `conftest.py` - Pytest configuration and shared fixtures
- `test_models.py` - Tests for database models
- (More test files to be added)

## Fixtures

### `temp_dir`

Creates a temporary directory for tests that is automatically cleaned up.

### `test_db`

Creates a test SQLite database with all tables created.

### `db_session`

Provides a database session for a single test.

## Writing Tests

When adding new tests:

1. Import the necessary models and fixtures
2. Use the `db_session` fixture for database tests
3. Use descriptive test names starting with `test_`
4. Add docstrings to explain what the test does
5. Clean up any resources created during the test

Example:

```python
def test_my_feature(db_session):
    """Test that my feature works correctly."""
    # Arrange
    app = App(name="Test", ...)

    # Act
    db_session.add(app)
    db_session.commit()

    # Assert
    assert app.id is not None
```

## Coverage

Tests aim to cover:

- Model creation and relationships
- State transitions
- Soft delete functionality
- API endpoints
- Core business logic

Current coverage can be viewed in the CI/CD pipeline or by running:

```bash
pytest --cov=mantyx --cov-report=html
```

Then open `htmlcov/index.html` in a browser.
