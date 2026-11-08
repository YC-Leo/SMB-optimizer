/* SMB Optimizer Suite — front end (vanilla JS, no external libraries). */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const clone = o => JSON.parse(JSON.stringify(o));
const ZONES = ["I", "II", "III", "IV", "V", "VI"];
const METRICS = ["extract_purity", "extract_recovery", "raffinate_purity", "raffinate_recovery"];
const KIND_LABEL = { desorbent: "Desorbent in", feed: "Feed in", extract: "Extract out", raffinate: "Raffinate out" };

const S = {
  defaults: null, problems: {}, objectives: {}, metricLabel: {}, workers: 1,
  prob: null, info: null, errors: [], validateTimer: null,
  job: null, runs: [], selected: null, scan: null, live: null,
  hidden: {}, pointTab: "window", progTab: "objective", profWhich: "optimum", splitWhich: "optimum",
};

/* ----------------------------------------------------------------- utils */
function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
function palette() { return [1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(i => css(`--c${i}`)); }
function compColor(i) { const p = palette(); return p[i % p.length]; }
function fmt(v, d) {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  if (d !== undefined) return Number(v).toFixed(d);
  const a = Math.abs(v);
  if (a === 0) return "0";
  if (a >= 1000) return v.toFixed(0);
  if (a >= 100) return v.toFixed(1);
  if (a >= 0.01) return v.toPrecision(3);
  return v.toExponential(2);
}
function f3(v) { return v === null || v === undefined ? "–" : Number(v).toFixed(Math.abs(v) >= 10 ? 2 : 3); }
function pct(v) { return v === null || v === undefined || Number.isNaN(v) ? "–" : Number(v).toFixed(2); }
function fmtTime(s) { return s < 60 ? `${s.toFixed(0)} s` : `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`; }
async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await r.json().catch(() => ({}));
  return { ok: r.ok, status: r.status, data };
}
function download(name, text, type) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
function setSeg(seg, v) { $$("button", seg).forEach(b => { const on = b.dataset.v === v; b.classList.toggle("on", on); b.setAttribute("aria-checked", on); }); }
function setTabs(tabs, v) { $$("button", tabs).forEach(b => b.classList.toggle("on", b.dataset.v === v)); }
function portColor(cfg, kind) {
  if (kind === "feed") return css("--ink-2");
  const role = kind === "desorbent" ? "desorbent" : kind;
  const i = cfg.components.findIndex(c => c.role === role);
  return i >= 0 ? compColor(i) : css("--ink-2");
}
function portLabels(cfg) {
  const L = { desorbent: "D", feed: "F", extract: "E", raffinate: "R" }, cnt = {}, seen = {};
  cfg.ports.forEach(p => cnt[p.kind] = (cnt[p.kind] || 0) + 1);
  return cfg.ports.map(p => { seen[p.kind] = (seen[p.kind] || 0) + 1; return L[p.kind] + (cnt[p.kind] > 1 ? seen[p.kind] : ""); });
}
function objMetric(o) { return o.startsWith("max_") && METRICS.includes(o.slice(4)) ? o.slice(4) : null; }
function objUnit(o) { return o === "max_feed" ? "mL/min" : o === "min_desorbent" ? "" : "%"; }
function objShort(o) { return { max_feed: "Feed throughput", min_desorbent: "Desorbent / feed" }[o] || S.metricLabel[objMetric(o)]; }

/* --------------------------------------------------------------- tooltip */
const tip = {
  el: null,
  show(html, x, y) {
    const t = this.el; t.innerHTML = html; t.hidden = false;
    const w = t.offsetWidth, h = t.offsetHeight;
    let left = x + 14, top = y + 14;
    if (left + w > innerWidth - 8) left = x - w - 14;
    if (top + h > innerHeight - 8) top = y - h - 14;
    t.style.left = left + "px"; t.style.top = top + "px";
  },
  hide() { this.el.hidden = true; },
};

/* ------------------------------------------------------------ SVG charts */
function niceTicks(min, max, count = 5) {
  if (!(max > min)) { max = min + 1; }
  const span = max - min, step0 = span / count, mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const err = step0 / mag, step = (err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1) * mag;
  const out = [];
  for (let v = Math.ceil(min / step - 1e-9) * step; v <= max + step * 1e-9; v += step) out.push(+v.toPrecision(12));
  return out;
}
function bsearch(xs, x) {
  let lo = 0, hi = xs.length - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (xs[m] < x) lo = m; else hi = m; }
  return Math.abs(xs[lo] - x) <= Math.abs(xs[hi] - x) ? lo : hi;
}
function legend(el, series, key, onChange) {
  if (!el) return;
  const hid = S.hidden[key] || (S.hidden[key] = new Set());
  el.innerHTML = "";
  for (const s of series) {
    const b = document.createElement("button");
    b.className = hid.has(s.name) ? "off" : "";
    b.innerHTML = `<i class="${s.dash ? "dash" : ""}" style="background:${s.color};color:${s.color}"></i><span>${esc(s.name)}</span>`;
    b.title = "Show / hide";
    b.onclick = () => { hid.has(s.name) ? hid.delete(s.name) : hid.add(s.name); onChange(); };
    el.appendChild(b);
  }
}
function lineChart(el, o) {
  const W = el.clientWidth || 600, H = el.clientHeight || 240;
  const m = { l: 58, r: 14, t: o.top || 12, b: 36 };
  const iw = Math.max(10, W - m.l - m.r), ih = Math.max(10, H - m.t - m.b);
  const hid = S.hidden[o.key] || new Set();
  const vis = o.series.filter(s => !hid.has(s.name) && s.x.length);
  let svg = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">`;
  if (!vis.length) {
    el.innerHTML = svg + `<text class="empty-msg" x="${W / 2}" y="${H / 2}" text-anchor="middle">${esc(o.empty || "No data yet")}</text></svg>`;
    el.onmousemove = el.onmouseleave = null; return;
  }
  let xmin = Infinity, xmax = -Infinity, ymin = Infinity, ymax = -Infinity;
  for (const s of vis) for (let i = 0; i < s.x.length; i++) {
    const x = s.x[i], y = s.y[i];
    if (y === null || !isFinite(y)) continue;
    if (x < xmin) xmin = x; if (x > xmax) xmax = x;
    if (y < ymin) ymin = y; if (y > ymax) ymax = y;
  }
  for (const h of o.hlines || []) { ymin = Math.min(ymin, h.y); ymax = Math.max(ymax, h.y); }
  if (o.xDomain) [xmin, xmax] = o.xDomain;
  if (xmax <= xmin) xmax = xmin + 1;
  if (o.yDomain) [ymin, ymax] = o.yDomain;
  else { if (o.yZero !== false) ymin = Math.min(0, ymin); const pad = (ymax - ymin) * 0.08 || Math.abs(ymax) * 0.05 || 1; ymax += pad; if (o.yZero === false) ymin -= pad; }
  if (ymax <= ymin) ymax = ymin + 1;
  const yT = niceTicks(ymin, ymax, Math.max(3, Math.round(ih / 50)));
  ymin = Math.min(ymin, yT[0]); ymax = Math.max(ymax, yT[yT.length - 1]);
  const sy = y => m.t + ih - (y - ymin) / (ymax - ymin) * ih;
  const sx = x => m.l + (x - xmin) / (xmax - xmin) * iw;
  const xT = o.xTicks || niceTicks(xmin, xmax, Math.max(3, Math.round(iw / 90)));
  for (const [i, b] of (o.bands || []).entries()) {
    const x0 = sx(Math.max(b.x0, xmin)), x1 = sx(Math.min(b.x1, xmax));
    svg += `<rect x="${x0}" y="${m.t}" width="${Math.max(0, x1 - x0)}" height="${ih}" fill="${b.fill || (i % 2 ? "var(--zone-b)" : "var(--zone-a)")}"/>`;
    if (b.label) svg += `<text class="zone-label" x="${(x0 + x1) / 2}" y="${m.t - 6}" text-anchor="middle">${esc(b.label)}</text>`;
  }
  svg += `<g class="grid">`;
  for (const t of yT) svg += `<line x1="${m.l}" x2="${m.l + iw}" y1="${sy(t)}" y2="${sy(t)}"/>`;
  for (const g of o.colLines || []) if (g > xmin && g < xmax) svg += `<line x1="${sx(g)}" x2="${sx(g)}" y1="${m.t}" y2="${m.t + ih}" stroke-dasharray="2 3"/>`;
  svg += `</g><g class="axis">`;
  for (const t of yT) svg += `<text x="${m.l - 8}" y="${sy(t) + 4}" text-anchor="end">${(o.fmtY || fmt)(t)}</text>`;
  for (const t of xT) if (t >= xmin - 1e-9 && t <= xmax + 1e-9) svg += `<text x="${sx(t)}" y="${m.t + ih + 16}" text-anchor="middle">${(o.fmtX || fmt)(t)}</text>`;
  svg += `<line x1="${m.l}" x2="${m.l + iw}" y1="${m.t + ih}" y2="${m.t + ih}"/></g>`;
  if (o.xTitle) svg += `<text class="axis-title" x="${m.l + iw / 2}" y="${H - 3}" text-anchor="middle">${esc(o.xTitle)}</text>`;
  if (o.yTitle) svg += `<text class="axis-title" transform="translate(12 ${m.t + ih / 2}) rotate(-90)" text-anchor="middle">${esc(o.yTitle)}</text>`;
  for (const h of o.hlines || []) svg += `<line x1="${m.l}" x2="${m.l + iw}" y1="${sy(h.y)}" y2="${sy(h.y)}" stroke="${h.color || "var(--ink-3)"}" stroke-dasharray="5 4"/><text class="axis-title" x="${m.l + iw - 4}" y="${sy(h.y) - 5}" text-anchor="end" style="fill:${h.color || "var(--ink-3)"}">${esc(h.label)}</text>`;
  for (const s of vis) {
    let d = "", pen = false;
    for (let i = 0; i < s.x.length; i++) {
      const y = s.y[i];
      if (y === null || !isFinite(y)) { pen = false; continue; }
      d += (pen ? "L" : "M") + sx(s.x[i]).toFixed(1) + " " + sy(y).toFixed(1); pen = true;
    }
    svg += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="${s.width || 2}" stroke-linejoin="round" stroke-linecap="round" ${s.dash ? `stroke-dasharray="${s.dash}"` : ""}/>`;
    if (s.dots) for (let i = 0; i < s.x.length; i++) if (s.y[i] !== null && isFinite(s.y[i])) {
      const hollow = s.hollow && s.hollow[i];
      svg += `<circle cx="${sx(s.x[i])}" cy="${sy(s.y[i])}" r="${hollow ? 3.4 : 3}" fill="${hollow ? "var(--surface)" : s.color}" stroke="${s.color}" stroke-width="1.6"/>`;
    }
  }
  for (const v of o.vlines || []) {
    if (v.x < xmin - 1e-9 || v.x > xmax + 1e-9) continue;
    const X = sx(v.x);
    svg += `<line x1="${X}" x2="${X}" y1="${m.t}" y2="${m.t + ih}" stroke="${v.color || "var(--ink-2)"}" stroke-width="${v.width || 1.2}" ${v.dash ? `stroke-dasharray="${v.dash}"` : ""}/>`;
    if (v.label) svg += `<g><rect x="${X - 9}" y="${m.t + 3}" width="18" height="16" rx="4" fill="${v.badge || "var(--ink-2)"}"/><text x="${X}" y="${m.t + 15}" text-anchor="middle" fill="#fff" font-size="10.5" font-weight="700">${esc(v.label)}</text></g>`;
  }
  svg += `<line class="crosshair" id="ch" x1="0" x2="0" y1="${m.t}" y2="${m.t + ih}" visibility="hidden"/>`;
  el.innerHTML = svg + "</svg>";
  const ch = el.querySelector("#ch");
  el.onmousemove = ev => {
    const r = el.getBoundingClientRect(), px = (ev.clientX - r.left) * (W / r.width);
    if (px < m.l || px > m.l + iw) { ch.setAttribute("visibility", "hidden"); tip.hide(); return; }
    const xv = xmin + (px - m.l) / iw * (xmax - xmin);
    const ref = vis[0], j = bsearch(ref.x, xv), xs = ref.x[j];
    ch.setAttribute("x1", sx(xs)); ch.setAttribute("x2", sx(xs)); ch.setAttribute("visibility", "visible");
    let html = `<div class="tt-head">${esc(o.tipX ? o.tipX(xs, j) : fmt(xs))}</div>`;
    for (const s of vis) {
      const k = bsearch(s.x, xs);
      html += `<div class="tt-row"><span><i style="background:${s.color}"></i>${esc(s.name)}</span><b>${(o.tipY || fmt)(s.y[k], s)}</b></div>`;
    }
    tip.show(html, ev.clientX, ev.clientY);
  };
  el.onmouseleave = () => { ch.setAttribute("visibility", "hidden"); tip.hide(); };
}

/* =========================================================== SETUP PANEL */
function cfg() { return S.prob.process; }
function renderSetup() {
  const p = S.prob, c = cfg();
  setSeg($("#schemeSeg"), c.scheme); setSeg($("#flowSeg"), c.flow_model);
  renderProcess(); renderVars();
  const os = $("#objSel");
  os.innerHTML = Object.entries(S.objectives).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
  os.value = p.objective;
  renderObjHint();
  renderSpecs();
  $("#maxFlow").value = p.max_zone_flow ?? ""; $("#minFlow").value = p.min_zone_flow;
  $("#ratioOn").checked = p.max_desorbent_ratio !== null && p.max_desorbent_ratio !== undefined;
  $("#ratioMax").value = p.max_desorbent_ratio ?? 5; $("#ratioRow").hidden = !$("#ratioOn").checked;
  $("#maxIter").value = p.max_iterations; $("#cssTol").value = p.css_tol; $("#fdStep").value = +(p.fd_step * 100).toPrecision(6);
  const ws = $("#workers");
  ws.innerHTML = `<option value="0">Automatic (${S.workers})</option>` + Array.from({ length: Math.max(8, S.workers) }, (_, i) => `<option value="${i + 1}">${i + 1}</option>`).join("");
  ws.value = String(p.workers || 0);
  updateChips();
}
function renderProcess() {
  const c = cfg(), labels = portLabels(c);
  const n = c.zones.reduce((a, b) => a + b, 0);
  const comps = c.components.map((x, i) => `<span class="pc"><i style="background:${compColor(i)}"></i>${esc(x.name)} <em>${x.role === "desorbent" ? "desorbent" : "→ " + x.role}</em></span>`).join("");
  let strip = "";
  c.zones.forEach((k, z) => {
    c.ports.forEach((p, i) => { if (p.zone === z) strip += `<span class="ls-port" style="background:${portColor(c, p.kind)}">${labels[i]}</span><span class="ls-arrow">›</span>`; });
    strip += `<span class="ls-zone">${ZONES[z]} · ${k}</span><span class="ls-arrow">›</span>`;
  });
  strip += c.open_loop ? `<span class="ls-zone">out</span>` : `<span class="ls-arrow">↺</span>`;
  const area = Math.PI * c.radius ** 2;
  const eps = c.porosity_spec === "split" ? c.bed_porosity + (1 - c.bed_porosity) * c.particle_porosity : c.porosity_total;
  $("#procSummary").innerHTML = `<div class="proc-comps">${comps}</div>
    <div class="layout-strip">${strip}</div>
    <div class="derived-inline"><span>${n} columns</span><span>L <b>${fmt(c.length)} cm</b></span><span>r <b>${fmt(c.radius)} cm</b></span>
    <span>V <b>${fmt(area * c.length)} mL</b></span><span>ε<sub>t</sub> <b>${fmt(eps)}</b></span><span>${c.open_loop ? "open loop" : "closed loop"}</span></div>`;
}
function renderVars() {
  const p = S.prob, c = cfg(), info = S.info;
  let h = `<thead><tr><th></th><th>Variable</th><th>Lower</th><th>Start</th><th>Upper</th></tr></thead><tbody>`;
  p.variables.forEach((v, i) => {
    h += `<tr class="${v.optimize ? "" : "off"}"><td><input type="checkbox" data-i="${i}" data-f="optimize" ${v.optimize ? "checked" : ""} aria-label="Optimize ${esc(v.label)}"></td>
      <td class="vname">${esc(v.label)}<small>${esc(v.unit)}</small></td>
      <td><input type="number" step="any" data-i="${i}" data-f="lower" value="${v.lower}"></td>
      <td><input type="number" step="any" data-i="${i}" data-f="start" value="${v.start}"></td>
      <td><input type="number" step="any" data-i="${i}" data-f="upper" value="${v.upper}"></td></tr>`;
  });
  const labels = portLabels(c);
  c.ports.forEach((pt, i) => {
    if (pt.balance && !["desorbent", "feed"].includes(pt.kind)) {
      const qb = info ? info.flows.balance_flow : null;
      h += `<tr class="balance"><td></td><td class="vname">${labels[i]} · ${KIND_LABEL[pt.kind]} (zone ${ZONES[pt.zone]})<small>balance</small></td><td colspan="3" class="computed">${qb === null ? "–" : f3(qb) + " mL/min, from the liquid balance"}</td></tr>`;
    }
  });
  $("#varTable").innerHTML = h + "</tbody>";
  renderStartDerived();
}
function renderStartDerived() {
  const info = S.info, el = $("#startDerived");
  if (!info) { el.innerHTML = ""; return; }
  const d = info.derived, z = d.zone_flows.map((_, i) => `<th>${ZONES[i]}</th>`).join("");
  el.innerHTML = `<table><thead><tr><th>At the start point</th>${z}</tr></thead><tbody>
    <tr><td>Flow, mL/min</td>${d.zone_flows.map(q => `<td>${f3(q)}</td>`).join("")}</tr>
    <tr><td>m-value</td>${d.m_values.map(q => `<td>${f3(q)}</td>`).join("")}</tr></tbody></table>
    <div class="kv"><span>Feed · desorbent / feed</span><b>${f3(info.flows.feed)} mL/min · ${fmt(info.flows.desorbent_ratio)}</b></div>`;
}
function renderObjHint() {
  const o = S.prob.objective;
  const H = {
    max_feed: "Process as much feed as possible while every specification below is met. This is the usual design goal: it sets the productivity of the unit.",
    min_desorbent: "Use as little desorbent per volume of feed as possible. Desorbent has to be recovered by evaporation or distillation, so it often sets the operating cost.",
  };
  $("#objHint").textContent = H[o] || `Push ${S.metricLabel[objMetric(o)].toLowerCase()} as high as possible while the other specifications below are met.`;
}
function renderSpecs() {
  const p = S.prob;
  $("#specTable").innerHTML = p.specs.map((s, i) => `<tr class="${s.enabled ? "" : "off"}"><td><label class="check inline"><input type="checkbox" data-s="${i}" data-f="enabled" ${s.enabled ? "checked" : ""}> ${esc(S.metricLabel[s.metric])}</label></td>
    <td>at least</td><td><div class="unit"><input type="number" step="any" data-s="${i}" data-f="minimum" value="${s.minimum}"><i>%</i></div></td></tr>`).join("");
}
function updateChips() {
  const p = S.prob, c = cfg();
  const ps = $("#presetSel");
  $("#chipProblem").textContent = ps.value ? (S.problems[ps.value] || {}).label?.split(" · ")[0] || "" : "custom";
  $("#chipProcess").textContent = `${c.components.length} comp · ${c.zones.join("-")}`;
  const ov = p.variables.filter(v => v.optimize).length;
  $("#chipVars").textContent = `${ov} of ${p.variables.length} free`;
  $("#chipObj").textContent = objShort(p.objective);
  const sp = p.specs.filter(s => s.enabled).map(s => `${S.metricLabel[s.metric].replace("Extract ", "E ").replace("Raffinate ", "R ")} ≥ ${s.minimum}`);
  $("#chipLimits").textContent = sp.join(" · ") || "no specs";
  $("#chipSolver").textContent = `${p.max_iterations} it · tol ${p.css_tol}`;
  $("#modePill").textContent = `${c.scheme === "original" ? "Original" : "Conservative"} · ${c.flow_model === "constant" ? "Constant flow" : "Volume change"}`;
  $("#scanBtn").disabled = !(S.info && S.info.classic) || !!S.job;
  $("#scanBtn").title = S.info && S.info.classic ? "Simulate a grid of (m2, m3) points and show where the specifications are met" : "Needs a classic closed-loop four-zone layout";
}
function markCustom() { const ps = $("#presetSel"); if (ps.value) { ps.value = ""; $("#presetHint").textContent = "Edited from an example."; } }
function onChange(rerenderVars) {
  markCustom(); updateChips();
  clearTimeout(S.validateTimer); S.validateTimer = setTimeout(() => validate(rerenderVars), 250);
}
async function validate(rerenderVars) {
  const { data } = await api("/api/validate", { problem: S.prob });
  S.errors = data.errors || [];
  S.info = data.info || null;
  const box = $("#errors");
  box.hidden = !S.errors.length;
  box.innerHTML = S.errors.length ? `<ul>${S.errors.map(e => `<li>${esc(e)}</li>`).join("")}</ul>` : "";
  $("#runBtn").disabled = !!S.errors.length || !!S.job;
  if (rerenderVars) renderVars(); else { renderStartDerived(); const bal = $("#varTable tr.balance .computed"); if (bal && S.info) bal.textContent = f3(S.info.flows.balance_flow) + " mL/min, from the liquid balance"; }
  updateChips();
  renderWindow();
}
function loadProblem(prob, presetKey) {
  S.prob = clone(prob);
  const ps = $("#presetSel");
  ps.value = presetKey || "";
  $("#presetHint").textContent = presetKey ? S.problems[presetKey].summary : "Loaded from a file.";
  S.scan = null;
  renderSetup(); validate(true);
}
function bindSetup() {
  $("#presetSel").onchange = () => { const k = $("#presetSel").value; if (S.problems[k]) loadProblem(S.problems[k].problem, k); };
  $("#resetBtn").onclick = () => { const k = $("#presetSel").value || "case2_feed"; loadProblem(S.problems[k].problem, k); };
  $("#exportBtn").onclick = () => download("smb_optimization_problem.json", JSON.stringify(S.prob, null, 2), "application/json");
  $("#importFile").onchange = async e => {
    const f = e.target.files[0]; if (!f) return;
    try { const d = JSON.parse(await f.text()); if (!d.process || !d.variables) throw new Error("not a problem file"); loadProblem(d, ""); }
    catch (err) { alertStatus("Could not read that file as an optimization problem: " + err.message); }
    e.target.value = "";
  };
  $("#importSetup").onchange = async e => {
    const f = e.target.files[0]; if (!f) return;
    try {
      const setup = JSON.parse(await f.text());
      const { ok, data } = await api("/api/from_setup", { setup, problem: S.prob });
      if (!ok) throw new Error((data.errors || ["unknown error"]).join("; "));
      loadProblem(data.problem, "");
      $("#presetHint").textContent = `Process from ${f.name}. Bounds were set to ±30 % around its operating point; adjust them as needed.`;
    } catch (err) { alertStatus("Could not use that setup: " + err.message); }
    e.target.value = "";
  };
  $("#schemeSeg").onclick = e => { const b = e.target.closest("button"); if (!b) return; cfg().scheme = b.dataset.v; setSeg($("#schemeSeg"), b.dataset.v); onChange(); };
  $("#flowSeg").onclick = e => { const b = e.target.closest("button"); if (!b) return; cfg().flow_model = b.dataset.v; setSeg($("#flowSeg"), b.dataset.v); onChange(); };
  $("#varTable").oninput = e => {
    const t = e.target, i = +t.dataset.i, f = t.dataset.f; if (Number.isNaN(i) || !f) return;
    const v = S.prob.variables[i];
    if (f === "optimize") { v.optimize = t.checked; t.closest("tr").classList.toggle("off", !t.checked); }
    else { const x = parseFloat(t.value); if (!Number.isFinite(x)) return; v[f] = x; syncProcess(v); }
    onChange();
  };
  $("#objSel").onchange = () => { S.prob.objective = $("#objSel").value; renderObjHint(); onChange(); };
  $("#specTable").oninput = e => {
    const t = e.target, i = +t.dataset.s, f = t.dataset.f; if (Number.isNaN(i) || !f) return;
    const s = S.prob.specs[i];
    if (f === "enabled") { s.enabled = t.checked; t.closest("tr").classList.toggle("off", !t.checked); }
    else { const x = parseFloat(t.value); if (Number.isFinite(x)) s.minimum = x; }
    onChange();
  };
  $("#maxFlow").oninput = () => { const x = parseFloat($("#maxFlow").value); S.prob.max_zone_flow = Number.isFinite(x) ? x : null; onChange(); };
  $("#minFlow").oninput = () => { const x = parseFloat($("#minFlow").value); if (Number.isFinite(x)) { S.prob.min_zone_flow = x; onChange(); } };
  $("#ratioOn").onchange = () => { $("#ratioRow").hidden = !$("#ratioOn").checked; S.prob.max_desorbent_ratio = $("#ratioOn").checked ? parseFloat($("#ratioMax").value) || 5 : null; onChange(); };
  $("#ratioMax").oninput = () => { const x = parseFloat($("#ratioMax").value); if (Number.isFinite(x) && $("#ratioOn").checked) { S.prob.max_desorbent_ratio = x; onChange(); } };
  $("#maxIter").oninput = () => { const x = parseInt($("#maxIter").value); if (x > 0) { S.prob.max_iterations = x; onChange(); } };
  $("#cssTol").oninput = () => { const x = parseFloat($("#cssTol").value); if (x > 0) { S.prob.css_tol = x; onChange(); } };
  $("#fdStep").oninput = () => { const x = parseFloat($("#fdStep").value); if (x > 0) { S.prob.fd_step = x / 100; onChange(); } };
  $("#workers").onchange = () => { S.prob.workers = parseInt($("#workers").value) || 0; onChange(); };
  $("#runBtn").onclick = startOptimization;
  $("#scanBtn").onclick = startScan;
  $("#cancelBtn").onclick = () => S.job && api(`/api/job/${S.job.id}/cancel`, {});
}
function syncProcess(v) {         // keep the process setup at the start values
  const c = cfg();
  if (v.key === "Q1") c.Q1 = v.start;
  else if (v.key === "step_time") c.step_time = v.start;
  else c.ports[+v.key.split(":")[1]].flow = v.start;
}
function alertStatus(msg) { $("#statusText").innerHTML = esc(msg); }

/* ================================================================== JOBS */
async function startOptimization() {
  if (S.job || S.errors.length) return;
  const { ok, data } = await api("/api/optimize", { problem: S.prob });
  if (!ok) { alertStatus((data.errors || ["Could not start."]).join(" ")); return; }
  S.job = { id: data.id, kind: "optimize", problem: clone(S.prob), label: $("#presetSel").selectedOptions[0]?.textContent || "Custom problem", t0: Date.now() };
  S.live = { history: [], start: null };
  jobUI(true);
  $("#statusText").innerHTML = "Simulating the start point to cyclic steady state…";
  poll();
}
async function startScan() {
  if (S.job || !S.info || !S.info.classic) return;
  const r = S.runs.find(x => x.id === S.selected);
  const values = r ? r.result.optimum.values : null;
  const n = parseInt($("#scanN").value) || 10;
  const { ok, data } = await api("/api/scan", { problem: S.prob, values, n });
  if (!ok) { alertStatus((data.errors || ["Could not start."]).join(" ")); return; }
  S.job = { id: data.id, kind: "scan", t0: Date.now(), n };
  jobUI(true);
  S.pointTab = "window"; renderPointTabs();
  $("#statusText").innerHTML = `Mapping the operating window: simulating the (m<sub>2</sub>, m<sub>3</sub>) grid…`;
  poll();
}
function jobUI(on) {
  $("#cancelBtn").hidden = !on; $("#runBtn").disabled = on || !!S.errors.length; $("#scanBtn").disabled = on || !(S.info && S.info.classic);
  $("#progressFill").classList.toggle("done", false);
  if (!on) $("#progressFill").style.width = "0";
}
async function poll() {
  const job = S.job; if (!job) return;
  const { data } = await api(`/api/job/${job.id}`);
  const elapsed = (Date.now() - job.t0) / 1000;
  if (data.status === "running") {
    const p = data.progress || {};
    if (job.kind === "optimize") {
      if (p.history) { S.live.history = p.history; }
      if (p.start) S.live.start = p.start;
      const it = Math.max(0, S.live.history.length - 1);
      const maxIt = job.problem.max_iterations;
      $("#progressFill").style.width = `${Math.min(97, 4 + 93 * it / maxIt)}%`;
      const h = S.live.history[S.live.history.length - 1];
      const objTxt = h ? ` · ${objShort(job.problem.objective)} <b>${f3(h.objective)} ${objUnit(job.problem.objective)}</b>${h.feasible ? "" : " (specs not yet met)"}` : "";
      $("#statusText").innerHTML = `Iteration <b>${it}</b>${objTxt} · ${p.evaluations || 0} simulations · ${fmtTime(elapsed)}`;
      renderLive();
    } else {
      const done = p.done || 0, tot = p.points || 1;
      $("#progressFill").style.width = `${Math.min(97, 3 + 94 * done / tot)}%`;
      $("#statusText").innerHTML = `Mapping the operating window: <b>${done}</b> of ${tot} points simulated · ${fmtTime(elapsed)}`;
    }
    setTimeout(poll, 900); return;
  }
  S.job = null; jobUI(false);
  if (data.status === "done") {
    $("#progressFill").style.width = "100%"; $("#progressFill").classList.add("done");
    if (job.kind === "optimize") finishOptimization(job, data.result);
    else { S.scan = data.result; $("#statusText").innerHTML = `Operating window mapped: ${data.result.grid.length} points in ${fmtTime(data.result.elapsed)}. Green cells meet every specification.`; renderWindow(); }
  } else if (data.status === "cancelled") {
    $("#statusText").textContent = "Cancelled.";
  } else {
    $("#statusText").innerHTML = `<span style="color:var(--bad)">Failed:</span> ${esc(data.error || "unknown error")}`;
  }
  validate();
}
function finishOptimization(job, res) {
  const run = { id: job.id, label: job.label, problem: job.problem, result: res };
  S.runs.unshift(run); S.selected = run.id; S.live = null;
  const o = res.objective, a = res.start.objective, b = res.optimum.objective;
  const ch = a ? (b - a) / Math.abs(a) * 100 : 0;
  $("#statusText").innerHTML = res.feasible
    ? `<b>Best point found</b> after ${res.history.length - 1} iterations and ${res.evaluations} simulations (${fmtTime(res.elapsed)}): ${objShort(o).toLowerCase()} ${f3(a)} → <b>${f3(b)} ${objUnit(o)}</b> (${ch >= 0 ? "+" : ""}${ch.toFixed(1)} %), every limit met.`
    : `<span style="color:var(--warn)">No point meeting every limit was found</span> within the bounds after ${res.history.length - 1} iterations. ${esc(res.message)}. Try wider bounds or looser specifications.`;
  renderAll();
}

/* ================================================================ RESULTS */
function current() { return S.runs.find(r => r.id === S.selected) || null; }
function renderAll() {
  renderKPIs(); renderPointTabs(); renderProgress(); renderProfile(); renderSplit(); renderRuns();
  $("#setupBtn").disabled = $("#csvBtn").disabled = !current();
}
function renderLive() {
  renderKPIs(); renderProgress();
  if (S.pointTab === "window") renderWindow();
}
function kpiTile(label, value, unit, sub, cls = "", bar = null) {
  return `<div class="kpi ${cls}"><div class="k-label">${esc(label)}</div><div class="k-value">${value}<small>${unit}</small></div><div class="k-sub">${sub}</div>${bar !== null ? `<div class="k-bar" style="width:${Math.max(0, Math.min(100, bar))}%"></div>` : ""}</div>`;
}
function renderKPIs() {
  const r = current(), live = S.live && S.job;
  const prob = live ? S.job.problem : r ? r.problem : S.prob;
  let start = null, best = null, res = null;
  if (live && S.live.history.length) { start = S.live.history[0]; best = S.live.history[S.live.history.length - 1]; }
  else if (r) { res = r.result; start = res.start; best = res.optimum; }
  const el = $("#kpis");
  if (!best) {
    el.innerHTML = [kpiTile(objShort(prob.objective), "–", "", "best value found"), kpiTile("Extract purity", "–", "", "group, desorbent-free"),
      kpiTile("Raffinate purity", "–", "", "group, desorbent-free"), kpiTile("Search effort", "–", "", "iterations · simulations")].map(s => s.replace('class="kpi ', 'class="kpi placeholder ')).join("");
    return;
  }
  const o = prob.objective;
  const ch = start.objective ? (best.objective - start.objective) / Math.abs(start.objective) * 100 : 0;
  const good = o === "min_desorbent" ? ch <= 0 : ch >= 0;
  const delta = `<span class="delta ${good ? "up" : "down"}">${ch >= 0 ? "▲" : "▼"} ${Math.abs(ch).toFixed(1)} %</span>`;
  const specOf = m => (prob.specs.find(s => s.metric === m && s.enabled) || null);
  const tile = m => {
    const s = specOf(m), v = best.metrics[m];
    const ok = s ? v >= s.minimum - 1e-3 : null;
    const sub = s ? `${ok ? "✓ meets" : "✗ below"} ${s.minimum} % · start ${pct(start.metrics[m])}` : `no limit · start ${pct(start.metrics[m])}`;
    return kpiTile(S.metricLabel[m], pct(v), "%", sub, ok === false ? "bad" : "", v);
  };
  const its = (live ? S.live.history.length : res.history.length) - 1;
  const evals = live ? "" : ` · ${res.evaluations} simulations`;
  const t = live ? (Date.now() - S.job.t0) / 1000 : res.elapsed;
  el.innerHTML = kpiTile(objShort(o) + (live ? " (so far)" : ""), f3(best.objective), objUnit(o), `${delta} from ${f3(start.objective)} at the start`, "hero") +
    METRICS.map(tile).join("") +
    (o !== "min_desorbent" ? kpiTile("Desorbent / feed", fmt(best.desorbent_ratio), "", `start ${fmt(start.desorbent_ratio)}`) : "") +
    (o !== "max_feed" ? kpiTile("Feed throughput", f3(best.feed), "mL/min", `start ${f3(start.feed)}`) : "") +
    kpiTile("Search effort", String(its), " it", `${fmtTime(t)}${evals}`);
}

/* ---------------------------------------------------- operating point card */
function renderPointTabs() {
  setTabs($("#pointTabs"), S.pointTab);
  $("#pWindow").hidden = S.pointTab !== "window"; $("#pCompare").hidden = S.pointTab !== "compare"; $("#pLimits").hidden = S.pointTab !== "limits";
  if (S.pointTab === "window") renderWindow(); else if (S.pointTab === "compare") renderCompare(); else renderLimits();
}
function historyNow() {
  if (S.live && S.job && S.job.kind === "optimize") return S.live.history;
  const r = current(); return r ? r.result.history : [];
}
function renderWindow() {
  const el = $("#windowChart"), side = $("#windowSide");
  if (!el || S.pointTab !== "window") return;
  const info = S.info, scanRes = S.scan, hist = historyNow();
  const W = el.clientWidth || 560, H = el.clientHeight || 380;
  let svg = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">`;
  if (!info) { el.innerHTML = svg + `<text class="empty-msg" x="${W / 2}" y="${H / 2}" text-anchor="middle">Load a problem</text></svg>`; return; }
  const henry = (scanRes && scanRes.henry) || info.henry;
  const comps = cfg().components;
  const hv = henry.map(h => h.H);
  const pts = hist.map(h => ({ m2: h.m_values[1], m3: h.m_values[2], ok: h.feasible }));
  const m0 = info.derived.m_values;
  let lo, hi;
  if (scanRes) { lo = Math.min(scanRes.m2[0], scanRes.m3[0]); hi = Math.max(scanRes.m2[scanRes.m2.length - 1], scanRes.m3[scanRes.m3.length - 1]); }
  else {
    const all = hv.concat([m0[1], m0[2]], pts.flatMap(p => [p.m2, p.m3]));
    lo = Math.min(...all); hi = Math.max(...all); const pad = (hi - lo) * 0.15 + 0.02; lo -= pad; hi += pad;
  }
  const m = { l: 56, r: 16, t: 14, b: 40 };
  const size = Math.min(W - m.l - m.r, H - m.t - m.b);
  const sx = x => m.l + (x - lo) / (hi - lo) * size, sy = y => m.t + size - (y - lo) / (hi - lo) * size;
  svg += `<defs><clipPath id="plotclip"><rect x="${m.l}" y="${m.t}" width="${size}" height="${size}"/></clipPath></defs><g clip-path="url(#plotclip)">`;
  // scanned cells
  if (scanRes) {
    const d2 = scanRes.m2.length > 1 ? scanRes.m2[1] - scanRes.m2[0] : 0.05, d3 = scanRes.m3.length > 1 ? scanRes.m3[1] - scanRes.m3[0] : 0.05;
    const worst = Math.min(-1, ...scanRes.grid.map(g => g.margin));
    for (const g of scanRes.grid) {
      const x0 = sx(g.m2 - d2 / 2), x1 = sx(g.m2 + d2 / 2), y0 = sy(g.m3 + d3 / 2), y1 = sy(g.m3 - d3 / 2);
      const fill = g.feasible ? "var(--good)" : "var(--ink-3)";
      const op = g.feasible ? 0.30 + 0.45 * Math.min(1, g.margin / 5) : 0.06 + 0.22 * Math.min(1, g.margin / worst);
      svg += `<rect class="cell" data-k="${g.i},${g.j}" x="${x0}" y="${y0}" width="${x1 - x0}" height="${y1 - y0}" fill="${fill}" fill-opacity="${op.toFixed(3)}"/>`;
    }
  }
  // ideal triangle from Henry constants
  const rafH = henry.filter(h => h.role === "raffinate").map(h => h.H), extH = henry.filter(h => h.role === "extract").map(h => h.H);
  if (rafH.length && extH.length) {
    const a = Math.max(...rafH), b = Math.min(...extH);
    if (b > a) svg += `<path d="M${sx(a)} ${sy(a)} L${sx(a)} ${sy(b)} L${sx(b)} ${sy(b)} Z" fill="var(--accent)" fill-opacity="0.08" stroke="var(--accent)" stroke-width="1.5" stroke-dasharray="5 4"/>`;
  }
  svg += `</g>`;
  // axes
  const T = niceTicks(lo, hi, 5);
  svg += `<g class="grid">`; for (const t of T) { if (t < lo || t > hi) continue; svg += `<line x1="${sx(t)}" x2="${sx(t)}" y1="${m.t}" y2="${m.t + size}"/><line x1="${m.l}" x2="${m.l + size}" y1="${sy(t)}" y2="${sy(t)}"/>`; } svg += `</g>`;
  svg += `<g class="axis">`; for (const t of T) { if (t < lo || t > hi) continue; svg += `<text x="${sx(t)}" y="${m.t + size + 16}" text-anchor="middle">${fmt(t)}</text><text x="${m.l - 8}" y="${sy(t) + 4}" text-anchor="end">${fmt(t)}</text>`; }
  svg += `<line x1="${m.l}" x2="${m.l + size}" y1="${m.t + size}" y2="${m.t + size}"/><line x1="${m.l}" x2="${m.l}" y1="${m.t}" y2="${m.t + size}"/></g>`;
  svg += `<text class="axis-title" x="${m.l + size / 2}" y="${m.t + size + 34}" text-anchor="middle">m₂ (zone II)</text>`;
  svg += `<text class="axis-title" transform="translate(14 ${m.t + size / 2}) rotate(-90)" text-anchor="middle">m₃ (zone III)</text>`;
  svg += `<line x1="${sx(lo)}" y1="${sy(lo)}" x2="${sx(hi)}" y2="${sy(hi)}" stroke="var(--ink-3)" stroke-width="1"/>`;
  svg += `<text class="axis-title" x="${sx(hi) - 4}" y="${sy(hi) + 14}" text-anchor="end">m₂ = m₃</text>`;
  // Henry lines (ticks on the diagonal)
  henry.forEach(h => {
    const i = comps.findIndex(c => c.name === h.name), col = compColor(i);
    if (h.H < lo || h.H > hi) return;
    if (h.role === "raffinate") svg += `<line x1="${sx(h.H)}" x2="${sx(h.H)}" y1="${sy(h.H)}" y2="${sy(hi)}" stroke="${col}" stroke-width="1" stroke-opacity=".7"/>`;
    else svg += `<line x1="${sx(lo)}" x2="${sx(h.H)}" y1="${sy(h.H)}" y2="${sy(h.H)}" stroke="${col}" stroke-width="1" stroke-opacity=".7"/>`;
    svg += `<circle cx="${sx(h.H)}" cy="${sy(h.H)}" r="3.5" fill="${col}"><title>${esc(h.name)}: H = ${fmt(h.H)}</title></circle>`;
  });
  // path
  if (pts.length) {
    svg += `<path d="${pts.map((p, i) => `${i ? "L" : "M"}${sx(p.m2).toFixed(1)} ${sy(p.m3).toFixed(1)}`).join("")}" fill="none" stroke="var(--ink)" stroke-width="1.6" stroke-opacity=".75"/>`;
    pts.forEach((p, i) => { if (i && i < pts.length - 1) svg += `<circle cx="${sx(p.m2)}" cy="${sy(p.m3)}" r="3" fill="${p.ok ? "var(--ink)" : "var(--surface)"}" stroke="var(--ink)" stroke-width="1.3"/>`; });
    const s = pts[0], e = pts[pts.length - 1];
    svg += `<circle cx="${sx(s.m2)}" cy="${sy(s.m3)}" r="6" fill="var(--surface)" stroke="var(--ink)" stroke-width="2"/>`;
    if (pts.length > 1) svg += star(sx(e.m2), sy(e.m3), 9, e.ok ? "var(--good)" : "var(--warn)");
  } else {
    svg += `<circle cx="${sx(m0[1])}" cy="${sy(m0[2])}" r="6" fill="var(--surface)" stroke="var(--ink)" stroke-width="2"/>`;
  }
  el.innerHTML = svg + "</svg>";
  // hover on scan cells
  el.onmousemove = ev => {
    const c = ev.target.closest && ev.target.closest(".cell");
    if (!c || !scanRes) { tip.hide(); return; }
    const [i, j] = c.dataset.k.split(",").map(Number), g = scanRes.grid.find(q => q.i === i && q.j === j);
    tip.show(`<div class="tt-head">m₂ ${fmt(g.m2)} · m₃ ${fmt(g.m3)} · feed ${f3(g.feed)} mL/min</div>` +
      METRICS.map(k => `<div class="tt-row"><span>${S.metricLabel[k]}</span><b>${pct(g.metrics[k])} %</b></div>`).join("") +
      `<div class="tt-row"><span>${g.feasible ? "Meets every specification" : "Misses a specification by"}</span><b>${g.feasible ? "✓" : pct(-g.margin) + " pts"}</b></div>`, ev.clientX, ev.clientY);
  };
  el.onmouseleave = () => tip.hide();
  // side panel
  const rows = henry.map(h => { const i = comps.findIndex(c => c.name === h.name); return `<tr><td><span class="sw" style="background:${compColor(i)}"></span>${esc(h.name)}</td><td>${h.role}</td><td>${fmt(h.H)}</td></tr>`; }).join("");
  const last = hist.length ? hist[hist.length - 1] : null;
  side.innerHTML = `<p class="side-note">Each operating point is drawn by its zone II and III flow ratios <i>m</i><sub>j</sub> = (Q<sub>j</sub>t* − εV)/((1−ε)V).
    The dashed triangle is equilibrium theory at infinite dilution: every raffinate component's Henry constant <i>H</i> below m₂ and every extract component's above m₃.
    Concentrated feeds compete for the adsorbent and shift the real window, so treat the triangle as a guide and use the full-model map below.</p>
    <div class="win-keys"><span><i class="k-start"></i>start</span><span><i class="k-path"></i>iterations (hollow = a spec missed)</span><span><i class="k-star"></i>best point</span>${scanRes ? `<span><i class="k-ok"></i>full model meets specs</span>` : ""}</div>
    <table class="perf mini"><thead><tr><th>Component</th><th>Leaves in</th><th>H</th></tr></thead><tbody>${rows}</tbody></table>
    ${scanRes ? `<p class="side-note">Grid at m₁ = ${f3(scanRes.m1)}, m₄ = ${f3(scanRes.m4)}, t* = ${f3(scanRes.t_star)} min.</p>` : `<p class="side-note">Press <b>Map the operating window</b> to colour the plane with the full model's result for each (m₂, m₃).</p>`}
    ${last ? `<p class="side-note">Current point: m₁ ${f3(last.m_values[0])}, m₂ ${f3(last.m_values[1])}, m₃ ${f3(last.m_values[2])}, m₄ ${f3(last.m_values[3])}.</p>` : ""}`;
  $("#pointSub").textContent = scanRes ? `${scanRes.grid.length} simulated points` : "";
}
function star(cx, cy, r, color) {
  let d = "";
  for (let k = 0; k < 10; k++) { const a = -Math.PI / 2 + k * Math.PI / 5, rr = k % 2 ? r * 0.45 : r; d += `${k ? "L" : "M"}${(cx + rr * Math.cos(a)).toFixed(1)} ${(cy + rr * Math.sin(a)).toFixed(1)}`; }
  return `<path d="${d}Z" fill="${color}" stroke="var(--surface)" stroke-width="1.5"/>`;
}
function renderCompare() {
  const r = current(), el = $("#pCompare");
  if (!r) { el.innerHTML = `<p class="muted">Run an optimization to compare the start and the best point.</p>`; return; }
  const res = r.result, a = res.start, b = res.optimum, vars = res.variables;
  const row = (label, x, y, unit, d = 3, extra = "", abs = false) => {
    let txt;
    if (abs) { const df = y - x; txt = Math.abs(df) < 5e-5 ? "–" : (df > 0 ? "+" : "") + df.toFixed(d); }
    else { const ch = x ? (y - x) / Math.abs(x) * 100 : 0; txt = Math.abs(ch) < 0.05 ? "–" : (ch > 0 ? "+" : "") + ch.toFixed(1) + " %"; }
    return `<tr><td>${label}</td><td>${Number(x).toFixed(d)}</td><td><b>${Number(y).toFixed(d)}</b></td><td>${txt}</td><td>${unit}</td><td>${extra}</td></tr>`;
  };
  const boundBar = v => {
    if (!v.optimize) return `<span class="muted small">fixed</span>`;
    const pos = (b.values[v.key] - v.lower) / (v.upper - v.lower) * 100, p0 = (a.values[v.key] - v.lower) / (v.upper - v.lower) * 100;
    const at = pos > 99.9 ? "at upper bound" : pos < 0.1 ? "at lower bound" : "";
    return `<span class="bbar" title="${v.lower} – ${v.upper} ${v.unit}"><i class="b0" style="left:${p0}%"></i><i class="b1" style="left:${pos}%"></i></span>${at ? `<span class="at">${at}</span>` : ""}`;
  };
  let h = `<table class="perf cmp"><thead><tr><th></th><th>Start</th><th>Best</th><th>Change</th><th></th><th>Position within bounds</th></tr></thead><tbody>`;
  h += `<tr class="grp"><td colspan="6">Decision variables</td></tr>`;
  vars.forEach(v => { h += row(esc(v.label), a.values[v.key], b.values[v.key], v.unit, v.key === "step_time" ? 4 : 4, boundBar(v)); });
  h += row("Balance outlet flow", a.balance_flow, b.balance_flow, "mL/min", 4);
  h += `<tr class="grp"><td colspan="6">Zones</td></tr>`;
  a.zone_flows.forEach((q, i) => { h += row(`Zone ${ZONES[i]} flow`, q, b.zone_flows[i], "mL/min", 3); });
  a.m_values.forEach((q, i) => { h += row(`m${i + 1} (zone ${ZONES[i]})`, q, b.m_values[i], "–", 4, "", true); });
  h += `<tr class="grp"><td colspan="6">Products</td></tr>`;
  METRICS.forEach(k => { h += row(S.metricLabel[k], a.metrics[k], b.metrics[k], "% (change in points)", 2, "", true); });
  h += row("Feed throughput", a.feed, b.feed, "mL/min", 4);
  h += row("Desorbent / feed", a.desorbent_ratio, b.desorbent_ratio, "–", 3);
  el.innerHTML = h + "</tbody></table>";
}
function renderLimits() {
  const r = current(), el = $("#pLimits");
  if (!r) { el.innerHTML = `<p class="muted">Run an optimization to see which limits decide the best point.</p>`; return; }
  const res = r.result;
  const bind = res.binding || [];
  const cons = res.optimum.constraints;
  let h = `<p class="side-note">At the best point some limits are <b>binding</b>: the optimizer pushed the operating point right up against them. The value shows how much the objective would improve if that limit were relaxed by one unit, from the Lagrange multipliers of the final iteration. Limits with slack can be tightened without cost.</p>`;
  h += `<table class="perf"><thead><tr><th>Limit or bound</th><th>Status</th><th>Worth of one unit of relaxation</th></tr></thead><tbody>`;
  for (const b of bind) h += `<tr><td>${esc(b.name)}</td><td>${b.binding ? `<span class="tag bind">binding</span>` : `<span class="tag">touching</span>`}</td><td>${b.binding ? `${b.value >= 0 ? "+" : ""}${Number(b.value).toPrecision(3)} ${esc(b.unit)}` : "–"}</td></tr>`;
  h += `</tbody></table><table class="perf top-gap"><thead><tr><th>Limit</th><th>Value at the best point</th><th>Met</th></tr></thead><tbody>`;
  for (const c of cons) h += `<tr><td>${esc(c.name)}</td><td>${fmt(c.value)}</td><td>${c.ok ? "✓" : `<b style="color:var(--bad)">✗</b>`}</td></tr>`;
  el.innerHTML = h + "</tbody></table>";
}

/* ------------------------------------------------------------ progress */
function renderProgress() {
  setTabs($("#progTabs"), S.progTab);
  const hist = historyNow(), el = $("#progChart");
  const r = current();
  const prob = S.live && S.job && S.job.kind === "optimize" ? S.job.problem : r ? r.problem : S.prob;
  const x = hist.map(h => h.iteration);
  const hollow = hist.map(h => !h.feasible);
  let series = [], hlines = [], yTitle = "", fmtY = fmt, yZero = false;
  if (S.progTab === "objective") {
    series = [{ name: objShort(prob.objective), color: "var(--accent)", x, y: hist.map(h => h.objective), dots: true, hollow }];
    yTitle = `${objShort(prob.objective)} ${objUnit(prob.objective) ? "(" + objUnit(prob.objective) + ")" : ""}`;
    $("#progFoot").textContent = "Hollow points miss at least one specification. The search may pass through such points on its way to the best one that meets them all.";
  } else if (S.progTab === "quality") {
    series = METRICS.map((m, i) => ({ name: S.metricLabel[m], color: [css("--c1"), css("--c3"), css("--c2"), css("--c4")][i], x, y: hist.map(h => h.metrics[m]), dots: true, dash: m.endsWith("recovery") ? "5 3" : null }));
    hlines = prob.specs.filter(s => s.enabled).map(s => ({ y: s.minimum, label: `${S.metricLabel[s.metric]} ≥ ${s.minimum} %` }));
    yTitle = "%"; fmtY = v => fmt(v);
    $("#progFoot").textContent = "Dashed horizontal lines are the specifications.";
  } else {
    const vars = prob.variables.filter(v => v.optimize);
    series = vars.map((v, i) => ({ name: v.label, color: compColor(i + 1), x, y: hist.map(h => (h.values[v.key] - v.lower) / (v.upper - v.lower) * 100), dots: true, raw: v }));
    yTitle = "Position within bounds (%)"; yZero = true;
    $("#progFoot").textContent = "0 % is the lower bound and 100 % the upper bound of each variable. Hover for the values.";
  }
  legend($("#progLegend"), series, "prog" + S.progTab, renderProgress);
  lineChart(el, {
    series, key: "prog" + S.progTab, hlines, yTitle, xTitle: "Iteration", yZero, fmtY,
    yDomain: S.progTab === "variables" ? [0, 100] : undefined,
    xTicks: x.length <= 16 ? x : undefined, fmtX: v => String(Math.round(v)),
    empty: "Run an optimization to follow it here",
    tipX: (xx, j) => `Iteration ${xx}${hist[j] && !hist[j].feasible ? " · a spec is missed" : ""}`,
    tipY: (y, s) => s.raw ? `${fmt(s.raw.lower + y / 100 * (s.raw.upper - s.raw.lower))} ${s.raw.unit}` : fmt(y),
  });
}

/* ------------------------------------------------------- CSS + products */
function viewOf(which) { const r = current(); return r ? r.result[which === "start" ? "start_view" : "optimum_view"] : null; }
function renderProfile() {
  setSeg($("#profSeg"), S.profWhich);
  const v = viewOf(S.profWhich), el = $("#profile");
  if (!v) { legend($("#profLegend"), [], "prof", renderProfile); lineChart(el, { series: [], key: "prof", empty: "The concentration profile of the best point appears here" }); return; }
  const c = v.config, n = c.zones.reduce((a, b) => a + b, 0), p = v.column_pitch;
  const series = c.components.map((x, i) => ({ name: x.name, color: compColor(i), x: v.x, y: v.C[i] }));
  const starts = []; let acc = 0; c.zones.forEach(k => { starts.push(acc); acc += k; });
  const bands = c.zones.map((k, i) => ({ x0: starts[i] * p, x1: (starts[i] + k) * p, label: `Zone ${ZONES[i]}`, fill: i % 2 ? "var(--zone-b)" : "var(--zone-a)" }));
  const labels = portLabels(c);
  const vlines = c.ports.map((pt, i) => ({ x: starts[pt.zone] * p, label: labels[i], badge: portColor(c, pt.kind), color: "var(--ink-3)" }));
  legend($("#profLegend"), series, "prof", renderProfile);
  lineChart(el, { series, key: "prof", bands, vlines, top: 22, xDomain: [0, n * p], yTitle: "C (g/mL)", xTitle: "Position from the start of zone I (cm)",
    colLines: Array.from({ length: n - 1 }, (_, k) => (k + 1) * p), tipX: xx => `x = ${xx.toFixed(1)} cm · column ${Math.min(n, Math.floor(xx / p) + 1)}` });
}
function renderSplit() {
  setSeg($("#splitSeg"), S.splitWhich);
  const v = viewOf(S.splitWhich), el = $("#split");
  if (!v) { el.innerHTML = `<p class="muted">Run an optimization to see where each component leaves the unit.</p>`; return; }
  const c = v.config, comps = v.metrics.components;
  let h = "";
  comps.forEach((k, i) => {
    if (k.role === "desorbent") return;
    const e = k.to_extract || 0, rr = k.to_raffinate || 0;
    const want = k.role === "extract" ? e : rr;
    h += `<div class="split-row"><div class="split-label"><b><span class="sw" style="background:${compColor(i)}"></span>${esc(k.name)}</b><span>${want.toFixed(1)} % to the ${k.role}</span></div>
      <div class="bar"><div style="width:${e}%;background:${portColor(c, "extract")}" title="Extract ${e.toFixed(1)} %">${e > 9 ? e.toFixed(0) + "%" : ""}</div><div style="width:${rr}%;background:${portColor(c, "raffinate")}" title="Raffinate ${rr.toFixed(1)} %">${rr > 9 ? rr.toFixed(0) + "%" : ""}</div></div></div>`;
  });
  h += `<div class="split-keys"><span><i style="background:${portColor(c, "extract")}"></i>to the extract</span><span><i style="background:${portColor(c, "raffinate")}"></i>to the raffinate</span></div>`;
  el.innerHTML = h;
}

/* ---------------------------------------------------------------- runs */
function renderRuns() {
  const tb = $("#runs tbody");
  if (!S.runs.length) { tb.innerHTML = `<tr class="empty"><td colspan="10">No runs yet.</td></tr>`; return; }
  tb.innerHTML = S.runs.map((r, i) => {
    const res = r.result, o = res.objective, a = res.start.objective, b = res.optimum.objective;
    const ch = a ? (b - a) / Math.abs(a) * 100 : 0;
    return `<tr data-id="${r.id}" class="${r.id === S.selected ? "sel" : ""}"><td>${S.runs.length - i}</td><td>${esc(r.label)}</td><td>${esc(objShort(o))}</td>
      <td>${f3(a)}</td><td><b>${f3(b)}</b></td><td>${ch >= 0 ? "+" : ""}${ch.toFixed(1)} %</td>
      <td><span class="dot ${res.feasible ? "" : "warn"}"></span> ${res.feasible ? "yes" : "no"}</td><td>${res.history.length - 1}</td><td>${res.evaluations}</td><td>${fmtTime(res.elapsed)}</td></tr>`;
  }).join("");
  $$("tr[data-id]", tb).forEach(tr => tr.onclick = () => { S.selected = tr.dataset.id; renderAll(); });
}
function exportSetup() {
  const r = current(); if (!r) return;
  download("smb_best_setup.json", JSON.stringify(r.result.optimum_config, null, 2), "application/json");
}
function exportCSV() {
  const r = current(); if (!r) return;
  const res = r.result, vars = res.variables;
  const head = ["iteration", "objective", ...vars.map(v => `${v.label} (${v.unit})`), ...METRICS, "m1", "m2", "m3", "m4", "meets_specs", "simulations", "elapsed_s"];
  const rows = res.history.map(h => [h.iteration, h.objective, ...vars.map(v => h.values[v.key]), ...METRICS.map(m => h.metrics[m]), ...h.m_values.slice(0, 4), h.feasible, h.evaluations, h.elapsed.toFixed(1)]);
  const q = s => /[",]/.test(String(s)) ? `"${String(s).replace(/"/g, '""')}"` : s;
  download("smb_optimization_iterations.csv", [head, ...rows].map(rw => rw.map(q).join(",")).join("\n"), "text/csv");
}

/* ---------------------------------------------------------------- theme */
function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem("smb-theme"); } catch (e) { /* storage unavailable */ }
  if (saved) document.documentElement.dataset.theme = saved;
  $("#themeBtn").onclick = () => {
    const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("smb-theme", next); } catch (e) { /* ignore */ }
    renderProcess(); renderAll(); renderWindow();
  };
}

/* ================================================================= INIT */
async function init() {
  tip.el = $("#tooltip");
  initTheme();
  const { data } = await api("/api/defaults");
  S.problems = data.problems; S.objectives = data.objectives; S.metricLabel = data.metrics; S.workers = data.workers;
  const ps = $("#presetSel");
  ps.innerHTML = Object.entries(S.problems).map(([k, p]) => `<option value="${k}">${esc(p.label)}</option>`).join("") + `<option value="" hidden>Custom problem</option>`;
  bindSetup();
  $("#pointTabs").onclick = e => { const b = e.target.closest("button"); if (!b) return; S.pointTab = b.dataset.v; renderPointTabs(); };
  $("#progTabs").onclick = e => { const b = e.target.closest("button"); if (!b) return; S.progTab = b.dataset.v; renderProgress(); };
  $("#profSeg").onclick = e => { const b = e.target.closest("button"); if (!b) return; S.profWhich = b.dataset.v; renderProfile(); };
  $("#splitSeg").onclick = e => { const b = e.target.closest("button"); if (!b) return; S.splitWhich = b.dataset.v; renderSplit(); };
  $("#setupBtn").onclick = exportSetup; $("#csvBtn").onclick = exportCSV;
  let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { renderPointTabs(); renderProgress(); renderProfile(); }, 120); });
  const first = Object.keys(S.problems)[0];
  loadProblem(S.problems[first].problem, first);
  renderAll();
}
init();
