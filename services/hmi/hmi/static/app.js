// DVAP HMI front end. No build step: plain JS + Chart.js.
// Everything that comes from the PLC, the historian or the agent bus is untrusted text
// (see docs/VULNERABILITIES.md), so it is only ever written with textContent, never innerHTML.

const $ = (id) => document.getElementById(id);
// ?presenter=1: the layout for a projector (see the end of style.css).
if (new URLSearchParams(location.search).get("presenter") === "1") document.body.classList.add("presenter");
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const clock = (ms) => new Date(ms).toLocaleTimeString([], { hour12: false });
const fmt = (v, digits = 1) => (typeof v === "number" ? v.toFixed(digits) : "—");
const getJSON = async (url) => {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
};

const WINDOW_MS = 10 * 60 * 1000; // charts show the last 10 minutes
const TANK = { top: 130, bottom: 360 }; // SVG y of 100 % and 0 %
const OVERDOSE_PPM = 4.0;
const INCIDENT_TITLES = {
  OVERFLOW: "Tank overflow",
  CHLORINE_OVERDOSE: "Chlorine overdose",
  DRY_RUN: "Pump dry run",
};

// --- charts ------------------------------------------------------------------

function makeChart(canvasId, label, yScale, limit) {
  const grid = css("--line"), dim = css("--dim");
  const datasets = [
    { label, data: [], borderColor: css("--water"), backgroundColor: css("--water"), borderWidth: 2 },
    { label: "Setpoint", data: [], borderColor: css("--text"), backgroundColor: css("--text"), borderWidth: 1.5, borderDash: [6, 4], stepped: true },
  ];
  if (limit !== undefined) {
    datasets.push({ label: `Overdose limit ${limit.toFixed(1)}`, data: [], borderColor: css("--bad"), backgroundColor: css("--bad"), borderWidth: 1.5, borderDash: [2, 4] });
  }
  return new Chart($(canvasId), {
    type: "line",
    data: { datasets },
    options: {
      animation: false, parsing: false, responsive: true, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      elements: { point: { radius: 0, hoverRadius: 4 } },
      scales: {
        x: { type: "linear", ticks: { color: dim, maxTicksLimit: 6, callback: (v) => clock(v) }, grid: { color: grid } },
        y: { ...yScale, ticks: { color: dim }, grid: { color: grid } },
      },
      plugins: {
        legend: { labels: { color: css("--text"), boxWidth: 22, boxHeight: 0 } },
        tooltip: { callbacks: { title: (items) => clock(items[0].parsed.x) } },
      },
    },
  });
}

const charts = {
  level: makeChart("chart-level", "Tank level", { min: 0, max: 100 }),
  ppm: makeChart("chart-ppm", "Chlorine", { min: 0, suggestedMax: 5 }, OVERDOSE_PPM),
};

async function loadHistory(chart, valueTag, setpointTag) {
  const points = async (tag) => (await getJSON(`/api/series?tag=${tag}`)).points.map(([ts, y]) => ({ x: ts * 1000, y }));
  try {
    const [values, setpoints] = await Promise.all([points(valueTag), points(setpointTag)]);
    chart.data.datasets[0].data.unshift(...values);
    chart.data.datasets[1].data.unshift(...setpoints);
  } catch { /* historian not up yet: the chart just starts empty */ }
}

function pushPoint(chart, now, value, setpoint) {
  const [series, sp, limit] = chart.data.datasets;
  if (typeof value === "number") series.data.push({ x: now, y: value });
  if (typeof setpoint === "number") sp.data.push({ x: now, y: setpoint });
  for (const d of [series, sp]) while (d.data.length && d.data[0].x < now - WINDOW_MS) d.data.shift();
  if (limit) limit.data = [{ x: now - WINDOW_MS, y: OVERDOSE_PPM }, { x: now, y: OVERDOSE_PPM }];
  chart.options.scales.x.min = now - WINDOW_MS;
  chart.options.scales.x.max = now;
  chart.update();
}

// --- live process view --------------------------------------------------------

function setChip(el, text, cls) {
  el.textContent = text;
  el.className = `chip ${cls || ""}`;
}

function setEquip(id, labelId, running, tripped, label) {
  $(id).setAttribute("class", `equip ${tripped ? "trip" : running ? "run" : "stop"}`);
  $(labelId).textContent = tripped ? `TRIPPED · ${label}` : label;
}

let incidentSince = null;

function renderIncident(incidents) {
  const banner = $("incident");
  document.body.classList.toggle("incident", incidents.length > 0);
  banner.hidden = incidents.length === 0;
  if (!incidents.length) return (incidentSince = null);
  incidentSince = Math.min(...incidents.map((i) => i.ts)) * 1000;
  $("incident-type").textContent = incidents.map((i) => INCIDENT_TITLES[i.name] || i.name).join(" · ");
  $("incident-since").textContent = `SINCE ${clock(incidentSince)}`;
}

function render(d) {
  const p = d.plant, plc = d.plc, now = d.ts * 1000;
  setChip($("conn"), p && plc ? "LIVE" : p ? "PLC DATA STALE" : "PLANT OFFLINE", p && plc ? "ok" : "warn");
  renderIncident(d.incidents);

  if (plc) {
    setChip($("mode"), plc.auto_mode ? "MODE AUTO" : "MODE MANUAL", plc.auto_mode ? "ok" : "warn");
    for (const [name, il] of Object.entries(d.interlocks)) {
      const label = $(`il-${name}`).textContent.replace(/ (TRIPPED|OFF)$/, "");
      if (!il.enabled) setChip($(`il-${name}`), `${label} OFF`, "off");
      else setChip($(`il-${name}`), il.tripped ? `${label} TRIPPED` : label, il.tripped ? "bad" : "ok");
    }
    $("bypass").hidden = !d.status.maintenance_bypass;
    $("bypass").className = "chip warn";
    $("device-tag").textContent = plc.device_tag || "—";
    $("alarm-message").textContent = plc.alarm_message || "—";
    $("operator-note").textContent = plc.operator_note || "—";
    $("v-level-sp").textContent = `${fmt(plc.level_setpoint)} %`;
    $("v-ppm-sp").textContent = `${fmt(plc.chlorine_setpoint, 2)} ppm`;
    const spY = TANK.bottom - ((TANK.bottom - TANK.top) * Math.min(plc.level_setpoint, 100)) / 100;
    $("sp-marker").style.transform = `translateY(${spY - 245}px)`;
  }
  if (!p) return;

  // Tank: water height follows the level, water colour shifts towards chlorine-yellow as ppm rises.
  const height = ((TANK.bottom - TANK.top) * p.tank_level_pct) / 100;
  $("water").setAttribute("y", TANK.bottom - height);
  $("water").setAttribute("height", height);
  $("water-surface").style.transform = `translateY(${TANK.bottom - height - 245}px)`;
  const tint = Math.max(0, Math.min(100, ((p.chlorine_ppm - 2) / 3) * 100));
  $("water").style.fill = `color-mix(in oklab, var(--chlorine) ${tint}%, var(--water))`;

  const names = d.incidents.map((i) => i.name);
  $("tank").setAttribute("class", `vessel ${names.includes("OVERFLOW") ? "bad" : ""}`);
  $("spill").toggleAttribute("hidden", !(names.includes("OVERFLOW") && p.tank_level_pct >= 99.5));

  $("v-level").textContent = `${fmt(p.tank_level_pct)} %`;
  $("v-inflow").textContent = `${fmt(p.inflow_rate_lps)} L/s`;
  $("v-outflow").textContent = `${fmt(p.outflow_lps)} L/s`;
  $("v-ppm").textContent = `${fmt(p.chlorine_ppm, 2)} ppm`;
  $("tag-cl").setAttribute("class", `tag ${p.chlorine_ppm > OVERDOSE_PPM ? "bad" : p.chlorine_ppm < 0.2 ? "warn" : ""}`);

  const s = d.status;
  setEquip("pump", "s-pump", p.inflow_pump_on, s.trip_level_hh || p.pump_dry_run, p.pump_dry_run ? "DRY RUN" : p.inflow_pump_on ? "RUNNING" : "STOPPED");
  setEquip("valve", "s-valve", p.drain_valve_pct > 0, s.trip_dry_run, `${fmt(p.drain_valve_pct)} % OPEN`);
  setEquip("doser", "s-doser", p.chlorine_pump_rate > 0, s.trip_chlorine_hh, `RATE ${fmt(p.chlorine_pump_rate, 2)}`);
  $("pipe-inflow").classList.toggle("flowing", p.inflow_rate_lps > 0.05);
  $("pipe-drain").classList.toggle("flowing", p.outflow_lps > 0.05);
  $("pipe-dosing").classList.toggle("flowing", p.chlorine_pump_rate > 0.01);

  pushPoint(charts.level, now, p.tank_level_pct, plc?.level_setpoint);
  pushPoint(charts.ppm, now, p.chlorine_ppm, plc?.chlorine_setpoint);
}

// --- alarms -------------------------------------------------------------------

function cell(row, text, badgeClass) {
  const td = row.insertCell();
  if (badgeClass === undefined) return (td.textContent = text);
  const badge = td.appendChild(document.createElement("span"));
  badge.className = `badge ${/^[a-z_]+$/.test(badgeClass) ? badgeClass : ""}`;
  badge.textContent = text;
}

function renderAlarms(events) {
  if (!events.length) return;
  const body = $("alarms").tBodies[0];
  body.replaceChildren();
  for (const e of events) {
    const row = body.insertRow();
    cell(row, clock(e.ts * 1000));
    cell(row, e.kind, e.kind);
    cell(row, e.name);
    cell(row, e.message);
  }
}

// --- agent activity (Server-Sent Events) --------------------------------------

function addAgentEvent(raw) {
  let e;
  try { e = JSON.parse(raw); } catch { e = null; }
  if (!e || typeof e !== "object") e = { type: "raw", summary: String(raw) };

  const log = $("agent-log");
  log.querySelector(".empty")?.remove();
  const li = document.createElement("li");
  const meta = li.appendChild(document.createElement("div"));
  meta.className = "meta";
  meta.appendChild(document.createElement("span")).textContent = clock(typeof e.ts === "number" ? e.ts * 1000 : Date.now());
  const type = String(e.type || "event");
  const badge = meta.appendChild(document.createElement("span"));
  badge.className = `badge ${/^[a-z_]+$/.test(type) ? type : ""}`;
  badge.textContent = type.replace(/_/g, " ");
  if (e.tool) {
    const tool = meta.appendChild(document.createElement("span"));
    tool.className = "tool";
    tool.textContent = String(e.tool);
  }
  const summary = e.summary ?? e.text ?? e.message;
  if (summary) {
    const div = li.appendChild(document.createElement("div"));
    div.className = "summary";
    div.textContent = String(summary).slice(0, 2000);
  }
  if (e.args !== undefined) {
    const div = li.appendChild(document.createElement("div"));
    div.className = "args";
    div.textContent = JSON.stringify(e.args).slice(0, 400);
  }
  log.prepend(li);
  while (log.children.length > 200) log.lastChild.remove();
}

function connectAgentStream() {
  const stream = new EventSource("/api/agent/stream"); // reconnects by itself
  stream.onopen = () => setChip($("agent-conn"), "LISTENING", "ok");
  stream.onerror = () => setChip($("agent-conn"), "OFFLINE", "warn");
  stream.onmessage = (m) => addAgentEvent(m.data);
}

// --- SafeEnvelope guard decisions ---------------------------------------------

const GUARD_CHIP = { allow: "ok", deny: "bad", review: "warn" };

function addGuardEvent(raw) {
  let e;
  try { e = JSON.parse(raw); } catch { return; }
  if (!e || typeof e !== "object" || e.type !== "guard") return;

  const log = $("guard-log");
  log.querySelector(".empty")?.remove();
  const li = document.createElement("li");
  li.className = `guard-${/^[a-z]+$/.test(e.action) ? e.action : "event"}`;

  const meta = li.appendChild(document.createElement("div"));
  meta.className = "meta";
  meta.appendChild(document.createElement("span")).textContent = clock(typeof e.ts === "number" ? e.ts * 1000 : Date.now());
  const badge = meta.appendChild(document.createElement("span"));
  badge.className = `badge ${GUARD_CHIP[e.action] || ""}`;
  badge.textContent = String(e.action || "event").toUpperCase();
  if (e.tool) {
    const tool = meta.appendChild(document.createElement("span"));
    tool.className = "tool";
    tool.textContent = String(e.tool);
  }
  if (e.anomaly) {
    const flag = meta.appendChild(document.createElement("span"));
    flag.className = "badge bad";
    flag.textContent = "ANOMALY";
  }
  for (const text of [e.reason, e.forecast].filter(Boolean)) {
    const div = li.appendChild(document.createElement("div"));
    div.className = "summary";
    div.textContent = String(text).slice(0, 2000);
  }
  if (e.provenance?.length) {
    const div = li.appendChild(document.createElement("div"));
    div.className = "args";
    div.textContent = `influenced by: ${e.provenance.join(", ")}`.slice(0, 400);
  }
  log.prepend(li);
  while (log.children.length > 200) log.lastChild.remove();
}

function connectGuardStream() {
  const stream = new EventSource("/api/guard/stream");
  stream.onopen = () => setChip($("guard-conn"), "LISTENING", "ok");
  stream.onerror = () => setChip($("guard-conn"), "OFFLINE", "warn");
  stream.onmessage = (m) => addGuardEvent(m.data);
}

// --- main loop ----------------------------------------------------------------

async function pollLive() {
  try { render(await getJSON("/api/live")); }
  catch { setChip($("conn"), "HMI OFFLINE", "bad"); }
}

async function pollAlarms() {
  try { renderAlarms((await getJSON("/api/events?limit=50")).events); } catch { /* shown by the conn chip */ }
}

function tickClock() {
  $("clock").textContent = clock(Date.now());
  if (incidentSince) {
    const s = Math.max(0, Math.floor((Date.now() - incidentSince) / 1000));
    $("incident-elapsed").textContent = `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")} elapsed`;
  }
}

(async () => {
  await Promise.all([
    loadHistory(charts.level, "tank_level_pct", "level_setpoint"),
    loadHistory(charts.ppm, "chlorine_ppm", "chlorine_setpoint"),
  ]);
  pollLive();
  pollAlarms();
  tickClock();
  setInterval(pollLive, 1000);
  setInterval(pollAlarms, 2000);
  setInterval(tickClock, 1000);
  connectAgentStream();
  connectGuardStream();
})();
