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

# Get project root directory (parent of scripts directory)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo "╔════════════════════════════════════════════════════════════╗"
echo "║     Mantyx Development Environment Setup                  ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Check Python version
log_info "Checking Python version..."
if ! command -v python3 &> /dev/null; then
    log_error "Python 3 is not installed. Please install Python 3.10 or higher."
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]); then
    log_error "Python 3.10 or higher is required. Found: $PYTHON_VERSION"
    exit 1
fi

log_success "Python $PYTHON_VERSION found"

# Check/Create virtual environment
log_info "Checking virtual environment..."
if [ ! -d ".venv" ]; then
    log_info "Creating virtual environment..."
    python3 -m venv .venv
    log_success "Virtual environment created"
else
    log_success "Virtual environment exists"
fi

# Activate virtual environment
log_info "Activating virtual environment..."
source .venv/bin/activate

# Upgrade pip
log_info "Upgrading pip..."
pip install --upgrade pip --quiet

# Install dependencies
log_info "Installing Mantyx with development dependencies..."
pip install -e ".[dev]" --quiet
log_success "Dependencies installed"

# Install pre-commit hooks
log_info "Setting up pre-commit hooks..."
if ! command -v pre-commit &> /dev/null; then
    log_error "pre-commit not found in PATH after installation"
    exit 1
fi

pre-commit install
log_success "Pre-commit hooks installed"

# Create development directories
log_info "Creating development directories..."
mkdir -p dev_data/{apps,backups,config,data,logs,temp,venvs}
log_success "Development directories created"

# Run pre-commit on all files (optional, can be slow)
read -p "Run pre-commit on all files now? This may take a while. (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    log_info "Running pre-commit on all files..."
    pre-commit run --all-files || log_warning "Some pre-commit checks failed. Review and fix before committing."
else
    log_info "Skipping pre-commit check. Run 'pre-commit run --all-files' manually when ready."
fi

# Run tests to verify setup
log_info "Running tests to verify setup..."
if pytest tests/ -v --tb=short; then
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
echo ""
echo "Next steps:"
echo "  1. Activate the virtual environment:"
echo "     ${BLUE}source .venv/bin/activate${NC}"
echo ""
echo "  2. Run the development server:"
echo "     ${BLUE}make run${NC}"
echo "     or"
echo "     ${BLUE}python -m mantyx.cli run${NC}"
echo ""
echo "  3. Open the web interface:"
echo "     ${BLUE}http://localhost:8420${NC}"
echo ""
echo "Useful commands:"
echo "  ${BLUE}make help${NC}           - Show all available make targets"
echo "  ${BLUE}make test${NC}           - Run tests"
echo "  ${BLUE}make format${NC}         - Format code"
echo "  ${BLUE}make pre-commit${NC}     - Run pre-commit hooks"
echo "  ${BLUE}./scripts/check-env.sh${NC} - Check environment health"
echo ""
