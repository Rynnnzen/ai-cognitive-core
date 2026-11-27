/* ---------------------------------------------------------------------------
 * Agent Memory Dashboard — app.js
 *
 * Single-page frontend for the ai_cognitive_core dashboard.
 * Talks to the FastAPI backend:
 *   GET  /api/status           cognitive status + Drive sync info
 *   GET  /api/graph            episode / entity graph
 *   GET  /api/memories         list of Markdown memory files
 *   GET  /api/memory?path=...  one memory file
 *   PUT  /api/memory           save a memory file
 *
 * When the backend is unreachable (e.g. plain `python -m http.server`
 * while developing the UI), inline mock data with the same shapes is
 * used instead so the page still renders.
 * ------------------------------------------------------------------------ */
"use strict";

/* ------------------------------------------------------------------ mock data
 * Same shapes as the real API responses. Used only as a fallback when a
 * fetch fails (local static-server testing, backend not running yet). */
const MOCK_STATUS = {
  core_version: "0.6.1",
  energy: 0.42,
  neuro: {
    cortisol: 0.001,
    oxytocin: 0.93,
    dopamine: 0.84,
    serotonin: 0.72,
    noradrenaline: 0.35,
  },
  pad_current: { P: 0.85, A: -0.23, D: 0.43 },
  pad_magnitude: 0.9,
  mood_intensity: "intense",
  emotional_nuance: "Drowsy",
  pad_trajectory: { direction: "steady", dp: 0.09, da: 0.06, dd: 0.03 },
  high_pleasure_streak: 3,
  circadian: { local_hour: 2, phase: "late_night" },
  heartbeat: { summary: "Detak terakhir: tenang, energi stabil di malam hari." },
  drive_last_sync: {
    last_sync_utc: "2026-11-27T18:49:40+00:00",
    ago_seconds: 1234,
    ago_human: "20 menit lalu",
    connected: true,
  },
  relationship: { trust_score: 1.0, stage: "deep_bond" },
  total_turns: 2425,
};

const MOCK_GRAPH = {
  nodes: [
    { id: "ep_abc", label: "Obrolan malam", type: "episode", emotion: "Exuberant", weight: 1.0, created: "2026-11-28T01:00:00+00:00" },
    { id: "ep_def", label: "Foto kenangan", type: "episode", emotion: "Relaxed", weight: 0.8, created: "2026-11-28T01:30:00+00:00" },
    { id: "ep_ghi", label: "Tugas builder", type: "episode", emotion: "Anxious", weight: 0.6, created: "2026-11-28T01:06:00+00:00" },
    { id: "ent_user", label: "user", type: "entity", emotion: "Dependent", weight: 1.5, created: "2026-11-13T00:00:00+00:00" },
    { id: "ent_agent", label: "agent", type: "entity", emotion: "Protective", weight: 1.4, created: "2026-11-13T00:00:00+00:00" },
  ],
  edges: [
    { from: "ep_abc", to: "ent_user", label: "mentions" },
    { from: "ep_abc", to: "ent_agent", label: "mentions" },
    { from: "ep_def", to: "ent_user", label: "mentions" },
    { from: "ep_ghi", to: "ent_agent", label: "mentions" },
  ],
};

const MOCK_MEMORIES = {
  memories: [
    { path: "MEMORY.md", title: "MEMORY.md", modified: "2026-11-28T01:19:00+00:00", size: 50910 },
    { path: "memory/2026-11-27.md", title: "2026-11-27.md", modified: "2026-11-27T06:45:00+00:00", size: 146863 },
    { path: "memory/2026-11-26.md", title: "2026-11-26.md", modified: "2026-11-26T00:01:00+00:00", size: 171075 },
  ],
};

const MOCK_MEMORY_CONTENT = {
  "MEMORY.md":
    "# MEMORY.md\\n\\nCatatan jangka panjang agent tentang user.\\n\\n- Ulang tahun user: 16 November.\\n- Gaya default agent saat ini: **Kasual**.\\n- Rencana liburan: Desember 2026, Tokyo.\\n",
  "memory/2026-11-27.md":
    "# 2026-11-27\\n\\nHari yang panjang: tugas analisis selesai, builder mulai jalan.\\n",
  "memory/2026-11-26.md":
    "# 2026-11-26\\n\\nServer baru jadi rumah pipeline. Semua model terverifikasi.\\n",
};

/* ------------------------------------------------------------- emotion colors
 * Map each mood octant / emotional nuance to a crayon color.
 * Hex values match the CSS palette so legend swatches line up. */
const EMOTION_COLORS = {
  Exuberant: "#ff6b9d",
  Euphoric: "#ff6b9d",
  Relaxed: "#34c77b",
  Docile: "#22b8cf",
  Bored: "#a78bfa",
  Depressed: "#8b5cf6",
  Disdainful: "#fb923c",
  Hostile: "#ef5350",
  Anxious: "#f5b90d",
  Dependent: "#f9a8d4",
  Drowsy: "#67e8f9",
  Teasing: "#fb923c",
  Protective: "#34c77b",
};

const DEFAULT_NODE_COLOR = "#22b8cf";

const NEURO_META = [
  { key: "cortisol", label: "Kortisol", colorClass: "orange" },
  { key: "oxytocin", label: "Oksitosin", colorClass: "pink" },
  { key: "dopamine", label: "Dopamin", colorClass: "yellow" },
  { key: "serotonin", label: "Serotonin", colorClass: "cyan" },
  { key: "noradrenaline", label: "Noradrenalin", colorClass: "purple" },
];

const CIRCADIAN_LABELS = {
  late_night: "Larut malam",
  morning: "Pagi",
  afternoon: "Siang",
  evening: "Sore",
  night: "Malam",
};

/* ------------------------------------------------------------------- state */
let currentMemoryPath = null; // path of the file currently open in the reader
let currentMemoryContent = ""; // last loaded content (used by the editor)
let isEditing = false;
let graphNetwork = null;
let graphNodes = null; // vis DataSet, kept for the click detail panel

/* ------------------------------------------------------------------ helpers */
function $(selector) {
  return document.querySelector(selector);
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function showToast(message, isError) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.toggle("error", Boolean(isError));
  toast.classList.add("show");
  window.clearTimeout(showToast._timer);
  showToast._timer = window.setTimeout(() => toast.classList.remove("show"), 3200);
}

/** Fetch JSON from the API; fall back to the given mock payload on failure. */
async function fetchJson(url, mockPayload, options) {
  try {
    const response = await fetch(url, options);
    if (!response.ok) {
      throw new Error("HTTP " + response.status);
    }
    return await response.json();
  } catch (error) {
    console.warn("API unavailable (" + url + "), using mock data:", error);
    return mockPayload;
  }
}

function formatBytes(size) {
  if (size == null) return "";
  if (size < 1024) return size + " B";
  if (size < 1024 * 1024) return (size / 1024).toFixed(1) + " KB";
  return (size / (1024 * 1024)).toFixed(1) + " MB";
}

function formatDate(isoString) {
  if (!isoString) return "–";
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return isoString;
  return date.toLocaleString("id-ID", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/* ------------------------------------------------------------- status bar */
function renderStatus(status) {
  // Mood chips: nuance + intensity + trajectory + streak.
  const chips = $("#mood-chips");
  const nuanceColor =
    EMOTION_COLORS[status.emotional_nuance] || DEFAULT_NODE_COLOR;
  chips.innerHTML = "";
  const chipDefs = [
    { text: status.emotional_nuance || "–", style: "background:" + nuanceColor + "33; border-color:" + nuanceColor },
    { text: "Intensitas: " + (status.mood_intensity || "–"), cls: "plain" },
    { text: "Arah: " + (status.pad_trajectory && status.pad_trajectory.direction ? status.pad_trajectory.direction : "–"), cls: "plain" },
    { text: "🔥 " + (status.high_pleasure_streak || 0) + " streak", cls: "plain" },
  ];
  chipDefs.forEach((def) => {
    const chip = document.createElement("span");
    chip.className = "mood-chip" + (def.cls ? " " + def.cls : "");
    chip.textContent = def.text;
    if (def.style) chip.setAttribute("style", def.style);
    chips.appendChild(chip);
  });

  // Meta line: PAD magnitude, turns, relationship.
  const meta = $("#status-meta");
  const magnitude =
    status.pad_magnitude != null ? Number(status.pad_magnitude).toFixed(2) : "–";
  const trust =
    status.relationship && status.relationship.trust_score != null
      ? status.relationship.trust_score
      : "–";
  const stage =
    status.relationship && status.relationship.stage
      ? status.relationship.stage
      : "–";
  meta.innerHTML =
    "Magnitudo PAD: <strong>" + magnitude + "</strong> · " +
    "Total turn: <strong>" + (status.total_turns || "–") + "</strong> · " +
    "Kepercayaan: <strong>" + trust + "</strong> · " +
    "Tahap: <strong>" + escapeHtml(stage) + "</strong>";

  // Energy bar.
  const energy = status.energy != null ? Number(status.energy) : 0;
  $("#energy-bar").style.width = Math.round(energy * 100) + "%";
  $("#energy-value").textContent = energy.toFixed(2);

  // Circadian phase.
  const circadian = status.circadian || {};
  const phaseLabel = CIRCADIAN_LABELS[circadian.phase] || circadian.phase || "–";
  $("#circadian-text").innerHTML =
    "Fase sirkadian: <strong>" + escapeHtml(phaseLabel) + "</strong>" +
    (circadian.local_hour != null ? " · jam lokal " + circadian.local_hour + ":00" : "");

  // Heartbeat summary.
  const heartbeat = status.heartbeat && status.heartbeat.summary
    ? status.heartbeat.summary
    : "Tidak ada ringkasan heartbeat.";
  $("#heartbeat-box").textContent = heartbeat;

  // Neurochemical bars (values are 0..1).
  NEURO_META.forEach((item) => {
    const value = status.neuro && status.neuro[item.key] != null
      ? Number(status.neuro[item.key])
      : 0;
    const fill = document.querySelector('[data-neuro="' + item.key + '"]');
    const valueEl = document.querySelector('[data-neuro-value="' + item.key + '"]');
    if (fill) fill.style.width = Math.round(value * 100) + "%";
    if (valueEl) valueEl.textContent = value.toFixed(2);
  });

  // PAD bars (values are roughly -1..1; map to 0..100% for the bar).
  ["P", "A", "D"].forEach((axis) => {
    const value = status.pad_current && status.pad_current[axis] != null
      ? Number(status.pad_current[axis])
      : 0;
    const fill = document.querySelector('[data-pad="' + axis + '"]');
    const valueEl = document.querySelector('[data-pad-value="' + axis + '"]');
    if (fill) fill.style.width = Math.round(((value + 1) / 2) * 100) + "%";
    if (valueEl) valueEl.textContent = value.toFixed(2);
  });

  // Drive last-sync badge.
  renderDriveBadge(status.drive_last_sync);

  // Footer version.
  if (status.core_version) {
    $("#footer-version").textContent = "ai_cognitive_core v" + status.core_version;
  }
}

function renderDriveBadge(sync) {
  const badge = $("#drive-sync-badge");
  const text = $("#drive-sync-text");
  if (!sync) {
    badge.className = "badge off";
    text.textContent = "Sinkronisasi Drive: tidak diketahui";
    return;
  }
  if (!sync.connected) {
    badge.className = "badge off";
    text.textContent = "Drive: tidak terhubung";
    return;
  }
  const ago = sync.ago_human || "";
  // Fresh (< 1 hour) = green, stale = amber.
  const fresh = sync.ago_seconds == null || sync.ago_seconds < 3600;
  badge.className = "badge " + (fresh ? "ok" : "stale");
  text.textContent = "Drive tersinkron" + (ago ? " · " + ago : "");
}

async function loadStatus() {
  const status = await fetchJson("/api/status", MOCK_STATUS);
  renderStatus(status);
}

/* ------------------------------------------------------------- memory graph */
function nodeColorFor(emotion) {
  return EMOTION_COLORS[emotion] || DEFAULT_NODE_COLOR;
}

/** Node size scales with weight (memory retention), clamped to a sane range. */
function nodeSizeFor(weight) {
  const w = weight != null ? Number(weight) : 1;
  return Math.max(14, Math.min(42, 12 + w * 14));
}

function buildLegend() {
  const legend = $("#graph-legend");
  legend.innerHTML = "";
  const seen = new Set();
  Object.entries(EMOTION_COLORS).forEach(([emotion, color]) => {
    if (seen.has(color)) return;
    seen.add(color);
    const item = document.createElement("span");
    item.className = "legend-item";
    const swatch = document.createElement("span");
    swatch.className = "legend-swatch";
    swatch.style.background = color;
    item.appendChild(swatch);
    item.appendChild(document.createTextNode(emotion));
    legend.appendChild(item);
  });
}

function showNodeDetail(node) {
  const panel = $("#node-detail");
  $("#node-detail-title").textContent = node.label || node.id;
  $("#node-detail-id").textContent = node.id;
  $("#node-detail-label").textContent = node.label || "–";
  $("#node-detail-type").textContent = node.type || "–";
  $("#node-detail-emotion").textContent = node.emotion || "–";
  $("#node-detail-weight").textContent =
    node.weight != null ? Number(node.weight).toFixed(2) : "–";
  $("#node-detail-created").textContent = formatDate(node.created);
  panel.hidden = false;
}

function renderGraph(graph) {
  const container = $("#graph");
  if (typeof vis === "undefined" || !vis.Network) {
    container.innerHTML =
      '<p class="empty-state">Pustaka graf (vis-network) belum termuat. Periksa koneksi internet lalu muat ulang.</p>';
    return;
  }

  const nodes = (graph.nodes || []).map((node) => {
    const color = nodeColorFor(node.emotion);
    return {
      id: node.id,
      label: node.label || node.id,
      title: (node.label || node.id) + (node.emotion ? " · " + node.emotion : ""),
      color: { background: color, border: "#3b3129", highlight: { background: color, border: "#3b3129" } },
      size: nodeSizeFor(node.weight),
      font: { size: 13, color: "#3b3129" },
      shape: node.type === "entity" ? "diamond" : "dot",
    };
  });

  const edges = (graph.edges || []).map((edge) => ({
    from: edge.from,
    to: edge.to,
    label: edge.label || "",
    font: { size: 11, color: "#6b5d4f" },
    color: { color: "#9a8c7c" },
    arrows: "to",
  }));

  graphNodes = new vis.DataSet(nodes);
  const edgesSet = new vis.DataSet(edges);

  if (graphNetwork) {
    graphNetwork.destroy();
  }
  graphNetwork = new vis.Network(
    container,
    { nodes: graphNodes, edges: edgesSet },
    {
      physics: { stabilization: { iterations: 120 } },
      interaction: { hover: true, tooltipDelay: 150 },
      nodes: { borderWidth: 2 },
      edges: { smooth: { type: "continuous" } },
    }
  );

  // Click a node -> detail panel. Click empty space -> hide it.
  graphNetwork.on("click", (params) => {
    if (params.nodes && params.nodes.length > 0) {
      const nodeId = params.nodes[0];
      const raw = (graph.nodes || []).find((n) => n.id === nodeId);
      if (raw) showNodeDetail(raw);
    } else {
      $("#node-detail").hidden = true;
    }
  });

  buildLegend();
}

async function loadGraph() {
  const graph = await fetchJson("/api/graph", MOCK_GRAPH);
  renderGraph(graph);
}

/* ------------------------------------------------------- memories: list */
function renderMemoryList(payload) {
  const list = $("#memory-list");
  list.innerHTML = "";
  const memories = payload.memories || [];
  if (memories.length === 0) {
    const empty = document.createElement("li");
    empty.className = "empty-state";
    empty.textContent = "Belum ada file memori.";
    list.appendChild(empty);
    return;
  }
  memories.forEach((memory) => {
    const item = document.createElement("li");
    item.className = "memory-item";
    item.dataset.path = memory.path;
    const title = document.createElement("div");
    title.className = "memory-title";
    title.textContent = memory.title || memory.path;
    const meta = document.createElement("div");
    meta.className = "memory-meta";
    meta.textContent =
      formatDate(memory.modified) +
      (memory.size != null ? " · " + formatBytes(memory.size) : "");
    item.appendChild(title);
    item.appendChild(meta);
    item.addEventListener("click", () => loadMemory(memory.path));
    list.appendChild(item);
  });
}

async function loadMemories() {
  const payload = await fetchJson("/api/memories", MOCK_MEMORIES);
  renderMemoryList(payload);
}

/* ----------------------------------------------------- memories: reader/editor */
function renderMarkdownPreview(markdown) {
  const preview = $("#memory-preview");
  if (typeof marked !== "undefined" && marked.parse) {
    preview.innerHTML = marked.parse(markdown || "");
  } else {
    // Fallback when the CDN renderer is unavailable: plain preformatted text.
    preview.innerHTML = "<pre>" + escapeHtml(markdown || "") + "</pre>";
  }
}

function setEditing(editing) {
  isEditing = editing;
  const preview = $("#memory-preview");
  const editor = $("#memory-editor");
  const toggle = $("#edit-toggle");
  const save = $("#save-memory");
  if (editing) {
    editor.value = currentMemoryContent;
    editor.hidden = false;
    preview.hidden = true;
    toggle.textContent = "Batal";
    save.disabled = false;
    editor.focus();
  } else {
    editor.hidden = true;
    preview.hidden = false;
    toggle.textContent = "Ubah";
    save.disabled = true;
    renderMarkdownPreview(currentMemoryContent);
  }
}

async function loadMemory(path) {
  // Highlight the active list item.
  document.querySelectorAll(".memory-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.path === path);
  });

  const payload = await fetchJson(
    "/api/memory?path=" + encodeURIComponent(path),
    { path: path, content: MOCK_MEMORY_CONTENT[path] || "# " + path + "\n\n(konten contoh — backend belum jalan)", modified: null }
  );

  currentMemoryPath = payload.path || path;
  currentMemoryContent = payload.content || "";
  $("#reader-title").textContent = currentMemoryPath;
  $("#edit-toggle").disabled = false;
  setEditing(false);
}

async function saveMemory() {
  if (!currentMemoryPath) return;
  const saveBtn = $("#save-memory");
  saveBtn.disabled = true;
  saveBtn.textContent = "Menyimpan…";
  try {
    const response = await fetch("/api/memory", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        path: currentMemoryPath,
        content: $("#memory-editor").value,
      }),
    });
    if (!response.ok) {
      throw new Error("HTTP " + response.status);
    }
    const result = await response.json();
    currentMemoryContent = $("#memory-editor").value;
    setEditing(false);
    showToast("Memori tersimpan: " + (result.path || currentMemoryPath));
    loadMemories(); // refresh sizes / modified dates
  } catch (error) {
    console.warn("Save failed, keeping editor open:", error);
    saveBtn.disabled = false;
    showToast("Gagal menyimpan memori. Coba lagi.", true);
  } finally {
    saveBtn.textContent = "Simpan";
    if (isEditing) saveBtn.disabled = false;
  }
}

/* -------------------------------------------------------------------- boot */
function init() {
  $("#edit-toggle").addEventListener("click", () => setEditing(!isEditing));
  $("#save-memory").addEventListener("click", saveMemory);
  $("#graph-refresh").addEventListener("click", loadGraph);
  $("#memory-list-refresh").addEventListener("click", loadMemories);

  loadStatus();
  loadGraph();
  loadMemories();

  // Refresh the status bar every minute so the Drive sync badge stays fresh.
  window.setInterval(loadStatus, 60 * 1000);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
