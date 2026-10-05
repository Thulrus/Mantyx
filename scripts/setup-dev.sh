#!/usr/bin/env bash
# Development Environment Setup Script for Mantyx
# This script sets up the complete development environment

set -e  # Exit on error

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

usage() {
    cat <<EOF
Usage: $0 [--recreate] [--all-hooks]

Sets up the development environment, and repairs it if something is wrong.
Safe to run any time; it only rebuilds what needs rebuilding.

  --recreate    Delete and recreate .venv even if it looks healthy
  --all-hooks   Also run every pre-commit hook on all files (slow)

Environment:
  PYTHON        Interpreter to build the venv with (default: python3)
EOF
}

RECREATE=false
RUN_ALL_HOOKS=false
for arg in "$@"; do
    case "$arg" in
        --recreate) RECREATE=true ;;
        --all-hooks) RUN_ALL_HOOKS=true ;;
        -h|--help) usage; exit 0 ;;
        *) log_error "Unknown option: $arg"; usage; exit 1 ;;
    esac
done

# Get project root directory (parent of scripts directory)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# shellcheck source=venv-health.sh
source "$SCRIPT_DIR/venv-health.sh"

VENV="$PROJECT_ROOT/.venv"
VENV_PYTHON="$VENV/bin/python"

# Pick the base interpreter from outside .venv. In a terminal where the venv is
# activated (VS Code does this automatically), `python3` would otherwise be
# the very venv we may be about to delete.
unset VIRTUAL_ENV
PATH="$(printf '%s' "$PATH" | tr ':' '\n' | grep -vxF "$VENV/bin" | paste -sd: -)"
export PATH
PYTHON="${PYTHON:-python3}"
if command -v "$PYTHON" &> /dev/null; then
    PYTHON="$(command -v "$PYTHON")"
fi

echo "╔════════════════════════════════════════════════════════════╗"
echo "║     Mantyx Development Environment Setup                  ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Check Python version
log_info "Checking Python version..."
if ! command -v "$PYTHON" &> /dev/null; then
    log_error "$PYTHON is not installed. Please install Python 3.10 or higher."
    exit 1
fi

if ! "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
    log_error "Python 3.10 or higher is required. Found: $("$PYTHON" --version 2>&1)"
    exit 1
fi

log_success "$("$PYTHON" --version) found ($(command -v "$PYTHON"))"

# Check/Create virtual environment
log_info "Checking virtual environment..."
if [ "$RECREATE" = true ] && [ -d "$VENV" ]; then
    log_warning "Recreating virtual environment (--recreate)"
    rm -rf "$VENV"
elif [ -d "$VENV" ]; then
    PROBLEMS="$(venv_problems "$VENV")"
    if [ -n "$PROBLEMS" ]; then
        log_warning "Virtual environment is broken:"
        while IFS= read -r problem; do
            echo "    - $problem"
        done <<< "$PROBLEMS"
        log_info "Removing it so it can be rebuilt..."
        rm -rf "$VENV"
    else
        log_success "Virtual environment is healthy"
    fi
fi

if [ ! -d "$VENV" ]; then
    log_info "Creating virtual environment with $("$PYTHON" --version)..."
    if ! "$PYTHON" -m venv "$VENV"; then
        log_error "Could not create the virtual environment."
        log_info "On Debian/Ubuntu you may need: sudo apt install python3-venv"
        rm -rf "$VENV"
        exit 1
    fi
    log_success "Virtual environment created"
fi

# Always go through the venv's interpreter (python -m ...) rather than
# activating it or calling console scripts like bin/pip, so a half-broken
# shell environment can't send commands to the wrong Python.

# Upgrade pip
log_info "Upgrading pip..."
"$VENV_PYTHON" -m pip install --upgrade pip --quiet

# Install dependencies
log_info "Installing Mantyx with development dependencies..."
"$VENV_PYTHON" -m pip install -e ".[dev]" --quiet
log_success "Dependencies installed"

# Install pre-commit hooks. --overwrite rewrites a hook left behind by an old
# or moved venv, which would otherwise make every `git commit` fail.
log_info "Setting up pre-commit hooks..."
"$VENV_PYTHON" -m pre_commit install --overwrite > /dev/null
HOOK_PROBLEMS="$(precommit_hook_problems "$VENV")"
if [ -n "$HOOK_PROBLEMS" ]; then
    log_error "$HOOK_PROBLEMS"
    exit 1
fi
log_success "Pre-commit hooks installed"

# Create development directories
log_info "Creating development directories..."
mkdir -p dev_data/{apps,backups,config,data,logs,temp,venvs}
log_success "Development directories created"

if [ "$RUN_ALL_HOOKS" = true ]; then
    log_info "Running pre-commit on all files..."
    "$VENV_PYTHON" -m pre_commit run --all-files || log_warning "Some pre-commit checks failed. Review and fix before committing."
else
    log_info "Skipping full pre-commit run (pass --all-hooks to include it)."
fi

# Run tests to verify setup
log_info "Running tests to verify setup..."
if "$VENV_PYTHON" -m pytest tests/ -q --tb=short --no-cov; then
    log_success "All tests passed"
else
    log_warning "Some tests failed. This might be expected for a fresh setup."
fi

echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║     Setup Complete! ✨                                     ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
log_info "Development environment is ready!"
echo -e ""
echo -e "Next steps:"
echo -e "  1. Activate the virtual environment:"
echo -e "     ${BLUE}source .venv/bin/activate${NC}"
echo -e ""
echo -e "  2. Run the development server:"
echo -e "     ${BLUE}make run${NC}"
echo -e "     or"
echo -e "     ${BLUE}python -m mantyx.cli run${NC}"
echo -e ""
echo -e "  3. Open the web interface:"
echo -e "     ${BLUE}http://localhost:8420${NC}"
echo -e ""
echo -e "Useful commands:"
echo -e "  ${BLUE}make help${NC}           - Show all available make targets"
echo -e "  ${BLUE}make test${NC}           - Run tests"
echo -e "  ${BLUE}make format${NC}         - Format code"
echo -e "  ${BLUE}make pre-commit${NC}     - Run pre-commit hooks"
echo -e "  ${BLUE}./scripts/check-env.sh${NC} - Check environment health"
echo -e ""
