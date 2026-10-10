"use strict";
/* All dynamic content is rendered with textContent (never innerHTML): the data shown here can
   originate from untrusted documents, so the UI itself must be injection-proof. */
const $ = (s) => document.querySelector(s);
const h = (tag, attrs, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") e.className = v; else if (k === "style") e.style.cssText = v; else if (k.startsWith("on")) e.addEventListener(k.slice(2), v); else if (v !== false && v != null) e.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) e.append(k.nodeType ? k : document.createTextNode(String(k)));
  return e;
};
const pill = (text, cls) => h("span", { class: "pill " + (cls || String(text).toLowerCase().replace(/\s/g, "_")) }, text);
const clear = (el) => { el.replaceChildren(); return el; };
let KEY = sessionStorage.getItem("rg_key") || "";

function banner(msg, err) { const b = $("#banner"); b.hidden = !msg; b.className = "banner" + (err ? " err" : ""); b.textContent = msg || ""; }

async function api(path, opts = {}) {
  const headers = { Authorization: "Bearer " + KEY, "X-Correlation-ID": "ui-" + crypto.randomUUID(), ...(opts.headers || {}) };
  if (opts.body) headers["Content-Type"] = "application/json";
  const r = await fetch(path, { method: opts.method || "GET", headers, body: opts.body ? JSON.stringify(opts.body) : undefined });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(data.title || r.statusText); e.data = data; e.status = r.status; e.cid = r.headers.get("x-correlation-id"); throw e; }
  return data;
}
const guard = (fn) => async (...a) => { try { banner(""); await fn(...a); } catch (e) { banner(`${e.status || ""} ${e.message}${e.cid ? " (correlationId " + e.cid + ")" : ""}`, true); } };

// ------------------------------------------------------------------ tabs
document.querySelectorAll("#tabs button").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("on", x === b));
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("on", p.id === "tab-" + b.dataset.tab));
  guard(LOAD[b.dataset.tab] || (() => {}))();
}));

// ------------------------------------------------------------------ overview
const kpi = (label, val, cls) => h("div", { class: "kpi" }, h("b", { class: cls || "" }, val), h("span", {}, label));
async function overview() {
  const s = await api("/api/v1/analysis/summary"); const c = s.counts;
  const k = clear($("#kpis"));
  k.append(kpi("Compliance score", s.complianceScore + "%"), kpi("In-scope obligations", c.inScope), kpi("Controls", c.controls), kpi("Open gaps", c.gaps),
    kpi("Critical / High", (c.gapsByBand.critical || 0) + " / " + (c.gapsByBand.high || 0)), kpi("Reg. conflicts", s.contradictions), kpi("Cross-reg clusters", s.crossRegulationClusters), kpi("Read-model cache", s.readModelCache));
  const tg = clear($("#topGaps"));
  s.topGaps.forEach((g) => tg.append(h("div", { class: "item" }, h("header", {}, pill(g.risk.band), h("span", { class: "t" }, g.title), h("span", { class: "hint" }, `${g.regCode} cl.${g.clause} · risk ${g.risk.riskScore}`)), h("div", { class: "hint" }, g.detail))));
  if (!s.topGaps.length) tg.append(h("p", { class: "hint" }, "No data yet - click “Load demo dataset”."));
  drawTrend(await api("/api/v1/monitoring/trend"));
}
function drawTrend(points) {
  const cv = $("#trend"), ctx = cv.getContext("2d"); ctx.clearRect(0, 0, cv.width, cv.height);
  const css = getComputedStyle(document.body); const ink = css.getPropertyValue("--muted"), brand = css.getPropertyValue("--brand");
  ctx.strokeStyle = ink; ctx.fillStyle = ink; ctx.font = "11px system-ui"; ctx.globalAlpha = .4;
  for (let i = 0; i <= 4; i++) { const y = 20 + i * 36; ctx.beginPath(); ctx.moveTo(30, y); ctx.lineTo(510, y); ctx.stroke(); }
  ctx.globalAlpha = 1; [100, 75, 50, 25, 0].forEach((v, i) => ctx.fillText(v, 4, 24 + i * 36));
  if (points.length < 1) return;
  ctx.strokeStyle = brand; ctx.fillStyle = brand; ctx.lineWidth = 2; ctx.beginPath();
  points.forEach((p, i) => { const x = 40 + (points.length === 1 ? 0 : i * 460 / (points.length - 1)), y = 164 - p.score * 1.44; i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
  ctx.stroke(); points.forEach((p, i) => { const x = 40 + (points.length === 1 ? 0 : i * 460 / (points.length - 1)), y = 164 - p.score * 1.44; ctx.beginPath(); ctx.arc(x, y, 3.5, 0, 7); ctx.fill(); });
}
function showTrace(tr, into) {
  const el = clear(into); if (!tr) return;
  el.append(h("p", { class: "hint" }, `Agent trace · correlationId ${tr.correlationId} · ${tr.totalMs} ms`));
  tr.steps.forEach((s) => el.append(h("div", { class: "step" }, pill(s.status === "ok" ? "ok" : "failed", s.status === "ok" ? "allow" : "block"), h("b", {}, s.agent), h("span", {}, s.action + (s.detail ? " — " + s.detail : "") + ` (${s.ms} ms)`))));
}
$("#loadSample").addEventListener("click", guard(async () => {
  const btn = $("#loadSample"); btn.disabled = true;
  try {
    const r = await api("/api/v1/sample/load", { method: "POST", headers: { "Idempotency-Key": "ui-sample-" + crypto.randomUUID() } });
    banner(`Loaded ${r.loaded.length} documents through the firewall. Score ${r.complianceScore}%, ${r.gaps} gaps. ` + r.loaded.filter((x) => x.impact).map((x) => x.impact).join(" | "));
    await overview();
  } finally { btn.disabled = false; }
}));

// ------------------------------------------------------------------ firewall lab
function fwRender(r, into) {
  const el = clear(into);
  el.append(h("div", { class: "row" }, pill(r.verdict.toUpperCase(), r.verdict), h("b", {}, "risk " + r.riskScore), h("span", { class: "hint" }, `${r.stats.latencyMs} ms · ${r.stats.sourceType} (${r.stats.trust}) · ${r.stats.decodedVariantsScanned} decoded variants · ${r.stats.hiddenSegments} hidden channels`)));
  Object.entries(r.categoryScores).forEach(([c, v]) => el.append(h("div", {}, h("span", { class: "hint" }, c + " " + v), h("div", { class: "bar" }, h("i", { style: `width:${Math.round(v * 100)}%` })))));
  if (r.session) el.append(h("p", { class: "hint" }, `Session: ${r.session.turns} turn(s)` + (r.session.escalated ? " — ESCALATED: " + r.session.reason : "")));
  const ul = h("ul");
  r.findings.slice(0, 10).forEach((f) => ul.append(h("li", {}, pill(f.category, f.severity === "critical" ? "critical" : "high"), ` ${f.explanation} `, h("span", { class: "hint" }, `[${f.channel}${f.encodedVia ? " via " + f.encodedVia.join("+") : ""}] “${f.excerpt}” conf ${f.confidence}`))));
  el.append(ul);
  el.append(h("h2", { style: "margin-top:12px" }, "Text that would reach the model"), h("div", { class: "san" }, r.sanitizedText === null ? "⛔ BLOCKED — nothing is forwarded to any agent." : (r.sanitizedText || "(empty)")));
}
$("#fwScan").addEventListener("click", guard(async () => {
  const body = { content: $("#fwText").value, sourceType: $("#fwSource").value };
  if ($("#fwSession").value) body.sessionId = $("#fwSession").value;
  fwRender(await api("/api/v1/firewall/scan", { method: "POST", body }), $("#fwResult"));
}));
$("#egScan").addEventListener("click", guard(async () => {
  const r = await api("/api/v1/firewall/egress", { method: "POST", body: { text: $("#egText").value } }); const el = clear($("#egResult"));
  el.append(h("div", { class: "row" }, pill(r.allowed ? "RELEASED" : "WITHHELD", r.allowed ? "allow" : "block")), h("div", { class: "san" }, r.redactedText), h("ul", {}, r.findings.map((f) => h("li", {}, `${f.type} (${f.severity}): ${f.detail}`))));
}));
async function firewallTab() {
  if ($("#fwSource").children.length) return;
  ["user", "web", "html", "pdf", "email", "markdown", "docx", "api", "ocr", "code", "image", "text"].forEach((s) => $("#fwSource").append(h("option", {}, s)));
  const samples = await api("/api/v1/firewall/samples");
  samples.forEach((s) => $("#fwSamples").append(h("button", { class: "chip", onclick: () => { $("#fwText").value = s.content; $("#fwSource").value = s.sourceType; } }, s.name)));
  $("#fwSamples").append(h("button", { class: "chip", onclick: () => { $("#fwText").value = "1.1 Regulated entities shall report every reportable cyber incident within 6 hours of detection."; $("#fwSource").value = "pdf"; } }, "benign regulation"));
  const c = await api("/api/v1/firewall/catalog");
  c.attackClasses.forEach((a) => $("#fwCatalog").append(h("span", { class: "chip" }, `${a.category} · ${a.rules} rules`)));
}

// ------------------------------------------------------------------ gaps
async function gapsTab() {
  const list = clear($("#gapList")); const gaps = await api("/api/v1/gaps?minBand=" + $("#gapBand").value);
  if (!gaps.length) list.append(h("p", { class: "hint" }, "No gaps at this level."));
  gaps.forEach((g) => list.append(h("div", { class: "item" },
    h("header", {}, pill(g.risk.band), h("span", { class: "t" }, g.title), h("span", { class: "hint" }, `${g.regCode} cl.${g.clause} · risk ${g.risk.riskScore} (sev ${g.risk.factors.severity} × lik ${g.risk.factors.likelihood} × urg ${g.risk.factors.urgency})`)),
    h("div", {}, g.obligation), h("div", { class: "hint" }, g.detail),
    h("div", { class: "hint" }, `Fix (${g.remediation.effort}, ~${g.remediation.targetDays}d, owner ${g.remediation.ownerRole}, +${g.remediation.expectedScoreUpliftPct}% score):`),
    h("ul", {}, g.remediation.steps.map((s) => h("li", {}, s))),
    h("button", { class: "btn small", onclick: guard(() => trace(g.obligationId)) }, "Show traceability chain"))));
}
$("#gapBand").addEventListener("change", guard(gapsTab));
async function trace(id) {
  const t = await api("/api/v1/trace/" + encodeURIComponent(id)); const box = clear($("#traceView")); const chain = h("div", { class: "chain" });
  t.chain.forEach((n) => { const body = h("div"); if (n.items) n.items.forEach((i) => body.append(h("div", {}, typeof i === "object" ? (i.title || i.id || i.type || i.summary || i.controlId || JSON.stringify(i).slice(0, 90)) : i))); else body.append(h("div", {}, n.text || n.ref || n.status || n.reason || (n.trend ? n.trend.map((x) => x.score + "%").join(" → ") : ""))); chain.append(h("div", { class: "node" }, h("h3", {}, n.stage), body)); });
  box.append(h("p", { class: "hint" }, id), chain); document.querySelector('[data-tab="overview"]').click(); $("#traceView").scrollIntoView({ behavior: "smooth" });
}

// ------------------------------------------------------------------ change / cross / what-if
async function changeTab() {
  const el = clear($("#changeList")); const imp = await api("/api/v1/impact");
  if (!imp.length) el.append(h("div", { class: "card hint" }, "No regulatory version changes yet. Load the demo dataset: IN-CYBER v2.0 arrives last and triggers autonomous impact analysis."));
  imp.forEach((r) => {
    const c = h("div", { class: "card" }, h("h2", {}, r.headline), h("div", { class: "row" }, pill("score " + r.scoreBefore + "% → " + r.scoreAfter + "%", r.scoreDelta < 0 ? "block" : "allow"), h("span", { class: "hint" }, "Impacted controls: " + (r.impactedControls.join(", ") || "none"))));
    if (r.change) {
      r.change.modified.forEach((m) => c.append(h("div", { class: "item" }, h("header", {}, pill("MODIFIED", "partial"), pill(m.materiality + " materiality", m.materiality === "high" ? "high" : "low"), h("span", { class: "t" }, "Clause " + m.new.clause)), h("div", { class: "hint" }, m.new.text), h("ul", {}, m.changes.map((x) => h("li", {}, x))))));
      r.change.added.forEach((a) => c.append(h("div", { class: "item" }, h("header", {}, pill("NEW", "allow"), h("span", { class: "t" }, "Clause " + a.clause)), h("div", {}, a.text))));
      r.change.removed.forEach((a) => c.append(h("div", { class: "item" }, h("header", {}, pill("REMOVED", "block"), h("span", { class: "t" }, "Clause " + a.clause)), h("div", {}, a.text))));
    }
    c.append(h("h2", {}, "Gaps created by this change"));
    r.newGaps.forEach((g) => c.append(h("div", { class: "item" }, h("header", {}, pill(g.risk.band), h("span", { class: "t" }, g.title)), h("div", { class: "hint" }, g.detail), h("div", {}, "→ " + g.remediation))));
    el.append(c);
  });
}
async function crossTab() {
  const [co, cr] = await Promise.all([api("/api/v1/contradictions"), api("/api/v1/cross-regulation")]);
  const a = clear($("#contraList")), b = clear($("#crossList"));
  if (!co.length) a.append(h("p", { class: "hint" }, "None detected."));
  co.forEach((c) => a.append(h("div", { class: "item" }, h("header", {}, pill(c.type, c.severity === "critical" ? "critical" : c.severity), h("span", { class: "hint" }, c.between.map((x) => `${x.regCode} cl.${x.clause}`).join("  ⟷  "))), h("div", {}, c.explanation), h("div", { class: "hint" }, "Resolution: " + c.resolution))));
  if (!cr.length) b.append(h("p", { class: "hint" }, "None detected."));
  cr.forEach((c) => b.append(h("div", { class: "item" }, h("header", {}, pill(c.cluster, "low"), h("span", { class: "t" }, c.regulations.join(" + ")), h("span", { class: "hint" }, c.topics.join(", "))), h("ul", {}, c.obligations.map((o) => h("li", {}, `${o.regCode} cl.${o.clause}: ${o.text}`))), h("div", { class: "hint" }, c.harmonisation + (c.reusableControls.length ? " Reuse: " + c.reusableControls.join(", ") : "")))));
}
const WI = {
  1: [{ type: "add_control", tested: true, control: { id: "C-99", title: "Marketing consent management", type: "preventive", automation: "automated", owner: "DPO", frequency: "continuous", description: "Explicit consent from data subjects is obtained before processing personal data for marketing purposes." } }],
  2: [{ type: "update_control", controlId: "C-04", frequency: "monthly", automation: "automated" }],
  3: [{ type: "change_regulation", regCode: "IN-CYBER", topic: "incident-reporting", deadlineHours: 1 }],
  4: [{ type: "remove_control", controlId: "C-01" }],
};
document.querySelectorAll("[data-wi]").forEach((b) => b.addEventListener("click", () => { $("#wiText").value = JSON.stringify(WI[b.dataset.wi], null, 2); }));
$("#wiRun").addEventListener("click", guard(async () => {
  const r = await api("/api/v1/whatif", { method: "POST", body: { changes: JSON.parse($("#wiText").value) } }); const el = clear($("#wiResult"));
  el.append(h("div", { class: "kpis" }, kpi("Score before", r.before.score + "%"), kpi("Score after", r.after.score + "%", r.deltaScore >= 0 ? "" : "bad"), kpi("Δ", (r.deltaScore > 0 ? "+" : "") + r.deltaScore), kpi("Gaps", r.before.gaps + " → " + r.after.gaps)));
  el.append(h("p", { class: "hint" }, "Applied: " + r.applied.join("; ")));
  r.gapsResolved.forEach((g) => el.append(h("div", { class: "item" }, pill("RESOLVED", "allow"), " " + g.title + " — " + g.obligation)));
  r.gapsIntroduced.forEach((g) => el.append(h("div", { class: "item" }, pill("NEW GAP", "block"), " " + g.title + " — " + g.detail)));
  r.obligationStatusShifts.forEach((s) => el.append(h("div", { class: "hint" }, `${s.from} → ${s.to}: ${s.text}`)));
}));

// ------------------------------------------------------------------ assistant / audit
$("#askBtn").addEventListener("click", guard(async () => {
  const el = clear($("#askResult"));
  try {
    const r = await api("/api/v1/assistant/ask", { method: "POST", body: { question: $("#askText").value } });
    el.append(h("div", { class: "item" }, h("div", {}, r.answer), h("p", { class: "hint" }, `provider ${r.provider} · input firewall ${r.inputFirewall.verdict} (${r.inputFirewall.riskScore}) · egress ${r.egressFirewall.allowed ? "released" : "WITHHELD"}`)));
  } catch (e) {
    if (e.data && e.data.code === "PROMPT_INJECTION_BLOCKED") { el.append(h("div", { class: "item" }, pill("BLOCKED", "block"), " " + e.message, h("div", { class: "hint" }, "Categories: " + (e.data.detail.categories || []).join(", ") + " · risk " + e.data.detail.riskScore))); } else throw e;
  }
}));
async function auditTab() {
  const [log, info] = await Promise.all([api("/api/v1/audit?limit=40"), api("/api/v1/system/info")]);
  const el = clear($("#auditList")); log.forEach((a) => el.append(h("div", { class: "step" }, h("b", {}, a.action), h("span", { class: "hint" }, `#${a.seq} ${a.ts.slice(11, 19)} ${a.actor} ${a.resource} · ${a.correlationId} · ${a.hash}`))));
  $("#sysInfo").textContent = JSON.stringify(info, null, 2);
}
$("#auditVerify").addEventListener("click", guard(async () => { const v = await api("/api/v1/audit/verify"); banner(v.valid ? `Audit chain intact: ${v.entries} entries, head ${v.headHash.slice(0, 16)}…` : `TAMPERING DETECTED at sequence ${v.brokenAtSeq}`, !v.valid); }));

const LOAD = { overview, firewall: firewallTab, gaps: gapsTab, change: changeTab, cross: crossTab, audit: auditTab };

// ------------------------------------------------------------------ connect
async function connect() {
  KEY = $("#key").value || KEY; const w = await api("/api/v1/whoami"); sessionStorage.setItem("rg_key", KEY);
  const el = $("#who"); el.className = "pill allow"; el.textContent = `${w.role} @ ${w.tenant}`; await overview();
}
$("#connect").addEventListener("click", guard(connect));
(async () => {
  if (!KEY) { try { const c = await (await fetch("/config.json")).json(); if (c.demoKey) KEY = c.demoKey; } catch (_) { /* ignore */ } }
  if (KEY) { $("#key").value = KEY; guard(connect)(); }
})();
