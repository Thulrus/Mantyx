# Debugging App Executions in Mantyx

This guide explains how to identify and troubleshoot issues when your apps don't execute properly.

## Quick Start: Finding Execution Logs

### Method 1: Via App Details (Recommended)

1. Click on any app card in the Mantyx web interface
2. In the "Recent Executions" section, you'll see a list of recent runs
3. Click the **"📄 View Logs"** button for any execution
4. This opens a modal showing:
   - Execution status and exit code
   - Standard output (stdout) - what your app printed
   - Standard error (stderr) - error messages and warnings

### Method 2: Via API

You can also access logs programmatically:

```bash
# Get execution history for an app
curl http://localhost:8420/api/executions?app_id=1&limit=10

# Get stdout for a specific execution
curl http://localhost:8420/api/executions/123/stdout

# Get stderr for a specific execution
curl http://localhost:8420/api/executions/123/stderr
```

## Understanding Execution Records

Every time an app runs (scheduled or manual), Mantyx creates an **Execution** record with:

- **Status**: `pending` → `running` → `success`/`failed`
- **Exit Code**: 0 = success, non-zero = error
- **Timestamps**: When it started and ended
- **Trigger Type**: `manual` or `scheduled`
- **Logs**: Stdout and stderr captured to files

## Common Issues and Solutions

### Issue 1: App Says It Ran But No Output

**Symptoms**: Execution status is "success" but nothing happened

**Possible Causes**:

1. **No print statements**: Your app might not print anything
2. **Output buffering**: Python buffers output by default
3. **Wrong entry point**: The script that ran isn't the one you expected

**Solution**:

```python
# Add explicit logging to your app
import sys
print("App starting...", flush=True)  # flush=True forces immediate output
print("Doing work...", flush=True)
print("App finished!", flush=True)
```

### Issue 2: Exit Code 0 But Expected Results Missing

**Symptoms**: Exit code is 0 (success) but files weren't created or data wasn't processed

**Check These**:

1. **Working directory**: Apps run from their `app/` directory
2. **File paths**: Use absolute paths or paths relative to the script location
3. **Permissions**: Ensure the app has write access to destination folders

**Debug Code**:

```python
import os
print(f"Current directory: {os.getcwd()}", flush=True)
print(f"Script directory: {os.path.dirname(os.path.abspath(__file__))}", flush=True)
print(f"Files in current dir: {os.listdir('.')}", flush=True)
```

### Issue 3: Import Errors

**Symptoms**: Execution fails with `ModuleNotFoundError`

**Solution**:

1. Check that `requirements.txt` lists all dependencies
2. After updating `requirements.txt`, **update the app** (not just reinstall)
   - Use the "Update App" button in the UI
   - Or: `curl -X POST http://localhost:8420/api/apps/{id}/update/git`
3. This will reinstall dependencies automatically

### Issue 4: App Runs Locally But Fails in Mantyx

**Possible Causes**:

1. **Different Python version**: Mantyx uses a virtual environment
2. **Missing environment variables**: Set them in app config
3. **Path dependencies**: Hardcoded paths that don't exist on server

**Debug Steps**:

1. Check Python version in logs:

   ```python
   import sys
   print(f"Python version: {sys.version}")
   ```

2. Check environment:

   ```python
   import os
   print(f"HOME: {os.environ.get('HOME')}")
   print(f"PATH: {os.environ.get('PATH')}")
   ```

### Issue 5: Silent Failures (No Error Message)

**Symptoms**: App status is "failed" but stderr is empty

**Cause**: Unhandled exception that wasn't caught

**Solution**: Add comprehensive error handling:

```python
import traceback
import sys

def main():
    try:
        # Your app code here
        print("Starting work...", flush=True)
        # ... do stuff ...
        print("Work completed!", flush=True)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr, flush=True)
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
```

## Checking Scheduled App Runs

For scheduled apps, you can see when they'll run next:

1. Click the app card
2. Look at the "Schedules" section
3. Check the next run time

You can also trigger a manual run to test:

1. Click the **"Run Now"** button on the app card
2. This executes immediately (ignores schedule)
3. Check the execution logs to see what happened

## Log File Locations

Logs are stored in the Mantyx data directory:

```
MANTYX_BASE_DIR/
  logs/
    <app_name>/
      execution_<id>_stdout.log
      execution_<id>_stderr.log
```

Default location (if not configured): `~/.local/share/mantyx/logs/`

## Best Practices for Debuggable Apps

1. **Always use flush=True** when printing important information
2. **Log at key points**: Start, major steps, completion
3. **Use exit codes properly**:

   ```python
   import sys
   sys.exit(0)  # Success
   sys.exit(1)  # Error
   ```

4. **Handle all exceptions** and print useful error messages
5. **Test manual runs** before relying on schedules
6. **Check execution history** regularly to catch recurring failures

## Advanced: Real-time Log Monitoring

For perpetual apps (long-running services), you can monitor logs in real-time:

```bash
# Find the execution ID from the web UI
EXEC_ID=123

# Tail stdout
tail -f ~/.local/share/mantyx/logs/<app_name>/execution_${EXEC_ID}_stdout.log

# Tail stderr
tail -f ~/.local/share/mantyx/logs/<app_name>/execution_${EXEC_ID}_stderr.log
```

## Getting Help

If you're still stuck:

1. Check the execution logs in the web UI
2. Look for error messages in stderr
3. Check the app's working directory and permissions
4. Try running the app manually: `python app/main.py`
5. Review the troubleshooting steps above

For scheduled apps that should have run but didn't, check the scheduler debug panel:

- Click the "🐛 Debug" button in the system info bar
- Verify the schedule is enabled and shows a next run time
