// Mantyx UI helpers: escaping, icons, API access, time formatting, toasts,
// dialogs, confirmations and menus. Loaded before schedule.js and main.js.
"use strict";

const API_BASE = "/api";

// ── Escaping ─────────────────────────────────────────────────────────────────

const ESC_MAP = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

/** Escape any value for safe use in HTML text or attribute values. */
function esc(value) {
  if (value === null || value === undefined) return "";
  return String(value).replace(/[&<>"']/g, (c) => ESC_MAP[c]);
}

// ── Icons (inline SVG, stroke-based) ─────────────────────────────────────────

const ICON_PATHS = {
  plus: '<path d="M12 5v14M5 12h14"/>',
  settings:
    '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
  book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  play: '<path d="M6 4l14 8-14 8z"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
  pause: '<path d="M8 5v14M16 5v14"/>',
  restart: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
  more: '<circle cx="12" cy="5" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="12" cy="19" r="1.2"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M17 8l-5-5-5 5M12 3v12"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5M12 15V3"/>',
  git: '<circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="9" r="2.5"/><path d="M6 8.5v7M18 11.5c0 3-3 4-9.5 5"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  external: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><path d="M15 3h6v6M10 14 21 3"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  alert: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/>',
  trash: '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/>',
  back: '<path d="M15 18l-6-6 6-6"/>',
  down: '<path d="M6 9l6 6 6-6"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  history: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l4 2"/>',
  terminal: '<path d="M4 17l6-5-6-5M12 19h8"/>',
  box: '<path d="M21 16V8a2 2 0 0 0-1-1.7l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.7l7 4a2 2 0 0 0 2 0l7-4a2 2 0 0 0 1-1.7z"/><path d="M3.3 7 12 12l8.7-5M12 22V12"/>',
  calendar: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
  wrench: '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z"/>',
  zip: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M10 9h1M10 12h1M10 15h1"/>',
  eye: '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12z"/><circle cx="12" cy="12" r="3"/>',
};

function icon(name, extraClass = "") {
  const paths = ICON_PATHS[name] || ICON_PATHS.info;
  return `<svg class="icon ${extraClass}" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${paths}</svg>`;
}

/** Replace <span data-icon="name"> placeholders inside `root` with SVGs. */
function hydrateIcons(root = document) {
  root.querySelectorAll("[data-icon]").forEach((el) => {
    if (el.dataset.iconDone) return;
    el.innerHTML = icon(el.dataset.icon);
    el.dataset.iconDone = "1";
  });
}

// ── API ──────────────────────────────────────────────────────────────────────

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

const connection = {
  ok: true,
  failures: 0,
  listeners: [],
  set(ok) {
    if (ok) this.failures = 0;
    else this.failures += 1;
    // One blip isn't worth alarming anyone; two in a row is.
    const nowOk = ok || this.failures < 2;
    if (nowOk !== this.ok) {
      this.ok = nowOk;
      this.listeners.forEach((fn) => fn(nowOk));
    }
  },
};

function describeApiError(detail, fallback) {
  if (!detail) return fallback;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // FastAPI validation errors
    return detail
      .map((d) => {
        const field = Array.isArray(d.loc) ? d.loc.filter((p) => p !== "body").join(" › ") : "";
        const msg = (d.msg || "").replace(/^Value error, /, "");
        return field ? `${field}: ${msg}` : msg;
      })
      .join("; ");
  }
  return fallback;
}

/**
 * Call the Mantyx API. Never shows UI itself: callers decide how to report
 * errors (usually with toast()). Throws ApiError with a readable message.
 *
 * options: { method, json, form, signal }
 */
async function api(path, options = {}) {
  const init = { method: options.method || "GET", signal: options.signal };
  if (options.json !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(options.json);
  } else if (options.form) {
    init.body = options.form;
  }

  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, init);
  } catch (err) {
    if (err.name === "AbortError") throw err;
    connection.set(false);
    throw new ApiError("Can't reach Mantyx. Check that the server is running.", 0);
  }
  // Any HTTP response means the server is reachable.
  connection.set(true);

  let data = null;
  const text = await response.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!response.ok) {
    const fallback = `Request failed (${response.status})`;
    throw new ApiError(describeApiError(data && data.detail, fallback), response.status);
  }
  return data;
}

// ── Time formatting ──────────────────────────────────────────────────────────

function toDate(value) {
  if (!value) return null;
  const d = value instanceof Date ? value : new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

function fmtDuration(seconds) {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "";
  seconds = Math.max(0, Math.round(seconds));
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m}m ${seconds % 60}s`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ${m % 60}m`;
  const d = Math.floor(h / 24);
  return `${d}d ${h % 24}h`;
}

/** "just now", "5 min ago", "3 h ago", "yesterday", "Oct 3". */
function fmtAgo(value) {
  const d = toDate(value);
  if (!d) return "";
  const s = (Date.now() - d.getTime()) / 1000;
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  if (s < 2 * 86400) return "yesterday";
  if (s < 7 * 86400) return `${Math.floor(s / 86400)} days ago`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function fmtTime(d) {
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

/** For upcoming times: "in 4 min", "today 18:00", "tomorrow 07:00", "Tue 07:00", "Oct 12 07:00". */
function fmtWhen(value) {
  const d = toDate(value);
  if (!d) return "";
  const s = (d.getTime() - Date.now()) / 1000;
  if (s < 0) return fmtAgo(d);
  if (s < 60) return "in under a minute";
  if (s < 3600) return `in ${Math.round(s / 60)} min`;
  const today = new Date();
  const startOfDay = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const dayDiff = Math.round((startOfDay(d) - startOfDay(today)) / 86400000);
  if (dayDiff === 0) return `today ${fmtTime(d)}`;
  if (dayDiff === 1) return `tomorrow ${fmtTime(d)}`;
  if (dayDiff < 7) return `${d.toLocaleDateString(undefined, { weekday: "short" })} ${fmtTime(d)}`;
  return `${d.toLocaleDateString(undefined, { month: "short", day: "numeric" })} ${fmtTime(d)}`;
}

/** Full timestamp for tooltips and tables. */
function fmtDateTime(value) {
  const d = toDate(value);
  if (!d) return "";
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

// ── Misc ─────────────────────────────────────────────────────────────────────

function slugify(text) {
  return String(text || "")
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
}

function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

function fmtBytes(bytes) {
  if (!bytes && bytes !== 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

const ANSI_RE = /\x1b\[[0-9;?]*[ -/]*[@-~]/g;
function stripAnsi(text) {
  return String(text || "").replace(ANSI_RE, "");
}

// ── Toasts ───────────────────────────────────────────────────────────────────

function toast(message, kind = "info", { timeout } = {}) {
  const host = document.getElementById("toasts");
  const el = document.createElement("div");
  el.className = `toast toast-${kind}`;
  el.setAttribute("role", kind === "error" ? "alert" : "status");
  const iconName = kind === "success" ? "check" : kind === "error" ? "alert" : "info";
  el.innerHTML = `${icon(iconName)}<span class="toast-msg">${esc(message)}</span>
    <button type="button" class="icon-btn toast-close" aria-label="Dismiss">${icon("x")}</button>`;
  const remove = () => {
    el.classList.add("toast-leave");
    setTimeout(() => el.remove(), 200);
  };
  el.querySelector(".toast-close").addEventListener("click", remove);
  host.appendChild(el);
  setTimeout(remove, timeout ?? (kind === "error" ? 9000 : 4000));
}

// ── Dialog ───────────────────────────────────────────────────────────────────

const dialogState = { onClose: null };

/**
 * Open the shared dialog. `body` and `footer` are HTML strings.
 * Returns the dialog body element for wiring up events.
 */
function openDialog({ title, body, footer = "", size = "md", onClose = null, onSubmit = null }) {
  const dlg = document.getElementById("dialog");
  if (dlg.open && dialogState.onClose) {
    const prev = dialogState.onClose;
    dialogState.onClose = null;
    prev();
  }
  dlg.className = `dialog dialog-${size}`;
  document.getElementById("dialogTitle").textContent = title;
  const bodyEl = document.getElementById("dialogBody");
  bodyEl.innerHTML = body;
  document.getElementById("dialogFooter").innerHTML = footer;
  document.getElementById("dialogFooter").hidden = !footer;
  hydrateIcons(dlg);
  dialogState.onClose = onClose;
  dialogState.onSubmit = onSubmit;
  if (!dlg.open) dlg.showModal();
  const focusTarget = bodyEl.querySelector("[autofocus]");
  if (focusTarget) focusTarget.focus();
  return bodyEl;
}

function closeDialog() {
  const dlg = document.getElementById("dialog");
  if (dlg.open) dlg.close();
}

function setDialogFooter(html) {
  const footer = document.getElementById("dialogFooter");
  footer.innerHTML = html;
  footer.hidden = !html;
  hydrateIcons(footer);
}

function setDialogTitle(text) {
  document.getElementById("dialogTitle").textContent = text;
}

function dialogIsOpen() {
  return document.getElementById("dialog").open;
}

document.addEventListener("DOMContentLoaded", () => {
  const dlg = document.getElementById("dialog");
  dlg.addEventListener("close", () => {
    const fn = dialogState.onClose;
    dialogState.onClose = null;
    dialogState.onSubmit = null;
    if (fn) fn();
  });
  dlg.addEventListener("click", (e) => {
    // Click on the backdrop closes (the dialog element itself is the backdrop area).
    if (e.target === dlg) dlg.close();
    if (e.target.closest("[data-action='close-dialog']")) dlg.close();
  });
  document.getElementById("dialogForm").addEventListener("submit", (e) => {
    e.preventDefault();
    if (dialogState.onSubmit) dialogState.onSubmit(e);
  });
});

// ── Confirmation ─────────────────────────────────────────────────────────────

/**
 * Ask the user to confirm something. Resolves true/false.
 * typeToConfirm: if set, the user must type this exact text to enable OK.
 */
function confirmAction({
  title,
  message = "",
  confirmLabel = "Confirm",
  danger = false,
  typeToConfirm = null,
}) {
  return new Promise((resolve) => {
    const dlg = document.getElementById("confirm");
    const ok = document.getElementById("confirmOk");
    document.getElementById("confirmTitle").textContent = title;
    const body = document.getElementById("confirmBody");
    body.innerHTML =
      `<div class="confirm-message">${message}</div>` +
      (typeToConfirm
        ? `<label class="field"><span class="field-label">Type <strong>${esc(typeToConfirm)}</strong> to confirm</span>
             <input type="text" class="input" id="confirmType" autocomplete="off" spellcheck="false" /></label>`
        : "");
    ok.textContent = confirmLabel;
    ok.className = `btn ${danger ? "btn-danger" : "btn-primary"}`;
    ok.disabled = !!typeToConfirm;

    const typeInput = body.querySelector("#confirmType");
    if (typeInput) {
      typeInput.addEventListener("input", () => {
        ok.disabled = typeInput.value.trim() !== typeToConfirm;
      });
    }

    let result = false;
    const onClick = (e) => {
      const which = e.target.closest("[data-confirm]");
      if (!which) return;
      e.preventDefault();
      if (which.dataset.confirm === "ok" && ok.disabled) return;
      result = which.dataset.confirm === "ok";
      dlg.close();
    };
    const onSubmit = (e) => {
      e.preventDefault();
      if (ok.disabled) return;
      result = true;
      dlg.close();
    };
    const form = document.getElementById("confirmForm");
    form.addEventListener("click", onClick);
    form.addEventListener("submit", onSubmit);
    dlg.addEventListener(
      "close",
      () => {
        form.removeEventListener("click", onClick);
        form.removeEventListener("submit", onSubmit);
        resolve(result);
      },
      { once: true },
    );
    dlg.showModal();
    (typeInput || (danger ? document.querySelector("#confirm [data-confirm='cancel']") : ok)).focus();
  });
}

// ── Menus (⋯ dropdowns) ──────────────────────────────────────────────────────

/**
 * Render a menu trigger plus its items. items: [{label, action, icon, danger, disabled}] or "divider".
 * Clicking an item dispatches through the global data-action handler.
 */
function menuHtml(items, { label = "More actions", data = "" } = {}) {
  const rows = items
    .filter(Boolean)
    .map((item) =>
      item === "divider"
        ? '<div class="menu-divider" role="separator"></div>'
        : `<button type="button" role="menuitem" class="menu-item${item.danger ? " danger" : ""}"
             data-action="${esc(item.action)}" ${data} ${item.disabled ? "disabled" : ""}>
             ${item.icon ? icon(item.icon) : ""}<span>${esc(item.label)}</span></button>`,
    )
    .join("");
  return `<div class="menu">
    <button type="button" class="icon-btn menu-trigger" aria-haspopup="menu" aria-expanded="false" aria-label="${esc(label)}" title="${esc(label)}">${icon("more")}</button>
    <div class="menu-list" role="menu" hidden>${rows}</div>
  </div>`;
}

function closeMenus(except = null) {
  document.querySelectorAll(".menu-list:not([hidden])").forEach((list) => {
    if (list === except) return;
    list.hidden = true;
    const trigger = list.parentElement.querySelector(".menu-trigger");
    if (trigger) trigger.setAttribute("aria-expanded", "false");
    list.closest(".card")?.classList.remove("menu-open");
  });
}

document.addEventListener("click", (e) => {
  const trigger = e.target.closest(".menu-trigger");
  if (trigger) {
    e.stopPropagation();
    const list = trigger.parentElement.querySelector(".menu-list");
    const willOpen = list.hidden;
    closeMenus(list);
    list.hidden = !willOpen;
    trigger.setAttribute("aria-expanded", String(willOpen));
    list.closest(".card")?.classList.toggle("menu-open", willOpen);
    if (willOpen) {
      // Flip upward if it would run off the bottom of the viewport.
      list.classList.remove("menu-up");
      const rect = list.getBoundingClientRect();
      if (rect.bottom > window.innerHeight - 8) list.classList.add("menu-up");
      list.querySelector(".menu-item:not([disabled])")?.focus();
    }
    return;
  }
  if (!e.target.closest(".menu-list")) closeMenus();
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeMenus();
});
