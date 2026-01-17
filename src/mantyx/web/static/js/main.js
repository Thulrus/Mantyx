// Mantyx Frontend JavaScript

// API Base URL
const API_BASE = "/api";

// State
let apps = [];
let currentAppId = null;
let systemTimezone = "UTC";

// Initialize
document.addEventListener("DOMContentLoaded", () => {
  initializeEventListeners();
  loadSystemInfo();
  loadApps();

  // Auto-refresh every 5 seconds
  setInterval(loadApps, 5000);
});

// Event Listeners
function initializeEventListeners() {
  // Upload button
  document.getElementById("uploadBtn").addEventListener("click", () => {
    openModal("uploadModal");
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
  const intervalFields = document.getElementById(`${formType}IntervalFields`);
  const cronFields = document.getElementById(`${formType}CronFields`);

  // Hide all first
  dailyFields.style.display = "none";
  weeklyFields.style.display = "none";
  intervalFields.style.display = "none";
  cronFields.style.display = "none";

  // Show the selected one
  const scheduleType = scheduleTypeSelect.value;
  if (scheduleType === "simple_daily") {
    dailyFields.style.display = "block";
  } else if (scheduleType === "simple_weekly") {
    weeklyFields.style.display = "block";
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
  const intervalFields = document.getElementById("intervalFieldsModal");
  const cronFields = document.getElementById("cronFieldsModal");

  // Hide all first
  dailyFields.style.display = "none";
  weeklyFields.style.display = "none";
  intervalFields.style.display = "none";
  cronFields.style.display = "none";

  // Show the selected one
  if (scheduleType === "simple_daily") {
    dailyFields.style.display = "block";
  } else if (scheduleType === "simple_weekly") {
    weeklyFields.style.display = "block";
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
    renderApps();
    updateStats();
  } catch (error) {
    console.error("Failed to load apps:", error);
  }
}

// Load System Info
async function loadSystemInfo() {
  try {
    const info = await apiCall("/system/info");
    systemTimezone = info.timezone;

    // Update all timezone display elements
    const timezoneInfoElements = document.querySelectorAll(".timezone-info");
    timezoneInfoElements.forEach((el) => {
      el.textContent = `Times are in ${systemTimezone} timezone`;
    });
  } catch (error) {
    console.error("Failed to load system info:", error);
  }
}

// Render Apps
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
                  app.web_url
                    ? `
                <div class="meta-item">
                    <span>🌐</span>
                    <a href="${app.web_url}" target="_blank" onclick="event.stopPropagation()">Open</a>
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
  if (confirm("Install dependencies for this app?")) {
    try {
      await apiCall(`/apps/${appId}/install`, { method: "POST" });
      alert("App installed successfully");
      loadApps();
    } catch (error) {
      // Error already handled in apiCall
    }
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

// Upload Handlers
async function handleZipUpload(e) {
  e.preventDefault();

  const formData = new FormData(e.target);

  try {
    const response = await fetch(`${API_BASE}/apps/upload/zip`, {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "Upload failed");
    }

    const result = await response.json();

    // If it's a scheduled app and schedule info was provided, create the schedule
    const appType = formData.get("app_type");
    if (appType === "SCHEDULED" || appType === "scheduled") {
      await createScheduleFromUpload(result.app_id, formData, "zip");
    }

    alert(`App uploaded successfully! Install it to continue.`);
    closeModal("uploadModal");
    e.target.reset();
    loadApps();
  } catch (error) {
    alert(`Upload failed: ${error.message}`);
  }
}

async function handleGitUpload(e) {
  e.preventDefault();

  const formData = new FormData(e.target);

  try {
    const response = await fetch(`${API_BASE}/apps/upload/git`, {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "Upload failed");
    }

    const result = await response.json();

    // If it's a scheduled app and schedule info was provided, create the schedule
    const appType = formData.get("app_type");
    if (appType === "SCHEDULED" || appType === "scheduled") {
      await createScheduleFromUpload(result.app_id, formData, "git");
    }

    alert(`App created from Git successfully! Install it to continue.`);
    closeModal("uploadModal");
    e.target.reset();
    loadApps();
  } catch (error) {
    alert(`Upload failed: ${error.message}`);
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
                  .map(
                    (exec) => `
                    <div style="background: var(--bg-tertiary); padding: 0.8rem; margin: 0.5rem 0; border-radius: 4px;">
                        <div><strong>ID:</strong> ${
                          exec.id
                        } | <strong>Status:</strong> ${exec.status}</div>
                        ${
                          exec.started_at
                            ? `<div><strong>Started:</strong> ${new Date(
                                exec.started_at,
                              ).toLocaleString()}</div>`
                            : ""
                        }
                        ${
                          exec.exit_code !== null
                            ? `<div><strong>Exit Code:</strong> ${exec.exit_code}</div>`
                            : ""
                        }
                    </div>
                `,
                  )
                  .join("")}
            </div>
        </div>
        `
            : ""
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
    document.getElementById("scheduleType").value = schedule.schedule_type;
    document.getElementById("scheduleEnabled").checked = schedule.is_enabled;

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
    } else {
      document.getElementById("cronExpression").value =
        schedule.cron_expression;
    }

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
