# App Update System

## Overview

Mantyx now supports updating applications without having to delete and recreate them. This preserves:
- ✓ App configuration and environment variables
- ✓ Schedules and execution history
- ✓ Process settings (restart policy, health checks, etc.)
- ✓ Version history

## Update Methods

### 1. ZIP Upload (Local Development)

Best for apps you develop locally:

1. Make changes to your app code on your local machine
2. Create a new ZIP file of your updated app
3. In Mantyx web UI:
   - Click the **Update** button on your app card
   - Upload the new ZIP file
   - (Optional) Uncheck "Create backup" if you don't need it
4. Mantyx will:
   - Stop the app if running
   - Create a backup (if enabled)
   - Replace the source code
   - Reinstall dependencies (if requirements.txt changed)
   - Auto-increment version number
   - Restart the app if it was running

**Example workflow:**
```bash
# Make changes to your app
vim my-weather-app/weather_fetch.py

# Zip it up
cd my-weather-app
zip -r weather-app-update.zip .

# Upload via web UI → Update button
```

### 2. Git Pull (Repository-based Apps)

Best for apps hosted on GitHub:

1. Push your changes to your GitHub repository
   ```bash
   git add .
   git commit -m "Improved weather parsing"
   git push
   ```

2. In Mantyx web UI:
   - Click the **Update** button on your app card
   - Switch to **"Pull from Git"** tab
   - Click **"Pull Latest Changes"**

3. Mantyx will:
   - Pull latest commits from the configured repository
   - Detect if changes occurred (shows "No changes" if already up to date)
   - Reinstall dependencies if requirements.txt changed
   - Auto-increment version if changes detected
   - Restart the app if it was running

**Note:** The Git tab only appears for apps originally created from a Git repository.

## What Happens During Update

1. **App is stopped** (if running)
2. **Backup created** (optional, recommended)
   - Stored in `mantyx_data/backups/{app_name}/{timestamp}/`
3. **Source code replaced** with new version
4. **Dependencies reinstalled** if requirements.txt exists/changed
5. **Version incremented** (e.g., 1.0.0 → 1.0.1)
6. **App restarted** (if it was running before update)

Total downtime: ~5-15 seconds depending on dependencies

## Version Management

Mantyx automatically manages version numbers:

- **Initial upload**: 1.0.0
- **Each update**: Increments patch version (1.0.0 → 1.0.1 → 1.0.2...)
- **Visible in UI**: Shows current version on app card
- **Tracked in database**: `last_updated_at` and `update_count` fields

## Backup System

Backups are **enabled by default** and highly recommended:

- **Location**: `mantyx_data/backups/{app_name}/{timestamp}/`
- **Contents**: Complete copy of app source code before update
- **Naming**: `YYYYMMDD_HHMMSS` format
- **Retention**: Manual cleanup (not auto-deleted)

To restore from backup:
```bash
# SSH to server
cd /path/to/mantyx/mantyx_data/backups/my-app

# Find the backup you want
ls -la

# Manually restore (example)
cp -r 20260118_144500/app/* ../apps/my-app/app/
```

## Update vs Delete+Recreate

| Feature               | Update         | Delete+Recreate     |
| --------------------- | -------------- | ------------------- |
| Schedules             | ✓ Preserved    | ✗ Lost              |
| Execution History     | ✓ Preserved    | ✗ Lost              |
| Version History       | ✓ Tracked      | ✗ Reset to 1.0.0    |
| Environment Variables | ✓ Preserved    | ✗ Lost              |
| Process Settings      | ✓ Preserved    | ✗ Reset to defaults |
| Downtime              | 5-15 seconds   | 1-2 minutes         |
| App Name              | Must stay same | Can change          |

**When to use Delete+Recreate:**
- Changing app name
- Switching between PERPETUAL ↔ SCHEDULED types
- Major refactor where you want a fresh start

## API Endpoints

For programmatic updates:

### Update from ZIP
```bash
curl -X POST http://localhost:8420/api/apps/{app_id}/update/zip \
  -F "file=@my-app-v2.zip" \
  -F "backup=true"
```

### Pull from Git
```bash
curl -X POST http://localhost:8420/api/apps/{app_id}/update/git \
  -F "backup=true"
```

## Troubleshooting

### Update fails: "Dependencies installation failed"

Check if your requirements.txt is valid:
```bash
# Test locally
pip install -r requirements.txt
```

### App won't start after update

1. Check logs in web UI or via API: `/api/apps/{id}`
2. Look for Python errors in app logs
3. Restore from backup if needed
4. Check that entrypoint file still exists (main.py, app.py, etc.)

### "No changes detected" for Git update

This is normal! It means your repository is already at the latest commit. To verify:
- Check your Git repo's latest commit hash
- Compare with commit hash shown in app details

### Version number not incrementing

Version only increments when:
- ✓ Update completes successfully
- ✓ For Git: actual changes detected
- ✗ Update fails partway through

## Best Practices

1. **Test locally first** before updating production apps
2. **Keep backups enabled** for production updates
3. **Use Git for versioned apps** - easier to track changes
4. **Check logs after update** to ensure app started correctly
5. **Update during low-traffic periods** to minimize impact
6. **Version your requirements.txt** to ensure reproducibility

## Development Workflow

Typical development cycle:

```
┌─────────────────────────────────────────┐
│ 1. Edit app code locally                │
│    vim my-app/main.py                   │
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│ 2. Test locally                         │
│    python my-app/main.py                │
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│ 3. Update in Mantyx                     │
│    - Zip and upload, OR                 │
│    - Git push + pull in UI              │
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│ 4. Verify in Mantyx                     │
│    - Check app status                   │
│    - View logs                          │
│    - Test execution                     │
└─────────────────────────────────────────┘
```

## Future Enhancements

Planned features (not yet implemented):
- Rollback to previous version from UI
- Update notifications (detect available updates for Git apps)
- Batch update multiple apps
- Scheduled updates
- Update history/changelog view
