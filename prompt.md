# Prompt

I want you to build the full framework of this application. It is a hostable python app management framework. This app is called Mantyx. A simple logo with a dark background is in the assets folder. All interfaces should have a dark theme. It will be tracked on GitHub.

**Role:**
You are a senior systems architect and Python infrastructure engineer. Your task is to design and implement a **single-node Python application orchestration framework** intended to run on a trusted home server.

This system is not a SaaS platform and not multi-tenant. It is an internal developer control plane for managing Python apps and scripts.

---

## 1. SYSTEM PURPOSE

Build a framework that:

* Manages **multiple independent Python applications**
* Supports:

  * **Scheduled jobs**
  * **Perpetual (long-running) services**
* Allows full **app lifecycle management** through a **web interface**
* Provides:

  * Dependency isolation
  * Process supervision
  * Scheduling
  * Health monitoring
  * Logging and history
* Runs continuously as a **system daemon**

---

## 2. CORE DESIGN PRINCIPLES (MANDATORY)

* All apps are treated as **immutable units with versioned updates**
* App code never executes inside the orchestrator process
* Every destructive operation must be explicit and reversible where feasible
* File system, database, and process state must stay consistent
* Web UI is the primary control surface

---

## 3. APPLICATION LIFECYCLE STATES

Each app must have a clearly defined lifecycle state:

* `uploaded`
* `installed`
* `enabled`
* `disabled`
* `running`
* `stopped`
* `failed`
* `deleted`

State transitions must be explicit and enforced.

---

## 4. APP INGESTION (UPLOAD) REQUIREMENTS

### 4.1 Supported Upload Methods

The web interface must support **at least** the following upload mechanisms:

1. **ZIP archive upload**

   * Uploaded via browser
   * Extracted into a dedicated app directory
2. **Single-file script upload**

   * Automatically wrapped as a minimal app
3. **Git repository import (optional but preferred)**

   * HTTPS URL
   * Optional branch/tag selection

---

### 4.2 Upload Validation

Before accepting an app, the system must:

* Validate archive structure
* Ensure no path traversal (`../`)
* Require:

  * An entrypoint file
* Optionally detect:

  * `requirements.txt`
  * `pyproject.toml`
* Reject uploads exceeding a configurable size limit

---

### 4.3 App Directory Layout (Enforced)

Each app must live in its own directory:

```
/srv/orchestrator/apps/<app_name>/
├── app/
│   └── source files
├── config.yaml
└── metadata.json
```

The orchestrator must **never mix app files** across directories.

---

## 5. APP REGISTRATION FLOW

Upon upload:

1. App enters `uploaded` state
2. User is prompted via UI to:

   * Name the app
   * Select type (scheduled / perpetual)
   * Choose entrypoint
   * Configure schedule or restart policy
3. Metadata is persisted
4. App moves to `installed` state after dependency resolution

No app may execute before explicit enablement.

---

## 6. APP UPDATE MECHANISM

### 6.1 Update Types

The system must support:

1. **Code update**

   * Replace app source
2. **Configuration-only update**
3. **Dependency update**

---

### 6.2 Update Process (MANDATORY)

Updates must follow a **safe, transactional process**:

1. App is stopped (if running)
2. Existing app directory is backed up:

   ```
   /srv/orchestrator/backups/<app_name>/<timestamp>/
   ```
3. New version is staged in a temporary directory
4. Validation is re-run
5. Dependencies are reinstalled if needed
6. New version is activated atomically
7. App is restarted if previously running

If any step fails:

* Roll back to previous version
* Surface error clearly in UI

---

## 7. APP DELETION

### 7.1 Deletion Requirements

Deleting an app must:

* Require explicit confirmation
* Stop all running processes
* Unschedule jobs
* Remove:

  * App files
  * Virtual environment
* Preserve:

  * Logs (configurable retention)
  * Execution history (database)

Optional:

* “Soft delete” mode for recovery

---

## 8. DEPENDENCY MANAGEMENT

* One virtual environment per app
* Dependency installation is:

  * Explicit
  * Logged
  * Viewable in UI
* Failed dependency installs must block execution

---

## 9. PERPETUAL SERVICE MANAGEMENT

(As previously specified, unchanged, but now integrated with lifecycle states.)

* Auto-start on enable
* Restart on failure
* Health checks
* Restart limits and backoff

---

## 10. SCHEDULING

* APScheduler for scheduled apps
* Persistent job store
* Enable/disable scheduling without deleting app

---

## 11. WEB INTERFACE FUNCTIONALITY

### 11.1 App Management Views

The UI must provide:

* Upload new app
* Update existing app
* Delete app
* Enable / disable app
* Start / stop / restart controls

---

### 11.2 Dashboard Enhancements

* Status badges
* Health indicators
* Last run / uptime
* Restart count
* **Clickable links to app-provided web interfaces**

---

## 12. API DESIGN

* All UI actions must map to REST endpoints
* No hidden state transitions
* API documented via OpenAPI

---

## 13. SECURITY CONSIDERATIONS

* Restrict upload size and type
* Sanitize filenames
* Prevent arbitrary file overwrite
* Assume apps are trusted but buggy

---

## 14. FILE SYSTEM LAYOUT (FINAL)

```
/srv/orchestrator/
├── apps/
├── venvs/
├── logs/
├── backups/
├── data/
│   └── orchestrator.db
├── config/
└── orchestrator.py
```

---

## 15. IMPLEMENTATION PHASES

1. App upload and validation
2. App registry and metadata
3. Dependency isolation
4. Execution engine
5. Scheduler and supervisor
6. Web UI
7. Safety and rollback mechanisms

---

## 16. NON-GOALS

* Multi-node orchestration
* Containerization
* Remote code execution
* User sandboxing

---

## DELIVERABLES

* Fully functional Python project
* Clear module boundaries
* Database schema
* systemd unit file
* README with operational details
