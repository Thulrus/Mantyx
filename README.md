# Mantyx

<p align="center">
  <img src="assets/logo.png" alt="Mantyx Logo" width="200"/>
</p>

**A locally hostable Python application orchestration framework.**

Mantyx is a single-node orchestration system designed to run on trusted home servers. It provides a complete solution for managing multiple Python applications with dependency isolation, process supervision, scheduling, and a web-based control interface.

---

## Features

- 🚀 **Full App Lifecycle Management** - Upload, install, enable, disable, and delete apps
- 📦 **Dependency Isolation** - Each app gets its own virtual environment
- ⏰ **Flexible Scheduling** - Cron expressions and interval-based scheduling
- 🔄 **Process Supervision** - Automatic restarts, health checks, and monitoring
- 🌐 **Web Interface** - Dark-themed, responsive UI for all management operations
- 📊 **Execution History** - Track all app runs with stdout/stderr capture
- 🔐 **Safe Updates** - Automatic backups before updates with rollback support
- 🎯 **Git Integration** - Deploy directly from Git repositories

---

## Installation

### Prerequisites

- Python 3.10 or higher
- Linux OS (tested on Ubuntu/Debian)
- sudo access for system service installation

### Quick Start

#### Option 1: Using VS Code Tasks (Recommended for Development)

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Thulrus/Mantyx.git
   cd Mantyx
   ```

2. **Open in VS Code:**
   ```bash
   code .
   ```

3. **Run the setup task:**
   - Press `Ctrl+Shift+P`
   - Type "Run Task"
   - Select "Mantyx: Setup Development Environment"
   
   This will automatically:
   - Create a `.venv` virtual environment
   - Install all dependencies
   - Clean the dev data directory

4. **Start the server:**
   - Press `Ctrl+Shift+B` (or F5 to debug)

5. **Access the web interface:**
   Open your browser to `http://localhost:8420`

#### Option 2: Manual Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Thulrus/Mantyx.git
   cd Mantyx
   ```

2. **Create a virtual environment and install:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -e .[dev]
   ```

3. **Run Mantyx:**
   ```bash
   mantyx run
   # or
   python -m mantyx.cli run
   ```

4. **Access the web interface:**
   Open your browser to `http://localhost:8420`

---

## System Service Installation

For production use, install Mantyx as a system service:

1. **Create mantyx user:**
   ```bash
   sudo useradd -r -s /bin/false mantyx
   ```

2. **Create base directory:**
   ```bash
   sudo mkdir -p /srv/mantyx
   sudo chown mantyx:mantyx /srv/mantyx
   ```

3. **Install Mantyx:**
   ```bash
   sudo -u mantyx python3 -m venv /srv/mantyx/venv
   sudo -u mantyx /srv/mantyx/venv/bin/pip install /path/to/Mantyx
   ```

4. **Install systemd service:**
   ```bash
   sudo cp mantyx.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable mantyx
   sudo systemctl start mantyx
   ```

5. **Check status:**
   ```bash
   sudo systemctl status mantyx
   ```

---

## Configuration

Mantyx can be configured via environment variables or a `.env` file:

```bash
# Copy example configuration
cp .env.example .env
```

### Configuration Options

| Variable                      | Default       | Description                 |
| ----------------------------- | ------------- | --------------------------- |
| `MANTYX_BASE_DIR`             | `/srv/mantyx` | Base directory for all data |
| `MANTYX_HOST`                 | `0.0.0.0`     | Server bind address         |
| `MANTYX_PORT`                 | `8420`        | Server port                 |
| `MANTYX_DEBUG`                | `false`       | Enable debug mode           |
| `MANTYX_DATABASE_URL`         | SQLite        | Database connection URL     |
| `MANTYX_MAX_UPLOAD_SIZE_MB`   | `100`         | Maximum upload size         |
| `MANTYX_DEFAULT_MAX_RESTARTS` | `3`           | Max restart attempts        |
| `MANTYX_LOG_RETENTION_DAYS`   | `30`          | Log retention period        |

---

## Directory Structure

```
/srv/mantyx/
├── apps/              # App installations
│   └── <app_name>/
│       ├── app/       # Source code
│       ├── config.yaml
│       └── metadata.json
├── venvs/             # Virtual environments
│   └── <app_name>/
├── logs/              # Application logs
│   └── <app_name>/
├── backups/           # App backups
│   └── <app_name>/
├── data/              # Database and persistent data
│   └── mantyx.db
├── config/            # Configuration files
└── temp/              # Temporary files
```

---

## Usage

### Uploading an Application

**Via Web Interface:**
1. Click "Upload App"
2. Choose between ZIP upload or Git repository
3. Fill in app details
4. Upload and install

**Via API:**
```bash
# Upload ZIP
curl -X POST http://localhost:8420/api/apps/upload/zip \
  -F "file=@myapp.zip" \
  -F "app_name=my-app" \
  -F "display_name=My Application"

# Clone from Git
curl -X POST http://localhost:8420/api/apps/upload/git \
  -F "git_url=https://github.com/user/repo.git" \
  -F "app_name=my-app" \
  -F "display_name=My Application"
```

### Managing Applications

1. **Install Dependencies:** Click "Install" after upload
2. **Enable App:** Makes the app available to run
3. **Start/Stop:** Control perpetual apps
4. **Disable:** Stop app and prevent automatic starts
5. **Delete:** Remove app and its data

### Creating Schedules

For scheduled apps, create schedules via the API:

```bash
curl -X POST http://localhost:8420/api/schedules \
  -H "Content-Type: application/json" \
  -d '{
    "app_id": 1,
    "name": "Daily Backup",
    "schedule_type": "cron",
    "cron_expression": "0 2 * * *",
    "timezone": "UTC"
  }'
```

---

## Application Types

### Perpetual Apps
Long-running services that should stay running:
- Web servers
- Background workers
- Monitoring agents

Features:
- Automatic restart on failure
- Health checks
- PID tracking
- Configurable restart policies

### Scheduled Apps
Jobs that run on a schedule:
- Data processing
- Backups
- Reports
- Maintenance tasks

Features:
- Cron expressions
- Interval-based scheduling
- Execution timeouts
- Misfire handling

---

## Application Structure

### Minimal App
```
myapp/
└── main.py
```

### Complete App
```
myapp/
├── main.py           # Entrypoint
├── requirements.txt  # Dependencies
├── config.yaml       # App config (optional)
└── modules/
    └── helper.py
```

### Example main.py
```python
#!/usr/bin/env python3
"""
Example Mantyx application.
"""

import sys
import time

def main():
    print("Starting my application...")
    
    # Your application logic here
    while True:
        print("Working...")
        time.sleep(60)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Shutting down...")
        sys.exit(0)
```

---

## API Documentation

Full API documentation is available at `/docs` when Mantyx is running.

### Key Endpoints

- `GET /api/apps` - List all applications
- `POST /api/apps/upload/zip` - Upload ZIP archive
- `POST /api/apps/upload/git` - Clone from Git
- `POST /api/apps/{id}/install` - Install dependencies
- `POST /api/apps/{id}/enable` - Enable app
- `POST /api/apps/{id}/start` - Start perpetual app
- `POST /api/apps/{id}/stop` - Stop app
- `DELETE /api/apps/{id}` - Delete app
- `GET /api/executions` - List executions
- `GET /api/schedules` - List schedules

---

## Development

### Setting up Development Environment

```bash
# Clone repository
git clone https://github.com/Thulrus/Mantyx.git
cd Mantyx

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install in development mode with dev dependencies
pip install -e ".[dev]"

# Run in debug mode
export MANTYX_DEBUG=true
export MANTYX_BASE_DIR=./dev_data
mantyx run
```

### Running Tests

```bash
pytest
pytest --cov=mantyx  # With coverage
```

---

## Troubleshooting

### App Won't Start
1. Check logs: `/srv/mantyx/logs/<app_name>/`
2. Verify virtual environment exists
3. Check dependencies are installed
4. Review app state in database

### Scheduler Not Running Jobs
1. Check schedule is enabled
2. Verify cron expression is valid
3. Check app is in "enabled" state
4. Review scheduler logs

### Permission Errors
1. Ensure mantyx user owns `/srv/mantyx`
2. Check file permissions in app directories
3. Verify systemd service runs as mantyx user

---

## Architecture

Mantyx consists of several core components:

- **App Manager**: Handles uploads, installations, and lifecycle
- **Virtual Environment Manager**: Isolates dependencies
- **Process Supervisor**: Monitors and restarts perpetual apps
- **Scheduler**: Manages scheduled jobs with APScheduler
- **REST API**: FastAPI-based API for all operations
- **Web UI**: Dark-themed single-page application
- **Database**: SQLAlchemy with SQLite (or PostgreSQL)

---

## Security Considerations

Mantyx is designed for **trusted home servers** and makes the following assumptions:

- All uploaded apps are from trusted sources
- Users have legitimate access to the system
- Apps do not require sandboxing from each other
- Network access is controlled at the firewall level

For enhanced security:
- Run Mantyx behind a reverse proxy
- Enable authentication at the proxy level
- Restrict file system access using AppArmor or SELinux
- Use PostgreSQL instead of SQLite for multi-user scenarios

---

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

---

## License

MIT License - see LICENSE file for details

---

## Support

- **Issues**: [GitHub Issues](https://github.com/Thulrus/Mantyx/issues)
- **Discussions**: [GitHub Discussions](https://github.com/Thulrus/Mantyx/discussions)

---

## Roadmap

- [ ] Docker container support
- [ ] Multi-node clustering
- [ ] Built-in authentication
- [ ] App marketplace
- [ ] Resource limits (CPU/memory)
- [ ] Real-time log streaming
- [ ] Metrics and alerting
- [ ] Backup/restore functionality
- [ ] App templates

---

**Made with ❤️ for Python developers who want simple, powerful app orchestration.**
