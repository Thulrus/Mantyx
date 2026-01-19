# Mantyx Deployment Guide

## Quick Start

Deploy Mantyx to your server with a single command:

```bash
./deploy.sh YOUR_SERVER_IP /path/to/mantyx
```

The script automatically:

- ✓ Detects if this is initial setup or an update
- ✓ Sets up systemd service (initial setup only)
- ✓ Preserves all app data during updates
- ✓ Installs dependencies
- ✓ Starts/restarts the service

## Prerequisites

1. **SSH key access** to the remote server:

   ```bash
   ssh-copy-id user@YOUR_SERVER_IP
   ```

2. **Python 3.12+** installed on the server:

   ```bash
   ssh user@YOUR_SERVER_IP 'python3 --version'
   ```

3. **Sudo privileges** for systemd service management

## Usage

### Deploy to Server

```bash
./deploy.sh 192.168.1.100 /home/user/mantyx
```

### Deploy to Custom Host/Path

```bash
./deploy.sh server.local /opt/mantyx
```

### Deploy from VS Code

Run Task → "Mantyx: Deploy to Server" (edit task args first)

The VS Code task is pre-configured for your server.

## What Happens During Deployment

### Initial Setup (First Time)

1. Creates directory structure on server
2. Syncs all Mantyx files
3. Creates Python virtual environment
4. Installs Mantyx package
5. Creates `mantyx_data/` directory structure
6. Sets up systemd service
7. Enables service for auto-start on boot
8. Starts the service

### Updates (Subsequent Deployments)

1. Syncs only changed code files
2. Preserves `mantyx_data/` (all apps, schedules, logs)
3. Updates Python dependencies
4. **Runs database migrations** (adds new columns/tables automatically)
5. Restarts service (2-3 second downtime)

## Database Migrations

Mantyx automatically handles database schema updates:

- **New columns/tables**: Added automatically on deployment
- **Migration scripts**: Run automatically from `migrations/` directory
- **Idempotent**: Safe to run multiple times
- **No downtime**: Migrations run before service restart

See `migrations/README.md` for details on the migration system.

## What Gets Preserved

During updates, these are **never** touched:

- ✓ Installed apps and their code
- ✓ App virtual environments
- ✓ Database (schedules, execution history)
- ✓ App configurations and environment variables
- ✓ Logs
- ✓ Backups

## Accessing Mantyx

After deployment, access the web interface at:

```
http://YOUR_SERVER_IP:8420
```

## Monitoring

### View Logs in Real-Time

From VS Code:

- Run Task → "Mantyx: View Remote Logs"

From terminal:

```bash
ssh user@YOUR_SERVER_IP 'sudo journalctl -u mantyx -f'
```

### Check Service Status

```bash
ssh user@YOUR_SERVER_IP 'sudo systemctl status mantyx'
```

### Restart Service Manually

```bash
ssh user@YOUR_SERVER_IP 'sudo systemctl restart mantyx'
```

## Troubleshooting

### Deployment Fails: SSH Connection

Check connectivity:

```bash
ping YOUR_SERVER_IP
ssh user@YOUR_SERVER_IP 'echo Connection OK'
```

Set up SSH key if needed:

```bash
ssh-copy-id user@YOUR_SERVER_IP
```

### Service Won't Start

View detailed error logs:

```bash
ssh user@YOUR_SERVER_IP 'sudo journalctl -u mantyx -n 100 --no-pager'
```

Check Python version:

```bash
ssh user@YOUR_SERVER_IP '/path/to/mantyx/.venv/bin/python --version'
```

### Port 8420 Not Accessible

Open firewall on server:

```bash
ssh user@YOUR_SERVER_IP 'sudo ufw allow 8420/tcp'
```

### Apps Not Running After Update

Updates only affect Mantyx code, not apps. If apps stop:

1. Check app state in web UI
2. Re-enable apps if needed
3. Check app logs in web UI

## Development Workflow

1. Make changes locally
2. Test in dev environment: `Run Development Server`
3. Deploy to server: `./deploy.sh YOUR_SERVER_IP /path/to/mantyx`
4. Verify in production: Open `http://YOUR_SERVER_IP:8420`

## Rollback

If deployment causes issues:

```bash
# SSH to server
ssh user@YOUR_SERVER_IP

# View logs
sudo journalctl -u mantyx -n 100

# If you have git on server
cd /path/to/mantyx
git checkout HEAD~1
sudo systemctl restart mantyx
```

## Firewall Configuration

Allow Mantyx web interface from your network:

```bash
ssh user@YOUR_SERVER_IP 'sudo ufw allow from 192.168.1.0/24 to any port 8420'
```

## Uninstall

To completely remove Mantyx:

```bash
ssh user@YOUR_SERVER_IP
sudo systemctl stop mantyx
sudo systemctl disable mantyx
sudo rm /etc/systemd/system/mantyx.service
sudo systemctl daemon-reload
rm -rf /path/to/mantyx
```

## Security Notes

- Designed for **trusted home networks**
- No built-in authentication
- Apps run as your user
- Keep server updated: `sudo apt update && sudo apt upgrade`
