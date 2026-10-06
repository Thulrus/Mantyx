# Mantyx

<p align="center">
  <img src="assets/logo.png" alt="Mantyx Logo" width="200"/>
</p>

**A locally hostable Python application orchestration framework.**

Mantyx is a single-node orchestration system designed to run on trusted home servers. It provides a complete solution for managing multiple Python applications with dependency isolation, process supervision, scheduling, and a web-based control interface.

The idea came about when I had a bunch of small python scripts that I wanted to run at certain times of the day, and a few that I wanted running all the time. I decided to develop a framework that I could host locally that would take care of the scheduling, handle dependencies, manage the different scripts, and give me a web UI so that I could see what was going on.

It isn't complete yet, but it's slowly getting better.

---

## Features

- 🚀 **Full App Lifecycle Management** - Add, start, stop, pause, update, roll back and delete apps
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
| `MANTYX_PIP_TIMEOUT`          | `900`         | pip install timeout (sec)   |

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

### Adding an application

**Via the web interface:** click **Add app** and follow the three steps:

1. **Source**: drop in a ZIP (a single enclosing folder is fine) or paste a Git URL.
2. **Details**: a name, and how it should run: *Always running* or *On a schedule*.
3. **Schedule / Finish**: pick when it runs (daily at a time, specific weekdays,
   every N minutes, or a custom cron expression, with a preview of the next runs).

Mantyx then uploads it, installs its dependencies, and starts it (or turns on its
schedule) in one go, showing each step as it happens.

**Via the API:**

```bash
# Upload a ZIP, install it and start it in one request
curl -X POST http://localhost:8420/api/apps/upload/zip \
  -F "file=@myapp.zip" \
  -F "app_name=my-app" \
  -F "display_name=My Application" \
  -F "install=true" -F "activate=true"

# Clone from Git
curl -X POST http://localhost:8420/api/apps/upload/git \
  -F "git_url=https://github.com/user/repo.git" \
  -F "app_name=my-app" \
  -F "display_name=My Application" \
  -F "install=true" -F "activate=true"
```

Both return a `task_id`; poll `GET /api/apps/tasks/{task_id}` for progress.

### Managing applications

Every app shows one plain-English status (Running, Stopped, Failed, Scheduled,
Last run failed, Paused, ...) with a short explanation of what's going on and the
most useful next action. Open an app to see:

- **Overview**: status, next/last run, web link, and recent activity
- **Logs**: live output of the current run, or any earlier run
- **Run history**: every run with its result, trigger and duration
- **Schedules** (scheduled apps): add, edit, turn on/off, with next run times
- **Settings**: name, file to run, environment variables (API keys etc.),
  crash/restart behaviour, web link; plus Rebuild environment and Delete
- **Versions**: update from a new ZIP or Git, and roll back to a saved version

Always-running apps stay stopped once you stop them (even across Mantyx restarts)
and are started again automatically when Mantyx restarts if they were running.

### Schedules

Schedules run in the timezone set under **Settings** (changes apply immediately).
Via the API:

```bash
curl -X POST http://localhost:8420/api/schedules \
  -H "Content-Type: application/json" \
  -d '{
    "app_id": 1,
    "name": "Weekday mornings",
    "schedule_type": "cron",
    "cron_expression": "30 7 * * mon-fri"
  }'
```

Use day **names** (`mon-fri`, `sat,sun`) in cron expressions. If you use numbers,
note that Mantyx's scheduler counts `0` as Monday, not Sunday.

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

## Preparing an App for Deployment

See [APP_PACKAGING.md](APP_PACKAGING.md) for the full guide to packaging an
app for Mantyx — package structure, Perpetual vs. Scheduled entrypoints,
persistent data storage, and the rules apps must follow. It's written to be
easy for a human **or an AI coding agent** to follow when preparing an app
for a Mantyx server.

A short version is also available from the web UI via the **Guide** button
in the header.

---

## API Documentation

Full API documentation is available at `/docs` when Mantyx is running.

### Key Endpoints

- `GET /api/apps` - List all applications
- `POST /api/apps/upload/zip` - Upload ZIP archive
- `POST /api/apps/upload/git` - Clone from Git
- `POST /api/apps/{id}/install` - Install dependencies
- `POST /api/apps/{id}/start` / `stop` / `restart` - Control an always-running app
- `POST /api/apps/{id}/enable` / `disable` - Activate or pause a scheduled app
- `POST /api/apps/{id}/run` - Run a scheduled app now
- `POST /api/apps/{id}/update/zip` / `update/git` - Update (with automatic backup)
- `GET /api/apps/{id}/backups` and `POST .../backups/{id}/restore` - Roll back
- `DELETE /api/apps/{id}` - Delete an app and everything belonging to it
- `GET /api/executions?app_id=` - Run history
- `GET /api/executions/{id}/log?stream=stdout&offset=-1` - Read/follow a run's output
- `POST /api/executions/{id}/cancel` - Stop an in-progress scheduled run
- `GET /api/schedules` / `POST /api/schedules/preview` - Schedules and next run times

---

## Development

### Quick Setup (Recommended)

Use the automated setup script:

```bash
# Clone repository
git clone https://github.com/Thulrus/Mantyx.git
cd Mantyx

# Run automated setup
./scripts/setup-dev.sh
```

This script will:

- Verify Python 3.10+
- Create virtual environment
- Install all dependencies
- Configure pre-commit hooks
- Create development directories
- Run tests to verify setup

### Manual Setup

```bash
# Clone repository
git clone https://github.com/Thulrus/Mantyx.git
cd Mantyx

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install in development mode with dev dependencies
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install

# Run in debug mode
export MANTYX_DEBUG=true
export MANTYX_BASE_DIR=./dev_data
mantyx run
```

### Environment Health Check

Verify your development environment:

```bash
./scripts/check-env.sh
# or
make check-env
```

### Running Tests

```bash
pytest
pytest --cov=mantyx  # With coverage
# or
make test
make test-cov
```

### Code Quality

```bash
make format      # Format code with black
make lint        # Run ruff linter
make pre-commit  # Run all pre-commit hooks
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed contribution guidelines.

---

## Troubleshooting

### Development Environment Issues

Run the environment check:

```bash
./scripts/check-env.sh
```

This will diagnose common setup issues.

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
