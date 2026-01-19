#!/usr/bin/env bash
# Environment Health Check Script for Mantyx
# Verifies that the development environment is properly configured

# Note: Don't use set -e because we want to run all checks

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
log_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

log_success() {
    echo -e "${GREEN}✓${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1"
}

# Get project root directory (parent of scripts directory)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo "╔════════════════════════════════════════════════════════════╗"
echo "║     Mantyx Environment Health Check                       ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

CHECKS_PASSED=0
CHECKS_FAILED=0

# Check 1: Python version
echo "Checking Python version..."
if ! command -v python3 &> /dev/null; then
    log_error "Python 3 not found"
    ((CHECKS_FAILED++))
else
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
    PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
    PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

    if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]); then
        log_error "Python 3.10+ required, found $PYTHON_VERSION"
        ((CHECKS_FAILED++))
    else
        log_success "Python $PYTHON_VERSION"
        ((CHECKS_PASSED++))
    fi
fi

# Check 2: Virtual environment
echo "Checking virtual environment..."
if [ ! -d ".venv" ]; then
    log_error "Virtual environment not found. Run: ./scripts/setup-dev.sh"
    ((CHECKS_FAILED++))
else
    log_success "Virtual environment exists"
    ((CHECKS_PASSED++))
fi

# Check 3: Virtual environment activation
echo "Checking if virtual environment can be activated..."
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
    log_success "Virtual environment activated"
    ((CHECKS_PASSED++))
else
    log_error "Cannot activate virtual environment"
    ((CHECKS_FAILED++))
fi

# Check 4: Mantyx package installed
echo "Checking Mantyx installation..."
if python3 -c "import mantyx" 2>/dev/null; then
    MANTYX_VERSION=$(python3 -c "import mantyx; print(getattr(mantyx, '__version__', '0.1.0'))")
    log_success "Mantyx installed (version $MANTYX_VERSION)"
    ((CHECKS_PASSED++))
else
    log_error "Mantyx not installed. Run: pip install -e '.[dev]'"
    ((CHECKS_FAILED++))
fi

# Check 5: Development dependencies
echo "Checking development dependencies..."
MISSING_DEPS=()

for dep in pytest black ruff pre-commit; do
    if ! command -v $dep &> /dev/null; then
        MISSING_DEPS+=($dep)
    fi
done

if [ ${#MISSING_DEPS[@]} -eq 0 ]; then
    log_success "All development tools installed"
    ((CHECKS_PASSED++))
else
    log_error "Missing tools: ${MISSING_DEPS[*]}"
    log_info "Run: pip install -e '.[dev]'"
    ((CHECKS_FAILED++))
fi

# Check 6: Pre-commit hooks installed
echo "Checking pre-commit hooks..."
if [ -f ".git/hooks/pre-commit" ] && grep -q "pre-commit" .git/hooks/pre-commit 2>/dev/null; then
    log_success "Pre-commit hooks installed"
    ((CHECKS_PASSED++))
else
    log_warning "Pre-commit hooks not installed"
    log_info "Run: pre-commit install"
    ((CHECKS_FAILED++))
fi

# Check 7: Development directories
echo "Checking development directories..."
if [ -d "dev_data" ]; then
    log_success "Development data directory exists"
    ((CHECKS_PASSED++))
else
    log_warning "Development data directory missing"
    log_info "Creating: mkdir -p dev_data/{apps,backups,config,data,logs,temp,venvs}"
    ((CHECKS_FAILED++))
fi

# Check 8: Configuration files
echo "Checking configuration files..."
MISSING_CONFIGS=()

for config in pyproject.toml .pre-commit-config.yaml .gitignore; do
    if [ ! -f "$config" ]; then
        MISSING_CONFIGS+=($config)
    fi
done

if [ ${#MISSING_CONFIGS[@]} -eq 0 ]; then
    log_success "All configuration files present"
    ((CHECKS_PASSED++))
else
    log_error "Missing configs: ${MISSING_CONFIGS[*]}"
    ((CHECKS_FAILED++))
fi

# Check 9: Test discovery
echo "Checking test discovery..."
if [ -d "tests" ] && ls tests/test_*.py &> /dev/null; then
    TEST_COUNT=$(find tests -name "test_*.py" | wc -l)
    log_success "Found $TEST_COUNT test file(s)"
    ((CHECKS_PASSED++))
else
    log_warning "No test files found in tests/"
    ((CHECKS_FAILED++))
fi

# Check 10: Quick import test
echo "Checking core module imports..."
if python3 -c "from mantyx.config import get_settings; from mantyx.database import init_db" 2>/dev/null; then
    log_success "Core modules import successfully"
    ((CHECKS_PASSED++))
else
    log_error "Failed to import core modules"
    ((CHECKS_FAILED++))
fi

# Summary
echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║     Results                                                ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "Checks passed: ${GREEN}$CHECKS_PASSED${NC}"
echo "Checks failed: ${RED}$CHECKS_FAILED${NC}"
echo ""

if [ $CHECKS_FAILED -eq 0 ]; then
    log_success "Environment is healthy! ✨"
    echo ""
    echo "You're ready to develop! Try:"
    echo "  ${BLUE}make run${NC}           - Start development server"
    echo "  ${BLUE}make test${NC}          - Run tests"
    echo "  ${BLUE}make format${NC}        - Format code"
    exit 0
else
    log_warning "Some checks failed. Please address the issues above."
    echo ""
    echo "Quick fixes:"
    echo "  ${BLUE}./scripts/setup-dev.sh${NC}  - Run full setup"
    echo "  ${BLUE}make dev${NC}                - Install dev dependencies"
    echo "  ${BLUE}pre-commit install${NC}      - Install git hooks"
    exit 1
fi
