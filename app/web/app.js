// Malaria dashboard monitor (ONT fragment monitoring). Author: Khadim Gueye
"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => Number(n || 0).toLocaleString("en-US");

const S = {
  catalog: [], selected: new Set(), groupBy: "category", filter: "All", search: "", settings: {}, defaults: {},
  platform: null, setupSeen: false,
  path: "", resolved: null, running: false, state: null, resultsVersion: -1, results: null,
  tab: "overview", covMetric: "depth", scale: "linear", updateShown: false, browsePath: null, roots: [],
};

const PANEL_ORDER = ["IGH", "NOMADS8", "NOMADS16", "NOMADS-MVP"];
const CAT_CLASS = { "Drug resistance": "cat-drug", "Diversity": "cat-div", "Deletion target": "cat-del", "Deletion flank": "cat-flank" };
const STATUS_LABEL = { detected: "Detected", low: "Below target", possible_deletion: "Possible deletion", insufficient: "Not enough data" };
const PANEL_SHORT = { IGH: "IGH", NOMADS8: "N8", NOMADS16: "N16", "NOMADS-MVP": "MVP" };

async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `Request failed (${r.status})`);
  return data;
}

function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.textContent = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), kind === "err" ? 7000 : 3500);
}

function show(id, on = true) { $("#" + id).hidden = !on; }

function confirmBox(title, text, yes = "OK") {
  return new Promise((resolve) => {
    $("#confirmTitle").textContent = title;
    $("#confirmText").textContent = text;
    $("#confirmYes").textContent = yes;
    show("confirmOverlay");
    const done = (v) => { show("confirmOverlay", false); resolve(v); };
    $("#confirmYes").onclick = () => done(true);
    $("#confirmNo").onclick = () => done(false);
  });
}

/* ---------- Theme ---------- */
function isDark() {
  const t = document.documentElement.dataset.theme;
  return t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
}
function css(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }
$("#themeBtn").onclick = () => {
  const next = isDark() ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("theme", next); } catch (e) {}
  renderResults(true);
};
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => renderResults(true));

/* ---------- Menu ---------- */
$("#menuBtn").onclick = (e) => { e.stopPropagation(); $("#menu").hidden = !$("#menu").hidden; };
document.addEventListener("click", () => ($("#menu").hidden = true));
$("#menu").onclick = async (e) => {
  const a = e.target.dataset.action;
  if (a === "open-results") openFolder();
  if (a === "check-update") {
    toast("Checking for updates...");
    try { S.updateShown = false; renderUpdate(await api("/api/check-update", {}), true); } catch (e) { toast(e.message, "err"); }
  }
  if (a === "about") toast(`ONT Fragment Monitoring Dashboard ${$("#verText").textContent}, by Khadim Gueye.`);
  if (a === "quit") {
    const msg = S.running ? "Monitoring is running and will be stopped. Close the dashboard?" : "Close the dashboard? Double-click the launcher to open it again.";
    if (await confirmBox("Close the dashboard", msg, "Close")) {
      S.closed = true;
      await api("/api/quit", {}).catch(() => {});
      document.body.innerHTML = '<div class="empty" style="margin:40px"><p>The dashboard is closed. You can close this tab.</p></div>';
    }
  }
};
async function openFolder() { try { await api("/api/open-folder", {}); } catch (e) { toast(e.message, "err"); } }
$("#openOutBtn").onclick = openFolder;

/* ---------- Init ---------- */
async function init() {
  const d = await api("/api/init");
  S.catalog = d.catalog;
  S.defaults = d.defaults;
  S.roots = d.roots;
  $("#verText").textContent = "v" + d.version;
  const p = d.prefs || {};
  // Only the settings changed by the user are kept, so new defaults reach everyone.
  // Preferences saved before version 3.0.1 held every setting: their CPU values are dropped once.
  S.custom = { ...(p.settings || {}) };
  if (p.settings_v !== 2) { delete S.custom.threads; delete S.custom.parallel; }
  for (const k of Object.keys(S.custom)) if (S.custom[k] === d.defaults[k]) delete S.custom[k];
  S.settings = { ...d.defaults, ...S.custom };
  const known = new Set(S.catalog.map((f) => f.id));
  const saved = (p.fragments || []).filter((id) => known.has(id));
  S.selected = new Set(saved.length ? saved : S.catalog.filter((f) => f.panel === "IGH").map((f) => f.id));
  $$("[data-setting]").forEach((el) => {
    el.value = S.settings[el.dataset.setting];
    el.onchange = () => {
      const k = el.dataset.setting, v = Number(el.value);
      S.settings[k] = v;
      if (v === S.defaults[k]) delete S.custom[k]; else S.custom[k] = v;
      savePrefs();
      if (k === "threshold") renderResults(true);
    };
  });
  if (p.fastq_pass) { $("#pathInput").value = p.fastq_pass; resolvePath(p.fastq_pass, true); }
  S.platform = d.platform;
  let g = "category";
  try { g = localStorage.getItem("groupBy") || g; } catch (e) {}
  setGroupBy(g);
  const deep = location.hash.match(/^#dashboard\/(\w+)/);
  if (deep) S.tab = deep[1];
  await pollState();
  if (deep) switchTab(deep[1]);
  setInterval(pollState, 2000);
}

let prefTimer;
function savePrefs() {
  clearTimeout(prefTimer);
  prefTimer = setTimeout(() => api("/api/prefs", { fragments: [...S.selected], settings: S.custom, settings_v: 2 }).catch(() => {}), 400);
}

/* ---------- Step 1: path ---------- */
let pathTimer;
$("#pathInput").addEventListener("input", (e) => {
  clearTimeout(pathTimer);
  pathTimer = setTimeout(() => resolvePath(e.target.value), 500);
});
async function resolvePath(value, quiet = false) {
  const box = $("#pathStatus");
  S.resolved = null;
  if (!value.trim()) { box.hidden = true; return; }
  try {
    const r = await api("/api/resolve", { path: value });
    S.resolved = r;
    box.className = "path-status ok";
    const what = r.unbarcoded ? "reads without barcodes" : `${r.barcodes} barcode${r.barcodes === 1 ? "" : "s"}`;
    box.innerHTML = `fastq_pass found, ${what}.<span class="sub">${esc(r.display)}</span>` +
      (r.note ? `<span class="sub">${esc(r.note)}</span>` : "");
  } catch (e) {
    if (quiet) { box.hidden = true; return; }
    box.className = "path-status err";
    box.textContent = e.message;
  }
  box.hidden = false;
}
$("#pickBtn").onclick = async () => {
  const btn = $("#pickBtn");
  btn.disabled = true;
  toast("A folder window is opening. It can appear behind the browser.");
  try {
    const r = await api("/api/pick-folder", {});
    if (!r.cancelled) { $("#pathInput").value = r.display; await resolvePath(r.display); }
  } catch (e) {
    toast(e.message + " Use Browse here instead.", "err");
  } finally { btn.disabled = false; }
};

/* in-app browser */
$("#browseBtn").onclick = () => {
  show("browseOverlay");
  $("#browseRoots").innerHTML = S.roots.map((r) => `<button class="chip" data-p="${esc(r.path)}">${esc(r.label)}</button>`).join("");
  $$("#browseRoots .chip").forEach((b) => (b.onclick = () => browseTo(b.dataset.p)));
  browseTo(S.resolved?.path || S.browsePath || S.roots[0]?.path || "~");
};
async function browseTo(path) {
  try {
    const d = await api("/api/ls?path=" + encodeURIComponent(path));
    S.browsePath = d.path;
    S.browseParent = d.parent;
    $("#browseCrumb").textContent = d.display;
    const icon = '<svg viewBox="0 0 24 24"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>';
    $("#browseList").innerHTML = d.entries.length
      ? d.entries.map((e) => `<li data-p="${esc(e.path)}" class="${/^(fastq_pass|barcode\d+)$/i.test(e.name) ? "hl" : ""}">${icon}${esc(e.name)}</li>`).join("")
      : '<li class="empty-dir">No sub-folders</li>';
    $$("#browseList li[data-p]").forEach((li) => (li.onclick = () => browseTo(li.dataset.p)));
    $("#browseUse").textContent = d.is_fastq_pass ? "Use this fastq_pass" : "Use this folder";
  } catch (e) { toast(e.message, "err"); }
}
$("#browseUp").onclick = () => S.browseParent && browseTo(S.browseParent);
$("#browseUse").onclick = async () => {
  show("browseOverlay", false);
  $("#pathInput").value = S.browsePath;
  await resolvePath(S.browsePath);
  if (S.resolved) $("#pathInput").value = S.resolved.display;
};
$$("[data-close]").forEach((b) => (b.onclick = () => show(b.dataset.close, false)));
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  ["browseOverlay", "customOverlay"].forEach((id) => show(id, false));
  if (!$("#confirmOverlay").hidden) $("#confirmNo").click();
});

/* ---------- Step 2: fragments ---------- */
const CATEGORIES = ["Drug resistance", "Diversity", "Diagnostic", "Vaccine", "Other"];
function catClass(c) {
  return { "Drug resistance": "cat-drug", Diversity: "cat-div", Diagnostic: "cat-del", Vaccine: "cat-vac" }[c] || "cat-other";
}
function tagStyle(key) {
  const c = COLOR[key];
  return `style="color:${c};background:color-mix(in srgb, ${c} 12%, transparent)"`;
}
const CAT_KEY = { "Drug resistance": "drug", Diversity: "div", Diagnostic: "diag", Vaccine: "vac" };
const COLOR = { drug: "#4f46e5", div: "#059669", diag: "#dc2626", vac: "#0891b2", other: "#64748b",
  p0: "#1d4ed8", p1: "#7c3aed", p2: "#c2410c", p3: "#0f766e", p4: "#be185d", p5: "#4d7c0f" };
function panelKey(p) {
  const all = [...new Set(S.catalog.map((f) => f.panel))].sort((a, b) =>
    (PANEL_ORDER.indexOf(a) + 1 || 99) - (PANEL_ORDER.indexOf(b) + 1 || 99) || a.localeCompare(b));
  return "p" + (Math.max(0, all.indexOf(p)) % 6);
}
function colorKey(g) {
  return S.groupBy === "category" ? CAT_KEY[g] || "other" : panelKey(g);
}
function groups() {
  const key = S.groupBy;
  const vals = [...new Set(S.catalog.map((f) => f[key]))];
  const order = key === "category" ? CATEGORIES : PANEL_ORDER;
  return vals.sort((a, b) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99) || a.localeCompare(b));
}
function countIn(g) {
  return g === "All" ? S.selected.size : S.catalog.filter((f) => f[S.groupBy] === g && S.selected.has(f.id)).length;
}
function matches(f) {
  const q = S.search.toLowerCase();
  return !q || `${f.name} ${f.gene} ${f.panel} ${f.category} ${f.chrom}`.toLowerCase().includes(q);
}
const EDIT_ICON = '<svg viewBox="0 0 24 24"><path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M14 6l4 4"/></svg>';
const DEL_ICON = '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>';
function shortChrom(c) { return c.replace("Pf3D7_", "chr").replace("_v3", ""); }

function renderCatalog() {
  const gs = groups();
  if (S.filter !== "All" && !gs.includes(S.filter)) S.filter = "All";
  $("#panelChips").innerHTML = ["All", ...gs].map((g) => {
    const n = countIn(g);
    const c = g === "All" ? "" : ` data-c="${colorKey(g)}"`;
    return `<button class="chip ${S.filter === g ? "active" : ""}" data-g="${esc(g)}"${c}>${esc(g)}${n ? `<span class="n">${n}</span>` : ""}</button>`;
  }).join("");
  $$("#panelChips .chip").forEach((c) => (c.onclick = () => { S.filter = c.dataset.g; renderCatalog(); }));

  const list = S.catalog.filter((f) => (S.filter === "All" || f[S.groupBy] === S.filter) && matches(f));
  const byCategory = S.groupBy === "category";
  let html = "";
  for (const g of gs) {
    const items = list.filter((f) => f[S.groupBy] === g);
    if (!items.length) continue;
    html += `<div class="frag-group-head"><span><i class="gdot" style="--c:${COLOR[colorKey(g)]}"></i>${esc(g)} <span class="hint">(${items.length})</span></span><span class="acts">
      <button data-all="${esc(g)}">Select all</button><button data-none="${esc(g)}">Clear</button></span></div>`;
    for (const f of items) {
      const tag = byCategory
        ? `<span class="cat" ${tagStyle(panelKey(f.panel))}>${esc(f.panel)}</span>`
        : `<span class="cat" ${tagStyle(CAT_KEY[f.category] || "other")}>${esc(f.category)}</span>`;
      html += `<label class="frag" title="${esc(f.gene)}${f.gene_id ? " | " + esc(f.gene_id) : ""}">
        <input type="checkbox" data-id="${esc(f.id)}" ${S.selected.has(f.id) ? "checked" : ""}>
        <span><span class="fname">${esc(f.name)}</span>${f.edited ? ' <span class="edited" title="Position changed by the user">edited</span>' : ""}
        <span class="fmeta">${esc(shortChrom(f.chrom))}:${fmt(f.start)}-${fmt(f.end)} (${fmt(f.length)} bp)</span></span>
        <span class="tools">${tag}
          <button class="edit-btn" data-edit="${esc(f.id)}" title="Change the position">${EDIT_ICON}</button>
          ${f.custom ? `<button class="edit-btn" data-del="${esc(f.id)}" title="Remove this fragment">${DEL_ICON}</button>` : ""}
        </span>
      </label>`;
    }
  }
  $("#fragList").innerHTML = html || '<div class="hint" style="padding:14px">No fragment matches the search.</div>';
  $$("#fragList input[type=checkbox]").forEach((cb) => (cb.onchange = () => {
    cb.checked ? S.selected.add(cb.dataset.id) : S.selected.delete(cb.dataset.id);
    updateSelCount(); savePrefs(); renderChipsCount();
  }));
  $$("#fragList [data-all]").forEach((b) => (b.onclick = (e) => { e.preventDefault(); bulk(b.dataset.all, true); }));
  $$("#fragList [data-none]").forEach((b) => (b.onclick = (e) => { e.preventDefault(); bulk(b.dataset.none, false); }));
  $$("#fragList [data-edit]").forEach((b) => (b.onclick = (e) => { e.preventDefault(); openFragDialog(S.catalog.find((f) => f.id === b.dataset.edit)); }));
  $$("#fragList [data-del]").forEach((b) => (b.onclick = async (e) => {
    e.preventDefault();
    if (!(await confirmBox("Remove fragment", "Remove this fragment from the list?", "Remove"))) return;
    const r = await api("/api/custom/delete", { ids: [b.dataset.del] });
    S.catalog = r.catalog; S.selected.delete(b.dataset.del); renderCatalog(); savePrefs();
  }));
  updateSelCount();
}
function renderChipsCount() {
  $$("#panelChips .chip").forEach((c) => {
    const n = countIn(c.dataset.g);
    c.innerHTML = esc(c.dataset.g) + (n ? `<span class="n">${n}</span>` : "");
  });
}
function bulk(g, on) {
  S.catalog.filter((f) => f[S.groupBy] === g && matches(f)).forEach((f) => (on ? S.selected.add(f.id) : S.selected.delete(f.id)));
  renderCatalog(); savePrefs();
}
function updateSelCount() {
  $("#selCount").textContent = `${S.selected.size} selected`;
  const hasHrp = S.catalog.some((f) => S.selected.has(f.id) && (f.gene === "hrp2" || f.gene === "hrp3"));
  $("#selCount").title = hasHrp ? "hrp2 or hrp3 is selected: the deletion screen tab will be shown." : "";
}
$("#fragSearch").addEventListener("input", (e) => { S.search = e.target.value; renderCatalog(); });
$$("#groupBy button").forEach((b) => (b.onclick = () => setGroupBy(b.dataset.v)));
function setGroupBy(v) {
  S.groupBy = v; S.filter = "All";
  $$("#groupBy button").forEach((x) => x.classList.toggle("active", x.dataset.v === v));
  try { localStorage.setItem("groupBy", v); } catch (e) {}
  renderCatalog();
}

/* add a fragment, or change the position of one */
let editing = null;
function fillChroms() {
  if ($("#cChrom").options.length) return;
  const chroms = [];
  for (let i = 1; i <= 14; i++) chroms.push(`Pf3D7_${String(i).padStart(2, "0")}_v3`);
  chroms.push("Pf3D7_API_v3", "Pf3D7_MIT_v3");
  $("#cChrom").innerHTML = chroms.map((c) => `<option value="${c}">${shortChrom(c)} (${c})</option>`).join("");
  $("#cCat").innerHTML = `<option value="auto">Automatic (from the gene name)</option>` + CATEGORIES.map((c) => `<option>${c}</option>`).join("");
}
function updateLen() {
  const s = Number($("#cStart").value), e = Number($("#cEnd").value);
  $("#cLen").value = s && e && e >= s ? `${fmt(e - s + 1)} bp` : "";
}
["cStart", "cEnd"].forEach((id) => $("#" + id).addEventListener("input", updateLen));
function openFragDialog(f) {
  fillChroms();
  editing = f || null;
  $("#customError").hidden = true;
  $("#customTitle").textContent = f ? `Change the position of ${f.name}` : "Add a fragment";
  $("#customSave").textContent = f ? "Save" : "Add";
  $("#customMode").hidden = !!f;
  $$("#customMode button").forEach((x, i) => x.classList.toggle("active", i === 0));
  $("#customForm").hidden = false;
  $("#customFile").hidden = true;
  $("#cName").value = f ? f.name : ""; $("#cName").disabled = !!f;
  $("#cPanel").value = f ? f.panel : "Custom"; $("#cPanel").disabled = !!f;
  $("#cGene").value = f ? f.gene : "";
  $("#cChrom").value = f ? f.chrom : "Pf3D7_01_v3";
  $("#cCat").value = f ? (CATEGORIES.includes(f.category) ? f.category : "Other") : "auto";
  $("#cStart").value = f ? f.start : "";
  $("#cEnd").value = f ? f.end : "";
  updateLen();
  const d = f && f.default;
  $("#cDefault").hidden = !d;
  if (d) $("#cDefault").textContent = `Default position: ${shortChrom(d.chrom)}:${fmt(d.start)}-${fmt(d.end)}.`;
  $("#customReset").hidden = !(f && f.edited);
  show("customOverlay");
}
$("#addFragBtn").onclick = () => openFragDialog(null);
$$("#customMode button").forEach((b) => (b.onclick = () => {
  $$("#customMode button").forEach((x) => x.classList.toggle("active", x === b));
  $("#customForm").hidden = b.dataset.v !== "form";
  $("#customFile").hidden = b.dataset.v !== "file";
}));
$("#customReset").onclick = async () => {
  if (!editing) return;
  const r = await api("/api/custom/delete", { ids: [editing.id] });
  S.catalog = r.catalog;
  show("customOverlay", false);
  renderCatalog();
  toast(`${editing.name}: default position restored.`, "ok");
};
$("#customSave").onclick = async () => {
  const err = $("#customError"); err.hidden = true;
  try {
    let r;
    if (!$("#customFile").hidden) {
      const file = $("#cFile").files[0];
      if (!file) throw new Error("Choose a file first.");
      r = await api("/api/custom/add", { text: await file.text(), panel: $("#cFilePanel").value || "Custom" });
    } else {
      const start = Number($("#cStart").value), end = Number($("#cEnd").value);
      if (!$("#cName").value.trim()) throw new Error("Give the fragment a name.");
      if (!start || !end || end <= start) throw new Error("Start and end are needed, and end must be greater than start.");
      r = await api("/api/custom/add", { items: [{
        name: $("#cName").value, gene: $("#cGene").value, chrom: $("#cChrom").value, panel: $("#cPanel").value,
        category: $("#cCat").value, start, end, gene_id: editing ? editing.gene_id : "" }] });
    }
    const before = new Set(S.catalog.map((f) => f.id));
    S.catalog = r.catalog;
    S.catalog.filter((f) => !before.has(f.id)).forEach((f) => S.selected.add(f.id));
    show("customOverlay", false);
    renderCatalog(); savePrefs();
    toast(editing ? `${editing.name}: new position saved.` : `${r.added} fragment${r.added === 1 ? "" : "s"} added and selected.`, "ok");
  } catch (e) { err.textContent = e.message; err.hidden = false; }
};

/* ---------- Start / stop ---------- */
$("#startBtn").onclick = async () => {
  const value = $("#pathInput").value.trim();
  if (!value) { toast("Choose the fastq_pass folder first (step 1).", "err"); $("#pathInput").focus(); return; }
  if (!S.selected.size) { toast("Select at least one fragment (step 2).", "err"); return; }
  $("#startBtn").disabled = true;
  try {
    const r = await api("/api/start", { path: value, fragments: [...S.selected], settings: S.settings });
    $("#pathInput").value = r.resolved.display;
    toast("Monitoring started.", "ok");
    pollState();
  } catch (e) { toast(e.message, "err"); }
  finally { $("#startBtn").disabled = false; }
};
$("#stopBtn").onclick = async () => {
  if (!(await confirmBox("Stop monitoring", "Stop looking for new reads? Results so far are kept and you can start again later.", "Stop"))) return;
  await api("/api/stop", {}).catch((e) => toast(e.message, "err"));
  pollState();
};
$("#refreshBtn").onclick = () => api("/api/refresh", {}).then(() => toast("Looking for new reads now.")).catch(() => {});

/* ---------- Polling ---------- */
const STATE_TEXT = { idle: "Ready", preparing: "Preparing", mapping: "Processing reads", waiting: "Monitoring", stopped: "Stopped", error: "Error" };
let polling = false;
async function pollState() {
  const forceUpdate = false;
  if (polling || S.closed) return;
  polling = true;
  try {
    const s = await api("/api/state");
    if (S.offline) { location.reload(); return; }
    S.state = s;
    S.running = s.running;
    renderSetup(s.setup);
    renderJob(s.job, s.running);
    renderUpdate(s.update, forceUpdate);
    $("#logBox").textContent = s.log.join("\n");
    if (S.tab === "log") $("#logBox").scrollTop = $("#logBox").scrollHeight;
    if (s.job.results_version !== S.resultsVersion) {
      S.resultsVersion = s.job.results_version;
      const r = await api("/api/results");
      S.results = r && r.fragments ? r : null;
      renderResults(true);
      autoFoldSidebar(S.running);
    }
  } catch (e) {
    if (!(e instanceof TypeError && /fetch/i.test(e.message))) { console.error(e); return; }
    S.offline = true;
    document.body.classList.add("offline");
    $("#stateText").textContent = "Offline";
    $("#statePill").className = "pill pill-error";
    show("offlineBar");
    show("progress", false);
    ["startBtn", "stopBtn", "pickBtn", "browseBtn"].forEach((id) => ($("#" + id).disabled = true));
  } finally { polling = false; }
}

function renderSetup(st) {
  let seen = S.setupSeen || location.hash.startsWith("#dashboard");
  try { seen = seen || sessionStorage.getItem("setupSeen") === "1"; } catch (e) {}
  const busy = !st.ready;
  show("setupOverlay", busy || !seen);
  if (!busy && seen) return;
  $$("#setupList li").forEach((li) => (li.className = st.steps[li.dataset.step] || ""));
  $("#setupTitle").textContent = busy ? "Checking the installation" : "Installation checked";
  $("#setupSub").hidden = !busy;
  show("readyBox", !busy);
  if (!busy) {
    $("#readyPlatform").textContent = S.platform ? `Running on ${S.platform.os}. Paths from this system are recognised automatically.` : "";
    show("dlProgress", false);
    $("#dlText").textContent = "";
    return;
  }
  const p = st.progress;
  show("dlProgress", !!p);
  if (p) {
    const pct = p.total ? (100 * p.done) / p.total : 0;
    $("#dlBar").style.width = pct.toFixed(1) + "%";
    $("#dlText").textContent = `Downloading the reference: ${(p.done / 1048576).toFixed(1)} MB` + (p.total ? ` of ${(p.total / 1048576).toFixed(1)} MB` : "");
  } else {
    $("#dlText").textContent = { indexing: "Indexing the reference...", checking: "Checking files..." }[st.step] || "";
  }
  $("#setupError").hidden = !st.error;
  $("#setupError").textContent = st.error ? st.error + "\n\nCheck the internet connection, then close and restart the dashboard." : "";
}

$("#readyGo").onclick = () => {
  S.setupSeen = true;
  try { sessionStorage.setItem("setupSeen", "1"); } catch (e) {}
  show("setupOverlay", false);
  S.sidebarUserSet = true;
  setSidebar(true);
  const card = $("#fragList").closest(".card");
  card.scrollIntoView({ behavior: "smooth", block: "start" });
  card.classList.add("flash-card");
  setTimeout(() => card.classList.remove("flash-card"), 1600);
  pollState();
};

/* small screens: the run setup folds away once there is something to look at */
function setSidebar(open) {
  $("#sidebar").classList.toggle("collapsed", !open);
  $("#setupToggle").setAttribute("aria-expanded", String(open));
}
$("#setupToggle").onclick = () => {
  S.sidebarUserSet = true;
  setSidebar($("#sidebar").classList.contains("collapsed"));
};
function autoFoldSidebar(running) {
  const n = S.selected.size;
  const run = S.state?.job?.fastq_display || $("#pathInput").value || "";
  const name = run.split(/[\\/]/).filter((x) => x && x !== "fastq_pass").pop() || "no run selected";
  $("#setupSummary").textContent = `${name} | ${n} fragment${n === 1 ? "" : "s"}`;
  if (S.sidebarUserSet) return;
  setSidebar(!(running || (S.results && S.results.barcodes && S.results.barcodes.length)));
}

function renderJob(job, running) {
  autoFoldSidebar(running);
  const state = job.state || "idle";
  $("#statePill").className = "pill pill-" + state;
  $("#stateText").textContent = STATE_TEXT[state] || state;
  $("#statusTitle").textContent = STATE_TEXT[state] || state;
  let msg = job.message || "";
  if (state === "waiting" && job.next_cycle_at) {
    const s = Math.max(0, Math.round(job.next_cycle_at - Date.now() / 1000));
    msg = `Up to date. Next check for new reads in ${s} s.`;
  }
  $("#statusMsg").textContent = msg;
  show("startBtn", !running);
  show("stopBtn", running);
  show("refreshBtn", running);
  show("openOutBtn", !!job.out_dir);
  $("#fragList").classList.toggle("locked", running);
  show("lockNote", running);
  $("#pathInput").disabled = running;
  $("#pickBtn").disabled = running;
  $("#browseBtn").disabled = running;
  $$("[data-setting]").forEach((el) => (el.disabled = running && el.dataset.setting !== "threshold"));

  const pr = job.progress;
  show("progress", !!pr);
  if (pr) $("#progressBar").style.width = ((100 * pr.current) / pr.total).toFixed(1) + "%";
  const meta = [];
  if (job.fastq_display) meta.push(`<span>Run <b class="path">${esc(job.fastq_display)}</b></span>`);
  if (pr) meta.push(`<span>Barcodes done <b>${pr.current} of ${pr.total}</b>${pr.running ? ` (${pr.running} running)` : ""}</span>`);
  if (job.cycle) meta.push(`<span>Check <b>#${job.cycle}</b></span>`);
  if (S.results?.updated) meta.push(`<span>Last result <b>${esc(S.results.updated.slice(11))}</b></span>`);
  $("#statusMeta").innerHTML = meta.join("");
}

function renderUpdate(u, force) {
  if (!u) return;
  if (force && u.checked && !u.available && !u.error) toast(`You have the latest version (${u.current}).`, "ok");
  if (force && u.error) toast(u.error, "err");
  if (!u.available || S.updateShown) return;
  let later = "";
  try { later = sessionStorage.getItem("updateLater"); } catch (e) {}
  if (later === u.latest && !force) return;
  S.updateShown = true;
  $("#updLatest").textContent = u.latest;
  $("#updCurrent").textContent = u.current;
  $("#updNotes").textContent = u.notes || "";
  $("#updNotes").hidden = !u.notes;
  $("#updError").hidden = true;
  show("updateOverlay");
}
$("#updLater").onclick = () => {
  try { sessionStorage.setItem("updateLater", $("#updLatest").textContent); } catch (e) {}
  show("updateOverlay", false);
};
$("#updYes").onclick = async () => {
  const btn = $("#updYes");
  btn.disabled = true; btn.textContent = "Updating...";
  try {
    if (S.running) await api("/api/stop", {});
    S.updating = true;
    await api("/api/update", {});
    btn.textContent = "Restarting...";
    const t0 = Date.now();
    const wait = async () => {
      try { await api("/api/ping"); location.reload(); }
      catch (e) { if (Date.now() - t0 < 600000) setTimeout(wait, 2000); }
    };
    setTimeout(wait, 3000);
  } catch (e) {
    $("#updError").textContent = e.message; $("#updError").hidden = false;
    btn.disabled = false; btn.textContent = "Yes, update";
  }
};

/* ---------- Tabs ---------- */
$$("#tabs .tab").forEach((t) => (t.onclick = () => switchTab(t.dataset.tab)));
function switchTab(name) {
  S.tab = name;
  $$("#tabs .tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  $$(".tab-panel").forEach((p) => p.classList.toggle("active", p.dataset.panel === name));
  renderResults(false);
  requestAnimationFrame(() => $$(`.tab-panel.active .js-plotly-plot`).forEach((el) => Plotly.Plots.resize(el)));
}

/* ---------- Charts ---------- */
const rendered = {};
function baseLayout(extra = {}) {
  const text = css("--text"), muted = css("--muted"), grid = css("--border");
  return {
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: css("--font").split(",")[0].replace(/"/g, "") + ", system-ui, sans-serif", color: text, size: 12 },
    margin: { l: 56, r: 16, t: 10, b: 70 },
    xaxis: { gridcolor: grid, linecolor: grid, tickfont: { color: muted }, automargin: true },
    yaxis: { gridcolor: grid, linecolor: grid, tickfont: { color: muted }, zerolinecolor: grid, automargin: true },
    hoverlabel: { bgcolor: css("--surface"), bordercolor: grid, font: { color: text } },
    ...extra,
  };
}
const PLOT_CFG = { responsive: true, displaylogo: false, modeBarButtonsToRemove: ["select2d", "lasso2d", "autoScale2d"], toImageButtonOptions: { format: "png", scale: 2 } };

function fragLabel(f) {
  const r = S.results;
  const dup = r.fragments.filter((x) => x.name === f.name).length > 1;
  return dup ? `${f.name} (${PANEL_SHORT[f.panel] || f.panel})` : f.name;
}
function threshold() { return Number(S.settings.threshold) || 100; }

function renderResults(force) {
  const r = S.results;
  const has = !!(r && r.barcodes && r.barcodes.length);
  show("emptyState", !has && S.tab !== "log");
  $$(".tab-panel").forEach((p) => { if (p.dataset.panel !== "log") p.style.display = has ? "" : "none"; });
  $("#delTab").hidden = !(r && r.deletion);
  if (S.tab === "deletion" && !(r && r.deletion)) return switchTab("overview");
  if (!has) return;
  const key = S.resultsVersion + "|" + isDark() + "|" + threshold() + "|" + S.covMetric + "|" + S.scale;
  if (!force && rendered[S.tab] === key) return;
  rendered[S.tab] = key;
  ({ overview: drawOverview, plate: drawPlate, fragments: drawFragments, coverage: drawCoverage, deletion: drawDeletion }[S.tab] || (() => {}))();
}

function drawOverview() {
  const r = S.results, thr = threshold();
  const frs = r.fragments, bcs = r.barcodes;
  const z = bcs.map((bc) => frs.map((f) => Math.min((r.reads[bc][f.id] || 0) / thr, 2) / 2));
  const text = bcs.map((bc) => frs.map((f) => r.reads[bc][f.id] || 0));
  const hover = bcs.map((bc) => frs.map((f) => {
    const n = r.reads[bc][f.id] || 0;
    return `<b>${esc(bc)}</b><br>${esc(f.name)} (${esc(f.panel)})<br>${fmt(n)} reads ${n >= thr ? "(target reached)" : `(${fmt(thr - n)} more needed)`}<br>mean depth ${r.depth[bc][f.id]}x, coverage ${r.breadth[bc][f.id]}%`;
  }));
  const el = $("#heatmap");
  const h = Math.max(280, 26 * bcs.length + 150);
  // The height grows with the number of barcodes; the container is sized first so Plotly follows.
  el.style.height = h + "px";
  const roomy = (el.clientWidth || 800) / Math.max(1, frs.length) >= 30;
  Plotly.react(el, [{
    type: "heatmap", z, x: frs.map(fragLabel), y: bcs, text, customdata: hover, texttemplate: roomy && bcs.length * frs.length <= 1500 ? "%{text}" : "",
    hovertemplate: "%{customdata}<extra></extra>", zmin: 0, zmax: 1, showscale: false, xgap: 2, ygap: 2,
    colorscale: [[0, css("--low-strong")], [0.4999, css("--low-soft")], [0.5, css("--pass-soft")], [1, css("--pass-strong")]],
    textfont: { size: 11 },
  }], baseLayout({ height: h, margin: { l: 90, r: 10, t: 10, b: 110 },
    yaxis: { autorange: "reversed", tickfont: { color: css("--muted") }, automargin: true },
    xaxis: { side: "bottom", tickangle: -40, tickfont: { color: css("--muted") }, automargin: true } }), PLOT_CFG);
  el.removeAllListeners?.("plotly_click");
  el.on("plotly_click", (ev) => {
    const f = frs[ev.points[0].pointIndex[1]];
    switchTab("fragments");
    setTimeout(() => {
      const card = document.getElementById("chart-" + f.id);
      if (card) { card.scrollIntoView({ behavior: "smooth", block: "center" }); card.classList.add("flash"); setTimeout(() => card.classList.remove("flash"), 1400); }
    }, 120);
  });
}

/* plate map: fixed layout chosen by the lab, barcode01 in A1 then down the column
   (barcode02 in B1 ... barcode08 in H1, barcode09 in A2). Barcode 97 and above go on a second plate. */
function wellOf(barcode) {
  const m = /(\d+)$/.exec(barcode);
  if (!m) return null;
  const i = Number(m[1]) - 1;
  if (i < 0) return null;
  const plate = Math.floor(i / 96), k = i % 96;
  return { plate, row: k % 8, col: Math.floor(k / 8) };
}
function shortCount(n) { return n >= 10000 ? Math.round(n / 1000) + "k" : n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, "") + "k" : String(n); }
function drawPlate() {
  const r = S.results, thr = threshold(), grid = $("#plateGrid");
  $("#lgPass").textContent = `${thr} reads or more`;
  $("#lgLow").textContent = `below ${thr}`;
  $("#plateHint").textContent = "Each well is a barcode: barcode01 in A1, barcode02 in B1, down each column (barcode09 in A2). Hover a well to see its read count.";
  const placed = r.barcodes.map((bc) => ({ bc, w: wellOf(bc) })).filter((x) => x.w);
  if (!placed.length) {
    grid.innerHTML = '<div class="empty"><p>The plate map needs barcoded samples (folders named barcode01, barcode02, ...).</p></div>';
    return;
  }
  const plates = [...new Set(placed.map((x) => x.w.plate))].sort((a, b) => a - b);
  const q = ($("#plateFilter").value || "").toLowerCase();
  const frs = r.fragments.filter((f) => !q || `${f.name} ${f.gene} ${f.panel}`.toLowerCase().includes(q));
  const rows = "ABCDEFGH";
  let html = "";
  for (const f of frs) {
    for (const p of plates) {
      const cells = {};
      placed.filter((x) => x.w.plate === p).forEach((x) => (cells[x.w.row * 12 + x.w.col] = x.bc));
      let n = 0, pass = 0;
      let g = '<div class="plate"><span></span>' + Array.from({ length: 12 }, (_, c) => `<span class="lab">${c + 1}</span>`).join("");
      for (let row = 0; row < 8; row++) {
        g += `<span class="lab">${rows[row]}</span>`;
        for (let col = 0; col < 12; col++) {
          const bc = cells[row * 12 + col];
          const well = `${rows[row]}${col + 1}`;
          if (!bc) { g += `<span class="well none" data-tip="${well}: no barcode"></span>`; continue; }
          const v = r.reads[bc][f.id] || 0;
          const cls = v === 0 ? "zero" : v >= thr ? "pass" : "low";
          n++; if (v >= thr) pass++;
          g += `<span class="well ${cls}" data-tip="${well} | ${esc(bc)} | ${fmt(v)} reads">${v ? shortCount(v) : ""}</span>`;
        }
      }
      g += "</div>";
      const plateLabel = plates.length > 1 ? ` | plate ${p + 1}` : "";
      html += `<div class="plate-card"><div class="ct"><b>${esc(fragLabel(f))}</b><span>${esc(f.panel)}${plateLabel}</span></div>${g}` +
        `<div class="sub">${pass} of ${n} barcodes at ${thr} reads or more</div></div>`;
    }
  }
  grid.innerHTML = html || '<div class="hint">No fragment matches the filter.</div>';
}
(() => {
  const tip = document.createElement("div");
  tip.className = "plate-tip"; tip.hidden = true;
  document.body.appendChild(tip);
  $("#plateGrid").addEventListener("mousemove", (e) => {
    const w = e.target.closest(".well");
    if (!w) { tip.hidden = true; return; }
    tip.textContent = w.dataset.tip;
    tip.hidden = false;
    const x = Math.min(e.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
    tip.style.left = x + "px"; tip.style.top = (e.clientY + 14) + "px";
  });
  $("#plateGrid").addEventListener("mouseleave", () => (tip.hidden = true));
  $("#plateGrid").addEventListener("click", (e) => {
    const w = e.target.closest(".well");
    if (w) toast(w.dataset.tip);
  });
})();
$("#plateFilter").addEventListener("input", () => renderResults(true));

function drawFragments() {
  const r = S.results, thr = threshold(), grid = $("#chartGrid");
  const q = ($("#chartFilter").value || "").toLowerCase();
  const frs = r.fragments.filter((f) => !q || `${f.name} ${f.gene} ${f.panel}`.toLowerCase().includes(q));
  const ids = new Set(frs.map((f) => f.id));
  $$(".chart-card", grid).forEach((c) => { if (!ids.has(c.dataset.id)) c.remove(); });
  frs.forEach((f, i) => {
    let card = document.getElementById("chart-" + f.id);
    if (!card) {
      card = document.createElement("div");
      card.className = "chart-card"; card.id = "chart-" + f.id; card.dataset.id = f.id;
      card.innerHTML = `<div class="ct"><b>${esc(fragLabel(f))}</b><span>${esc(f.panel)} | ${esc(f.chrom.replace("Pf3D7_", "chr").replace("_v3", ""))}:${fmt(f.start)}-${fmt(f.end)}</span></div><div class="plot"></div>`;
    }
    if (grid.children[i] !== card) grid.insertBefore(card, grid.children[i] || null);
    const y = r.barcodes.map((bc) => r.reads[bc][f.id] || 0);
    const colors = y.map((v) => (v >= thr ? css("--pass-strong") : css("--bad")));
    const log = S.scale === "log";
    Plotly.react($(".plot", card), [{
      type: "bar", x: r.barcodes, y: log ? y.map((v) => Math.max(v, 0.9)) : y, marker: { color: colors, line: { width: 0 } },
      customdata: y, hovertemplate: "<b>%{x}</b><br>%{customdata:,} reads<extra></extra>",
    }], baseLayout({
      height: 260, bargap: 0.25, margin: { l: 50, r: 10, t: 8, b: 60 },
      yaxis: { title: { text: "Reads", font: { size: 11, color: css("--muted") } }, type: log ? "log" : "linear", gridcolor: css("--border"), tickfont: { color: css("--muted") }, rangemode: "tozero" },
      xaxis: { tickangle: -45, tickfont: { color: css("--muted"), size: 10 } },
      shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: thr, y1: thr, line: { color: css("--bad"), width: 1.5, dash: "dash" } }],
      annotations: [{ xref: "paper", x: 1, y: log ? Math.log10(thr) : thr, yanchor: "bottom", xanchor: "right", text: `target ${thr}`, showarrow: false, font: { size: 10, color: css("--bad") } }],
    }), { ...PLOT_CFG, displayModeBar: false });
  });
}
$("#chartFilter").addEventListener("input", () => { rendered.fragments = null; renderResults(true); });
$$("#chartScale button").forEach((b) => (b.onclick = () => {
  S.scale = b.dataset.v; $$("#chartScale button").forEach((x) => x.classList.toggle("active", x === b)); renderResults(true);
}));

function drawCoverage() {
  const r = S.results, frs = r.fragments, bcs = r.barcodes;
  const depth = S.covMetric === "depth";
  const minD = r.settings.min_depth;
  $("#covTitle").textContent = depth ? "Mean depth" : `Coverage (bases with depth of ${minD} or more)`;
  $("#covHint").textContent = depth ? "Average number of reads over each base of the fragment." : `Percentage of the fragment covered by at least ${minD} reads.`;
  const src = depth ? r.depth : r.breadth;
  const z = bcs.map((bc) => frs.map((f) => src[bc][f.id] || 0));
  const zmax = depth ? Math.max(threshold(), ...z.flat()) : 100;
  $("#covHeatmap").style.height = Math.max(280, 26 * bcs.length + 150) + "px";
  Plotly.react($("#covHeatmap"), [{
    type: "heatmap", z, x: frs.map(fragLabel), y: bcs, zmin: 0, zmax,
    texttemplate: bcs.length * frs.length <= 1500 ? (depth ? "%{z:.0f}" : "%{z:.0f}%") : "", textfont: { size: 10 },
    hovertemplate: `<b>%{y}</b><br>%{x}<br>${depth ? "mean depth %{z:.1f}x" : "coverage %{z:.1f}%"}<extra></extra>`,
    colorscale: [[0, isDark() ? "#1f2937" : "#f1f5f9"], [0.5, "#7dd3fc"], [1, isDark() ? "#2563eb" : "#1e3a8a"]],
    colorbar: { thickness: 10, outlinewidth: 0, tickfont: { color: css("--muted") }, title: { text: depth ? "x" : "%", font: { color: css("--muted") } } },
    xgap: 2, ygap: 2,
  }], baseLayout({ height: Math.max(280, 26 * bcs.length + 150), margin: { l: 90, r: 10, t: 10, b: 110 },
    yaxis: { autorange: "reversed", tickfont: { color: css("--muted") }, automargin: true },
    xaxis: { tickangle: -40, tickfont: { color: css("--muted") }, automargin: true } }), PLOT_CFG);

  const fsel = $("#profFrag"), bsel = $("#profBc");
  const fv = fsel.value, bv = bsel.value;
  fsel.innerHTML = frs.map((f) => `<option value="${esc(f.id)}">${esc(fragLabel(f))} (${esc(f.panel)})</option>`).join("");
  bsel.innerHTML = `<option value="">All barcodes</option>` + bcs.map((b) => `<option>${esc(b)}</option>`).join("");
  if (frs.some((f) => f.id === fv)) fsel.value = fv;
  if (bcs.includes(bv)) bsel.value = bv;
  drawProfile();
}
function drawProfile() {
  const r = S.results; if (!r) return;
  const fid = $("#profFrag").value, only = $("#profBc").value;
  const p = r.profiles[fid]; if (!p) return;
  const bcs = only ? [only] : r.barcodes;
  const palette = ["#2563eb", "#0ea5e9", "#14b8a6", "#22c55e", "#eab308", "#f97316", "#ef4444", "#ec4899", "#a855f7", "#6366f1", "#64748b", "#0f766e"];
  const traces = bcs.map((bc, i) => ({
    type: "scatter", mode: "lines", name: bc, x: p.x, y: p.y[bc] || [], line: { width: only ? 2.5 : 1.5, color: palette[i % palette.length], shape: "spline", smoothing: 0.4 },
    fill: only ? "tozeroy" : "none", hovertemplate: `<b>${esc(bc)}</b><br>position %{x:,}<br>depth %{y:,}<extra></extra>`,
  }));
  const minD = r.settings.min_depth;
  Plotly.react($("#profile"), traces, baseLayout({
    height: 340, margin: { l: 60, r: 10, t: 10, b: 50 }, showlegend: bcs.length <= 24, legend: { font: { size: 10, color: css("--muted") } },
    xaxis: { title: { text: "Position on the chromosome", font: { size: 11, color: css("--muted") } }, gridcolor: css("--border"), tickfont: { color: css("--muted") }, tickformat: "," },
    yaxis: { title: { text: "Depth", font: { size: 11, color: css("--muted") } }, gridcolor: css("--border"), tickfont: { color: css("--muted") }, rangemode: "tozero" },
    shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: minD, y1: minD, line: { color: css("--warn"), width: 1, dash: "dot" } }],
  }), PLOT_CFG);
}
$("#profFrag").onchange = drawProfile;
$("#profBc").onchange = drawProfile;
$$("#covMetric button").forEach((b) => (b.onclick = () => {
  S.covMetric = b.dataset.v; $$("#covMetric button").forEach((x) => x.classList.toggle("active", x === b)); renderResults(true);
}));

function drawDeletion() {
  const r = S.results, d = r.deletion; if (!d) return;
  const thr = r.settings.threshold;
  $("#delHint").textContent =
    `A gene is Detected when it has at least ${thr} reads. Possible deletion means the other fragments of the barcode reached ${thr} reads (median) ` +
    `while the gene has less than ${Math.round(d.ratio * 100)}% of that median. These rules are a monitoring convention of this dashboard, not a published ` +
    `deletion call: confirm a possible deletion with the lab's validated method.` + (d.controls ? "" : " No other fragment is selected, so deletions cannot be suggested.");
  $("#delGrid").innerHTML = r.barcodes.map((bc) => {
    const row = d.rows[bc];
    return `<div class="del-card"><div class="bc">${esc(bc)}<small>others: ${row.control_median == null ? "n/a" : fmt(Math.round(row.control_median))} reads</small></div>` +
      d.genes.map((g) => {
        const x = row[g];
        return `<div class="del-row"><span class="g">${g}</span><span class="st st-${x.status}">${STATUS_LABEL[x.status]}</span>` +
          `<span class="nums">${fmt(x.reads)} reads<br>${x.depth}x, ${x.breadth}%</span></div>`;
      }).join("") + "</div>";
  }).join("");
  const colors = { hrp2: "#2563eb", hrp3: "#f97316" };
  const traces = d.genes.map((g) => ({
    type: "bar", name: g, x: r.barcodes, y: r.barcodes.map((bc) => d.rows[bc][g].ratio ?? 0), marker: { color: colors[g] },
    hovertemplate: `<b>%{x}</b><br>${g}: %{y:.2f} of the median of the other fragments<extra></extra>`,
  }));
  Plotly.react($("#delChart"), traces, baseLayout({
    height: 320, barmode: "group", margin: { l: 56, r: 10, t: 10, b: 70 }, legend: { orientation: "h", y: 1.12, font: { color: css("--muted") } },
    yaxis: { title: { text: "Ratio to other fragments", font: { size: 11, color: css("--muted") } }, gridcolor: css("--border"), tickfont: { color: css("--muted") }, rangemode: "tozero" },
    xaxis: { tickangle: -45, tickfont: { color: css("--muted"), size: 10 } },
    shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: d.ratio, y1: d.ratio, line: { color: css("--bad"), width: 1.5, dash: "dash" } }],
  }), PLOT_CFG);
}

/* closing the dashboard window closes the application (a reload does not, see server.py) */
window.addEventListener("pagehide", () => {
  if (S.closed || S.updating) return;
  try {
    fetch("/api/closing", { method: "POST", keepalive: true, headers: { "Content-Type": "application/json" }, body: "{}" });
  } catch (e) {}
});

let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => $$(".tab-panel.active .js-plotly-plot").forEach((el) => Plotly.Plots.resize(el)), 150);
});

if (typeof Plotly === "undefined") {
  const s = document.createElement("script");
  s.src = "https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js";
  s.onload = init;
  document.body.appendChild(s);
} else {
  init();
}
