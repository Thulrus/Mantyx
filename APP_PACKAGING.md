# Mantyx App Packaging Guide

Mantyx is a Python app orchestration system that runs on a home server. It manages Python apps by installing their dependencies in isolated virtual environments and either running them as persistent background processes or on a schedule.

## Package Structure

To prepare a Python app for Mantyx, package it as a ZIP file with this structure:

```
your-app-name.zip
├── main.py          ← required entrypoint (or app.py, run.py, etc.)
└── requirements.txt ← optional, list pip dependencies here
```

## App Types

### Perpetual

A long-running process. The entrypoint must run a loop and handle `KeyboardInterrupt` gracefully to allow clean shutdown:

```python
import sys
import time

def main():
    while True:
        # do work
        time.sleep(10)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
```

### Scheduled

Runs on a cron or interval schedule, does its work, then exits with `sys.exit(0)` on success or `sys.exit(1)` on failure:

```python
import sys

def main():
    # do work
    sys.exit(0)

if __name__ == "__main__":
    main()
```

## Rules

- All output goes to stdout/stderr — it is captured and logged automatically
- No special imports or SDK required — it is just a plain Python script
- List all third-party dependencies in `requirements.txt`; standard library modules need no entry
