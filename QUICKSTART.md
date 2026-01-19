# Mantyx Quick Start Guide

This guide will get you up and running with Mantyx in 5 minutes.

## Step 1: Installation

### Option A: VS Code (Recommended)

```bash
# Clone the repository
git clone https://github.com/Thulrus/Mantyx.git
cd Mantyx

# Open in VS Code
code .
```

Then:

1. Press `Ctrl+Shift+P`
2. Type "Run Task"
3. Select **"Mantyx: Setup Development Environment"**

This will automatically create the venv and install all dependencies!

### Option B: Manual Setup

```bash
# Clone the repository
git clone https://github.com/Thulrus/Mantyx.git
cd Mantyx

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install Mantyx with dev dependencies
pip install -e .[dev]
```

## Step 2: Start Mantyx

### Option A: VS Code

Press `Ctrl+Shift+B` to run the development server (or `F5` to debug).

### Option B: Command Line

```bash
# Set development environment (optional)
export MANTYX_BASE_DIR=./dev_data
export MANTYX_DEBUG=true

# Run the server
mantyx run
# or
python -m mantyx.cli run
```

You should see output like:

```
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8420
```

## Step 3: Access the Web Interface

Open your browser to: **<http://localhost:8420>**

You should see the Mantyx dashboard with 0 apps.

## Step 4: Upload Your First App

### Option A: Upload the Example App

1. Create a ZIP of the hello-world example:

   ```bash
   cd examples/hello-world
   zip -r hello-world.zip .
   cd ../..
   ```

2. In the Mantyx web interface:
   - Click "Upload App"
   - Select "ZIP Upload" tab
   - Choose the `hello-world.zip` file
   - App Name: `hello-world`
   - Display Name: `Hello World`
   - Description: `Simple example application`
   - Click "Upload"

### Option B: Clone from Git

1. In the Mantyx web interface:
   - Click "Upload App"
   - Select "Git Repository" tab
   - Git URL: (your repository URL)
   - Branch: `main`
   - App Name: `my-app`
   - Display Name: `My Application`
   - Click "Clone & Upload"

## Step 5: Install and Run

1. After upload, you'll see your app in "uploaded" state
2. Click "Install" to create virtual environment and install dependencies
3. Click "Enable" to enable the app
4. For perpetual apps, click "Start" to begin execution
5. Watch the app run! Check the dashboard for status updates

## Step 6: View App Details

Click on any app card to see:

- Current status and PID
- Recent execution history
- Configuration details
- Schedules (if any)

## Creating Your Own App

### Minimal App Structure

```
my-app/
├── main.py
└── requirements.txt
```

### Example main.py (Perpetual)

```python
#!/usr/bin/env python3
import time
from datetime import datetime

def main():
    print("App started!")
    while True:
        print(f"Running at {datetime.now()}")
        time.sleep(60)

if __name__ == "__main__":
    main()
```

### Example main.py (Scheduled)

```python
#!/usr/bin/env python3
import sys

def main():
    print("Scheduled task running!")
    # Do work here
    print("Task complete!")
    sys.exit(0)

if __name__ == "__main__":
    main()
```

## Next Steps

1. **Explore the API**: Visit <http://localhost:8420/docs> for interactive API documentation
2. **Create schedules**: Use the API to add cron or interval schedules for your apps
3. **Monitor logs**: Check the logs directory for app output
4. **Try updates**: Upload new versions of your apps with automatic backups
5. **Deploy to production**: Follow the systemd service installation in the main README

## Common Commands

```bash
# Start Mantyx
mantyx run

# View configuration
mantyx

# Check logs (if running as service)
sudo journalctl -u mantyx -f

# List apps via API
curl http://localhost:8420/api/apps

# Check app status
curl http://localhost:8420/api/apps/1/status
```

## Troubleshooting

### Port already in use

Change the port:

```bash
export MANTYX_PORT=8421
mantyx run
```

### Permission denied

Make sure you have write access to the base directory:

```bash
chmod 755 ./dev_data
```

### App won't start

1. Check the app is in "enabled" state
2. Verify dependencies are installed (click "Install")
3. Check logs in `dev_data/logs/<app-name>/`

## Getting Help

- **Documentation**: See the main README.md
- **Examples**: Check the `examples/` directory
- **API Docs**: Visit `/docs` endpoint when running
- **Issues**: <https://github.com/Thulrus/Mantyx/issues>

---

**Happy orchestrating! 🚀**
