// Schedule editing and plain-English schedule descriptions.
//
// Schedules are stored as cron expressions or intervals. The editor offers
// three friendly modes and always writes weekdays as names ("mon,wed,fri"),
// which mean the same thing in every cron dialect. (Numbers don't: Mantyx's
// scheduler counts 0 = Monday, while classic cron counts 0 = Sunday.)
"use strict";

const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const DAY_SHORT = { mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun" };
const DAY_LONG = {
  mon: "Monday",
  tue: "Tuesday",
  wed: "Wednesday",
  thu: "Thursday",
  fri: "Friday",
  sat: "Saturday",
  sun: "Sunday",
};

/** Parse a cron day-of-week field into a Set of day names, or null if it's too fancy. */
function parseDayField(field) {
  if (field === "*" || field === "?") return new Set(DAYS);
  const toIndex = (token) => {
    const t = token.toLowerCase();
    if (DAYS.includes(t)) return DAYS.indexOf(t);
    if (/^[0-6]$/.test(t)) return Number(t); // scheduler numbering: 0 = Monday
    return null;
  };
  const result = new Set();
  for (const part of field.split(",")) {
    const range = part.split("-");
    if (range.length === 1) {
      const i = toIndex(range[0]);
      if (i === null) return null;
      result.add(DAYS[i]);
    } else if (range.length === 2) {
      const a = toIndex(range[0]);
      const b = toIndex(range[1]);
      if (a === null || b === null || b < a) return null;
      for (let i = a; i <= b; i += 1) result.add(DAYS[i]);
    } else {
      return null;
    }
  }
  return result.size ? result : null;
}

function dayFieldFor(days) {
  const list = DAYS.filter((d) => days.has(d));
  if (list.length === 7) return "*";
  if (list.join(",") === "mon,tue,wed,thu,fri") return "mon-fri";
  return list.join(",");
}

function pad2(n) {
  return String(n).padStart(2, "0");
}

/** Turn a stored schedule into the editor's model. */
function parseSchedule(spec) {
  const model = {
    mode: "time",
    time: "07:00",
    days: new Set(DAYS),
    intervalValue: 15,
    intervalUnit: "minutes",
    cron: "",
  };
  if (!spec || !spec.schedule_type) return model;

  if (spec.schedule_type === "interval") {
    const s = spec.interval_seconds || 900;
    model.mode = "interval";
    if (s % 86400 === 0) [model.intervalValue, model.intervalUnit] = [s / 86400, "days"];
    else if (s % 3600 === 0) [model.intervalValue, model.intervalUnit] = [s / 3600, "hours"];
    else if (s % 60 === 0) [model.intervalValue, model.intervalUnit] = [s / 60, "minutes"];
    else [model.intervalValue, model.intervalUnit] = [s, "seconds"];
    return model;
  }

  const expr = (spec.cron_expression || "").trim();
  model.cron = expr;
  const parts = expr.split(/\s+/);
  if (
    parts.length === 5 &&
    /^\d{1,2}$/.test(parts[0]) &&
    /^\d{1,2}$/.test(parts[1]) &&
    parts[2] === "*" &&
    parts[3] === "*"
  ) {
    const days = parseDayField(parts[4]);
    if (days && Number(parts[0]) < 60 && Number(parts[1]) < 24) {
      model.mode = "time";
      model.time = `${pad2(parts[1])}:${pad2(parts[0])}`;
      model.days = days;
      return model;
    }
  }
  model.mode = "custom";
  return model;
}

/** Turn the editor's model into what the API stores. Throws Error with a readable message. */
function buildSchedule(model) {
  if (model.mode === "interval") {
    const value = Number(model.intervalValue);
    if (!Number.isFinite(value) || value < 1) throw new Error("Enter how often it should run");
    const mult = { seconds: 1, minutes: 60, hours: 3600, days: 86400 }[model.intervalUnit] || 60;
    return { schedule_type: "interval", interval_seconds: Math.round(value * mult), cron_expression: null };
  }
  if (model.mode === "custom") {
    const cron = (model.cron || "").trim().replace(/\s+/g, " ");
    if (!cron) throw new Error("Enter a cron expression");
    return { schedule_type: "cron", cron_expression: cron, interval_seconds: null };
  }
  if (!model.days.size) throw new Error("Pick at least one day");
  const [h, m] = (model.time || "07:00").split(":").map(Number);
  return {
    schedule_type: "cron",
    cron_expression: `${m} ${h} * * ${dayFieldFor(model.days)}`,
    interval_seconds: null,
  };
}

function describeDays(days) {
  const list = DAYS.filter((d) => days.has(d));
  if (list.length === 7) return "Every day";
  if (list.join(",") === "mon,tue,wed,thu,fri") return "Weekdays";
  if (list.join(",") === "sat,sun") return "Weekends";
  if (list.length === 1) return `Every ${DAY_LONG[list[0]]}`;
  const names = list.map((d) => DAY_SHORT[d]);
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

function describeInterval(seconds) {
  const units = [
    [86400, "day"],
    [3600, "hour"],
    [60, "minute"],
    [1, "second"],
  ];
  for (const [size, name] of units) {
    if (seconds % size === 0) {
      const n = seconds / size;
      return n === 1 ? `Every ${name}` : `Every ${n} ${name}s`;
    }
  }
  return `Every ${seconds} seconds`;
}

/** Plain-English description of a stored schedule. */
function describeSchedule(spec) {
  if (!spec) return "";
  if (spec.schedule_type === "interval") return describeInterval(spec.interval_seconds || 0);
  const model = parseSchedule(spec);
  if (model.mode === "time") return `${describeDays(model.days)} at ${model.time}`;
  return `Custom: ${spec.cron_expression}`;
}

/** Format a time in the scheduler's timezone (what the schedule is defined in). */
function fmtInZone(value, tz, withDate = true) {
  const d = toDate(value);
  if (!d) return "";
  const opts = { hour: "2-digit", minute: "2-digit", timeZone: tz || undefined };
  if (withDate) Object.assign(opts, { weekday: "short", month: "short", day: "numeric" });
  try {
    return d.toLocaleString(undefined, opts);
  } catch {
    delete opts.timeZone;
    return d.toLocaleString(undefined, opts);
  }
}

// ── Editor component ─────────────────────────────────────────────────────────

function scheduleEditorHtml(model, { idPrefix = "sched" } = {}) {
  const p = idPrefix;
  const chip = (d) =>
    `<label class="day-chip"><input type="checkbox" name="${p}-day" value="${d}" ${model.days.has(d) ? "checked" : ""}/><span>${DAY_SHORT[d]}</span></label>`;
  const unitOpt = (u, label) =>
    `<option value="${u}" ${model.intervalUnit === u ? "selected" : ""}>${label}</option>`;
  const modeBtn = (mode, label) =>
    `<button type="button" class="seg-btn${model.mode === mode ? " active" : ""}" data-sched-mode="${mode}" aria-pressed="${model.mode === mode}">${label}</button>`;

  return `
  <div class="schedule-editor" data-prefix="${p}">
    <div class="segmented" role="group" aria-label="Schedule type">
      ${modeBtn("time", "At a time of day")}
      ${modeBtn("interval", "Repeatedly")}
      ${modeBtn("custom", "Custom (cron)")}
    </div>

    <div class="sched-pane" data-pane="time" ${model.mode === "time" ? "" : "hidden"}>
      <div class="field-row">
        <label class="field field-time">
          <span class="field-label">Time</span>
          <input type="time" class="input" name="${p}-time" value="${esc(model.time)}" required />
        </label>
        <div class="field">
          <span class="field-label">Days</span>
          <div class="day-chips">${DAYS.map(chip).join("")}</div>
          <div class="quick-days">
            <button type="button" class="link-btn" data-days="all">Every day</button>
            <button type="button" class="link-btn" data-days="weekdays">Weekdays</button>
            <button type="button" class="link-btn" data-days="weekends">Weekends</button>
          </div>
        </div>
      </div>
    </div>

    <div class="sched-pane" data-pane="interval" ${model.mode === "interval" ? "" : "hidden"}>
      <div class="field-row">
        <label class="field field-narrow">
          <span class="field-label">Every</span>
          <input type="number" class="input" min="1" step="1" name="${p}-ivalue" value="${esc(model.intervalValue)}" />
        </label>
        <label class="field field-narrow">
          <span class="field-label">&nbsp;</span>
          <select class="input" name="${p}-iunit">
            ${unitOpt("minutes", "minutes")}${unitOpt("hours", "hours")}${unitOpt("days", "days")}${unitOpt("seconds", "seconds")}
          </select>
        </label>
      </div>
      <p class="hint">Counts from when Mantyx starts, so after a restart the next run is one full interval later.</p>
    </div>

    <div class="sched-pane" data-pane="custom" ${model.mode === "custom" ? "" : "hidden"}>
      <label class="field">
        <span class="field-label">Cron expression</span>
        <input type="text" class="input mono" name="${p}-cron" value="${esc(model.cron)}" placeholder="0 */6 * * *" spellcheck="false" autocomplete="off" />
      </label>
      <p class="hint">Five fields: <code>minute hour day-of-month month day-of-week</code>.
        Use day names for the last field, e.g. <code>30 8 * * mon-fri</code> or <code>0 9 1 * *</code> (9:00 on the 1st of each month).</p>
    </div>

    <div class="sched-preview" aria-live="polite">
      <div class="sched-summary"></div>
      <div class="sched-next"></div>
    </div>
  </div>`;
}

/**
 * Wire up an editor rendered by scheduleEditorHtml inside `root`.
 * Returns { getModel(), getSpec() } where getSpec throws on invalid input.
 */
function bindScheduleEditor(root, model, { onChange } = {}) {
  const editor = root.querySelector(".schedule-editor");
  const p = editor.dataset.prefix;
  const q = (name) => editor.querySelector(`[name="${p}-${name}"]`);
  const summaryEl = editor.querySelector(".sched-summary");
  const nextEl = editor.querySelector(".sched-next");
  let previewSeq = 0;

  const read = () => {
    model.time = q("time").value || "07:00";
    model.days = new Set([...editor.querySelectorAll(`[name="${p}-day"]:checked`)].map((c) => c.value));
    model.intervalValue = q("ivalue").value;
    model.intervalUnit = q("iunit").value;
    model.cron = q("cron").value;
  };

  const preview = debounce(async (spec, seq) => {
    try {
      const res = await api("/schedules/preview", { method: "POST", json: { ...spec, count: 3 } });
      if (seq !== previewSeq) return;
      const times = res.next_runs.map((t) => fmtInZone(t, res.timezone)).join(" · ");
      nextEl.innerHTML = times
        ? `<span class="muted">Next runs:</span> ${esc(times)} <span class="muted">(${esc(res.timezone)})</span>`
        : `<span class="muted">This schedule never runs.</span>`;
      nextEl.classList.remove("error");
    } catch (err) {
      if (seq !== previewSeq) return;
      nextEl.textContent = err.message;
      nextEl.classList.add("error");
    }
  }, 300);

  const refresh = () => {
    read();
    let spec;
    try {
      spec = buildSchedule(model);
    } catch (err) {
      summaryEl.textContent = "";
      nextEl.textContent = err.message;
      nextEl.classList.add("error");
      onChange && onChange(null);
      return;
    }
    summaryEl.innerHTML = `${icon("calendar")}<strong>${esc(describeSchedule(spec))}</strong>`;
    nextEl.classList.remove("error");
    previewSeq += 1;
    preview(spec, previewSeq);
    onChange && onChange(spec);
  };

  editor.addEventListener("click", (e) => {
    const modeBtn = e.target.closest("[data-sched-mode]");
    if (modeBtn) {
      model.mode = modeBtn.dataset.schedMode;
      editor.querySelectorAll("[data-sched-mode]").forEach((b) => {
        const on = b === modeBtn;
        b.classList.toggle("active", on);
        b.setAttribute("aria-pressed", String(on));
      });
      editor.querySelectorAll(".sched-pane").forEach((pane) => {
        pane.hidden = pane.dataset.pane !== model.mode;
      });
      if (model.mode === "custom" && !q("cron").value) {
        // Seed the custom field with the equivalent of what was set up so far.
        read();
        try {
          q("cron").value = buildSchedule({ ...model, mode: "time" }).cron_expression;
        } catch {
          /* no days picked yet; leave it empty */
        }
      }
      refresh();
      return;
    }
    const quick = e.target.closest("[data-days]");
    if (quick) {
      const sets = {
        all: DAYS,
        weekdays: ["mon", "tue", "wed", "thu", "fri"],
        weekends: ["sat", "sun"],
      };
      const chosen = new Set(sets[quick.dataset.days]);
      editor.querySelectorAll(`[name="${p}-day"]`).forEach((c) => {
        c.checked = chosen.has(c.value);
      });
      refresh();
    }
  });
  editor.addEventListener("input", refresh);
  editor.addEventListener("change", refresh);
  refresh();

  return {
    getModel: () => (read(), model),
    getSpec: () => (read(), buildSchedule(model)),
  };
}
