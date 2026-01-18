#!/usr/bin/env bash
# Mantyx Deployment Script
# Handles both initial setup and code updates automatically

set -e

# Load deployment configuration if it exists
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_CONFIG="${SCRIPT_DIR}/.deploy.env"

if [ -f "$DEPLOY_CONFIG" ]; then
    # Source the config file
    source "$DEPLOY_CONFIG"
    
    # Use config values as defaults if arguments not provided
    REMOTE_TARGET="${1:-$DEPLOY_TARGET}"
    REMOTE_PATH="${2:-$DEPLOY_PATH}"
    SERVICE_NAME="${DEPLOY_SERVICE:-mantyx}"
else
    # No config file - require arguments
    REMOTE_TARGET="$1"
    REMOTE_PATH="$2"
    SERVICE_NAME="mantyx"
fi

# Validate we have the required values
if [ -z "$REMOTE_TARGET" ] || [ -z "$REMOTE_PATH" ]; then
    echo "Error: Missing required configuration"
    echo ""
    echo "Option 1: Create a .deploy.env file (recommended)"
    echo "  cp .deploy.env.example .deploy.env"
    echo "  # Edit .deploy.env with your server details"
    echo "  $0"
    echo ""
    echo "Option 2: Pass arguments directly"
    echo "  $0 USER@HOST PATH"
    echo ""
    echo "Arguments:"
    echo "  USER@HOST   Remote server (user@hostname or user@IP)"
    echo "  PATH        Installation path on remote server"
    echo ""
    echo "Examples:"
    echo "  $0 user@192.168.1.100 /home/user/mantyx"
    echo "  $0 admin@server.local /opt/mantyx"
    exit 1
fi

# Parse user@host
if [[ "$REMOTE_TARGET" == *"@"* ]]; then
    REMOTE_USER="${REMOTE_TARGET%%@*}"
    REMOTE_HOST="${REMOTE_TARGET##*@}"
else
    # If no @ symbol, assume current user
    REMOTE_USER="$USER"
    REMOTE_HOST="$REMOTE_TARGET"
fi

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

show_usage() {
    echo "Mantyx Deployment Script"
    echo ""
    echo "Option 1: Use config file (recommended)"
    echo "  cp .deploy.env.example .deploy.env"
    echo "  # Edit .deploy.env with your server details"
    echo "  $0"
    echo ""
    echo "Option 2: Pass arguments directly"
    echo "  $0 USER@HOST PATH"
    echo ""
    echo "Arguments:"
    echo "  USER@HOST   Remote server (user@hostname or user@IP)"
    echo "  PATH        Installation path on remote server"
    echo ""
    echo "Examples:"
    echo "  $0 user@192.168.1.100 /home/user/mantyx"
    echo "  $0 admin@server.local /opt/mantyx"
}

check_ssh() {
    log_step "Checking SSH connectivity to ${REMOTE_USER}@${REMOTE_HOST}..."
    
    # Test SSH connection
    if ! ssh -o ConnectTimeout=5 "${REMOTE_USER}@${REMOTE_HOST}" 'exit' 2>/dev/null; then
        log_error "SSH connection failed"
        exit 1
    fi
    
    log_info "SSH connection OK"
    
    # Check if using password authentication
    if ssh -o BatchMode=yes -o ConnectTimeout=2 "${REMOTE_USER}@${REMOTE_HOST}" 'exit' 2>&1 | grep -q "Permission denied"; then
        log_warn "Password authentication detected. For better experience, set up SSH key:"
        echo "  ssh-copy-id ${REMOTE_USER}@${REMOTE_HOST}"
        echo ""
    fi
    
    # Check sudo access
    log_step "Checking sudo access..."
    if ! ssh "${REMOTE_USER}@${REMOTE_HOST}" "sudo -n true" 2>/dev/null; then
        log_warn "Sudo requires password. Adding passwordless sudo access..."
        echo ""
        echo "Please enter your password when prompted to configure passwordless sudo."
        echo "This only needs to be done once."
        echo ""
        
        # Add user to sudoers for systemd commands
        ssh -t "${REMOTE_USER}@${REMOTE_HOST}" "echo '${REMOTE_USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl, /bin/systemctl, /usr/bin/journalctl, /bin/journalctl' | sudo tee /etc/sudoers.d/mantyx-deploy > /dev/null && sudo chmod 440 /etc/sudoers.d/mantyx-deploy"
        
        if [ $? -eq 0 ]; then
            log_info "Passwordless sudo configured"
        else
            log_error "Failed to configure sudo access"
            exit 1
        fi
    else
        log_info "Sudo access OK"
    fi
}

check_remote_setup() {
    log_step "Checking if Mantyx is already installed..."
    if ssh "${REMOTE_USER}@${REMOTE_HOST}" "[ -d '${REMOTE_PATH}' ] && [ -f '${REMOTE_PATH}/src/mantyx/__init__.py' ]"; then
        return 0  # Already installed
    else
        return 1  # Need initial setup
    fi
}

initial_setup() {
    log_info "Performing initial setup on ${REMOTE_HOST}..."
    
    log_step "Creating directory structure..."
    ssh "${REMOTE_USER}@${REMOTE_HOST}" "mkdir -p '${REMOTE_PATH}'"
    
    log_step "Syncing all files to server..."
    rsync -avz --exclude='.git/' --exclude='dev_data/' --exclude='.venv/' --exclude='__pycache__/' \
        ./ "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PATH}/"
    
    log_step "Creating virtual environment on server..."
    ssh "${REMOTE_USER}@${REMOTE_HOST}" "cd '${REMOTE_PATH}' && python3 -m venv .venv"
    
    log_step "Installing Mantyx and dependencies..."
    ssh "${REMOTE_USER}@${REMOTE_HOST}" "cd '${REMOTE_PATH}' && .venv/bin/pip install -e . --quiet"
    
    log_step "Creating mantyx_data directory..."
    ssh "${REMOTE_USER}@${REMOTE_HOST}" "mkdir -p '${REMOTE_PATH}/mantyx_data'/{apps,venvs,logs,backups,temp,config,data}"
    
    log_step "Setting up systemd service..."
    setup_systemd
    
    log_info "Initial setup complete!"
}

deploy_update() {
    log_info "Deploying code updates to ${REMOTE_HOST}..."
    
    log_step "Syncing code changes..."
    rsync -avz --delete \
        --exclude='.git/' --exclude='dev_data/' --exclude='.venv/' \
        --exclude='__pycache__/' --exclude='*.pyc' --exclude='mantyx_data/' \
        ./ "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PATH}/"
    
    log_step "Updating dependencies..."
    ssh "${REMOTE_USER}@${REMOTE_HOST}" "cd '${REMOTE_PATH}' && .venv/bin/pip install -e . --quiet"
    
    log_step "Running database migrations..."
    # Run migrations if they exist
    if ssh "${REMOTE_USER}@${REMOTE_HOST}" "[ -d '${REMOTE_PATH}/migrations' ]"; then
        # Find all migration scripts and run them
        ssh "${REMOTE_USER}@${REMOTE_HOST}" "
            export MANTYX_BASE_DIR='${REMOTE_PATH}/mantyx_data'
            for migration in '${REMOTE_PATH}/migrations'/*.py; do
                if [ -f \"\$migration\" ]; then
                    echo \"Running migration: \$(basename \$migration)\"
                    '${REMOTE_PATH}/.venv/bin/python' \"\$migration\" || true
                fi
            done
        "
    fi
    
    # Check if service exists
    if ! ssh "${REMOTE_USER}@${REMOTE_HOST}" "sudo systemctl list-unit-files ${SERVICE_NAME}.service" 2>/dev/null | grep -q "${SERVICE_NAME}"; then
        log_warn "Systemd service not found - setting it up..."
        setup_systemd
    else
        log_step "Restarting Mantyx service..."
        ssh "${REMOTE_USER}@${REMOTE_HOST}" "sudo systemctl restart ${SERVICE_NAME}"
    fi
    
    log_info "Update complete!"
}

setup_systemd() {
    log_step "Creating systemd service file..."
    
    # Create service file content
    cat > /tmp/mantyx.service <<EOF
[Unit]
Description=Mantyx Application Orchestrator
After=network.target

[Service]
Type=simple
User=${REMOTE_USER}
Group=${REMOTE_USER}
WorkingDirectory=${REMOTE_PATH}
Environment="MANTYX_BASE_DIR=${REMOTE_PATH}/mantyx_data"
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${REMOTE_PATH}/.venv/bin"
ExecStart=${REMOTE_PATH}/.venv/bin/python -m mantyx.cli run
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
    
    # Copy to server and install
    scp /tmp/mantyx.service "${REMOTE_USER}@${REMOTE_HOST}:/tmp/"
    rm /tmp/mantyx.service
    
    ssh -t "${REMOTE_USER}@${REMOTE_HOST}" "sudo mv /tmp/mantyx.service /etc/systemd/system/ && \
        sudo systemctl daemon-reload && \
        sudo systemctl enable ${SERVICE_NAME} && \
        sudo systemctl start ${SERVICE_NAME}"
    
    log_info "Systemd service configured and started"
}

check_service() {
    log_step "Checking service status..."
    sleep 3  # Give service time to start
    
    if ssh "${REMOTE_USER}@${REMOTE_HOST}" "sudo systemctl is-active --quiet ${SERVICE_NAME}"; then
        log_info "${GREEN}✓ Mantyx service is running${NC}"
        log_info "${GREEN}✓ Access web interface at: http://${REMOTE_HOST}:8420${NC}"
        
        # Show service status
        echo ""
        ssh "${REMOTE_USER}@${REMOTE_HOST}" "sudo systemctl status ${SERVICE_NAME} --no-pager -l" | head -n 10
        return 0
    else
        log_error "Service failed to start"
        log_warn "Checking logs..."
        echo ""
        ssh "${REMOTE_USER}@${REMOTE_HOST}" "sudo journalctl -u ${SERVICE_NAME} -n 30 --no-pager"
        echo ""
        log_error "Check logs above for errors"
        return 1
    fi
}

# Main deployment
main() {
    if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
        show_usage
        exit 0
    fi
    
    echo ""
    log_info "Mantyx Deployment Script"
    log_info "Target: ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PATH}"
    echo ""
    
    check_ssh
    
    if check_remote_setup; then
        log_info "Existing installation detected - performing update"
        deploy_update
    else
        log_info "No existing installation - performing initial setup"
        initial_setup
    fi
    
    check_service
    
    echo ""
    log_info "${GREEN}Deployment successful!${NC}"
    echo ""
}

main "$@"
