// Mantyx Frontend JavaScript

// API Base URL
const API_BASE = "/api";

// State
let apps = [];
let currentAppId = null;
let systemTimezone = "UTC";

// Per-app git update check cache: { [appId]: { timestamp, updateAvailable, remoteCommit } }
const gitUpdateCache = {};
const SHORT_COMMIT_LENGTH = 8;

function getShortCommit(commit) {
  return commit ? commit.substring(0, SHORT_COMMIT_LENGTH) : "";
}

// Initialize
document.addEventListener("DOMContentLoaded", () => {
  initializeEventListeners();
  loadSystemInfo();
  loadApps();

  // Auto-refresh every 5 seconds
  setInterval(loadApps, 5000);

  // Update clock every second
  updateClock();
  setInterval(updateClock, 1000);
});

// Event Listeners
function initializeEventListeners() {
  // Upload button
  document.getElementById("uploadBtn").addEventListener("click", () => {
    openModal("uploadModal");
  });

  // Deployment guide button
  document.getElementById("deployGuideBtn").addEventListener("click", () => {
    openModal("deployGuideModal");
  });

  // Settings button
  document.getElementById("settingsBtn").addEventListener("click", () => {
    openSettingsModal();
  });

  // Refresh button
  document.getElementById("refreshBtn").addEventListener("click", () => {
    loadApps();
  });

  // Modal close buttons
  document.querySelectorAll(".modal .close").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      const modal = e.target.closest(".modal");
      closeModal(modal.id);
    });
  });

  // Click outside modal to close
  document.querySelectorAll(".modal").forEach((modal) => {
    modal.addEventListener("click", (e) => {
      if (e.target === modal) {
        closeModal(modal.id);
      }
    });
  });

  // Tab switching
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      const tabName = e.target.dataset.tab;
      switchTab(tabName);
    });
  });

  // Forms
  document
    .getElementById("zipUploadForm")
    .addEventListener("submit", handleZipUpload);
  document
    .getElementById("gitUploadForm")
    .addEventListener("submit", handleGitUpload);
  document
    .getElementById("scheduleForm")
    .addEventListener("submit", handleScheduleSubmit);
  document
    .getElementById("settingsForm")
    .addEventListener("submit", handleSettingsSubmit);
  document
    .getElementById("zipUpdateForm")
    .addEventListener("submit", handleZipUpdate);
  document
    .getElementById("gitUpdateForm")
    .addEventListener("submit", handleGitUpdate);
}

// Toggle schedule fields in upload forms
function toggleScheduleFields(formType) {
  const appTypeSelect = document.getElementById(`${formType}AppType`);
  const scheduleFields = document.getElementById(`${formType}ScheduleFields`);

  if (appTypeSelect.value === "SCHEDULED") {
    scheduleFields.style.display = "block";
  } else {
    scheduleFields.style.display = "none";
  }
}

// Toggle between different schedule input types
function toggleScheduleInputs(formType) {
  const scheduleTypeSelect = document.getElementById(`${formType}ScheduleType`);
  const dailyFields = document.getElementById(`${formType}DailyFields`);
  const weeklyFields = document.getElementById(`${formType}WeeklyFields`);
  const multiWeeklyFields = document.getElementById(
    `${formType}MultiWeeklyFields`,
  );
  const intervalFields = document.getElementById(`${formType}IntervalFields`);
  const cronFields = document.getElementById(`${formType}CronFields`);

  // Hide all first
  dailyFields.style.display = "none";
  weeklyFields.style.display = "none";
  if (multiWeeklyFields) multiWeeklyFields.style.display = "none";
  intervalFields.style.display = "none";
  cronFields.style.display = "none";

  // Show the selected one
  const scheduleType = scheduleTypeSelect.value;
  if (scheduleType === "simple_daily") {
    dailyFields.style.display = "block";
  } else if (scheduleType === "simple_weekly") {
    weeklyFields.style.display = "block";
  } else if (scheduleType === "simple_multi_weekly") {
    if (multiWeeklyFields) multiWeeklyFields.style.display = "block";
  } else if (scheduleType === "interval") {
    intervalFields.style.display = "block";
  } else if (scheduleType === "cron") {
    cronFields.style.display = "block";
  }
}

// Toggle schedule type in schedule modal
function toggleScheduleTypeFields() {
  const scheduleType = document.getElementById("scheduleType").value;
  const dailyFields = document.getElementById("dailyFieldsModal");
  const weeklyFields = document.getElementById("weeklyFieldsModal");
  const multiWeeklyFields = document.getElementById("multiWeeklyFieldsModal");
  const intervalFields = document.getElementById("intervalFieldsModal");
  const cronFields = document.getElementById("cronFieldsModal");

  // Hide all first
  dailyFields.style.display = "none";
  weeklyFields.style.display = "none";
  if (multiWeeklyFields) multiWeeklyFields.style.display = "none";
  intervalFields.style.display = "none";
  cronFields.style.display = "none";

  // Show the selected one
  if (scheduleType === "simple_daily") {
    dailyFields.style.display = "block";
  } else if (scheduleType === "simple_weekly") {
    weeklyFields.style.display = "block";
  } else if (scheduleType === "simple_multi_weekly") {
    if (multiWeeklyFields) multiWeeklyFields.style.display = "block";
  } else if (scheduleType === "interval") {
    intervalFields.style.display = "block";
  } else if (scheduleType === "cron") {
    cronFields.style.display = "block";
  }
}

// Modal Management
function openModal(modalId) {
  const modal = document.getElementById(modalId);
  modal.classList.add("active");
}

function closeModal(modalId) {
  const modal = document.getElementById(modalId);
  modal.classList.remove("active");
}

// Progress Modal — shows live logs for long-running background operations
// (uploads, installs, updates) so the UI doesn't look frozen while pip
// installs or a git clone runs.
let progressPollTimer = null;
let progressLoggedCount = 0;

function openProgressModal(title) {
  progressLoggedCount = 0;
  document.getElementById("progressModalTitle").textContent = title;
  document.getElementById("progressLogOutput").textContent = "";
  const spinner = document.getElementById("progressSpinner");
  spinner.className = "spinner";
  document.getElementById("progressStatusText").textContent = "Running...";
  openModal("progressModal");
}

function appendProgressLogs(lines) {
  if (!lines || lines.length === 0) return;
  const output = document.getElementById("progressLogOutput");
  output.textContent += (output.textContent ? "\n" : "") + lines.join("\n");
  output.scrollTop = output.scrollHeight;
}

function setProgressFinished(status, message) {
  const spinner = document.getElementById("progressSpinner");
  spinner.className = `spinner done ${status}`;
  document.getElementById("progressStatusText").textContent = message;
}

function stopProgressPolling() {
  if (progressPollTimer) {
    clearInterval(progressPollTimer);
    progressPollTimer = null;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const dismissBtn = document.getElementById("progressModalDismiss");
  if (dismissBtn) {
    dismissBtn.addEventListener("click", () => {
      closeModal("progressModal");
      stopProgressPolling();
    });
  }
});

/**
 * Start a background task, show a progress modal with live log tailing, and
 * resolve once the task finishes.
 *
 * @param {string} title - shown in the modal header
 * @param {() => Promise<{task_id: string}>} startTask - kicks off the backend task
 * @param {string} successMessage - shown when the task completes
 * @returns {Promise<object>} the task's `result` payload on success
 */
function runWithProgress(title, startTask, successMessage) {
  return new Promise((resolve, reject) => {
    openProgressModal(title);

    startTask()
      .then((startResponse) => {
        const taskId = startResponse.task_id;
        stopProgressPolling();

        progressPollTimer = setInterval(async () => {
          try {
            const res = await fetch(
              `${API_BASE}/apps/tasks/${taskId}?since=${progressLoggedCount}`,
            );
            if (!res.ok) {
              throw new Error(`Failed to fetch task status (${res.status})`);
            }
            const task = await res.json();
            appendProgressLogs(task.logs);
            progressLoggedCount = task.log_count;

            if (task.status === "success") {
              stopProgressPolling();
              setProgressFinished("success", successMessage);
              resolve({ ...(task.result || {}), task_id: taskId });
            } else if (task.status === "failed") {
              stopProgressPolling();
              setProgressFinished("failed", `Failed: ${task.error}`);
              reject(new Error(task.error || "Task failed"));
            }
          } catch (error) {
            stopProgressPolling();
            setProgressFinished("failed", `Failed: ${error.message}`);
            reject(error);
          }
        }, 800);
      })
      .catch((error) => {
        setProgressFinished("failed", `Failed: ${error.message}`);
        reject(error);
      });
  });
}

function switchTab(tabName) {
  // Update tab buttons
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tabName);
  });

  // Update tab content
  document.querySelectorAll(".tab-content").forEach((content) => {
    const contentTab = content.id.replace("Tab", "");
    content.classList.toggle("active", contentTab === tabName);
  });
}

// API Calls
async function apiCall(endpoint, options = {}) {
  try {
    const response = await fetch(`${API_BASE}${endpoint}`, {
      headers: {
        "Content-Type": "application/json",
        ...options.headers,
      },
      ...options,
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "API request failed");
    }

    return await response.json();
  } catch (error) {
    console.error("API Error:", error);
    alert(`Error: ${error.message}`);
    throw error;
  }
}

// Load Apps
async function loadApps() {
  try {
    apps = await apiCall("/apps");

    // Load schedules for each scheduled app
    for (let app of apps) {
      if (app.app_type === "SCHEDULED" || app.app_type === "scheduled") {
        try {
          const schedules = await apiCall(`/schedules?app_id=${app.id}`);
          app.schedules = schedules;
        } catch (error) {
          console.error(`Failed to load schedules for app ${app.id}:`, error);
          app.schedules = [];
        }
      }
    }

    // Check for git updates in parallel (rate-limited to once every 5 minutes per app)
    const GIT_CHECK_TTL_MS = 5 * 60 * 1000;
    const now = Date.now();
    const gitApps = apps.filter(
      (a) => a.git_url && a.state !== "DELETED" && a.state !== "deleted",
    );

    await Promise.all(
      gitApps.map(async (app) => {
        const cached = gitUpdateCache[app.id];
        if (cached && now - cached.timestamp < GIT_CHECK_TTL_MS) {
          app._updateAvailable = cached.updateAvailable;
          app._remoteCommit = cached.remoteCommit;
          return;
        }
        try {
          const result = await fetch(`${API_BASE}/apps/${app.id}/check-git-update`);
          if (result.ok) {
            const data = await result.json();
            gitUpdateCache[app.id] = {
              timestamp: now,
              updateAvailable: data.update_available,
              remoteCommit: data.remote_commit,
            };
            app._updateAvailable = data.update_available;
            app._remoteCommit = data.remote_commit;
          } else {
            // Non-2xx: mark as unknown so the card renders without update indicators
            app._updateAvailable = undefined;
            app._remoteCommit = undefined;
          }
        } catch (error) {
          console.error(`Failed to check git updates for app ${app.id}:`, error);
          app._updateAvailable = undefined;
          app._remoteCommit = undefined;
        }
      }),
    );

    renderApps();
    updateStats();
  } catch (error) {
    console.error("Failed to load apps:", error);
  }
}

// Load System Info
async function loadSystemInfo() {
  try {
    const tzInfo = await apiCall("/settings/timezone");
    systemTimezone = tzInfo.timezone;

    // Update timezone display
    document.getElementById("currentTimezone").textContent = systemTimezone;

    // Update all timezone display elements
    const timezoneInfoElements = document.querySelectorAll(".timezone-info");
    timezoneInfoElements.forEach((el) => {
      el.textContent = `Times are in ${systemTimezone} timezone`;
    });
  } catch (error) {
    console.error("Failed to load system info:", error);
  }
}

// Update clock
function updateClock() {
  const now = new Date();
  const timeString = now.toLocaleTimeString("en-US", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  document.getElementById("currentTime").textContent = timeString;
}

// Format datetime for display
function formatDateTime(dateString) {
  if (!dateString) return "N/A";

  const date = new Date(dateString);
  const now = new Date();
  const diffMs = date - now;
  const diffMins = Math.floor(diffMs / 60000);

  // If within next hour, show relative time
  if (diffMins >= 0 && diffMins < 60) {
    if (diffMins === 0) return "in <1 min";
    return `in ${diffMins} min`;
  }

  // Otherwise show formatted time
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

// Render Apps
// Resolve the link to an app's web interface: a manually-set full URL wins,
// otherwise fall back to the auto-detected port on the current host.
function getAppWebLink(app) {
  if (app.web_url) return app.web_url;
  if (app.web_port) {
    return `${window.location.protocol}//${window.location.hostname}:${app.web_port}`;
  }
  return null;
}

function renderApps() {
  const container = document.getElementById("appsList");

  if (apps.length === 0) {
    container.innerHTML = `
            <div class="empty-state">
                <h3>No applications yet</h3>
                <p>Click "Upload App" to get started</p>
            </div>
        `;
    return;
  }

  container.innerHTML = apps
    .map(
      (app) => `
        <div class="app-card" onclick="showAppDetails(${app.id})">
            <div class="app-header">
                <div>
                    <div class="app-title">${app.display_name}</div>
                    <div class="app-name">${app.name}</div>
                </div>
                <span class="status-badge ${app.state}">${app.state}</span>
            </div>

            ${
              app.description
                ? `<div class="app-description">${app.description}</div>`
                : ""
            }

            <div class="app-meta">
                <div class="meta-item">
                    <span>📦</span>
                    <span>${app.app_type}</span>
                </div>
                <div class="meta-item">
                    <span>🔢</span>
                    <span>v${app.version}</span>
                </div>
                ${
                  app.pid
                    ? `
                <div class="meta-item">
                    <span>🔧</span>
                    <span>PID: ${app.pid}</span>
                </div>
                `
                    : ""
                }
                ${
                  getAppWebLink(app)
                    ? `
                <div class="meta-item">
                    <span>🌐</span>
                    <a href="${escapeHtml(getAppWebLink(app))}" target="_blank" onclick="event.stopPropagation()">Open</a>
                    ${app.web_port_source === "auto" ? `<span class="badge-auto" title="Auto-detected from the running process">auto</span>` : ""}
                </div>
                `
                    : ""
                }
                ${
                  app.schedules &&
                  app.schedules.length > 0 &&
                  app.schedules[0].next_run
                    ? `
                <div class="meta-item">
                    <span>⏰</span>
                    <span>Next: ${formatDateTime(app.schedules[0].next_run)}</span>
                </div>
                `
                    : ""
                }
            </div>

            <div class="app-actions" onclick="event.stopPropagation()">
                ${getAppActions(app)}
            </div>
        </div>
    `,
    )
    .join("");
}

// Get App Actions
function getAppActions(app) {
  let actions = [];

  // State-specific actions
  if (app.state === "UPLOADED" || app.state === "uploaded") {
    actions.push(
      `<button class="btn btn-success btn-small" onclick="installApp(${app.id})">Install</button>`,
    );
  }

  if (
    app.state === "INSTALLED" ||
    app.state === "installed" ||
    app.state === "DISABLED" ||
    app.state === "disabled"
  ) {
    actions.push(
      `<button class="btn btn-success btn-small" onclick="enableApp(${app.id})">Enable</button>`,
    );
  }

  if (
    app.state === "ENABLED" ||
    app.state === "enabled" ||
    app.state === "RUNNING" ||
    app.state === "running" ||
    app.state === "STOPPED" ||
    app.state === "stopped"
  ) {
    actions.push(
      `<button class="btn btn-warning btn-small" onclick="disableApp(${app.id})">Disable</button>`,
    );
  }

  // Perpetual app controls
  if (app.app_type === "PERPETUAL" || app.app_type === "perpetual") {
    if (app.state === "RUNNING" || app.state === "running") {
      actions.push(
        `<button class="btn btn-warning btn-small" onclick="stopApp(${app.id})">Stop</button>`,
      );
      actions.push(
        `<button class="btn btn-secondary btn-small" onclick="restartApp(${app.id})">Restart</button>`,
      );
    } else if (
      app.state === "ENABLED" ||
      app.state === "enabled" ||
      app.state === "STOPPED" ||
      app.state === "stopped" ||
      app.state === "FAILED" ||
      app.state === "failed"
    ) {
      actions.push(
        `<button class="btn btn-success btn-small" onclick="startApp(${app.id})">Start</button>`,
      );
    }
  }

  // Scheduled app controls
  if (app.app_type === "SCHEDULED" || app.app_type === "scheduled") {
    actions.push(
      `<button class="btn btn-secondary btn-small" onclick="manageSchedule(${app.id})">⏰ Schedule</button>`,
    );
    // Run now button for testing
    if (
      app.state === "ENABLED" ||
      app.state === "enabled" ||
      app.state === "STOPPED" ||
      app.state === "stopped" ||
      app.state === "INSTALLED" ||
      app.state === "installed" ||
      app.state === "DISABLED" ||
      app.state === "disabled"
    ) {
      actions.push(
        `<button class="btn btn-success btn-small" onclick="runScheduledApp(${app.id})">▶ Run Now</button>`,
      );
    }
  }

  // Delete
  actions.push(
    `<button class="btn btn-danger btn-small" onclick="deleteApp(${app.id})">Delete</button>`,
  );

  // Update button (for all states except deleted)
  if (app.state !== "deleted" && app.state !== "DELETED") {
    actions.push(
      `<button class="btn btn-primary btn-small" onclick="showUpdateModal(${app.id})">Update</button>`,
    );
  }

  // Git update controls (for git-based apps that are not deleted)
  if (app.git_url && app.state !== "deleted" && app.state !== "DELETED") {
    if (app._updateAvailable === true) {
      const shortCommit = getShortCommit(app._remoteCommit) || "unknown";
      actions.push(
        `<button class="btn btn-success btn-small" onclick="pullGitUpdate(${app.id}, '${shortCommit}')">⬆ Pull Update (${shortCommit})</button>`,
      );
    } else if (app._updateAvailable === false) {
      actions.push(`<span class="btn btn-secondary btn-small" style="opacity:0.6;">✓ Up to date</span>`);
    }
  }

  return actions.join("");
}

// Update Stats
function updateStats() {
  const total = apps.length;
  const running = apps.filter((a) => a.state === "running").length;
  const enabled = apps.filter(
    (a) => a.state === "enabled" || a.state === "running",
  ).length;
  const failed = apps.filter((a) => a.state === "failed").length;

  document.getElementById("totalApps").textContent = total;
  document.getElementById("runningApps").textContent = running;
  document.getElementById("enabledApps").textContent = enabled;
  document.getElementById("failedApps").textContent = failed;
}

// App Actions
async function installApp(appId) {
  if (!confirm("Install dependencies for this app?")) return;

  try {
    await runWithProgress(
      "Installing app...",
      () =>
        fetch(`${API_BASE}/apps/${appId}/install`, { method: "POST" }).then(
          async (res) => {
            if (!res.ok) {
              const error = await res.json();
              throw new Error(error.detail || "Install failed to start");
            }
            return res.json();
          },
        ),
      "App installed successfully",
    );
    loadApps();
  } catch (error) {
    // Progress modal already shows the failure; just refresh state.
    loadApps();
  }
}

async function saveWebLink(appId) {
  const port = document.getElementById("webPortInput").value;
  const url = document.getElementById("webUrlInput").value.trim();

  try {
    await apiCall(`/apps/${appId}`, {
      method: "PATCH",
      body: JSON.stringify({
        web_port: port ? parseInt(port, 10) : null,
        web_url: url || null,
      }),
    });
    await loadApps();
    showAppDetails(appId);
  } catch (error) {
    // Error already handled in apiCall
  }
}

async function clearWebLink(appId) {
  try {
    await apiCall(`/apps/${appId}`, {
      method: "PATCH",
      body: JSON.stringify({ web_port: null, web_url: null }),
    });
    await loadApps();
    showAppDetails(appId);
  } catch (error) {
    // Error already handled in apiCall
  }
}

async function detectWebPortNow(appId) {
  try {
    await apiCall(`/apps/${appId}/detect-port`, { method: "POST" });
    await loadApps();
    showAppDetails(appId);
  } catch (error) {
    // Error already handled in apiCall
  }
}

async function enableApp(appId) {
  try {
    await apiCall(`/apps/${appId}/enable`, { method: "POST" });
    loadApps();
  } catch (error) {
    // Error already handled
  }
}

async function disableApp(appId) {
  try {
    await apiCall(`/apps/${appId}/disable`, { method: "POST" });
    loadApps();
  } catch (error) {
    // Error already handled
  }
}

async function startApp(appId) {
  try {
    await apiCall(`/apps/${appId}/start`, { method: "POST" });
    loadApps();
  } catch (error) {
    // Error already handled
  }
}

async function stopApp(appId) {
  if (confirm("Stop this app?")) {
    try {
      await apiCall(`/apps/${appId}/stop`, { method: "POST" });
      loadApps();
    } catch (error) {
      // Error already handled
    }
  }
}

async function restartApp(appId) {
  if (confirm("Restart this app?")) {
    try {
      await apiCall(`/apps/${appId}/restart`, { method: "POST" });
      loadApps();
    } catch (error) {
      // Error already handled
    }
  }
}

async function runScheduledApp(appId) {
  if (confirm("Run this scheduled app now?")) {
    try {
      await apiCall(`/apps/${appId}/run`, { method: "POST" });
      alert("App execution started. Check Executions tab for results.");
      loadApps();
    } catch (error) {
      // Error already handled
    }
  }
}

async function deleteApp(appId) {
  if (
    confirm(
      "Are you sure you want to delete this app? This action cannot be undone.",
    )
  ) {
    try {
      await apiCall(`/apps/${appId}`, { method: "DELETE" });
      alert("App deleted successfully");
      loadApps();
    } catch (error) {
      // Error already handled
    }
  }
}

// Update App Modal
function showUpdateModal(appId) {
  const app = apps.find((a) => a.id === appId);
  if (!app) {
    alert("App not found");
    return;
  }

  // Set app ID in both forms
  document.getElementById("updateAppId").value = appId;
  document.getElementById("updateGitAppId").value = appId;

  // Set app info
  document.getElementById("updateAppInfo").textContent =
    `Updating: ${app.display_name} (${app.name}) - v${app.version}`;

  // Show/hide Git tab based on whether app is from Git
  const gitTab = document.getElementById("updateGitTab");
  if (app.git_url) {
    gitTab.style.display = "block";
    document.getElementById("updateGitInfo").textContent =
      `Repository: ${app.git_url}\nBranch: ${app.git_branch || "main"}\nCurrent commit: ${getShortCommit(app.git_commit) || "unknown"}`;
  } else {
    gitTab.style.display = "none";
    // Reset to ZIP tab if Git was selected
    switchTab("updateZip");
  }

  openModal("updateModal");
}

// Update Handlers
async function handleZipUpdate(e) {
  e.preventDefault();

  const formData = new FormData(e.target);
  const appId = document.getElementById("updateAppId").value;
  closeModal("updateModal");

  try {
    await runWithProgress(
      "Updating app...",
      () =>
        fetch(`${API_BASE}/apps/${appId}/update/zip`, {
          method: "POST",
          body: formData,
        }).then(async (res) => {
          if (!res.ok) {
            const error = await res.json();
            throw new Error(error.detail || "Update failed to start");
          }
          return res.json();
        }),
      "App updated successfully!",
    );
    e.target.reset();
    loadApps();
  } catch (error) {
    loadApps();
  }
}

async function handleGitUpdate(e) {
  e.preventDefault();

  const appId = document.getElementById("updateGitAppId").value;
  const backup = document.getElementById("updateGitBackup").checked;
  closeModal("updateModal");

  try {
    const formData = new FormData();
    formData.append("backup", backup);

    await runWithProgress(
      "Updating app...",
      () =>
        fetch(`${API_BASE}/apps/${appId}/update/git`, {
          method: "POST",
          body: formData,
        }).then(async (res) => {
          if (!res.ok) {
            const error = await res.json();
            throw new Error(error.detail || "Update failed to start");
          }
          return res.json();
        }),
      "App updated successfully!",
    );
    e.target.reset();
    loadApps();
  } catch (error) {
    loadApps();
  }
}

// Pull the latest Git commit for an app directly from the card button
async function pullGitUpdate(appId, remoteCommitShort) {
  const confirmed = confirm(
    `New commit ${remoteCommitShort} is available.\n\nPull update and restart the app?`,
  );
  if (!confirmed) return;

  try {
    const formData = new FormData();
    formData.append("backup", "true");

    await runWithProgress(
      "Pulling Git updates...",
      () =>
        fetch(`${API_BASE}/apps/${appId}/update/git`, {
          method: "POST",
          body: formData,
        }).then(async (res) => {
          if (!res.ok) {
            const error = await res.json();
            throw new Error(error.detail || "Update failed to start");
          }
          return res.json();
        }),
      "App updated successfully!",
    );

    // Invalidate the cache entry so next load re-checks the remote
    delete gitUpdateCache[appId];
    loadApps();
  } catch (error) {
    loadApps();
  }
}

// Upload Handlers
async function handleZipUpload(e) {
  e.preventDefault();

  const formData = new FormData(e.target);
  closeModal("uploadModal");

  try {
    const result = await runWithProgress(
      "Uploading app...",
      () =>
        fetch(`${API_BASE}/apps/upload/zip`, {
          method: "POST",
          body: formData,
        }).then(async (res) => {
          if (!res.ok) {
            const error = await res.json();
            throw new Error(error.detail || "Upload failed to start");
          }
          return res.json();
        }),
      "App uploaded successfully! Install it to continue.",
    );

    // If it's a scheduled app and schedule info was provided, create the schedule
    const appType = formData.get("app_type");
    if (appType === "SCHEDULED" || appType === "scheduled") {
      await createScheduleFromUpload(result.app_id, formData, "zip");
    }

    e.target.reset();
    loadApps();
  } catch (error) {
    loadApps();
  }
}

async function handleGitUpload(e) {
  e.preventDefault();

  const formData = new FormData(e.target);
  closeModal("uploadModal");

  try {
    const result = await runWithProgress(
      "Cloning repository...",
      () =>
        fetch(`${API_BASE}/apps/upload/git`, {
          method: "POST",
          body: formData,
        }).then(async (res) => {
          if (!res.ok) {
            const error = await res.json();
            throw new Error(error.detail || "Clone failed to start");
          }
          return res.json();
        }),
      "App created from Git successfully! Install it to continue.",
    );

    // If it's a scheduled app and schedule info was provided, create the schedule
    const appType = formData.get("app_type");
    if (appType === "SCHEDULED" || appType === "scheduled") {
      await createScheduleFromUpload(result.app_id, formData, "git");
    }

    e.target.reset();
    loadApps();
  } catch (error) {
    loadApps();
  }
}

// Create schedule from upload form data
async function createScheduleFromUpload(appId, formData, formType) {
  const scheduleType = formData.get("schedule_type") || "simple_daily";
  let scheduleName = formData.get("schedule_name") || "Default Schedule";

  const scheduleData = {
    app_id: appId,
    name: scheduleName,
    is_enabled: true,
  };

  // Convert simple schedule types to cron or interval
  if (scheduleType === "simple_daily") {
    // Daily at specific time - convert to cron
    const time = formData.get("daily_time") || "07:00";
    const [hour, minute] = time.split(":");
    scheduleData.schedule_type = "cron";
    scheduleData.cron_expression = `${minute} ${hour} * * *`;
  } else if (scheduleType === "simple_weekly") {
    // Weekly on specific day - convert to cron
    const time = formData.get("weekly_time") || "07:00";
    const [hour, minute] = time.split(":");
    const dayOfWeek = formData.get("week_day") || "0";
    scheduleData.schedule_type = "cron";
    scheduleData.cron_expression = `${minute} ${hour} * * ${dayOfWeek}`;
  } else if (scheduleType === "simple_multi_weekly") {
    // Multiple days per week - convert to cron
    const time = formData.get("multi_weekly_time") || "07:00";
    const [hour, minute] = time.split(":");
    const selectedDays = formData.getAll("multi_week_days");
    if (selectedDays.length === 0) {
      throw new Error("Please select at least one day");
    }
    const daysString = selectedDays.sort((a, b) => a - b).join(",");
    scheduleData.schedule_type = "cron";
    scheduleData.cron_expression = `${minute} ${hour} * * ${daysString}`;
  } else if (scheduleType === "interval") {
    // Interval - convert to seconds
    const intervalValue = parseInt(formData.get("interval_value") || "5");
    const intervalUnit = formData.get("interval_unit") || "minutes";

    let seconds = intervalValue;
    if (intervalUnit === "minutes") seconds *= 60;
    else if (intervalUnit === "hours") seconds *= 3600;
    else if (intervalUnit === "days") seconds *= 86400;

    scheduleData.schedule_type = "interval";
    scheduleData.interval_seconds = seconds;
  } else if (scheduleType === "cron") {
    // Advanced cron expression
    scheduleData.schedule_type = "cron";
    scheduleData.cron_expression =
      formData.get("cron_expression") || "0 7 * * *";
  }

  try {
    await apiCall("/schedules", {
      method: "POST",
      body: JSON.stringify(scheduleData),
    });
  } catch (error) {
    console.error("Failed to create schedule:", error);
    // Don't fail the upload if schedule creation fails
  }
}

// App Details
async function showAppDetails(appId) {
  currentAppId = appId;
  const app = apps.find((a) => a.id === appId);

  if (!app) return;

  // Load executions
  let executions = [];
  try {
    executions = await apiCall(`/executions?app_id=${appId}&limit=10`);
  } catch (error) {
    console.error("Failed to load executions:", error);
  }

  // Load schedules
  let schedules = [];
  try {
    schedules = await apiCall(`/schedules?app_id=${appId}`);
  } catch (error) {
    console.error("Failed to load schedules:", error);
  }

  const content = document.getElementById("appDetailsContent");
  content.innerHTML = `
        <h2>${app.display_name}</h2>
        <p class="app-name">${app.name}</p>

        <div style="margin: 1.5rem 0;">
            <h3>Status</h3>
            <p><strong>State:</strong> <span class="status-badge ${
              app.state
            }">${app.state}</span></p>
            <p><strong>Type:</strong> ${app.app_type}</p>
            <p><strong>Version:</strong> ${app.version}</p>
            ${app.pid ? `<p><strong>PID:</strong> ${app.pid}</p>` : ""}
            ${
              app.restart_count > 0
                ? `<p><strong>Restart Count:</strong> ${app.restart_count}</p>`
                : ""
            }
        </div>

        ${
          app.description
            ? `
        <div style="margin: 1.5rem 0;">
            <h3>Description</h3>
            <p>${app.description}</p>
        </div>
        `
            : ""
        }

        <div style="margin: 1.5rem 0;">
            <h3>Web Interface</h3>
            ${
              getAppWebLink(app)
                ? `
            <p>
                <a href="${escapeHtml(getAppWebLink(app))}" target="_blank">${escapeHtml(getAppWebLink(app))}</a>
                ${
                  app.web_port_source === "auto"
                    ? `<span class="badge-auto" title="Detected automatically from the running process">auto-detected</span>`
                    : `<span class="badge-auto" title="Set manually">manual</span>`
                }
            </p>
            `
                : `<p style="color: var(--text-secondary);">No web interface detected yet.</p>`
            }
            <div style="display: flex; gap: 0.5rem; flex-wrap: wrap; margin: 0.5rem 0;">
                <input type="number" id="webPortInput" placeholder="Port" value="${app.web_port || ""}" style="width: 90px;">
                <input type="text" id="webUrlInput" placeholder="Custom URL (optional, overrides port)" value="${escapeHtml(app.web_url || "")}" style="flex: 1; min-width: 200px;">
            </div>
            <div style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
                <button class="btn btn-primary btn-small" onclick="saveWebLink(${app.id})">Save</button>
                <button class="btn btn-secondary btn-small" onclick="clearWebLink(${app.id})">Reset to auto-detect</button>
                <button class="btn btn-secondary btn-small" onclick="detectWebPortNow(${app.id})" ${app.pid ? "" : "disabled"}>Detect now</button>
            </div>
        </div>

        <div style="margin: 1.5rem 0;">
            <h3>Configuration</h3>
            <p><strong>Entrypoint:</strong> <code>${app.entrypoint}</code></p>
            <p><strong>Restart Policy:</strong> ${app.restart_policy}</p>
            ${
              app.git_url
                ? `<p><strong>Git URL:</strong> ${app.git_url}</p>`
                : ""
            }
            ${
              app.git_branch
                ? `<p><strong>Git Branch:</strong> ${app.git_branch}</p>`
                : ""
            }
        </div>

        ${
          executions.length > 0
            ? `
        <div style="margin: 1.5rem 0;">
            <h3>Recent Executions</h3>
            <div style="max-height: 300px; overflow-y: auto;">
                ${executions
                  .map((exec) => {
                    const dur =
                      exec.started_at && exec.ended_at
                        ? formatDuration(
                            (new Date(exec.ended_at) - new Date(exec.started_at)) / 1000,
                          )
                        : null;
                    return `
                    <div style="background: var(--bg-tertiary); padding: 0.8rem; margin: 0.5rem 0; border-radius: 4px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                            <div>
                                <strong>#${exec.id}</strong> &nbsp;
                                <span class="status-badge ${exec.status}">${exec.status}</span>
                                ${exec.exit_code !== null ? ` &nbsp; <strong>Exit:</strong> ${exec.exit_code}` : ""}
                                ${dur ? ` &nbsp; <strong>Duration:</strong> ${dur}` : ""}
                            </div>
                            <button class="btn btn-sm btn-secondary" onclick="viewExecutionLogs(${exec.id})">
                                📄 View Logs
                            </button>
                        </div>
                        ${
                          exec.started_at
                            ? `<div style="font-size: 0.85em; color: var(--text-secondary);">
                                <strong>Started:</strong> ${new Date(exec.started_at).toLocaleString()}
                                ${exec.ended_at ? ` &rarr; ${new Date(exec.ended_at).toLocaleString()}` : ""}
                               </div>`
                            : ""
                        }
                        ${
                          exec.error_message
                            ? `<div style="font-size: 0.85em; color: var(--error); margin-top: 0.25rem;">⚠ ${escapeHtml(exec.error_message)}</div>`
                            : ""
                        }
                    </div>
                `;
                  })
                  .join("")}
            </div>
        </div>
        `
            : `
        <div style="margin: 1.5rem 0;">
            <h3>Recent Executions</h3>
            <p style="color: var(--text-secondary);">No executions recorded yet.</p>
        </div>
        `
        }

        ${
          schedules.length > 0
            ? `
        <div style="margin: 1.5rem 0;">
            <h3>Schedules</h3>
            ${schedules
              .map(
                (sched) => `
                <div style="background: var(--bg-tertiary); padding: 0.8rem; margin: 0.5rem 0; border-radius: 4px;">
                    <div><strong>${sched.name}</strong> - ${
                      sched.schedule_type
                    } ${sched.is_enabled ? "✓" : "✗"}</div>
                    <div>${
                      sched.cron_expression ||
                      `Every ${formatInterval(sched.interval_seconds)}`
                    }</div>
                    <div>Run count: ${sched.run_count} | Last: ${
                      sched.last_run
                        ? new Date(sched.last_run).toLocaleString()
                        : "Never"
                    }</div>
                </div>
            `,
              )
              .join("")}
        </div>
        `
            : ""
        }
    `;

  openModal("appDetailsModal");
}

// Format interval seconds to human-readable
function formatInterval(seconds) {
  if (!seconds) return "N/A";
  if (seconds < 60) return `${seconds} seconds`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} minutes`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} hours`;
  return `${Math.floor(seconds / 86400)} days`;
}

// Manage Schedule
async function manageSchedule(appId) {
  const app = apps.find((a) => a.id === appId);
  if (!app) return;

  // Load existing schedules
  let schedules = [];
  try {
    schedules = await apiCall(`/schedules?app_id=${appId}`);
  } catch (error) {
    console.error("Failed to load schedules:", error);
  }

  // If schedule exists, populate form for editing
  if (schedules.length > 0) {
    const schedule = schedules[0]; // Use first schedule
    document.getElementById("scheduleModalTitle").textContent = "Edit Schedule";
    document.getElementById("scheduleId").value = schedule.id;
    document.getElementById("scheduleName").value = schedule.name;
    document.getElementById("scheduleDescription").value =
      schedule.description || "";
    document.getElementById("scheduleEnabled").checked = schedule.is_enabled;

    // Detect schedule type and populate appropriate fields
    let detectedType = schedule.schedule_type;

    if (schedule.schedule_type === "interval") {
      // Convert seconds back to human-readable
      const seconds = schedule.interval_seconds;
      let value, unit;
      if (seconds % 86400 === 0) {
        value = seconds / 86400;
        unit = "days";
      } else if (seconds % 3600 === 0) {
        value = seconds / 3600;
        unit = "hours";
      } else {
        value = seconds / 60;
        unit = "minutes";
      }
      document.getElementById("intervalValue").value = value;
      document.getElementById("intervalUnit").value = unit;
      detectedType = "interval";
    } else if (schedule.schedule_type === "cron") {
      // Try to detect if it's a simple daily or weekly pattern
      const cron = schedule.cron_expression;
      const parts = cron.split(" ");

      // Check for daily pattern: "M H * * *"
      if (
        parts.length === 5 &&
        parts[2] === "*" &&
        parts[3] === "*" &&
        parts[4] === "*"
      ) {
        const minute = parts[0];
        const hour = parts[1];
        const time = `${hour.padStart(2, "0")}:${minute.padStart(2, "0")}`;
        document.getElementById("dailyTime").value = time;
        detectedType = "simple_daily";
      }
      // Check for weekly pattern: "M H * * D" or multi-weekly "M H * * D1,D2,D3"
      else if (
        parts.length === 5 &&
        parts[2] === "*" &&
        parts[3] === "*" &&
        parts[4] !== "*"
      ) {
        const minute = parts[0];
        const hour = parts[1];
        const time = `${hour.padStart(2, "0")}:${minute.padStart(2, "0")}`;
        const daysString = parts[4];

        // Check if it's multiple days (contains comma)
        if (daysString.includes(",")) {
          // Multi-day weekly pattern
          const days = daysString.split(",");
          document.getElementById("multiWeeklyTime").value = time;
          // Check the appropriate day checkboxes
          const checkboxes = document.querySelectorAll(
            'input[name="multi_week_days"]',
          );
          checkboxes.forEach((checkbox) => {
            checkbox.checked = days.includes(checkbox.value);
          });
          detectedType = "simple_multi_weekly";
        } else {
          // Single day weekly pattern
          document.getElementById("weeklyTime").value = time;
          document.getElementById("weekDay").value = daysString;
          detectedType = "simple_weekly";
        }
      }
      // Otherwise it's an advanced cron
      else {
        document.getElementById("cronExpression").value = cron;
        detectedType = "cron";
      }
    }

    document.getElementById("scheduleType").value = detectedType;
    toggleScheduleTypeFields();
  } else {
    // New schedule
    document.getElementById("scheduleModalTitle").textContent =
      "Create Schedule";
    document.getElementById("scheduleForm").reset();
    document.getElementById("scheduleId").value = "";
    document.getElementById("scheduleName").value =
      `${app.display_name} Schedule`;
    toggleScheduleTypeFields();
  }

  document.getElementById("scheduleAppId").value = appId;
  openModal("scheduleModal");
}

// Handle schedule form submission
async function handleScheduleSubmit(e) {
  e.preventDefault();

  const formData = new FormData(e.target);
  const scheduleId = formData.get("schedule_id");
  const appId = formData.get("app_id");
  const scheduleType = formData.get("schedule_type");

  const scheduleData = {
    app_id: parseInt(appId),
    name: formData.get("name"),
    description: formData.get("description") || null,
    is_enabled: document.getElementById("scheduleEnabled").checked,
  };

  // Convert simple schedule types to cron or interval
  if (scheduleType === "simple_daily") {
    // Daily at specific time - convert to cron
    const time = formData.get("daily_time") || "07:00";
    const [hour, minute] = time.split(":");
    scheduleData.schedule_type = "cron";
    scheduleData.cron_expression = `${minute} ${hour} * * *`;
  } else if (scheduleType === "simple_weekly") {
    // Weekly on specific day - convert to cron
    const time = formData.get("weekly_time") || "07:00";
    const [hour, minute] = time.split(":");
    const dayOfWeek = formData.get("week_day") || "0";
    scheduleData.schedule_type = "cron";
    scheduleData.cron_expression = `${minute} ${hour} * * ${dayOfWeek}`;
  } else if (scheduleType === "simple_multi_weekly") {
    // Multiple days per week - convert to cron
    const time = formData.get("multi_weekly_time") || "07:00";
    const [hour, minute] = time.split(":");
    const selectedDays = formData.getAll("multi_week_days");
    if (selectedDays.length === 0) {
      alert("Please select at least one day");
      return;
    }
    const daysString = selectedDays.sort((a, b) => a - b).join(",");
    scheduleData.schedule_type = "cron";
    scheduleData.cron_expression = `${minute} ${hour} * * ${daysString}`;
  } else if (scheduleType === "interval") {
    // Interval - convert to seconds
    const intervalValue = parseInt(formData.get("interval_value"));
    const intervalUnit = formData.get("interval_unit");

    let seconds = intervalValue;
    if (intervalUnit === "minutes") seconds *= 60;
    else if (intervalUnit === "hours") seconds *= 3600;
    else if (intervalUnit === "days") seconds *= 86400;

    scheduleData.schedule_type = "interval";
    scheduleData.interval_seconds = seconds;
  } else if (scheduleType === "cron") {
    // Advanced cron expression
    scheduleData.schedule_type = "cron";
    scheduleData.cron_expression = formData.get("cron_expression");
  }

  try {
    if (scheduleId) {
      // Update existing schedule
      await apiCall(`/schedules/${scheduleId}`, {
        method: "PATCH",
        body: JSON.stringify(scheduleData),
      });
      alert("Schedule updated successfully");
    } else {
      // Create new schedule
      await apiCall("/schedules", {
        method: "POST",
        body: JSON.stringify(scheduleData),
      });
      alert("Schedule created successfully");
    }

    closeModal("scheduleModal");
    loadApps();
  } catch (error) {
    // Error already handled in apiCall
  }
}

// Settings Management
async function openSettingsModal() {
  openModal("settingsModal");

  // Load current settings and available timezones
  try {
    const [settings, tzData] = await Promise.all([
      apiCall("/settings"),
      apiCall("/settings/available-timezones"),
    ]);

    const tzInfo = await apiCall("/settings/timezone");

    // Populate timezone select
    const select = document.getElementById("timezoneSelect");
    select.innerHTML = "";

    // Add common timezones first
    const commonTimezones = [
      "America/New_York",
      "America/Chicago",
      "America/Denver",
      "America/Los_Angeles",
      "America/Phoenix",
      "Europe/London",
      "Europe/Paris",
      "Asia/Tokyo",
      "Australia/Sydney",
      "UTC",
    ];

    const commonGroup = document.createElement("optgroup");
    commonGroup.label = "Common Timezones";
    commonTimezones.forEach((tz) => {
      const option = document.createElement("option");
      option.value = tz;
      option.textContent = tz;
      commonGroup.appendChild(option);
    });
    select.appendChild(commonGroup);

    // Add all timezones grouped by region
    Object.entries(tzData.grouped).forEach(([region, timezones]) => {
      const group = document.createElement("optgroup");
      group.label = region;
      timezones.forEach((tz) => {
        const option = document.createElement("option");
        option.value = tz;
        option.textContent = tz;
        group.appendChild(option);
      });
      select.appendChild(group);
    });

    // Set current timezone
    select.value = tzInfo.timezone;

    // Show detected timezone
    document.getElementById("detectedTimezone").textContent =
      tzInfo.detected_timezone;
  } catch (error) {
    console.error("Failed to load settings:", error);
    alert("Failed to load settings");
  }
}

async function handleSettingsSubmit(e) {
  e.preventDefault();

  const formData = new FormData(e.target);
  const timezone = formData.get("timezone");

  try {
    const result = await apiCall("/settings/timezone", {
      method: "PUT",
      body: JSON.stringify({ value: timezone }),
    });

    alert(result.message);
    closeModal("settingsModal");

    // Reload system info to update timezone displays
    loadSystemInfo();
  } catch (error) {
    // Error already handled in apiCall
  }
}

// Backup & Restore
async function exportBackup() {
  try {
    const result = await runWithProgress(
      "Creating backup...",
      () =>
        fetch(`${API_BASE}/backup/export`, { method: "POST" }).then(
          async (res) => {
            if (!res.ok) {
              const error = await res.json();
              throw new Error(error.detail || "Backup failed to start");
            }
            return res.json();
          },
        ),
      "Backup created successfully!",
    );

    // Trigger the browser download of the finished archive
    window.location.href = `${API_BASE}/backup/export/${result.task_id}/download`;
  } catch (error) {
    // Error already surfaced by the progress modal
  }
}

async function importBackup() {
  const fileInput = document.getElementById("restoreFileInput");
  const file = fileInput.files[0];
  if (!file) {
    alert("Choose a backup file first.");
    return;
  }

  const confirmed = confirm(
    "This will stop every app and permanently replace the current database " +
      "and app files with the contents of this backup. This cannot be undone. " +
      "Continue?",
  );
  if (!confirmed) return;

  const formData = new FormData();
  formData.append("file", file);

  try {
    await runWithProgress(
      "Restoring backup...",
      () =>
        fetch(`${API_BASE}/backup/import`, {
          method: "POST",
          body: formData,
        }).then(async (res) => {
          if (!res.ok) {
            const error = await res.json();
            throw new Error(error.detail || "Restore failed to start");
          }
          return res.json();
        }),
      "Backup restored successfully! Reloading...",
    );

    fileInput.value = "";
    closeModal("settingsModal");
    setTimeout(() => window.location.reload(), 1000);
  } catch (error) {
    // Error already surfaced by the progress modal
  }
}

// Scheduler Debug Functions
function toggleSchedulerDebug() {
  const panel = document.getElementById("schedulerDebugPanel");
  if (panel.style.display === "none") {
    panel.style.display = "block";
    refreshSchedulerDebug();
  } else {
    panel.style.display = "none";
  }
}

async function refreshSchedulerDebug() {
  const content = document.getElementById("schedulerDebugContent");
  content.innerHTML = '<p class="loading">Loading scheduler information...</p>';

  try {
    const status = await apiCall("/schedules/debug/scheduler-status");

    let html = `
      <div class="debug-info">
        <div class="debug-row">
          <strong>Scheduler Running:</strong>
          <span class="${status.running ? "status-running" : "status-stopped"}">
            ${status.running ? "✓ Yes" : "✗ No"}
          </span>
        </div>
        <div class="debug-row">
          <strong>Scheduler Timezone:</strong>
          <span>${status.scheduler_timezone || "Not set"}</span>
        </div>
        <div class="debug-row">
          <strong>Current Server Time:</strong>
          <span>${
            status.current_time
              ? new Date(status.current_time).toLocaleString()
              : "Unknown"
          }</span>
        </div>
        <div class="debug-row">
          <strong>Number of Jobs:</strong>
          <span>${status.num_jobs}</span>
        </div>
      </div>
    `;

    if (status.jobs && status.jobs.length > 0) {
      html += `
        <div class="debug-section">
          <h4>Scheduled Jobs:</h4>
          <table class="debug-table">
            <thead>
              <tr>
                <th>Job ID</th>
                <th>Name</th>
                <th>Next Run (UTC)</th>
                <th>Next Run (Local)</th>
                <th>Trigger</th>
              </tr>
            </thead>
            <tbody>
      `;

      status.jobs.forEach((job) => {
        const nextRunUTC = job.next_run_time
          ? new Date(job.next_run_time).toLocaleString()
          : "Not scheduled";

        const nextRunLocal = job.next_run_time_local
          ? formatDateTime(new Date(job.next_run_time_local))
          : "Not scheduled";

        html += `
          <tr>
            <td><code>${job.id}</code></td>
            <td>${job.name}</td>
            <td>${nextRunUTC}</td>
            <td>${nextRunLocal}</td>
            <td><code>${job.trigger}</code></td>
          </tr>
        `;
      });

      html += `
            </tbody>
          </table>
        </div>
      `;
    } else {
      html += `
        <div class="debug-info">
          <p><em>No jobs currently scheduled</em></p>
        </div>
      `;
    }

    contentEl.innerHTML = html;
  } catch (error) {
    contentEl.innerHTML = `
      <div style="color: var(--error-color);">
        <p><strong>Error loading scheduler status:</strong></p>
        <p>${error.message}</p>
      </div>
    `;
  }
}

// Strip ANSI escape codes from terminal output
function stripAnsi(str) {
  return str.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, "");
}

// Format a duration in seconds as a human-readable string
function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return null;
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

// View execution logs
async function viewExecutionLogs(executionId) {
  try {
    const [stdoutRes, stderrRes, execution] = await Promise.all([
      fetch(`${API_BASE}/executions/${executionId}/stdout`),
      fetch(`${API_BASE}/executions/${executionId}/stderr`),
      apiCall(`/executions/${executionId}`),
    ]);

    const stdoutData = await stdoutRes.json();
    const stderrData = await stderrRes.json();

    const stdout = stripAnsi(stdoutData.output || "");
    const stderr = stripAnsi(stderrData.output || "");

    const duration =
      execution.started_at && execution.ended_at
        ? formatDuration(
            (new Date(execution.ended_at) - new Date(execution.started_at)) / 1000
          )
        : null;

    const content = document.getElementById("logsModalContent");
    content.innerHTML = `
      <div class="logs-header">
        <h3>Execution #${executionId} Logs</h3>
        <div class="logs-info">
          <p><strong>Status:</strong> <span class="status-badge ${execution.status}">${execution.status}</span></p>
          ${execution.exit_code !== null ? `<p><strong>Exit Code:</strong> ${execution.exit_code}</p>` : ""}
          ${execution.started_at ? `<p><strong>Started:</strong> ${new Date(execution.started_at).toLocaleString()}</p>` : ""}
          ${execution.ended_at ? `<p><strong>Ended:</strong> ${new Date(execution.ended_at).toLocaleString()}</p>` : ""}
          ${duration ? `<p><strong>Duration:</strong> ${duration}</p>` : ""}
          ${execution.trigger_type ? `<p><strong>Trigger:</strong> ${execution.trigger_type}${execution.trigger_details ? ` (${execution.trigger_details})` : ""}</p>` : ""}
        </div>
      </div>

      ${
        execution.error_message
          ? `<div class="logs-error-banner">
              <strong>⚠ Error:</strong> ${escapeHtml(execution.error_message)}
            </div>`
          : ""
      }

      <div class="logs-section">
        <h4 style="color: var(--success-color); margin-bottom: 0.5rem;">📤 Standard Output (stdout)</h4>
        <pre class="log-output">${stdout ? escapeHtml(stdout) : '<span style="opacity:0.5">(empty)</span>'}</pre>
      </div>

      <div class="logs-section">
        <h4 style="color: var(--error-color); margin-bottom: 0.5rem;">📥 Standard Error (stderr)</h4>
        <pre class="log-output">${stderr ? escapeHtml(stderr) : '<span style="opacity:0.5">(empty)</span>'}</pre>
      </div>
    `;

    openModal("logsModal");
  } catch (error) {
    alert(`Failed to load logs: ${error.message}`);
  }
}

// Helper to escape HTML
function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}
