// Mantyx web UI.
//
// Two views, chosen by the URL hash:
//   #/            dashboard: every app as a card with a plain-English status
//   #/app/<id>    one app: status explanation, logs, runs, schedules, settings, versions
//
// App state is polled from the API every few seconds; the server computes the
// user-facing status (see mantyx/core/status.py) so the UI only explains it.
"use strict";

const POLL_MS = 4000;
const POLL_HIDDEN_MS = 15000;
const TASK_POLL_MS = 700;
const LOG_POLL_MS = 1500;
const MAX_LOG_CHARS = 600000;

const state = {
  apps: [],
  loaded: false,
  loadError: null,
  filter: "all",
  search: "",
  systemInfo: null,
  route: { name: "dashboard" },
  cardCache: new Map(),
  detail: null, // per-detail-page state, reset on navigation
};

const view = () => document.getElementById("view");
const appById = (id) => state.apps.find((a) => a.id === Number(id));
const isPerpetual = (app) => String(app.app_type).toLowerCase() === "perpetual";
const isScheduled = (app) => String(app.app_type).toLowerCase() === "scheduled";
const lower = (v) => String(v || "").toLowerCase();

// ── Status presentation ──────────────────────────────────────────────────────

const STATUS_TONE = {
  running: "success",
  running_now: "active",
  starting: "active",
  working: "active",
  scheduled: "info",
  paused: "neutral",
  stopped: "neutral",
  not_installed: "warning",
  no_schedule: "warning",
  failed: "danger",
  last_failed: "danger",
};

function statusPill(app) {
  const tone = STATUS_TONE[app.status] || "neutral";
  return `<span class="pill pill-${tone}"><span class="pill-dot"></span>${esc(app.status_label || app.status)}</span>`;
}

function runningSince(app) {
  return app.current_run && app.current_run.started_at;
}

function recentlyRestarted(app) {
  if (!app.restart_count || !app.last_restart_at) return false;
  return Date.now() - toDate(app.last_restart_at).getTime() < 3600 * 1000;
}

/** One short line under the status pill. */
function statusDetail(app) {
  const last = app.last_run;
  switch (app.status) {
    case "working":
      return "In progress…";
    case "not_installed":
      return "Dependencies haven't been installed yet";
    case "running": {
      const parts = [];
      const since = runningSince(app);
      if (since) parts.push(`Up ${fmtDuration((Date.now() - toDate(since)) / 1000)}`);
      if (recentlyRestarted(app)) parts.push(`restarted ${fmtAgo(app.last_restart_at)} after a crash`);
      return parts.join(" · ") || "Running";
    }
    case "starting":
      return "Starting up…";
    case "failed":
      return app.last_error || "Stopped unexpectedly";
    case "stopped":
      return "Not running";
    case "running_now":
      return app.current_run ? `Started ${fmtAgo(app.current_run.started_at)}` : "Running";
    case "paused":
      return lower(app.state) === "installed"
        ? "Not activated yet, so it won't run on a schedule"
        : "Scheduled runs are skipped while paused";
    case "no_schedule":
      return "No schedule yet, so it only runs when you click Run now";
    case "last_failed": {
      const when = last ? fmtAgo(last.ended_at || last.started_at) : "";
      const why = last && last.exit_code !== null && last.exit_code !== undefined ? `exit code ${last.exit_code}` : last?.error_message || "";
      return [when && `Failed ${when}`, why, app.next_run && `next run ${fmtWhen(app.next_run)}`].filter(Boolean).join(" · ");
    }
    case "scheduled": {
      const parts = [];
      if (app.next_run) parts.push(`Next run ${fmtWhen(app.next_run)}`);
      if (last && last.ended_at) {
        parts.push(last.status === "success" ? `last run OK ${fmtAgo(last.ended_at)}` : `last run ${last.status} ${fmtAgo(last.ended_at)}`);
      }
      return parts.join(" · ") || "Waiting for its next run";
    }
    default:
      return "";
  }
}

function typeLabel(app) {
  return isPerpetual(app) ? "Always running" : "Scheduled";
}

function typeIcon(app) {
  return isPerpetual(app) ? icon("refresh") : icon("clock");
}

function webLink(app) {
  if (app.web_url) return app.web_url;
  if (app.web_port) return `${window.location.protocol}//${window.location.hostname}:${app.web_port}`;
  return null;
}

function btn(label, action, appId, { kind = "secondary", iconName = null, size = "", extra = "", title = "" } = {}) {
  return `<button type="button" class="btn btn-${kind}${size ? ` btn-${size}` : ""}" data-action="${action}" data-app-id="${appId}" ${title ? `title="${esc(title)}"` : ""} ${extra}>${iconName ? icon(iconName) : ""}<span>${esc(label)}</span></button>`;
}

/** The one most useful action for an app right now. */
function primaryAction(app, size = "sm") {
  const id = app.id;
  switch (app.status) {
    case "working":
      return app.active_task ? btn("Show progress", "show-task", id, { size, extra: `data-task-id="${esc(app.active_task.id)}"` }) : "";
    case "not_installed":
      return btn("Install", "install", id, { kind: "primary", iconName: "download", size });
    case "running":
    case "starting":
      return btn("Stop", "stop", id, { iconName: "stop", size });
    case "stopped":
    case "failed":
      return btn("Start", "start", id, { kind: "primary", iconName: "play", size });
    case "running_now":
      return app.current_run ? btn("Stop run", "cancel-run", id, { iconName: "stop", size, extra: `data-execution-id="${app.current_run.id}"` }) : "";
    case "paused":
      return btn(lower(app.state) === "installed" ? "Activate" : "Resume", "enable", id, { kind: "primary", iconName: "play", size });
    case "no_schedule":
      return btn("Add schedule", "add-schedule", id, { kind: "primary", iconName: "calendar", size });
    default:
      return btn("Run now", "run-now", id, { iconName: "play", size });
  }
}

function appMenuItems(app, { inDetail = false } = {}) {
  const installed = app.status !== "not_installed";
  const busy = app.status === "working";
  const items = [];
  if (!inDetail) items.push({ label: "Open", action: "open", icon: "info" });
  if (isPerpetual(app) && ["running", "starting"].includes(app.status))
    items.push({ label: "Restart", action: "restart", icon: "restart", disabled: busy });
  if (isScheduled(app) && installed && app.status !== "running_now")
    items.push({ label: "Run now", action: "run-now", icon: "play", disabled: busy });
  if (isScheduled(app) && installed) {
    items.push(
      app.enabled && lower(app.state) !== "installed"
        ? { label: "Pause schedule", action: "disable", icon: "pause", disabled: busy }
        : { label: lower(app.state) === "installed" ? "Activate" : "Resume schedule", action: "enable", icon: "play", disabled: busy },
    );
  }
  if (!inDetail) items.push({ label: "View logs", action: "open-logs", icon: "terminal" });
  items.push({ label: "Update…", action: "update", icon: "upload", disabled: busy });
  items.push("divider");
  items.push({ label: installed ? "Rebuild environment…" : "Retry install", action: installed ? "rebuild" : "install", icon: "wrench", disabled: busy });
  items.push({ label: "Delete…", action: "delete", icon: "trash", danger: true, disabled: busy });
  return items;
}

// ── Data loading ─────────────────────────────────────────────────────────────

let pollTimer = null;

async function refreshApps() {
  clearTimeout(pollTimer);
  try {
    state.apps = await api("/apps");
    state.loaded = true;
    state.loadError = null;
    renderCurrent();
  } catch (err) {
    state.loadError = err.message;
    if (!state.loaded) renderCurrent();
  } finally {
    pollTimer = setTimeout(refreshApps, document.hidden ? POLL_HIDDEN_MS : POLL_MS);
  }
}

async function loadSystemInfo() {
  try {
    state.systemInfo = await api("/system/info");
  } catch {
    /* clock falls back to browser time */
  }
  updateClock();
}

function updateClock() {
  const el = document.getElementById("clock");
  const tz = state.systemInfo && state.systemInfo.timezone;
  let time;
  try {
    time = new Date().toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", timeZone: tz || undefined });
  } catch {
    time = fmtTime(new Date());
  }
  el.innerHTML = `${icon("clock")}<span>${esc(time)}</span>${tz ? `<span class="clock-tz">${esc(tz)}</span>` : ""}`;
}

// ── Routing ──────────────────────────────────────────────────────────────────

function parseRoute() {
  const hash = window.location.hash.replace(/^#\/?/, "");
  const parts = hash.split("/").filter(Boolean);
  if (parts[0] === "app" && parts[1]) return { name: "app", id: Number(parts[1]), tab: parts[2] || "overview" };
  return { name: "dashboard" };
}

function navigate(hash) {
  if (window.location.hash === hash) onRoute();
  else window.location.hash = hash;
}

function onRoute() {
  const route = parseRoute();
  const prev = state.route;
  state.route = route;
  closeMenus();
  if (route.name === "app") {
    if (prev.name !== "app" || prev.id !== route.id) {
      teardownDetail();
      renderDetailShell(route.id);
    }
    showTab(route.tab);
  } else {
    teardownDetail();
    renderDashboardShell();
  }
  view().focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

function renderCurrent() {
  if (state.route.name === "app") updateDetail();
  else updateDashboard();
}

// ── Dashboard ────────────────────────────────────────────────────────────────

const FILTERS = [
  { key: "all", label: "All", test: () => true },
  { key: "attention", label: "Needs attention", test: (a) => a.attention },
  { key: "running", label: "Running", test: (a) => ["running", "running_now", "starting", "working"].includes(a.status) },
  { key: "scheduled", label: "Scheduled", test: (a) => isScheduled(a) && ["scheduled", "last_failed", "running_now", "no_schedule"].includes(a.status) },
  { key: "inactive", label: "Stopped & paused", test: (a) => ["stopped", "paused", "not_installed"].includes(a.status) },
];

function renderDashboardShell() {
  document.title = "Mantyx";
  state.cardCache.clear();
  view().innerHTML = `
    <div class="page">
      <div class="page-head">
        <div>
          <h1>Apps</h1>
          <p class="page-sub" id="dashSummary"></p>
        </div>
        <label class="search">
          ${icon("search")}
          <input type="search" id="appSearch" placeholder="Search apps" value="${esc(state.search)}" aria-label="Search apps" />
        </label>
      </div>
      <div class="filters" id="filters" role="tablist" aria-label="Filter apps"></div>
      <div id="dashBody"></div>
    </div>`;
  document.getElementById("appSearch").addEventListener("input", (e) => {
    state.search = e.target.value;
    updateDashboard();
  });
  updateDashboard();
}

function updateDashboard() {
  const body = document.getElementById("dashBody");
  if (!body) return;

  if (!state.loaded) {
    body.innerHTML = state.loadError
      ? emptyState("alert", "Can't load your apps", esc(state.loadError), "")
      : `<div class="loading">${icon("refresh", "spin")} Loading apps…</div>`;
    return;
  }

  const apps = state.apps;
  const attention = apps.filter((a) => a.attention);
  const running = apps.filter((a) => a.status === "running" || a.status === "running_now").length;
  const summary = document.getElementById("dashSummary");
  summary.textContent = apps.length
    ? `${apps.length} app${apps.length === 1 ? "" : "s"} · ${running} running` +
      (attention.length ? ` · ${attention.length} need${attention.length === 1 ? "s" : ""} attention` : "")
    : "";

  const filtersEl = document.getElementById("filters");
  filtersEl.hidden = apps.length === 0;
  filtersEl.innerHTML = FILTERS.map((f) => {
    const count = apps.filter(f.test).length;
    if (f.key === "attention" && !count && state.filter !== "attention") return "";
    return `<button type="button" role="tab" class="filter${state.filter === f.key ? " active" : ""}${f.key === "attention" ? " filter-attention" : ""}"
      aria-selected="${state.filter === f.key}" data-action="filter" data-filter="${f.key}">${esc(f.label)} <span class="count">${count}</span></button>`;
  }).join("");

  if (!apps.length) {
    state.cardCache.clear();
    body.innerHTML = emptyState(
      "box",
      "No apps yet",
      "Mantyx runs your Python scripts for you, either always running in the background or on a schedule. Add your first app to get started.",
      `<div class="empty-actions">
         <button type="button" class="btn btn-primary" data-action="add-app">${icon("plus")}<span>Add app</span></button>
         <button type="button" class="btn btn-ghost" data-action="open-guide">${icon("book")}<span>How to package an app</span></button>
       </div>`,
    );
    return;
  }

  const filter = FILTERS.find((f) => f.key === state.filter) || FILTERS[0];
  const term = state.search.trim().toLowerCase();
  const visible = apps.filter(
    (a) =>
      filter.test(a) &&
      (!term || [a.display_name, a.name, a.description].some((v) => lower(v).includes(term))),
  );

  let grid = body.querySelector(".grid");
  if (!grid) {
    body.innerHTML = `<div class="grid" id="appGrid"></div><div id="gridEmpty"></div>`;
    grid = body.querySelector(".grid");
    state.cardCache.clear();
  }
  const emptyEl = body.querySelector("#gridEmpty");
  emptyEl.innerHTML = visible.length
    ? ""
    : emptyState("search", "No matching apps", "Try a different search or filter.", `<button type="button" class="btn btn-ghost" data-action="filter" data-filter="all">Show all apps</button>`);

  // Keyed update: only touch cards whose content changed, so hover/focus and
  // open menus aren't lost every poll.
  const seen = new Set();
  visible.forEach((app) => {
    seen.add(app.id);
    const html = cardHtml(app);
    let card = grid.querySelector(`[data-card="${app.id}"]`);
    if (!card) {
      card = document.createElement("article");
      card.dataset.card = app.id;
      grid.appendChild(card);
    }
    if (state.cardCache.get(app.id) !== html && !card.classList.contains("menu-open")) {
      card.className = `card tone-${STATUS_TONE[app.status] || "neutral"}`;
      card.innerHTML = html;
      state.cardCache.set(app.id, html);
    }
    grid.appendChild(card); // keeps order in sync
  });
  grid.querySelectorAll("[data-card]").forEach((card) => {
    if (!seen.has(Number(card.dataset.card))) {
      state.cardCache.delete(Number(card.dataset.card));
      card.remove();
    }
  });
}

function cardHtml(app) {
  const link = webLink(app);
  const meta = [
    `<span class="meta" title="Version">v${esc(app.version)}</span>`,
    app.git_url ? `<span class="meta" title="${esc(app.git_url)}">${icon("git")}${esc(app.git_branch || "main")}</span>` : "",
    app.update_available ? `<button type="button" class="badge badge-info" data-action="update" data-app-id="${app.id}" title="A newer commit is available">Update available</button>` : "",
    link
      ? `<a class="meta meta-link" href="${esc(link)}" target="_blank" rel="noopener" title="${esc(link)}">${icon("external")}Open</a>`
      : "",
  ].join("");

  return `
    <a class="card-cover" href="#/app/${app.id}" aria-label="Open ${esc(app.display_name)}"></a>
    <header class="card-head">
      <div class="card-titles">
        <h3 class="card-title">${esc(app.display_name)}</h3>
        <span class="card-type">${typeIcon(app)}${typeLabel(app)}</span>
      </div>
      ${menuHtml(appMenuItems(app), { data: `data-app-id="${app.id}"`, label: `Actions for ${app.display_name}` })}
    </header>
    <div class="card-status">
      ${statusPill(app)}
      <span class="card-detail" title="${esc(statusDetail(app))}">${esc(statusDetail(app))}</span>
    </div>
    ${app.description ? `<p class="card-desc">${esc(app.description)}</p>` : ""}
    <footer class="card-foot">
      <div class="card-meta">${meta}</div>
      <div class="card-actions">${primaryAction(app)}</div>
    </footer>`;
}

function emptyState(iconName, title, text, actions) {
  return `<div class="empty">
    <div class="empty-icon">${icon(iconName)}</div>
    <h2>${esc(title)}</h2>
    <p>${text}</p>
    ${actions || ""}
  </div>`;
}

// ── App detail page ──────────────────────────────────────────────────────────

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "logs", label: "Logs" },
  { key: "runs", label: "Run history" },
  { key: "schedules", label: "Schedules", scheduledOnly: true },
  { key: "settings", label: "Settings" },
  { key: "versions", label: "Versions" },
];

function teardownDetail() {
  if (!state.detail) return;
  clearTimeout(state.detail.logTimer);
  if (state.detail.logAbort) state.detail.logAbort.abort();
  state.detail = null;
}

function renderDetailShell(appId) {
  state.detail = {
    id: appId,
    tab: null,
    headHtml: "",
    overviewHtml: "",
    log: null,
    logTimer: null,
    runs: [],
    runsLimit: 25,
    lastRunsFetch: 0,
    lastEventsFetch: 0,
    events: [],
    schedules: null,
  };
  view().innerHTML = `
    <div class="page page-detail">
      <a href="#/" class="back-link">${icon("back")}<span>All apps</span></a>
      <div id="detailHead"></div>
      <nav class="tabs" id="detailTabs" role="tablist" aria-label="App sections"></nav>
      <section id="tabPanel" class="tab-panel" role="tabpanel"></section>
    </div>`;
  updateDetail();
}

function detailApp() {
  return state.detail && appById(state.detail.id);
}

function updateDetail() {
  const d = state.detail;
  if (!d) return;
  const app = detailApp();
  const head = document.getElementById("detailHead");
  if (!head) return;

  if (!app) {
    if (state.loaded) {
      head.innerHTML = emptyState("alert", "App not found", "It may have been deleted.", `<a class="btn btn-primary" href="#/">Back to all apps</a>`);
      document.getElementById("detailTabs").innerHTML = "";
      document.getElementById("tabPanel").innerHTML = "";
    } else {
      head.innerHTML = `<div class="loading">${icon("refresh", "spin")} Loading…</div>`;
    }
    return;
  }

  document.title = `${app.display_name} · Mantyx`;
  const html = detailHeadHtml(app);
  if (html !== d.headHtml && !head.querySelector(".menu-list:not([hidden])")) {
    head.innerHTML = html;
    d.headHtml = html;
  }

  const tabs = document.getElementById("detailTabs");
  const tabHtml = TABS.filter((t) => !t.scheduledOnly || isScheduled(app))
    .map(
      (t) =>
        `<a role="tab" class="tab${d.tab === t.key ? " active" : ""}" aria-selected="${d.tab === t.key}" href="#/app/${app.id}/${t.key}">${esc(t.label)}${
          t.key === "schedules" && app.schedule_count ? ` <span class="count">${app.schedule_count}</span>` : ""
        }</a>`,
    )
    .join("");
  if (tabs.innerHTML !== tabHtml) tabs.innerHTML = tabHtml;

  refreshTabLive(app);
}

function detailHeadHtml(app) {
  const link = webLink(app);
  const actions = [];
  const id = app.id;
  const busy = app.status === "working";
  if (link) actions.push(`<a class="btn btn-ghost" href="${esc(link)}" target="_blank" rel="noopener">${icon("external")}<span>Open web UI</span></a>`);
  if (isPerpetual(app) && ["running", "starting"].includes(app.status)) actions.push(btn("Restart", "restart", id, { iconName: "restart" }));
  if (isScheduled(app) && !["not_installed", "running_now", "working"].includes(app.status) && app.status !== "no_schedule")
    actions.push(btn("Run now", "run-now", id, { iconName: "play" }));
  const primary = primaryAction(app, "");
  // Emphasise constructive actions; Stop / Stop run stay neutral.
  const emphasise = ["not_installed", "stopped", "failed", "paused", "no_schedule"].includes(app.status);
  if (primary && !(app.status === "scheduled" || app.status === "last_failed"))
    actions.push(emphasise ? primary.replace("btn-secondary", "btn-primary") : primary);
  if (app.status === "no_schedule") actions.push(btn("Run now", "run-now", id, { iconName: "play" }));

  return `
    <div class="detail-head">
      <div class="detail-titles">
        <h1>${esc(app.display_name)}</h1>
        <div class="detail-sub">
          <span class="card-type">${typeIcon(app)}${typeLabel(app)}</span>
          <span class="sep">·</span><code title="App ID">${esc(app.name)}</code>
          <span class="sep">·</span><span>v${esc(app.version)}</span>
        </div>
      </div>
      <div class="detail-actions">${busy ? "" : actions.join("")}${menuHtml(appMenuItems(app, { inDetail: true }), { data: `data-app-id="${id}"` })}</div>
    </div>
    ${statusBannerHtml(app)}`;
}

function policyText(app) {
  if (app.restart_policy === "never") return "Mantyx won't restart it automatically if it stops.";
  if (app.restart_policy === "always") return "If it stops, Mantyx always restarts it.";
  return `If it crashes, Mantyx restarts it (giving up after ${app.max_restarts} crashes within a few minutes).`;
}

function statusBannerHtml(app) {
  const tone = STATUS_TONE[app.status] || "neutral";
  const id = app.id;
  let headline = "";
  let text = "";
  let cta = "";
  const last = app.last_run;

  switch (app.status) {
    case "working":
      headline = app.status_label;
      text = "This can take a few minutes for apps with many dependencies. You can leave this page; it keeps going.";
      if (app.active_task) cta = btn("Show progress", "show-task", id, { extra: `data-task-id="${esc(app.active_task.id)}"` });
      break;
    case "not_installed":
      headline = "Not installed yet";
      text = "Mantyx has the app's files but hasn't installed its dependencies (from requirements.txt) yet.";
      cta = btn("Install", "install", id, { kind: "primary", iconName: "download" });
      break;
    case "running": {
      const since = runningSince(app);
      headline = since ? `Running for ${fmtDuration((Date.now() - toDate(since)) / 1000)}` : "Running";
      text = `${policyText(app)} It also starts automatically whenever Mantyx starts.`;
      if (recentlyRestarted(app) && app.last_error) text = `Recovered from a crash ${fmtAgo(app.last_restart_at)} (${app.last_error.toLowerCase()}). ` + text;
      cta = `<button type="button" class="btn btn-ghost" data-action="tab" data-tab="logs">${icon("terminal")}<span>Watch output</span></button>`;
      break;
    }
    case "starting":
      headline = "Starting";
      text = "Mantyx is starting the app.";
      break;
    case "failed":
      headline = "Stopped because of an error";
      text = `${esc(sentence(app.last_error || "The app stopped unexpectedly"))} Check the logs to find out why, fix the problem (for example by updating the app or its settings), then start it again.`;
      cta = `<button type="button" class="btn btn-secondary" data-action="tab" data-tab="logs">${icon("terminal")}<span>View logs</span></button>`;
      return banner(tone, headline, text, cta);
    case "stopped":
      headline = "Stopped";
      text = "This app isn't running and won't start on its own (not even when Mantyx restarts) until you start it.";
      break;
    case "running_now":
      headline = "Running now";
      text = app.current_run ? `This run started ${fmtAgo(app.current_run.started_at)}.` : "";
      cta = `<button type="button" class="btn btn-ghost" data-action="tab" data-tab="logs">${icon("terminal")}<span>Watch output</span></button>`;
      break;
    case "paused":
      headline = lower(app.state) === "installed" ? "Not activated" : "Paused";
      text = "Its schedules won't run until you activate it. You can still run it manually at any time.";
      break;
    case "no_schedule":
      headline = "No schedule";
      text = "This app doesn't have an active schedule, so it only runs when you click Run now.";
      cta = btn("Add schedule", "add-schedule", id, { kind: "secondary", iconName: "calendar" });
      break;
    case "last_failed":
      headline = "The last run failed";
      text = `It failed ${esc(fmtAgo(last && (last.ended_at || last.started_at)))}${
        last && last.error_message ? `: ${esc(last.error_message.replace(/[.\s]+$/, ""))}` : ""
      }. ${app.next_run ? `The next run is still scheduled for ${esc(fmtWhen(app.next_run))}.` : ""}`;
      cta = last ? `<button type="button" class="btn btn-secondary" data-action="view-run-log" data-execution-id="${last.id}">${icon("terminal")}<span>See what happened</span></button>` : "";
      return banner(tone, headline, text, cta);
    case "scheduled":
      headline = app.next_run ? `Next run ${fmtWhen(app.next_run)}` : "Scheduled";
      text = `Runs automatically on ${app.enabled_schedule_count === 1 ? "its schedule" : `${app.enabled_schedule_count} schedules`}.` +
        (last && last.ended_at ? ` The last run ${last.status === "success" ? "succeeded" : last.status} ${fmtAgo(last.ended_at)}.` : " It hasn't run yet.");
      break;
    default:
      headline = app.status_label;
  }
  return banner(tone, headline, esc(text), cta);
}

/** textHtml must already be escaped. */
/** Make sure a message ends like a sentence before more text follows it. */
function sentence(text) {
  const t = String(text || "").trim();
  return /[.!?)]$/.test(t) ? (t.endsWith(")") ? `${t}.` : t) : `${t}.`;
}

function banner(tone, headline, textHtml, cta) {
  return `<div class="status-banner tone-${tone}">
    <span class="status-banner-dot"></span>
    <div class="status-banner-text"><strong>${esc(headline)}</strong><p>${textHtml}</p></div>
    ${cta ? `<div class="status-banner-cta">${cta}</div>` : ""}
  </div>`;
}

function showTab(tab) {
  const d = state.detail;
  if (!d) return;
  const app = detailApp();
  const valid = TABS.some((t) => t.key === tab && (!t.scheduledOnly || !app || isScheduled(app)));
  tab = valid ? tab : "overview";
  if (d.tab === tab) return;
  d.tab = tab;
  clearTimeout(d.logTimer);
  if (d.logAbort) d.logAbort.abort();
  d.overviewHtml = "";
  updateDetail();
  const panel = document.getElementById("tabPanel");
  if (!panel) return;
  panel.innerHTML = `<div class="loading">${icon("refresh", "spin")} Loading…</div>`;
  if (!app) return;
  ({
    overview: renderOverviewTab,
    logs: renderLogsTab,
    runs: renderRunsTab,
    schedules: renderSchedulesTab,
    settings: renderSettingsTab,
    versions: renderVersionsTab,
  })[tab](app);
}

/** Called after every poll: refresh the parts of the active tab that show live data. */
function refreshTabLive(app) {
  const d = state.detail;
  if (!d || !d.tab) return;
  const panel = document.getElementById("tabPanel");
  if (!panel) return;
  if (d.tab === "overview") renderOverviewTab(app, { live: true });
  if (d.tab === "runs" && Date.now() - d.lastRunsFetch > POLL_MS - 500) loadRuns(app);
  if (d.tab === "schedules" && d.schedules) renderSchedulesList(app);
  if (d.tab === "logs") syncLogRunChoice(app);
}

// ── Overview tab ─────────────────────────────────────────────────────────────

async function renderOverviewTab(app, { live = false } = {}) {
  const d = state.detail;
  if (!live || Date.now() - d.lastEventsFetch > 15000) {
    d.lastEventsFetch = Date.now();
    try {
      d.events = await api(`/apps/${app.id}/events?limit=15`);
    } catch {
      /* activity is optional */
    }
    app = detailApp() || app;
  }
  if (!state.detail || state.detail.tab !== "overview") return;

  const link = webLink(app);
  const last = app.last_run;
  const facts = [];
  facts.push(["Type", isPerpetual(app) ? "Always running: keeps going in the background and is restarted if it crashes." : "Scheduled: runs, does its job and exits, on the schedules you set."]);
  if (isPerpetual(app) && app.status === "running" && runningSince(app)) facts.push(["Running since", fmtDateTime(runningSince(app))]);
  if (isScheduled(app)) {
    facts.push(["Next run", app.next_run ? `${fmtWhen(app.next_run)}` : app.enabled ? "Not scheduled" : "Paused"]);
    facts.push(["Last run", last && last.ended_at ? `${runStatusLabel(last.status, app)}, ${fmtAgo(last.ended_at)}` : "Never"]);
  }
  facts.push(["Version", `v${app.version}${app.last_updated_at ? `, updated ${fmtAgo(app.last_updated_at)}` : ""}`]);
  facts.push(["Source", app.git_url ? `Git: ${app.git_url} (${app.git_branch || "main"}${app.git_commit ? ` @ ${app.git_commit.slice(0, 8)}` : ""})` : "Uploaded ZIP"]);
  facts.push(["Runs", app.entrypoint]);
  if (isPerpetual(app)) {
    facts.push(["Web interface", link ? link : "None detected. If the app serves a web page, Mantyx finds its port automatically once it's running."]);
  }

  const events = (d.events || [])
    .map(
      (e) => `<li class="event event-${esc(e.level)}">
        <span class="event-dot"></span>
        <span class="event-msg">${esc(e.message)}</span>
        <time title="${esc(fmtDateTime(e.timestamp))}">${esc(fmtAgo(e.timestamp))}</time>
      </li>`,
    )
    .join("");

  const html = `
    <div class="overview">
      <div class="panel">
        <h2 class="panel-title">Details</h2>
        <dl class="facts">${facts
          .map(([k, v]) => `<dt>${esc(k)}</dt><dd>${k === "Web interface" && link ? `<a href="${esc(link)}" target="_blank" rel="noopener">${esc(v)}</a>` : k === "Runs" ? `<code>${esc(v)}</code>` : esc(v)}</dd>`)
          .join("")}</dl>
        ${app.description ? `<h2 class="panel-title">Description</h2><p class="prose">${esc(app.description)}</p>` : ""}
      </div>
      <div class="panel">
        <h2 class="panel-title">Recent activity</h2>
        ${events ? `<ul class="events">${events}</ul>` : `<p class="muted">Nothing yet. Starts, crashes, runs and updates show up here.</p>`}
      </div>
    </div>`;
  if (html !== d.overviewHtml) {
    document.getElementById("tabPanel").innerHTML = html;
    d.overviewHtml = html;
  }
}

// ── Runs tab ─────────────────────────────────────────────────────────────────

const TRIGGER_LABEL = {
  manual: "Manual",
  scheduled: "Schedule",
  startup: "Mantyx started",
  "auto-restart": "Restart after crash",
  update: "After update",
};

function runStatusLabel(status, app) {
  const s = lower(status);
  if (s === "success") return app && isPerpetual(app) ? "Stopped" : "Succeeded";
  return { failed: "Failed", timeout: "Timed out", cancelled: "Stopped", running: "Running", pending: "Starting" }[s] || s;
}

function runTone(status) {
  return { success: "success", failed: "danger", timeout: "danger", cancelled: "neutral", running: "active", pending: "active" }[lower(status)] || "neutral";
}

function runDuration(run) {
  const start = toDate(run.started_at);
  if (!start) return "";
  const end = toDate(run.ended_at) || new Date();
  return fmtDuration((end - start) / 1000);
}

function renderRunsTab(app) {
  document.getElementById("tabPanel").innerHTML = `<div class="panel"><div id="runsTable"><div class="loading">${icon("refresh", "spin")} Loading…</div></div></div>`;
  loadRuns(app);
}

async function loadRuns(app) {
  const d = state.detail;
  d.lastRunsFetch = Date.now();
  try {
    d.runs = await api(`/executions?app_id=${app.id}&limit=${d.runsLimit}`);
  } catch (err) {
    const el = document.getElementById("runsTable");
    if (el) el.innerHTML = `<p class="error-text">${esc(err.message)}</p>`;
    return;
  }
  const el = document.getElementById("runsTable");
  if (!el || !state.detail || state.detail.tab !== "runs") return;
  if (!d.runs.length) {
    el.innerHTML = `<p class="muted">No runs yet. ${isScheduled(app) ? "Runs appear here each time the app runs, on schedule or via Run now." : "Each time the app is started, a run appears here."}</p>`;
    return;
  }
  el.innerHTML = `
    <div class="table-wrap"><table class="table">
      <thead><tr><th>Result</th><th>Started</th><th>Duration</th><th>Trigger</th><th>Details</th><th class="right"></th></tr></thead>
      <tbody>${d.runs
        .map(
          (r) => `<tr>
            <td><span class="pill pill-${runTone(r.status)}"><span class="pill-dot"></span>${esc(runStatusLabel(r.status, app))}</span></td>
            <td title="${esc(fmtDateTime(r.started_at))}">${esc(r.started_at ? fmtAgo(r.started_at) : "–")}</td>
            <td>${esc(runDuration(r))}</td>
            <td>${esc(TRIGGER_LABEL[r.trigger_type] || r.trigger_type)}</td>
            <td class="run-details">${r.error_message ? esc(r.error_message) : r.exit_code !== null && r.exit_code !== undefined ? `Exit code ${r.exit_code}` : ""}</td>
            <td class="right nowrap">
              ${["running", "pending"].includes(lower(r.status)) && isScheduled(app) ? `<button type="button" class="btn btn-ghost btn-sm" data-action="cancel-run" data-app-id="${app.id}" data-execution-id="${r.id}">Stop</button>` : ""}
              <button type="button" class="btn btn-ghost btn-sm" data-action="view-run-log" data-execution-id="${r.id}">${icon("terminal")}<span>Logs</span></button>
            </td>
          </tr>`,
        )
        .join("")}</tbody>
    </table></div>
    ${d.runs.length >= d.runsLimit ? `<div class="center"><button type="button" class="btn btn-ghost" data-action="more-runs">Show more</button></div>` : ""}`;
}

// ── Logs tab ─────────────────────────────────────────────────────────────────

async function renderLogsTab(app, { executionId = null } = {}) {
  const d = state.detail;
  const panel = document.getElementById("tabPanel");
  let runs = [];
  try {
    runs = await api(`/executions?app_id=${app.id}&limit=30`);
  } catch (err) {
    panel.innerHTML = `<p class="error-text">${esc(err.message)}</p>`;
    return;
  }
  if (!state.detail || state.detail.tab !== "logs") return;
  if (!runs.length) {
    panel.innerHTML = `<div class="panel">${emptyState("terminal", "No output yet", isScheduled(app) ? "Output appears here once the app has run." : "Output appears here once the app has been started.", "")}</div>`;
    d.log = null;
    return;
  }
  const preferred = executionId || (app.current_run && app.current_run.id) || runs[0].id;
  d.log = { runs, executionId: preferred, stream: "stdout", offset: -1, follow: true, autoPicked: !executionId };

  panel.innerHTML = `
    <div class="panel panel-flush">
      <div class="log-toolbar">
        <label class="field-inline">
          <span class="sr-only">Run</span>
          <select class="input input-sm" id="logRun">${runOptions(runs, app, preferred)}</select>
        </label>
        <div class="segmented segmented-sm" role="group" aria-label="Output stream">
          <button type="button" class="seg-btn active" data-log-stream="stdout" aria-pressed="true">Output</button>
          <button type="button" class="seg-btn" data-log-stream="stderr" aria-pressed="false">Errors</button>
        </div>
        <label class="toggle"><input type="checkbox" id="logFollow" checked /><span>Follow</span></label>
        <span class="grow"></span>
        <span class="muted small" id="logState"></span>
        <a class="btn btn-ghost btn-sm" id="logRaw" target="_blank" rel="noopener">${icon("external")}<span>Full log</span></a>
      </div>
      <pre class="log" id="logOutput" tabindex="0" aria-label="Log output"></pre>
    </div>`;

  document.getElementById("logRun").addEventListener("change", (e) => {
    d.log.executionId = Number(e.target.value);
    d.log.autoPicked = false;
    restartLog();
  });
  panel.querySelectorAll("[data-log-stream]").forEach((b) =>
    b.addEventListener("click", () => {
      d.log.stream = b.dataset.logStream;
      panel.querySelectorAll("[data-log-stream]").forEach((x) => {
        x.classList.toggle("active", x === b);
        x.setAttribute("aria-pressed", String(x === b));
      });
      restartLog();
    }),
  );
  document.getElementById("logFollow").addEventListener("change", (e) => {
    d.log.follow = e.target.checked;
    if (d.log.follow) {
      const out = document.getElementById("logOutput");
      out.scrollTop = out.scrollHeight;
      pollLog();
    }
  });
  restartLog();
}

function runOptions(runs, app, selected) {
  return runs
    .map((r) => {
      const when = r.started_at ? fmtDateTime(r.started_at) : `#${r.id}`;
      const live = ["running", "pending"].includes(lower(r.status));
      const label = live ? `Current run (started ${fmtAgo(r.started_at)})` : `${when} · ${runStatusLabel(r.status, app)}`;
      return `<option value="${r.id}" ${r.id === selected ? "selected" : ""}>${esc(label)}</option>`;
    })
    .join("");
}

/** When a new run starts (restart, next scheduled run) jump to it if we were following the latest. */
async function syncLogRunChoice(app) {
  const d = state.detail;
  if (!d || !d.log || !d.log.autoPicked) return;
  const current = app.current_run && app.current_run.id;
  if (current && current !== d.log.executionId) {
    renderLogsTab(app);
  }
}

function restartLog() {
  const d = state.detail;
  clearTimeout(d.logTimer);
  if (d.logAbort) d.logAbort.abort();
  d.log.offset = -1;
  const out = document.getElementById("logOutput");
  out.textContent = "";
  document.getElementById("logRaw").href = `${API_BASE}/executions/${d.log.executionId}/log/raw?stream=${d.log.stream}`;
  pollLog();
}

async function pollLog() {
  const d = state.detail;
  if (!d || !d.log || d.tab !== "logs") return;
  clearTimeout(d.logTimer);
  const { executionId, stream } = d.log;
  d.logAbort = new AbortController();
  let chunk;
  try {
    chunk = await api(`/executions/${executionId}/log?stream=${stream}&offset=${d.log.offset}`, { signal: d.logAbort.signal });
  } catch (err) {
    if (err.name === "AbortError") return;
    document.getElementById("logState").textContent = err.message;
    d.logTimer = setTimeout(pollLog, LOG_POLL_MS * 2);
    return;
  }
  if (!state.detail || !d.log || d.log.executionId !== executionId || d.log.stream !== stream) return;

  const out = document.getElementById("logOutput");
  if (!out) return;
  const atBottom = out.scrollHeight - out.scrollTop - out.clientHeight < 40;
  if (chunk.reset || out.querySelector(".muted")) out.textContent = "";
  if (d.log.offset === -1 && chunk.truncated) {
    out.textContent = "… earlier output omitted. Use “Full log” to see everything …\n";
  }
  if (chunk.output) {
    out.textContent += stripAnsi(chunk.output);
    if (out.textContent.length > MAX_LOG_CHARS) out.textContent = out.textContent.slice(-MAX_LOG_CHARS);
  }
  if (!out.textContent) {
    out.innerHTML = `<span class="muted">${chunk.running ? "Waiting for output…" : stream === "stderr" ? "No errors were written." : "No output was written."}</span>`;
  }
  d.log.offset = chunk.offset;
  if (d.log.follow && (atBottom || chunk.output)) out.scrollTop = out.scrollHeight;
  document.getElementById("logState").textContent = chunk.running ? "Live" : "Finished";
  document.getElementById("logState").classList.toggle("live", chunk.running);

  if (chunk.running && d.log.follow) d.logTimer = setTimeout(pollLog, LOG_POLL_MS);
}

// ── Schedules tab ────────────────────────────────────────────────────────────

async function renderSchedulesTab(app) {
  const panel = document.getElementById("tabPanel");
  try {
    state.detail.schedules = await api(`/schedules?app_id=${app.id}`);
  } catch (err) {
    panel.innerHTML = `<p class="error-text">${esc(err.message)}</p>`;
    return;
  }
  if (!state.detail || state.detail.tab !== "schedules") return;
  const tz = (state.systemInfo && state.systemInfo.timezone) || "";
  panel.innerHTML = `
    <div class="panel">
      <div class="panel-head">
        <p class="muted">Times are in <strong>${esc(tz)}</strong>. <button type="button" class="link-btn" data-action="open-settings">Change timezone</button></p>
        <button type="button" class="btn btn-primary btn-sm" data-action="add-schedule" data-app-id="${app.id}">${icon("plus")}<span>Add schedule</span></button>
      </div>
      <div id="scheduleList"></div>
    </div>`;
  renderSchedulesList(app);
}

function renderSchedulesList(app) {
  const list = document.getElementById("scheduleList");
  const schedules = state.detail && state.detail.schedules;
  if (!list || !schedules) return;
  const paused = !app.enabled || lower(app.state) === "installed";
  const note = paused && schedules.length
    ? `<div class="note note-warning">${icon("pause")}<span>This app is ${lower(app.state) === "installed" ? "not activated" : "paused"}, so these schedules don't run.</span>
         <button type="button" class="btn btn-sm btn-secondary" data-action="enable" data-app-id="${app.id}">${lower(app.state) === "installed" ? "Activate" : "Resume"}</button></div>`
    : "";
  if (!schedules.length) {
    list.innerHTML = emptyState("calendar", "No schedules", "Add a schedule to run this app automatically, for example every morning at 7:00 or every 15 minutes.", "");
    return;
  }
  const html =
    note +
    `<ul class="schedules">${schedules
      .map((s) => {
        const desc = describeSchedule(s);
        const next = s.is_enabled && !paused && s.next_run ? `Next: ${fmtWhen(s.next_run)}` : s.is_enabled ? "" : "Turned off";
        return `<li class="schedule ${s.is_enabled ? "" : "is-off"}">
          <label class="switch" title="${s.is_enabled ? "Turn off" : "Turn on"}">
            <input type="checkbox" data-action="toggle-schedule" data-schedule-id="${s.id}" ${s.is_enabled ? "checked" : ""} aria-label="Schedule ${esc(s.name)} enabled" />
            <span class="switch-track"></span>
          </label>
          <div class="schedule-main">
            <div class="schedule-name">${esc(s.name)}</div>
            <div class="schedule-desc">${icon("calendar")}${esc(desc)}${s.timeout_seconds ? ` · stops after ${fmtDuration(s.timeout_seconds)}` : ""}</div>
            ${usesDayNumbers(s) ? `<div class="schedule-warn">${icon("alert")}<span>Uses day numbers, which older Mantyx versions saved one day off (1 means Tuesday). Check these are the days you want; saving it again from Edit stores day names.</span></div>` : ""}
          </div>
          <div class="schedule-meta">
            <div>${esc(next)}</div>
            <div class="muted small">${s.last_run ? `Last ran ${esc(fmtAgo(s.last_run))}` : "Hasn't run yet"} · ${s.run_count} run${s.run_count === 1 ? "" : "s"}</div>
          </div>
          <div class="schedule-actions">
            <button type="button" class="btn btn-ghost btn-sm" data-action="edit-schedule" data-schedule-id="${s.id}">Edit</button>
            <button type="button" class="icon-btn" data-action="delete-schedule" data-schedule-id="${s.id}" aria-label="Delete schedule ${esc(s.name)}" title="Delete">${icon("trash")}</button>
          </div>
        </li>`;
      })
      .join("")}</ul>`;
  if (list.innerHTML !== html) list.innerHTML = html;
}

/** True for cron schedules whose weekday field uses numbers (possibly saved by the old editor). */
function usesDayNumbers(schedule) {
  if (schedule.schedule_type !== "cron" || !schedule.cron_expression) return false;
  const parts = schedule.cron_expression.trim().split(/\s+/);
  return parts.length === 5 && /\d/.test(parts[4]);
}

function openScheduleDialog(app, schedule = null) {
  const model = parseSchedule(schedule);
  const timeoutMin = schedule && schedule.timeout_seconds ? Math.round(schedule.timeout_seconds / 60) : "";
  const body = openDialog({
    title: schedule ? "Edit schedule" : `Add a schedule for ${app.display_name}`,
    size: "md",
    body: `
      <label class="field">
        <span class="field-label">Name</span>
        <input type="text" class="input" name="schedName" value="${esc(schedule ? schedule.name : "")}" placeholder="e.g. Every morning" maxlength="255" />
      </label>
      ${scheduleEditorHtml(model, { idPrefix: "edit" })}
      <details class="advanced" ${timeoutMin ? "open" : ""}>
        <summary>Advanced</summary>
        <label class="field field-narrow">
          <span class="field-label">Stop the run if it takes longer than</span>
          <div class="input-suffix"><input type="number" class="input" name="schedTimeout" min="1" value="${esc(timeoutMin)}" placeholder="No limit" /><span>minutes</span></div>
        </label>
      </details>
      <p class="error-text" id="schedError" hidden></p>`,
    footer: `<button type="button" class="btn btn-ghost" data-action="close-dialog">Cancel</button>
             <button type="submit" class="btn btn-primary">${schedule ? "Save schedule" : "Add schedule"}</button>`,
    onSubmit: async () => {
      const errEl = body.querySelector("#schedError");
      errEl.hidden = true;
      let spec;
      try {
        spec = editor.getSpec();
      } catch (err) {
        errEl.textContent = err.message;
        errEl.hidden = false;
        return;
      }
      const name = body.querySelector("[name=schedName]").value.trim() || describeSchedule(spec);
      const timeout = Number(body.querySelector("[name=schedTimeout]").value);
      const payload = { ...spec, name, timeout_seconds: timeout > 0 ? Math.round(timeout * 60) : null };
      try {
        if (schedule) await api(`/schedules/${schedule.id}`, { method: "PATCH", json: payload });
        else await api("/schedules", { method: "POST", json: { ...payload, app_id: app.id, is_enabled: true } });
      } catch (err) {
        errEl.textContent = err.message;
        errEl.hidden = false;
        return;
      }
      closeDialog();
      toast(schedule ? "Schedule saved" : "Schedule added", "success");
      if (!schedule && lower(app.state) === "installed") {
        if (await confirmAction({ title: "Activate the app?", message: `<p>${esc(app.display_name)} isn't activated yet, so the schedule won't run until it is. Activate it now?</p>`, confirmLabel: "Activate" })) {
          await doAction(() => api(`/apps/${app.id}/enable`, { method: "POST" }), "Activated");
        }
      }
      await refreshApps();
      if (state.detail && state.detail.tab === "schedules") renderSchedulesTab(detailApp());
      else if (state.route.name === "app") navigate(`#/app/${app.id}/schedules`);
    },
  });
  const editor = bindScheduleEditor(body, model);
}

// ── Settings tab ─────────────────────────────────────────────────────────────

async function renderSettingsTab(app) {
  const panel = document.getElementById("tabPanel");
  let files = [];
  try {
    files = (await api(`/apps/${app.id}/files`)).python_files;
  } catch {
    files = [app.entrypoint];
  }
  if (!state.detail || state.detail.tab !== "settings") return;
  if (!files.includes(app.entrypoint)) files.unshift(app.entrypoint);
  const env = Object.entries(app.environment || {});
  const manualLink = app.web_port_source === "manual";

  panel.innerHTML = `
    <form class="settings-form" id="appSettings" novalidate>
      <section class="panel">
        <h2 class="panel-title">General</h2>
        <label class="field">
          <span class="field-label">Name</span>
          <input type="text" class="input" name="display_name" value="${esc(app.display_name)}" required maxlength="255" />
        </label>
        <label class="field">
          <span class="field-label">Description <span class="optional">optional</span></span>
          <textarea class="input" name="description" rows="2">${esc(app.description || "")}</textarea>
        </label>
        <label class="field">
          <span class="field-label">File to run</span>
          <select class="input mono" name="entrypoint">${files.map((f) => `<option ${f === app.entrypoint ? "selected" : ""}>${esc(f)}</option>`).join("")}</select>
          <span class="hint">Mantyx runs this with Python. Updates keep your choice as long as the file still exists.</span>
        </label>
      </section>

      ${isPerpetual(app) ? `
      <section class="panel">
        <h2 class="panel-title">If it stops unexpectedly</h2>
        <div class="radio-list">
          <label class="radio"><input type="radio" name="restart_policy" value="on-failure" ${app.restart_policy === "on-failure" ? "checked" : ""}/>
            <span><strong>Restart it, but give up if it keeps crashing</strong><span class="hint">Recommended. Avoids endless crash loops.</span></span></label>
          <label class="radio"><input type="radio" name="restart_policy" value="always" ${app.restart_policy === "always" ? "checked" : ""}/>
            <span><strong>Always restart it</strong><span class="hint">Keeps trying forever.</span></span></label>
          <label class="radio"><input type="radio" name="restart_policy" value="never" ${app.restart_policy === "never" ? "checked" : ""}/>
            <span><strong>Leave it stopped</strong><span class="hint">You'll see it as Failed and can start it yourself.</span></span></label>
        </div>
        <div class="field-row">
          <label class="field field-narrow"><span class="field-label">Give up after</span>
            <div class="input-suffix"><input type="number" class="input" name="max_restarts" min="0" max="1000" value="${esc(app.max_restarts)}" /><span>crashes</span></div></label>
          <label class="field field-narrow"><span class="field-label">Wait between restarts</span>
            <div class="input-suffix"><input type="number" class="input" name="restart_delay" min="0" max="3600" value="${esc(app.restart_delay)}" /><span>seconds</span></div></label>
        </div>
      </section>` : ""}

      <section class="panel">
        <h2 class="panel-title">Environment variables</h2>
        <p class="hint">Settings and secrets for your app, such as API keys. Read them in Python with <code>os.environ["NAME"]</code>. Changes apply the next time the app starts.</p>
        <div class="env-list" id="envList">${env.map(([k, v]) => envRow(k, v)).join("")}</div>
        <button type="button" class="btn btn-ghost btn-sm" data-action="add-env">${icon("plus")}<span>Add variable</span></button>
        <p class="hint">Mantyx also sets <code>APP_DATA_DIR</code> (a folder that survives updates) and <code>PYTHONUNBUFFERED</code> (so output shows up live).</p>
      </section>

      ${isPerpetual(app) ? `
      <section class="panel">
        <h2 class="panel-title">Web interface link</h2>
        <div class="radio-list">
          <label class="radio"><input type="radio" name="web_mode" value="auto" ${manualLink ? "" : "checked"}/>
            <span><strong>Detect automatically</strong><span class="hint">${app.web_port && !manualLink ? `Found port ${esc(app.web_port)}.` : "Mantyx looks for a port the app is listening on while it runs."}</span></span></label>
          <label class="radio"><input type="radio" name="web_mode" value="manual" ${manualLink ? "checked" : ""}/>
            <span><strong>Set it myself</strong></span></label>
        </div>
        <div class="field-row" id="webManual" ${manualLink ? "" : "hidden"}>
          <label class="field field-narrow"><span class="field-label">Port</span>
            <input type="number" class="input" name="web_port" min="1" max="65535" value="${esc(manualLink ? app.web_port || "" : "")}" placeholder="8080" /></label>
          <label class="field"><span class="field-label">or full URL</span>
            <input type="url" class="input" name="web_url" value="${esc(manualLink ? app.web_url || "" : "")}" placeholder="https://myapp.example.com" /></label>
        </div>
      </section>` : ""}

      <div class="save-bar" id="saveBar" hidden>
        <span>You have unsaved changes.</span>
        <button type="button" class="btn btn-ghost" data-action="reset-settings">Discard</button>
        <button type="submit" class="btn btn-primary">Save changes</button>
      </div>
    </form>

    <section class="panel danger-zone">
      <h2 class="panel-title">Maintenance</h2>
      <div class="danger-row">
        <div><strong>Rebuild environment</strong><p class="hint">Deletes and reinstalls the app's Python packages. Try this if it fails with import errors after a system Python upgrade.</p></div>
        <button type="button" class="btn btn-secondary" data-action="rebuild" data-app-id="${app.id}">${icon("wrench")}<span>Rebuild</span></button>
      </div>
      <div class="danger-row">
        <div><strong>Delete app</strong><p class="hint">Stops it and permanently removes its files, data folder, logs, history and saved versions.</p></div>
        <button type="button" class="btn btn-danger" data-action="delete" data-app-id="${app.id}">${icon("trash")}<span>Delete</span></button>
      </div>
    </section>`;

  const form = document.getElementById("appSettings");
  const saveBar = document.getElementById("saveBar");
  const markDirty = () => (saveBar.hidden = false);
  form.addEventListener("input", markDirty);
  form.addEventListener("change", (e) => {
    markDirty();
    if (e.target.name === "web_mode") document.getElementById("webManual").hidden = e.target.value !== "manual";
  });
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    saveAppSettings(app.id, form);
  });
}

function envRow(key = "", value = "") {
  return `<div class="env-row">
    <input type="text" class="input mono" name="env_key" value="${esc(key)}" placeholder="NAME" spellcheck="false" autocomplete="off" aria-label="Variable name" />
    <div class="input-reveal">
      <input type="password" class="input mono" name="env_value" value="${esc(value)}" placeholder="value" spellcheck="false" autocomplete="off" aria-label="Value" />
      <button type="button" class="icon-btn" data-action="reveal" title="Show/hide value" aria-label="Show value">${icon("eye")}</button>
    </div>
    <button type="button" class="icon-btn" data-action="remove-env" title="Remove" aria-label="Remove variable">${icon("x")}</button>
  </div>`;
}

async function saveAppSettings(appId, form) {
  const app = appById(appId);
  const fd = new FormData(form);
  const payload = {
    display_name: (fd.get("display_name") || "").trim(),
    description: (fd.get("description") || "").trim() || null,
    entrypoint: fd.get("entrypoint"),
  };
  if (!payload.display_name) {
    toast("Give the app a name", "error");
    return;
  }
  const environment = {};
  const keys = fd.getAll("env_key");
  const values = fd.getAll("env_value");
  for (let i = 0; i < keys.length; i += 1) {
    const k = keys[i].trim();
    if (!k) continue;
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(k)) {
      toast(`"${k}" isn't a valid variable name. Use letters, digits and _, not starting with a digit.`, "error");
      return;
    }
    environment[k] = values[i];
  }
  payload.environment = environment;
  if (isPerpetual(app)) {
    payload.restart_policy = fd.get("restart_policy");
    payload.max_restarts = Number(fd.get("max_restarts"));
    payload.restart_delay = Number(fd.get("restart_delay"));
    if (fd.get("web_mode") === "manual") {
      payload.web_port = fd.get("web_port") ? Number(fd.get("web_port")) : null;
      payload.web_url = (fd.get("web_url") || "").trim() || null;
      if (!payload.web_port && !payload.web_url) {
        toast("Enter a port or a URL, or choose automatic detection", "error");
        return;
      }
    } else if (app.web_port_source === "manual") {
      payload.web_port = null;
      payload.web_url = null;
    }
  }

  const needsRestart =
    app.status === "running" &&
    (payload.entrypoint !== app.entrypoint || JSON.stringify(environment) !== JSON.stringify(app.environment || {}));

  try {
    await api(`/apps/${appId}`, { method: "PATCH", json: payload });
  } catch (err) {
    toast(err.message, "error");
    return;
  }
  toast("Settings saved", "success");
  await refreshApps();
  if (state.detail && state.detail.tab === "settings") renderSettingsTab(detailApp());
  if (needsRestart) {
    const ok = await confirmAction({
      title: "Restart to apply?",
      message: `<p>${esc(app.display_name)} is running with the old settings. Restart it now so the changes take effect?</p>`,
      confirmLabel: "Restart now",
    });
    if (ok) await doAction(() => api(`/apps/${appId}/restart`, { method: "POST" }), "Restarted");
  }
}

// ── Versions tab ─────────────────────────────────────────────────────────────

async function renderVersionsTab(app) {
  const panel = document.getElementById("tabPanel");
  let backups = [];
  try {
    backups = await api(`/apps/${app.id}/backups`);
  } catch {
    /* shown as empty */
  }
  if (!state.detail || state.detail.tab !== "versions") return;
  const git = app.git_status;
  let gitLine = "";
  if (app.git_url) {
    if (git && git.update_available) gitLine = `<span class="badge badge-info">${git.commits_behind || "New"} new commit${git.commits_behind === 1 ? "" : "s"} available</span>`;
    else if (git && git.update_available === false) gitLine = `<span class="muted">Up to date${git.checked_at ? ` (checked ${esc(fmtAgo(git.checked_at))})` : ""}</span>`;
    else if (git && git.error) gitLine = `<span class="error-text">Couldn't check: ${esc(git.error)}</span>`;
  }

  panel.innerHTML = `
    <section class="panel">
      <h2 class="panel-title">Current version</h2>
      <dl class="facts">
        <dt>Version</dt><dd>v${esc(app.version)}${app.last_updated_at ? ` · updated ${esc(fmtAgo(app.last_updated_at))}` : ""}</dd>
        <dt>Source</dt><dd>${app.git_url ? `${icon("git")} ${esc(app.git_url)} <span class="muted">(${esc(app.git_branch || "main")}${app.git_commit ? ` @ ${esc(app.git_commit.slice(0, 8))}` : ""})</span>` : "Uploaded ZIP"}</dd>
        ${app.git_url ? `<dt>Updates</dt><dd id="gitLine">${gitLine || '<span class="muted">Not checked yet</span>'}</dd>` : ""}
      </dl>
      <div class="button-row">
        <button type="button" class="btn btn-primary" data-action="update" data-app-id="${app.id}">${icon("upload")}<span>${app.git_url ? "Update…" : "Upload new version…"}</span></button>
        ${app.git_url ? `<button type="button" class="btn btn-ghost" data-action="check-git" data-app-id="${app.id}">${icon("refresh")}<span>Check for updates</span></button>` : ""}
      </div>
    </section>
    <section class="panel">
      <h2 class="panel-title">Saved versions</h2>
      <p class="hint">Before each update Mantyx saves the version being replaced, so you can roll back. The newest few are kept. The app's data folder is never touched by updates or rollbacks.</p>
      ${
        backups.length
          ? `<ul class="backups">${backups
              .map(
                (b) => `<li>
                  <div><strong>${b.version ? `v${esc(b.version)}` : "Earlier version"}</strong>
                    <span class="muted">· saved ${esc(fmtAgo(b.created_at))}${b.git_commit ? ` · ${esc(b.git_commit.slice(0, 8))}` : ""}</span>
                    ${b.reason ? `<div class="muted small">${esc(b.reason)}</div>` : ""}</div>
                  <button type="button" class="btn btn-ghost btn-sm" data-action="restore-backup" data-app-id="${app.id}" data-backup-id="${esc(b.id)}" data-backup-label="${esc(b.version ? `v${b.version}` : fmtDateTime(b.created_at))}">${icon("history")}<span>Restore</span></button>
                </li>`,
              )
              .join("")}</ul>`
          : `<p class="muted">No saved versions yet. One is created each time you update.</p>`
      }
    </section>`;
}

// ── Background tasks (install / update / add / backup) ──────────────────────

const watchedTasks = new Map(); // taskId -> label, for completion toasts after the dialog closes

/**
 * Show a task's progress in the dialog. `start` either kicks off a task
 * (returns {task_id}) or is a known task id string to re-attach to.
 * Resolves with the task result on success, or null on failure/cancel.
 */
function runTask({ title, start, successText, doneButtons = () => "", onSuccess = null }) {
  return new Promise((resolve) => {
    let taskId = null;
    let since = 0;
    let finished = false;
    let timer = null;
    let detached = false;

    const body = openDialog({
      title,
      size: "md",
      body: `
        <div class="task">
          <ol class="steps" id="taskSteps" hidden></ol>
          <div class="task-status" id="taskStatus">${icon("refresh", "spin")}<span>Starting…</span></div>
          <details class="task-log" id="taskLogWrap">
            <summary>Details</summary>
            <pre class="log log-sm" id="taskLog"></pre>
          </details>
        </div>`,
      footer: `<button type="button" class="btn btn-ghost" data-action="close-dialog">Run in background</button>`,
      onClose: () => {
        if (!finished) {
          detached = true;
          clearTimeout(timer);
          if (taskId) watchedTasks.set(taskId, title);
          watchInBackground();
          resolve(null);
        }
      },
    });

    const statusEl = body.querySelector("#taskStatus");
    const stepsEl = body.querySelector("#taskSteps");
    const logEl = body.querySelector("#taskLog");

    const renderSteps = (steps) => {
      if (!steps || !steps.length) return;
      stepsEl.hidden = false;
      stepsEl.innerHTML = steps
        .map((s) => {
          const ic = { done: icon("check"), failed: icon("x"), running: icon("refresh", "spin"), skipped: icon("down") }[s.status] || "";
          return `<li class="step step-${esc(s.status)}"><span class="step-icon">${ic}</span><span>${esc(s.label)}</span></li>`;
        })
        .join("");
    };

    const poll = async () => {
      if (detached) return;
      let task;
      try {
        task = await api(`/apps/tasks/${taskId}?since=${since}`);
      } catch (err) {
        timer = setTimeout(poll, TASK_POLL_MS * 3);
        return;
      }
      if (detached) return;
      if (task.logs.length) {
        const atBottom = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 30;
        logEl.textContent += (logEl.textContent ? "\n" : "") + task.logs.map(stripAnsi).join("\n");
        if (atBottom) logEl.scrollTop = logEl.scrollHeight;
        const lastLine = task.logs.filter((l) => l.trim() && !l.startsWith("──")).pop();
        if (task.status === "running" && lastLine) statusEl.innerHTML = `${icon("refresh", "spin")}<span>${esc(lastLine.slice(0, 160))}</span>`;
      }
      since = task.log_count;
      renderSteps(task.steps);

      if (task.status === "running") {
        timer = setTimeout(poll, TASK_POLL_MS);
        return;
      }
      finished = true;
      if (task.status === "success") {
        statusEl.className = "task-status task-success";
        statusEl.innerHTML = `${icon("check")}<span>${esc(typeof successText === "function" ? successText(task.result || {}) : successText)}</span>`;
        const result = { ...(task.result || {}), task_id: taskId };
        setDialogFooter(`${doneButtons(result)}<button type="button" class="btn btn-primary" data-action="close-dialog">Done</button>`);
        refreshApps();
        if (onSuccess) onSuccess(result);
        resolve(result);
      } else {
        statusEl.className = "task-status task-failed";
        statusEl.innerHTML = `${icon("alert")}<span>${esc(task.error || "Something went wrong")}</span>`;
        body.querySelector("#taskLogWrap").open = true;
        logEl.scrollTop = logEl.scrollHeight;
        setDialogFooter(`<button type="button" class="btn btn-primary" data-action="close-dialog">Close</button>`);
        refreshApps();
        resolve(null);
      }
    };

    (async () => {
      if (typeof start === "string") {
        taskId = start;
      } else {
        try {
          taskId = (await start()).task_id;
        } catch (err) {
          finished = true;
          statusEl.className = "task-status task-failed";
          statusEl.innerHTML = `${icon("alert")}<span>${esc(err.message)}</span>`;
          setDialogFooter(`<button type="button" class="btn btn-primary" data-action="close-dialog">Close</button>`);
          resolve(null);
          return;
        }
      }
      refreshApps();
      poll();
    })();
  });
}

let backgroundWatcher = null;
function watchInBackground() {
  if (backgroundWatcher) return;
  const tick = async () => {
    for (const [taskId, label] of [...watchedTasks]) {
      try {
        const task = await api(`/apps/tasks/${taskId}?since=999999`);
        if (task.status === "success") {
          watchedTasks.delete(taskId);
          toast(`${label.replace(/…$/, "")}: done`, "success");
          refreshApps();
        } else if (task.status === "failed") {
          watchedTasks.delete(taskId);
          toast(`${label.replace(/…$/, "")} failed: ${task.error}`, "error");
          refreshApps();
        }
      } catch (err) {
        if (err.status === 404) watchedTasks.delete(taskId);
      }
    }
    backgroundWatcher = watchedTasks.size ? setTimeout(tick, 2000) : null;
  };
  backgroundWatcher = setTimeout(tick, 2000);
}

// ── Add app wizard ───────────────────────────────────────────────────────────

function openAddApp() {
  const w = {
    step: 1,
    source: "zip",
    file: null,
    gitUrl: "",
    branch: "main",
    display: "",
    id: "",
    idEdited: false,
    description: "",
    type: null,
    sched: parseSchedule(null),
    schedName: "",
    activate: true,
    editor: null,
  };
  renderAddStep(w);
}

function addStepIndicator(w) {
  const labels = ["Source", "Details", w.type === "SCHEDULED" ? "Schedule" : "Finish"];
  return `<ol class="wizard-steps">${labels
    .map((l, i) => `<li class="${i + 1 === w.step ? "current" : i + 1 < w.step ? "done" : ""}"><span>${i + 1 < w.step ? icon("check") : i + 1}</span>${esc(l)}</li>`)
    .join("")}</ol>`;
}

function renderAddStep(w) {
  let body = "";
  if (w.step === 1) {
    body = `
      ${addStepIndicator(w)}
      <p class="lead">Where is your app's code?</p>
      <div class="segmented" role="group" aria-label="Source">
        <button type="button" class="seg-btn ${w.source === "zip" ? "active" : ""}" data-src="zip" aria-pressed="${w.source === "zip"}">${icon("zip")}Upload a ZIP</button>
        <button type="button" class="seg-btn ${w.source === "git" ? "active" : ""}" data-src="git" aria-pressed="${w.source === "git"}">${icon("git")}Git repository</button>
      </div>
      <div ${w.source === "zip" ? "" : "hidden"}>
        ${dropzoneHtml(w.file)}
        <p class="hint">Put your main <code>.py</code> file at the top level (a single folder around everything is fine) and list packages in <code>requirements.txt</code>. <button type="button" class="link-btn" data-action="open-guide">Packaging guide</button></p>
      </div>
      <div ${w.source === "git" ? "" : "hidden"}>
        <label class="field"><span class="field-label">Repository URL</span>
          <input type="text" class="input" name="gitUrl" value="${esc(w.gitUrl)}" placeholder="https://github.com/you/your-app.git" autocomplete="off" spellcheck="false" ${w.source === "git" ? "autofocus" : ""}/></label>
        <label class="field field-narrow"><span class="field-label">Branch</span>
          <input type="text" class="input" name="branch" value="${esc(w.branch)}" autocomplete="off" spellcheck="false" /></label>
        <p class="hint">The server must be able to clone it: public repos work as-is; private ones need credentials set up for the Mantyx user.</p>
      </div>`;
  } else if (w.step === 2) {
    body = `
      ${addStepIndicator(w)}
      <label class="field"><span class="field-label">Name</span>
        <input type="text" class="input" name="display" value="${esc(w.display)}" placeholder="Weather bot" maxlength="255" autofocus /></label>
      <div class="field">
        <span class="field-label">App ID</span>
        <div class="id-row">
          <input type="text" class="input mono" name="appId" value="${esc(w.id)}" maxlength="64" spellcheck="false" autocomplete="off" />
        </div>
        <span class="hint">Used for its folders. Lowercase letters, numbers, - and _. Can't be changed later.</span>
      </div>
      <label class="field"><span class="field-label">Description <span class="optional">optional</span></span>
        <textarea class="input" name="description" rows="2" placeholder="What does it do?">${esc(w.description)}</textarea></label>
      <div class="field">
        <span class="field-label">How should it run?</span>
        <div class="choice-cards">
          <label class="choice"><input type="radio" name="type" value="PERPETUAL" ${w.type === "PERPETUAL" ? "checked" : ""}/>
            <span class="choice-body">${icon("refresh")}<strong>Always running</strong>
            <span>Keeps running in the background and is restarted if it crashes. For bots, web servers, watchers.</span></span></label>
          <label class="choice"><input type="radio" name="type" value="SCHEDULED" ${w.type === "SCHEDULED" ? "checked" : ""}/>
            <span class="choice-body">${icon("clock")}<strong>On a schedule</strong>
            <span>Starts at set times, does its job and exits. For reports, backups, syncs.</span></span></label>
        </div>
      </div>
      <p class="error-text" id="addError" hidden></p>`;
  } else {
    const isSched = w.type === "SCHEDULED";
    body = `
      ${addStepIndicator(w)}
      ${
        isSched
          ? `<p class="lead">When should it run?</p>
             <label class="field"><span class="field-label">Schedule name <span class="optional">optional</span></span>
               <input type="text" class="input" name="schedName" value="${esc(w.schedName)}" placeholder="e.g. Every morning" /></label>
             ${scheduleEditorHtml(w.sched, { idPrefix: "add" })}`
          : `<p class="lead">Ready to add <strong>${esc(w.display)}</strong>.</p>
             <ul class="checklist">
               <li>${icon("check")}${w.source === "zip" ? `Upload <strong>${esc(w.file && w.file.name)}</strong>` : `Clone <strong>${esc(w.gitUrl)}</strong> (${esc(w.branch)})`}</li>
               <li>${icon("check")}Install its dependencies into a private Python environment</li>
             </ul>`
      }
      <label class="toggle toggle-block"><input type="checkbox" name="activate" ${w.activate ? "checked" : ""}/>
        <span>${isSched ? "Turn on the schedule right away" : "Start it right away"}</span></label>
      <p class="error-text" id="addError" hidden></p>`;
  }

  const footer = `
    ${w.step > 1 ? `<button type="button" class="btn btn-ghost" data-wiz="back">Back</button>` : `<span></span>`}
    <span class="grow"></span>
    <button type="submit" class="btn btn-primary">${w.step === 3 ? "Add app" : "Continue"}</button>`;

  const bodyEl = openDialog({
    title: "Add an app",
    size: "md",
    body,
    footer,
    onSubmit: () => wizardNext(w, bodyEl),
  });
  document.getElementById("dialogFooter").onclick = (e) => {
    if (e.target.closest("[data-wiz='back']")) {
      readWizard(w, bodyEl);
      w.step -= 1;
      renderAddStep(w);
    }
  };

  if (w.step === 1) {
    bodyEl.querySelectorAll("[data-src]").forEach((b) =>
      b.addEventListener("click", () => {
        readWizard(w, bodyEl);
        w.source = b.dataset.src;
        renderAddStep(w);
      }),
    );
    bindDropzone(bodyEl, (file) => {
      w.file = file;
      if (!w.display) w.display = titleFromFilename(file.name);
    });
  }
  if (w.step === 2) {
    const nameInput = bodyEl.querySelector("[name=display]");
    const idInput = bodyEl.querySelector("[name=appId]");
    if (!w.id && w.display) idInput.value = w.id = slugify(w.display);
    nameInput.addEventListener("input", () => {
      if (!w.idEdited) idInput.value = slugify(nameInput.value);
    });
    idInput.addEventListener("input", () => {
      w.idEdited = true;
    });
  }
  if (w.step === 3 && w.type === "SCHEDULED") {
    w.editor = bindScheduleEditor(bodyEl, w.sched);
  }
}

function readWizard(w, bodyEl) {
  const val = (name) => {
    const el = bodyEl.querySelector(`[name=${name}]`);
    return el ? el.value : undefined;
  };
  if (w.step === 1) {
    w.gitUrl = (val("gitUrl") ?? w.gitUrl).trim();
    w.branch = (val("branch") ?? w.branch).trim() || "main";
  } else if (w.step === 2) {
    w.display = (val("display") ?? "").trim();
    w.id = (val("appId") ?? "").trim();
    w.description = (val("description") ?? "").trim();
    const type = bodyEl.querySelector("[name=type]:checked");
    w.type = type ? type.value : null;
  } else {
    w.schedName = (val("schedName") ?? "").trim();
    const act = bodyEl.querySelector("[name=activate]");
    w.activate = act ? act.checked : w.activate;
    if (w.editor) w.sched = w.editor.getModel();
  }
}

function wizardError(bodyEl, message) {
  const el = bodyEl.querySelector("#addError") || bodyEl.querySelector(".dropzone-error");
  if (el) {
    el.textContent = message;
    el.hidden = false;
  } else {
    toast(message, "error");
  }
}

function wizardNext(w, bodyEl) {
  readWizard(w, bodyEl);
  if (w.step === 1) {
    if (w.source === "zip" && !w.file) return wizardError(bodyEl, "Choose a ZIP file first");
    if (w.source === "git") {
      if (!w.gitUrl) return wizardError(bodyEl, "Enter the repository URL");
      if (!w.display) w.display = titleFromFilename(w.gitUrl.split("/").pop().replace(/\.git$/, ""));
    }
    w.step = 2;
    return renderAddStep(w);
  }
  if (w.step === 2) {
    if (!w.display) return wizardError(bodyEl, "Give the app a name");
    if (!/^[a-z0-9][a-z0-9_-]{0,63}$/.test(w.id)) return wizardError(bodyEl, "The App ID can only use lowercase letters, numbers, - and _, and must start with a letter or number");
    if (state.apps.some((a) => a.name === w.id)) return wizardError(bodyEl, `An app with the ID “${w.id}” already exists`);
    if (!w.type) return wizardError(bodyEl, "Choose how it should run");
    w.step = 3;
    return renderAddStep(w);
  }
  let schedule = null;
  if (w.type === "SCHEDULED") {
    try {
      const spec = w.editor.getSpec();
      schedule = { ...spec, name: w.schedName || describeSchedule(spec) };
    } catch (err) {
      return wizardError(bodyEl, err.message);
    }
  }
  submitNewApp(w, schedule);
}

async function submitNewApp(w, schedule) {
  const form = new FormData();
  form.append("app_name", w.id);
  form.append("display_name", w.display);
  form.append("app_type", w.type);
  if (w.description) form.append("description", w.description);
  form.append("install", "true");
  form.append("activate", String(w.activate));
  if (schedule) form.append("schedule", JSON.stringify(schedule));
  let path = "/apps/upload/zip";
  if (w.source === "zip") {
    form.append("file", w.file);
  } else {
    path = "/apps/upload/git";
    form.append("git_url", w.gitUrl);
    form.append("branch", w.branch);
  }

  const result = await runTask({
    title: `Adding ${w.display}`,
    start: () => api(path, { method: "POST", form }),
    successText: () =>
      w.type === "SCHEDULED"
        ? w.activate
          ? `${w.display} is ready and will run on its schedule.`
          : `${w.display} is installed. Activate it when you want the schedule to run.`
        : w.activate
          ? `${w.display} is installed and running.`
          : `${w.display} is installed. Start it whenever you're ready.`,
    doneButtons: (r) => (r.app_id ? `<a class="btn btn-ghost" href="#/app/${r.app_id}" data-action="close-dialog">Open app</a>` : ""),
  });
  if (result === null) refreshApps();
}

function titleFromFilename(name) {
  const base = String(name || "").replace(/\.zip$/i, "").replace(/[-_]+/g, " ").trim();
  return base.replace(/\b\w/g, (c) => c.toUpperCase()).replace(/([a-z])([A-Z])/g, "$1 $2");
}

function dropzoneHtml(file) {
  return `<label class="dropzone ${file ? "has-file" : ""}" tabindex="0">
    <input type="file" accept=".zip,application/zip" hidden />
    ${icon(file ? "zip" : "upload")}
    <span class="dropzone-title">${file ? esc(file.name) : "Drop a .zip file here or click to choose"}</span>
    <span class="dropzone-sub">${file ? `${esc(fmtBytes(file.size))} · click to choose a different file` : ""}</span>
    <span class="dropzone-error error-text" hidden></span>
  </label>`;
}

function bindDropzone(root, onFile) {
  const zone = root.querySelector(".dropzone");
  if (!zone) return;
  const input = zone.querySelector("input[type=file]");
  const accept = (file) => {
    if (!file) return;
    if (!/\.zip$/i.test(file.name)) {
      const err = zone.querySelector(".dropzone-error");
      err.textContent = "That isn't a .zip file";
      err.hidden = false;
      return;
    }
    onFile(file);
    zone.outerHTML = dropzoneHtml(file);
    bindDropzone(root, onFile);
  };
  input.addEventListener("change", () => accept(input.files[0]));
  zone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      input.click();
    }
  });
  ["dragenter", "dragover"].forEach((ev) =>
    zone.addEventListener(ev, (e) => {
      e.preventDefault();
      zone.classList.add("drag");
    }),
  );
  ["dragleave", "drop"].forEach((ev) =>
    zone.addEventListener(ev, (e) => {
      e.preventDefault();
      zone.classList.remove("drag");
    }),
  );
  zone.addEventListener("drop", (e) => accept(e.dataTransfer.files[0]));
}

// ── Update dialog ────────────────────────────────────────────────────────────

function openUpdateDialog(app) {
  const u = { mode: app.git_url ? "git" : "zip", file: null, check: null };
  const running = ["running", "starting"].includes(app.status);
  const render = () => {
    const body = openDialog({
      title: `Update ${app.display_name}`,
      size: "md",
      body: `
        <p class="muted">Currently v${esc(app.version)}${app.git_commit ? ` (${esc(app.git_commit.slice(0, 8))})` : ""}.</p>
        ${
          app.git_url
            ? `<div class="segmented" role="group">
                 <button type="button" class="seg-btn ${u.mode === "git" ? "active" : ""}" data-umode="git">${icon("git")}Pull from Git</button>
                 <button type="button" class="seg-btn ${u.mode === "zip" ? "active" : ""}" data-umode="zip">${icon("zip")}Upload a ZIP</button>
               </div>`
            : ""
        }
        <div ${u.mode === "git" ? "" : "hidden"}>
          <div class="git-check" id="gitCheck">${gitCheckHtml(app, u.check)}</div>
        </div>
        <div ${u.mode === "zip" ? "" : "hidden"}>${dropzoneHtml(u.file)}</div>
        <label class="toggle toggle-block"><input type="checkbox" name="backup" checked /><span>Save the current version first, so I can roll back</span></label>
        <div class="note">${icon("info")}<span>${
          running
            ? `${esc(app.display_name)} will be stopped only while the new version is installed, then started again. If anything fails, the current version keeps running.`
            : "If anything fails, the current version is kept."
        } Your app's data folder isn't affected.</span></div>`,
      footer: `<button type="button" class="btn btn-ghost" data-action="close-dialog">Cancel</button>
               <button type="submit" class="btn btn-primary" id="updateGo">${u.mode === "git" ? "Pull and update" : "Upload and update"}</button>`,
      onSubmit: () => go(body),
    });
    body.querySelectorAll("[data-umode]").forEach((b) =>
      b.addEventListener("click", () => {
        u.mode = b.dataset.umode;
        render();
      }),
    );
    bindDropzone(body, (file) => {
      u.file = file;
    });
    if (u.mode === "git" && !u.check) checkGit(body);
  };

  const checkGit = async (body) => {
    u.check = { loading: true };
    body.querySelector("#gitCheck").innerHTML = gitCheckHtml(app, u.check);
    try {
      u.check = await api(`/apps/${app.id}/check-git-update?refresh=true`);
    } catch (err) {
      u.check = { error: err.message };
    }
    const el = document.querySelector("#gitCheck");
    if (el) el.innerHTML = gitCheckHtml(app, u.check);
  };

  const go = async (body) => {
    const backup = body.querySelector("[name=backup]").checked;
    const form = new FormData();
    form.append("backup", String(backup));
    let path = `/apps/${app.id}/update/git`;
    if (u.mode === "zip") {
      if (!u.file) {
        const err = body.querySelector(".dropzone-error");
        err.textContent = "Choose a ZIP file first";
        err.hidden = false;
        return;
      }
      form.append("file", u.file);
      path = `/apps/${app.id}/update/zip`;
    }
    await runTask({
      title: `Updating ${app.display_name}`,
      start: () => api(path, { method: "POST", form }),
      successText: (r) =>
        r.changed === false
          ? "Already up to date. Nothing was changed."
          : `Updated to v${r.new_version}${running ? " and restarted" : ""}.`,
    });
  };

  render();
}

function gitCheckHtml(app, check) {
  if (!check || check.loading) return `${icon("refresh", "spin")}<span>Checking ${esc(app.git_branch || "main")} for new commits…</span>`;
  if (check.error) return `${icon("alert")}<span class="error-text">${esc(check.error)}</span>`;
  if (check.update_available)
    return `${icon("download")}<span><strong>${check.commits_behind || "New"} new commit${check.commits_behind === 1 ? "" : "s"}</strong> on ${esc(app.git_branch || "main")} (${esc(
      check.local_commit.slice(0, 8),
    )} → ${esc(check.remote_commit.slice(0, 8))})</span>`;
  return `${icon("check")}<span>Already up to date with ${esc(app.git_branch || "main")} (${esc((check.local_commit || "").slice(0, 8))}).</span>`;
}

// ── Settings dialog ──────────────────────────────────────────────────────────

const COMMON_TIMEZONES = [
  "UTC",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Phoenix",
  "America/Los_Angeles",
  "Europe/London",
  "Europe/Berlin",
  "Europe/Paris",
  "Asia/Tokyo",
  "Australia/Sydney",
];

async function openSettings(tab = "general") {
  const body = openDialog({
    title: "Settings",
    size: "lg",
    body: `
      <nav class="tabs tabs-sm" role="tablist">
        <button type="button" class="tab ${tab === "general" ? "active" : ""}" data-stab="general">General</button>
        <button type="button" class="tab ${tab === "backup" ? "active" : ""}" data-stab="backup">Backup &amp; restore</button>
        <button type="button" class="tab ${tab === "about" ? "active" : ""}" data-stab="about">About</button>
      </nav>
      <div id="settingsPane"><div class="loading">${icon("refresh", "spin")} Loading…</div></div>`,
  });
  body.querySelectorAll("[data-stab]").forEach((b) => b.addEventListener("click", () => openSettings(b.dataset.stab)));
  const pane = body.querySelector("#settingsPane");

  if (tab === "general") {
    let tzInfo;
    let all;
    try {
      [tzInfo, all] = await Promise.all([api("/settings/timezone"), api("/settings/available-timezones")]);
    } catch (err) {
      pane.innerHTML = `<p class="error-text">${esc(err.message)}</p>`;
      return;
    }
    const opt = (tz) => `<option value="${esc(tz)}" ${tz === tzInfo.timezone ? "selected" : ""}>${esc(tz.replace(/_/g, " "))}</option>`;
    pane.innerHTML = `
      <label class="field">
        <span class="field-label">Timezone for schedules</span>
        <select class="input" id="tzSelect">
          <optgroup label="Common">${COMMON_TIMEZONES.map(opt).join("")}</optgroup>
          ${Object.entries(all.grouped).map(([region, list]) => `<optgroup label="${esc(region)}">${list.map(opt).join("")}</optgroup>`).join("")}
        </select>
        <span class="hint">“7:00 every day” means 7:00 in this timezone. The server's own timezone is ${esc(tzInfo.detected_timezone)}. Changes apply immediately.</span>
      </label>
      <div class="button-row"><button type="button" class="btn btn-primary" id="tzSave">Save</button></div>`;
    pane.querySelector("#tzSave").addEventListener("click", async () => {
      const value = pane.querySelector("#tzSelect").value;
      try {
        const res = await api("/settings/timezone", { method: "PUT", json: { value } });
        toast(res.message, "success");
        await loadSystemInfo();
        refreshApps();
      } catch (err) {
        toast(err.message, "error");
      }
    });
  } else if (tab === "backup") {
    pane.innerHTML = `
      <section class="settings-section">
        <h3>Back up everything</h3>
        <p class="hint">Downloads one file with every app, its data folder, schedules, run history and settings. Python environments aren't included; they're rebuilt automatically when you restore.</p>
        <button type="button" class="btn btn-secondary" data-action="export-backup">${icon("download")}<span>Download backup</span></button>
      </section>
      <section class="settings-section">
        <h3>Restore from a backup</h3>
        <p class="hint"><strong>This replaces everything</strong>: all current apps, data and settings are swapped for the backup's contents. Apps are stopped during the restore and started again afterwards.</p>
        ${dropzoneHtml(null)}
        <div class="button-row"><button type="button" class="btn btn-danger" id="restoreGo" disabled>Restore…</button></div>
      </section>`;
    let file = null;
    bindDropzone(pane, (f) => {
      file = f;
      pane.querySelector("#restoreGo").disabled = false;
    });
    pane.querySelector("#restoreGo").addEventListener("click", async () => {
      if (!file) return;
      const ok = await confirmAction({
        title: "Replace everything with this backup?",
        message: `<p>All current apps, their data and settings will be replaced by the contents of <strong>${esc(file.name)}</strong>. This can't be undone.</p>`,
        confirmLabel: "Restore backup",
        danger: true,
        typeToConfirm: "restore",
      });
      if (!ok) return;
      const form = new FormData();
      form.append("file", file);
      const result = await runTask({
        title: "Restoring backup",
        start: () => api("/backup/import", { method: "POST", form }),
        successText: (r) =>
          `Restored ${r.app_count} app${r.app_count === 1 ? "" : "s"}.` +
          (r.venv_errors && r.venv_errors.length ? ` ${r.venv_errors.length} couldn't install dependencies; use Rebuild environment on them.` : ""),
      });
      if (result) navigate("#/");
    });
  } else {
    let info;
    let sched;
    try {
      [info, sched] = await Promise.all([api("/system/info"), api("/schedules/debug/scheduler-status")]);
    } catch (err) {
      pane.innerHTML = `<p class="error-text">${esc(err.message)}</p>`;
      return;
    }
    pane.innerHTML = `
      <dl class="facts">
        <dt>Version</dt><dd>Mantyx ${esc(info.version)}</dd>
        <dt>Scheduler</dt><dd>${sched.running ? "Running" : "Not running"} · ${esc(sched.scheduler_timezone)}</dd>
        <dt>API docs</dt><dd><a href="/docs" target="_blank" rel="noopener">/docs</a></dd>
      </dl>
      <details class="advanced">
        <summary>Scheduled jobs (diagnostics)</summary>
        <div class="table-wrap"><table class="table table-sm">
          <thead><tr><th>Job</th><th>Next run</th><th>Trigger</th></tr></thead>
          <tbody>${sched.jobs
            .map((j) => `<tr><td>${esc(j.name)}</td><td>${esc(j.next_run_time ? fmtInZone(j.next_run_time, sched.scheduler_timezone) : "Paused")}</td><td><code>${esc(j.trigger)}</code></td></tr>`)
            .join("")}</tbody>
        </table></div>
      </details>`;
  }
}

// ── Guide ────────────────────────────────────────────────────────────────────

function openGuide() {
  openDialog({
    title: "Preparing an app for Mantyx",
    size: "lg",
    body: `
      <div class="prose guide">
        <p>Mantyx runs plain Python scripts, each in its own private Python environment, so their packages never clash. No Mantyx-specific code is needed.</p>

        <h3>1. Package it</h3>
        <pre class="code">my-app.zip
├── main.py           ← the file Mantyx runs (or app.py, run.py…)
├── requirements.txt  ← packages to install (optional)
└── …any other files and folders</pre>
        <p>Zipping the folder itself is fine too. Or skip the ZIP and point Mantyx at a Git repository.</p>

        <h3>2. Pick how it runs</h3>
        <p><strong>Always running</strong> apps keep going (a loop, a bot, a web server). If they crash, Mantyx restarts them. They also start automatically whenever Mantyx starts.</p>
        <pre class="code">import time

while True:
    do_work()
    time.sleep(60)</pre>
        <p><strong>Scheduled</strong> apps do their job and exit. Exit with a non-zero code (or let an exception escape) to mark a run as failed.</p>
        <pre class="code">import sys

def main():
    ...

if __name__ == "__main__":
    sys.exit(main())</pre>

        <h3>3. Keep data in APP_DATA_DIR</h3>
        <p>Your app's own files are replaced on every update. Store anything you need to keep (databases, caches, state) in the folder Mantyx gives you:</p>
        <pre class="code">import os
from pathlib import Path

data_dir = Path(os.environ.get("APP_DATA_DIR", "./data"))
data_dir.mkdir(parents=True, exist_ok=True)</pre>

        <h3>4. Settings and secrets</h3>
        <p>Add API keys and other settings as <strong>environment variables</strong> on the app's Settings tab, and read them with <code>os.environ["NAME"]</code>. Don't put secrets in your code.</p>

        <h3>5. Logs</h3>
        <p>Everything your app prints (and any errors) shows up live on its Logs tab. Each run keeps its own log.</p>

        <h3>Using an AI assistant?</h3>
        <p>Ask it to: <em>“Package this as a Mantyx app: a top-level main.py entrypoint, a requirements.txt, read config from environment variables, and store persistent files under the APP_DATA_DIR environment variable.”</em> The full guide is <code>APP_PACKAGING.md</code> in the Mantyx repository.</p>
      </div>`,
    footer: `<button type="button" class="btn btn-primary" data-action="close-dialog">Got it</button>`,
  });
}

// ── Actions ──────────────────────────────────────────────────────────────────

/** Run an API call for a quick action, toasting the outcome. */
async function doAction(call, successMessage) {
  try {
    await call();
    if (successMessage) toast(successMessage, "success");
  } catch (err) {
    toast(err.message, "error");
  }
  await refreshApps();
}

const ACTIONS = {
  "add-app": () => openAddApp(),
  "open-guide": () => openGuide(),
  "open-settings": () => openSettings(),
  filter: (_, el) => {
    state.filter = el.dataset.filter;
    if (state.filter === "all") state.search = "";
    renderDashboardShell();
  },
  open: (app) => navigate(`#/app/${app.id}`),
  "open-logs": (app) => navigate(`#/app/${app.id}/logs`),
  tab: (_, el) => navigate(`#/app/${state.detail.id}/${el.dataset.tab}`),
  install: (app) =>
    runTask({
      title: `Installing ${app.display_name}`,
      start: () => api(`/apps/${app.id}/install`, { method: "POST" }),
      successText: `${app.display_name} is installed. ${isPerpetual(app) ? "Start it when you're ready." : "Activate it to run on its schedule."}`,
      doneButtons: () =>
        isPerpetual(app)
          ? `<button type="button" class="btn btn-ghost" data-action="start" data-app-id="${app.id}">${icon("play")}<span>Start now</span></button>`
          : "",
    }),
  start: (app) => {
    if (dialogIsOpen()) closeDialog();
    return doAction(() => api(`/apps/${app.id}/start`, { method: "POST" }), `${app.display_name} started`);
  },
  stop: async (app) => {
    const ok = await confirmAction({
      title: `Stop ${app.display_name}?`,
      message: "<p>It will stay stopped, even if Mantyx restarts, until you start it again.</p>",
      confirmLabel: "Stop",
    });
    if (ok) await doAction(() => api(`/apps/${app.id}/stop`, { method: "POST" }), `${app.display_name} stopped`);
  },
  restart: (app) => doAction(() => api(`/apps/${app.id}/restart`, { method: "POST" }), `${app.display_name} restarted`),
  enable: (app) =>
    doAction(
      () => api(`/apps/${app.id}/enable`, { method: "POST" }),
      isScheduled(app) ? `${app.display_name} will run on its schedule` : `${app.display_name} started`,
    ),
  disable: async (app) => {
    const ok = await confirmAction({
      title: `Pause ${app.display_name}?`,
      message: "<p>Its schedules won't run until you resume it. You can still run it manually.</p>",
      confirmLabel: "Pause",
    });
    if (ok) await doAction(() => api(`/apps/${app.id}/disable`, { method: "POST" }), `${app.display_name} paused`);
  },
  "run-now": async (app) => {
    await doAction(() => api(`/apps/${app.id}/run`, { method: "POST" }), `${app.display_name} is running`);
    if (state.route.name === "app" && state.detail && state.detail.tab === "logs") setTimeout(() => renderLogsTab(detailApp()), 800);
  },
  "cancel-run": async (app, el) => {
    const ok = await confirmAction({ title: "Stop this run?", message: "<p>The app will be told to stop. The run is recorded as stopped.</p>", confirmLabel: "Stop run" });
    if (ok) await doAction(() => api(`/executions/${el.dataset.executionId}/cancel`, { method: "POST" }), "Stopping run");
  },
  "show-task": (app, el) => runTask({ title: app.active_task ? app.active_task.name : "Working", start: el.dataset.taskId, successText: "Finished." }),
  update: (app) => openUpdateDialog(app),
  rebuild: async (app) => {
    const ok = await confirmAction({
      title: "Rebuild the Python environment?",
      message: `<p>Mantyx deletes ${esc(app.display_name)}'s installed packages and reinstalls them from requirements.txt.${
        app.status === "running" ? " The app is stopped meanwhile and started again afterwards." : ""
      }</p>`,
      confirmLabel: "Rebuild",
    });
    if (ok)
      runTask({
        title: `Rebuilding ${app.display_name}`,
        start: () => api(`/apps/${app.id}/rebuild-venv`, { method: "POST" }),
        successText: "Environment rebuilt.",
      });
  },
  delete: async (app) => {
    const ok = await confirmAction({
      title: `Delete ${app.display_name}?`,
      message: `<p>This stops the app and permanently deletes its files, its data folder, logs, run history and saved versions. Consider downloading a backup first (Settings → Backup).</p>`,
      confirmLabel: "Delete forever",
      danger: true,
      typeToConfirm: app.name,
    });
    if (!ok) return;
    try {
      await api(`/apps/${app.id}`, { method: "DELETE" });
      toast(`${app.display_name} deleted`, "success");
      navigate("#/");
    } catch (err) {
      toast(err.message, "error");
    }
    refreshApps();
  },
  "add-schedule": (app) => openScheduleDialog(app),
  "edit-schedule": (_, el) => {
    const s = state.detail.schedules.find((x) => x.id === Number(el.dataset.scheduleId));
    if (s) openScheduleDialog(detailApp(), s);
  },
  "delete-schedule": async (_, el) => {
    const s = state.detail.schedules.find((x) => x.id === Number(el.dataset.scheduleId));
    if (!s) return;
    const ok = await confirmAction({ title: "Delete this schedule?", message: `<p>“${esc(s.name)}” (${esc(describeSchedule(s))}) will be removed.</p>`, confirmLabel: "Delete", danger: true });
    if (!ok) return;
    await doAction(() => api(`/schedules/${s.id}`, { method: "DELETE" }), "Schedule deleted");
    renderSchedulesTab(detailApp());
  },
  "toggle-schedule": async (_, el) => {
    const id = el.dataset.scheduleId;
    const on = el.checked;
    await doAction(() => api(`/schedules/${id}/${on ? "enable" : "disable"}`, { method: "POST" }), on ? "Schedule turned on" : "Schedule turned off");
    renderSchedulesTab(detailApp());
  },
  "view-run-log": async (_, el) => {
    const app = detailApp();
    const executionId = Number(el.dataset.executionId);
    if (state.detail.tab !== "logs") {
      history.replaceState(null, "", `#/app/${app.id}/logs`);
      state.route = parseRoute();
      state.detail.tab = "logs";
      updateDetail();
    }
    document.getElementById("tabPanel").innerHTML = `<div class="loading">${icon("refresh", "spin")} Loading…</div>`;
    renderLogsTab(app, { executionId });
  },
  "more-runs": () => {
    state.detail.runsLimit += 50;
    loadRuns(detailApp());
  },
  "add-env": () => {
    document.getElementById("envList").insertAdjacentHTML("beforeend", envRow());
    document.getElementById("saveBar").hidden = false;
    const rows = document.querySelectorAll("#envList .env-row");
    rows[rows.length - 1].querySelector("input").focus();
  },
  "remove-env": (_, el) => {
    el.closest(".env-row").remove();
    document.getElementById("saveBar").hidden = false;
  },
  reveal: (_, el) => {
    const input = el.parentElement.querySelector("input");
    input.type = input.type === "password" ? "text" : "password";
  },
  "reset-settings": () => renderSettingsTab(detailApp()),
  "check-git": async (app) => {
    const line = document.getElementById("gitLine");
    if (line) line.innerHTML = `${icon("refresh", "spin")} Checking…`;
    try {
      await api(`/apps/${app.id}/check-git-update?refresh=true`);
    } catch (err) {
      toast(err.message, "error");
    }
    await refreshApps();
    if (state.detail && state.detail.tab === "versions") renderVersionsTab(detailApp());
  },
  "restore-backup": async (app, el) => {
    const label = el.dataset.backupLabel;
    const ok = await confirmAction({
      title: `Roll back to ${label}?`,
      message: `<p>The app's code goes back to ${esc(label)}. The current version is saved first, so you can undo this. The data folder isn't touched.${
        app.status === "running" ? " The app restarts on the restored version." : ""
      }</p>`,
      confirmLabel: "Roll back",
    });
    if (!ok) return;
    await runTask({
      title: `Rolling back ${app.display_name}`,
      start: () => api(`/apps/${app.id}/backups/${encodeURIComponent(el.dataset.backupId)}/restore`, { method: "POST" }),
      successText: (r) => `Restored v${r.new_version}.`,
      onSuccess: () => state.detail && state.detail.tab === "versions" && setTimeout(() => renderVersionsTab(detailApp()), 300),
    });
  },
  "export-backup": () =>
    runTask({
      title: "Creating backup",
      start: () => api("/backup/export", { method: "POST" }),
      successText: "Backup created. Your download should start now.",
      onSuccess: (r) => {
        window.location.href = `${API_BASE}/backup/export/${r.task_id}/download`;
      },
    }),
};

function handleActionEvent(e) {
  const el = e.target.closest("[data-action]");
  if (!el || el.disabled) return;
  const action = el.dataset.action;
  const handler = ACTIONS[action];
  if (!handler) return; // e.g. close-dialog is handled by ui.js
  if (el.tagName === "INPUT" && e.type === "click") return; // checkboxes act on change
  if (el.tagName !== "INPUT" && e.type === "change") return;
  e.preventDefault();
  closeMenus();
  const appId = el.dataset.appId || (state.detail && state.detail.id);
  const app = appId ? appById(appId) : null;
  if (el.dataset.appId && !app) {
    toast("That app no longer exists", "error");
    return;
  }
  handler(app, el, e);
}

// ── Boot ─────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  hydrateIcons(document);
  document.addEventListener("click", handleActionEvent);
  document.addEventListener("change", handleActionEvent);

  connection.listeners.push((ok) => {
    const bannerEl = document.getElementById("banner");
    const conn = document.getElementById("connection");
    conn.dataset.state = ok ? "ok" : "down";
    conn.querySelector(".connection-label").textContent = ok ? "Connected" : "Offline";
    conn.title = ok ? "Connected to Mantyx" : "Can't reach the Mantyx server";
    if (ok) {
      bannerEl.hidden = true;
      toast("Reconnected to Mantyx", "success");
      loadSystemInfo();
    } else {
      bannerEl.hidden = false;
      bannerEl.innerHTML = `${icon("alert")}<span>Can't reach the Mantyx server. Retrying… (Your apps keep running; this only affects this page.)</span>`;
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && !e.target.closest("input, textarea, select") && !dialogIsOpen()) {
      const search = document.getElementById("appSearch");
      if (search) {
        e.preventDefault();
        search.focus();
      }
    }
  });

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refreshApps();
  });

  window.addEventListener("hashchange", onRoute);
  onRoute();
  loadSystemInfo();
  refreshApps();
  setInterval(updateClock, 15000);
});
