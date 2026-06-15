// Hermes Loom — 檢視台 (Inspector). Vanilla-JS port of the Claude Design handoff,
// wired to the real Loom records API. Master–detail: left rail list + right
// provenance pipeline. No build step; reuses loom-theme.css / loom-proto.css.

// ───────────────────────── helpers ─────────────────────────
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k === "class") e.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(e.style, v);
    else if (k === "html") e.innerHTML = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    e.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return e;
};

// inline SVG icons (ported from the design's loom-data/loom-store)
const ICONS = {
  pencil: '<path d="M11 2.5l2.5 2.5L6 12.5 3 13l.5-3L11 2.5z"/>',
  spark: '<path d="M8 2l1.3 4.7L14 8l-4.7 1.3L8 14l-1.3-4.7L2 8l4.7-1.3L8 2z"/>',
  link: '<g><path d="M7 9a3 3 0 004 0l2-2a3 3 0 00-4-4l-1 1"/><path d="M9 7a3 3 0 00-4 0L3 9a3 3 0 004 4l1-1"/></g>',
  search: '<g><circle cx="7" cy="7" r="4.2"/><path d="M10.5 10.5L14 14"/></g>',
  trash: '<g><path d="M3 4.5h10M6 4.5V3h4v1.5M5 4.5l.5 8.5h5l.5-8.5"/></g>',
  undo: '<path d="M4 7h6a3 3 0 010 6H6M4 7l2.5-2.5M4 7l2.5 2.5"/>',
  filter: '<path d="M2.5 3.5h11l-4.2 5v4l-2.6 1.2v-5.2L2.5 3.5z"/>',
  sun: '<g><circle cx="8" cy="8" r="3"/><path d="M8 1v1.5M8 13.5V15M15 8h-1.5M2.5 8H1M12.7 3.3l-1 1M4.3 11.7l-1 1M12.7 12.7l-1-1M4.3 4.3l-1-1"/></g>',
  moon: '<path d="M13 9.5A5.5 5.5 0 016.5 3a5.5 5.5 0 100 11c2.5 0 4.7-1.7 5.4-4z"/>',
  pin: '<path d="M6 2h4l-.5 4 2 2.5H4.5L6.5 6 6 2zM8 8.5V14"/>',
  flow: '<g><circle cx="3.5" cy="8" r="1.8"/><circle cx="12.5" cy="3.5" r="1.8"/><circle cx="12.5" cy="12.5" r="1.8"/><path d="M5.3 8h2M9 4.5l1.7-.6M9 11.5l1.7.6M7.5 8c2 0 1.5-3.5 3.3-3.9M7.5 8c2 0 1.5 3.5 3.3 3.9"/></g>',
  clock: '<g><circle cx="8" cy="8" r="6"/><path d="M8 5v3l2 1.5"/></g>',
  layers: '<g><path d="M8 2l6 3-6 3-6-3 6-3z"/><path d="M2 8l6 3 6-3M2 11l6 3 6-3"/></g>',
  pack: '<g><path d="M2.5 5l5.5-3 5.5 3v6l-5.5 3-5.5-3V5z"/><path d="M2.5 5L8 8l5.5-3M8 8v6"/></g>',
  tag: '<g><path d="M2.5 2.5h5L13 8l-5 5-5.5-5.5v-5z"/><circle cx="5" cy="5" r="1" fill="currentColor" stroke="none"/></g>',
  plus: '<path d="M8 3v10M3 8h10"/>',
  check: '<path d="M3 8.5l3.2 3L13 4.5"/>',
  x: '<path d="M4 4l8 8M12 4l-8 8"/>',
  note: '<g><path d="M3 3.5h10v6l-3 3H3v-9z"/><path d="M13 9.5h-3v3"/></g>',
  dots: '<circle cx="3.5" cy="8" r="1.3"/><circle cx="8" cy="8" r="1.3"/><circle cx="12.5" cy="8" r="1.3"/>',
  globe: '<g><circle cx="8" cy="8" r="6"/><ellipse cx="8" cy="8" rx="2.6" ry="6"/><path d="M2 8h12"/></g>',
};
function icon(name, { s = 13, color, w = 1.5 } = {}) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("width", s); svg.setAttribute("height", s);
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("fill", name === "dots" ? "currentColor" : "none");
  if (name !== "dots") {
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", w);
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
  }
  svg.style.flex = "0 0 auto";
  if (color) svg.style.color = color;
  svg.innerHTML = ICONS[name] || "";
  return svg;
}

const api = {
  async get(p) {
    const r = await fetch("/api" + p);
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
    return r.json();
  },
  async post(p, body) {
    const r = await fetch("/api" + p, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok || d.ok === false) throw new Error(d.error || r.statusText);
    return d;
  },
};

// ───────────────────────── char-level diff ─────────────────────────
function loomDiff(a, b) {
  a = a || ""; b = b || "";
  const n = a.length, m = b.length;
  const dp = Array.from({ length: n + 1 }, () => new Int32Array(m + 1));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const raw = []; let i = 0, j = 0;
  const push = (t, s) => { const l = raw[raw.length - 1]; if (l && l.t === t) l.s += s; else raw.push({ t, s }); };
  while (i < n && j < m) {
    if (a[i] === b[j]) { push("eq", a[i]); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) push("del", a[i++]);
    else push("add", b[j++]);
  }
  while (i < n) push("del", a[i++]);
  while (j < m) push("add", b[j++]);
  return raw;
}
function diffEl(a, b) {
  return el("span", { class: "di" },
    ...loomDiff(a, b).map((p) => el("span", { class: "di-" + p.t }, p.s)));
}

// ───────────────────────── line-level diff ─────────────────────────
// LCS over whole lines — the right granularity for a full SKILL.md. Cheap
// enough for real files (line counts, not char counts), so no DIFF_MAX guard.
function lineDiff(a, b) {
  const A = (a || "").split("\n"), B = (b || "").split("\n");
  const n = A.length, m = B.length;
  const dp = Array.from({ length: n + 1 }, () => new Int32Array(m + 1));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out = []; let i = 0, j = 0;
  while (i < n && j < m) {
    if (A[i] === B[j]) { out.push({ t: "eq", s: A[i] }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) out.push({ t: "del", s: A[i++] });
    else out.push({ t: "add", s: B[j++] });
  }
  while (i < n) out.push({ t: "del", s: A[i++] });
  while (j < m) out.push({ t: "add", s: B[j++] });
  return out;
}
function lineDiffEl(a, b) {
  const runs = lineDiff(a, b);
  const mark = { eq: "", del: "−", add: "+" };
  if (!runs.some((p) => p.t !== "eq"))
    return el("div", { class: "loom-meta", style: { padding: "10px 12px" } }, tr("diff.identical"));
  return el("div", { class: "loom-diff" },
    ...runs.map((p) => el("div", p.t === "eq" ? {} : { class: p.t },
      el("span", { class: "mk" }, mark[p.t]),
      el("span", { style: { whiteSpace: "pre-wrap", wordBreak: "break-word" } }, p.s || " "))));
}

// ───────────────────────── state ─────────────────────────
const S = {
  records: [], cats: [], selId: null, skillSummary: null,
  filter: "all", query: "", humanOnly: false,
  toasts: [], mode: null, draft: "", menuOpen: false,
  view: "inspector", soul: null,
  promptList: [], promptSel: null,
  packs: [], packSel: null,
};
const D = {}; // persistent DOM refs

// i18n (i18n.js is loaded first). tr()/relTime() read the current language live,
// so a language switch is a pure re-render — see the header toggle. Named `tr`
// (not `t`) because `t` is used pervasively here as a loop variable (tags/toasts).
const tr = window.LoomI18n.t;
const relTime = window.LoomI18n.relTime;

const DIFF_MAX = 4000; // skip live char-diff above this (O(n·m) LCS would hang)
const fmtTime = (ts) => ts ? new Date(ts * 1000).toLocaleString() : tr("common.dash");
const catLabel = (k) => tr("cat." + k);
// Backend sends display text as i18n keys + params; render them here.
const detailText = (r) => r.detailKey ? tr(r.detailKey, r.detailParams) : "";
const whenText = (r) => relTime(r.whenTs) || tr("common.dash");
const activeValue = (r) => r.versions[r.active].value;
const isTouched = (r) => r.versions.some((v) => v.kind === "human") || !!r.annotation || !!r.reclassified;
const selected = () => S.records.find((r) => r.id === S.selId) || null;

// ───────────────────────── data load ─────────────────────────
async function loadRecords(prefer) {
  const data = await api.get("/records");
  S.records = data.records; S.cats = data.cats; S.skillSummary = data.skill_summary || null;
  if (prefer) {
    const m = S.records.find(prefer);
    if (m) S.selId = m.id;
  }
  if (!S.records.find((r) => r.id === S.selId)) {
    const vis = visibleRecords();
    S.selId = vis.length ? vis[0].id : (S.records[0] && S.records[0].id) || null;
  }
  renderChips(); renderRailList(); renderDetail();
  renderStats();
}

function visibleRecords() {
  const q = S.query.toLowerCase();
  return S.records
    // Only "new deposit" skills are shown. Non-agent-created skills are hidden
    // from the main list (data is NOT deleted — just filtered on metadata).
    .filter((r) => r.target_type !== "skill" || r.is_agent_created)
    .filter((r) => S.filter === "all" || r.cat === S.filter)
    .filter((r) => !S.humanOnly || isTouched(r))
    .filter((r) => !q || (activeValue(r) + detailText(r) + r.origin).toLowerCase().includes(q));
}

// ───────────────────────── toasts ─────────────────────────
let _tid = 0;
function pushToast({ tone, text, onUndo }) {
  const id = ++_tid;
  S.toasts.push({ id, tone, text, onUndo });
  renderToasts();
  setTimeout(() => { S.toasts = S.toasts.filter((t) => t.id !== id); renderToasts(); }, 6500);
}
function closeToast(id) { S.toasts = S.toasts.filter((t) => t.id !== id); renderToasts(); }
function renderToasts() {
  const host = D.toasts; host.replaceChildren();
  for (const t of S.toasts) {
    const isErr = t.tone === "err";
    const toneBg = (t.tone === "del" || isErr) ? "var(--del-soft)" : t.tone === "human" ? "var(--human-soft)" : "var(--accent-soft)";
    const toneFg = (t.tone === "del" || isErr) ? "var(--del)" : t.tone === "human" ? "var(--human)" : "var(--accent-ink)";
    const tIcon = t.tone === "del" ? "trash" : isErr ? "x" : t.tone === "undo" ? "undo" : "check";
    host.append(el("div", { class: "loom-toast" },
      el("span", { class: "ic", style: { background: toneBg, color: toneFg } }, icon(tIcon, { s: 13 })),
      el("span", {}, t.text),
      t.onUndo && el("button", { class: "undo", onclick: () => { closeToast(t.id); t.onUndo(); } }, icon("undo", { s: 12 }), tr("toast.undo")),
      el("button", { class: "loom-iconbtn", style: { width: "26px", height: "26px" }, onclick: () => closeToast(t.id) }, icon("x", { s: 12 }))));
  }
}

// ───────────────────────── mutations ─────────────────────────
// Surface any mutation failure (e.g. a stale server missing a route → 404) as a
// visible error toast instead of silently doing nothing.
function guard(fn) {
  return async (...args) => {
    try { return await fn(...args); }
    catch (e) { pushToast({ tone: "err", text: tr("toast.opFailed", { msg: (e && e.message) || e }) }); }
  };
}

const doEdit = guard(async function (r, value, { restored } = {}) {
  const prev = activeValue(r);
  if (!value || value === prev) return;
  await api.post("/records/edit", { target_type: r.target_type, target_key: r.target_key, new_value: value });
  await loadRecords((x) => x.target_type === r.target_type && activeValue(x) === value);
  pushToast({
    tone: restored ? "undo" : "human",
    text: restored ? tr("toast.restored") : tr("toast.savedNewVersion"),
    onUndo: async () => { await api.post("/records/edit", { target_type: r.target_type, target_key: entryKeyOf(value, r), new_value: prev }).catch(() => {}); await loadRecords((x) => x.target_type === r.target_type && activeValue(x) === prev); },
  });
});
// memory keys change after edit; for undo we look up the record by current value instead.
function entryKeyOf(value, r) {
  const m = S.records.find((x) => x.target_type === r.target_type && activeValue(x) === value);
  return m ? m.target_key : r.target_key;
}

const doDelete = guard(async function (r) {
  const val = activeValue(r);
  await api.post("/records/delete", { target_type: r.target_type, target_key: r.target_key });
  const canUndo = r.target_type !== "skill";
  await loadRecords();
  pushToast({
    tone: "del",
    text: tr("toast.deleted", { val: val.slice(0, 14) + (val.length > 14 ? "…" : "") }) + (canUndo ? "" : tr("toast.skillDisabledBackup")),
    onUndo: canUndo ? async () => {
      await api.post("/records/add", { store_type: r.target_type, text: val, from_store: r.from_store }).catch(() => {});
      await loadRecords((x) => x.target_type === r.target_type && activeValue(x) === val);
    } : undefined,
  });
});

const doAnnotate = guard(async function (r, text) {
  const prev = r.annotation ? r.annotation.text : "";
  await api.post("/records/annotate", { target_type: r.target_type, target_key: r.target_key, text });
  await loadRecords((x) => x.id === r.id);
  pushToast({
    tone: "human", text: text.trim() ? tr("toast.annotationAdded") : tr("toast.annotationRemoved"),
    onUndo: async () => { await api.post("/records/annotate", { target_type: r.target_type, target_key: r.target_key, text: prev }).catch(() => {}); await loadRecords((x) => x.id === r.id); },
  });
});

const doPin = guard(async function (r) {
  await api.post("/records/pin", { target_type: r.target_type, target_key: r.target_key, pinned: !r.pinned });
  await loadRecords((x) => x.id === r.id);
});

// Change category = physically move the entry. 記憶→MEMORY.md, 偏好→USER.md,
// 暫存(hold)→Loom-only (removed from all files; not compiled).
const catFile = (k) => tr("catFile." + k);
const doRecat = guard(async function (r, toCat) {
  const fromCat = r.cat;
  S.mode = null;
  const res = await api.post("/records/recategorize",
    { target_type: r.target_type, target_key: r.target_key, to_cat: toCat });
  await loadRecords((x) => x.id === res.new_id);
  pushToast({
    tone: "human",
    text: toCat === "hold"
      ? tr("toast.recatHold")
      : tr("toast.recatDone", { cat: catLabel(toCat), file: catFile(toCat) }),
    onUndo: async () => {
      await api.post("/records/recategorize",
        { target_type: res.to_target_type, target_key: res.new_key, to_cat: fromCat }).catch(() => {});
      await loadRecords((x) => x.id === r.id);
    },
  });
});

// Skill records carry only their description in the list; the full SKILL.md is
// fetched lazily on demand (and cached on the record).
function ensureSkillContent(r) {
  if (r.target_type !== "skill" || r.skill_content !== undefined) return Promise.resolve();
  r.skill_content = null; // sentinel: loading
  return api.get("/records/" + encodeURIComponent(r.id))
    .then((d) => {
      r.skill_content = (d && d.skill_content) || "";
      r.skill_versions = (d && d.skill_versions) || [];
    })
    .catch(() => { r.skill_content = ""; });
}

const doSkillEdit = guard(async function (r, newContent, oldContent) {
  if (newContent === oldContent) { S.mode = null; renderDetail(); return; }
  await api.post("/records/edit", { target_type: "skill", target_key: r.target_key, new_value: newContent });
  await loadRecords((x) => x.target_type === "skill" && x.target_key === r.target_key);
  pushToast({
    tone: "human", text: tr("toast.skillUpdated"),
    onUndo: async () => {
      await api.post("/records/edit", { target_type: "skill", target_key: r.target_key, new_value: oldContent }).catch(() => {});
      await loadRecords((x) => x.target_type === "skill" && x.target_key === r.target_key);
    },
  });
});

// ───────────────────────── atoms ─────────────────────────
function catChip(cat) {
  return el("span", { class: "loom-cat cat-" + cat }, el("span", { class: "cd" }), catLabel(cat));
}
function touchedTag(human) {
  return human
    ? el("span", { class: "loom-tag tag-human" }, icon("pencil", { s: 10 }), tr("tag.humanEdited"))
    : el("span", { class: "loom-tag tag-auto" }, icon("spark", { s: 10 }), tr("tag.autoDeposit"));
}
function conf(n) {
  return el("span", { class: "loom-conf", title: tr("conf.title", { n }) },
    ...[1, 2, 3].map((i) => el("i", { class: i <= n ? "on" : "" })));
}

// ───────────────────────── header ─────────────────────────
function buildHeader() {
  const stats = el("span", { class: "loom-meta", style: { marginRight: "4px" } });
  D.stats = stats;
  const themeBtn = el("button", { class: "loom-btn", onclick: toggleTheme });
  D.themeBtn = themeBtn; paintThemeBtn();
  const langBtn = el("button", { class: "loom-btn", title: tr("lang.switchTitle"),
    onclick: () => window.LoomI18n.toggleLang() }, icon("globe", { s: 14 }), tr("lang.name"));
  const pill = el("span", { class: "loom-pill" }, el("span", { class: "loom-dot" }), tr("status.checking"));
  D.pill = pill;
  return el("div", { class: "loom-top" },
    el("div", { class: "loom-brand" },
      el("div", { class: "loom-logo" }),
      el("div", { class: "loom-name", html: 'Hermes Loom <span class="sub">/ ' + tr("header.subtitle") + '</span>' })),
    buildNav(),
    pill,
    el("div", { class: "loom-top-spacer" }),
    stats, langBtn, themeBtn);
}

// Top-level view switcher: the Inspector (observed growth) vs the SOUL editor.
const NAV_VIEWS = [
  { k: "inspector", labelKey: "nav.inspector", icon: "flow" },
  { k: "soul", labelKey: "nav.soul", icon: "spark" },
  { k: "packs", labelKey: "nav.packs", icon: "pack" },
  { k: "prompts", labelKey: "nav.prompts", icon: "layers" },
];
function buildNav() {
  const nav = el("div", { style: { display: "flex", gap: "2px", padding: "2px", borderRadius: "8px", background: "var(--surface-2)", marginLeft: "14px" } });
  D.nav = nav;
  paintNav();
  return nav;
}
function paintNav() {
  if (!D.nav) return;
  D.nav.replaceChildren(...NAV_VIEWS.map((v) => {
    const on = S.view === v.k;
    return el("button", {
      class: "loom-btn", style: {
        height: "26px", padding: "0 11px", fontSize: "12px", border: "none",
        background: on ? "var(--surface)" : "transparent",
        color: on ? "var(--text)" : "var(--text-3)",
        boxShadow: on ? "var(--shadow-1, 0 1px 2px rgba(0,0,0,.08))" : "none",
        fontWeight: on ? "600" : "500",
      },
      onclick: () => setView(v.k),
    }, icon(v.icon, { s: 13 }), tr(v.labelKey));
  }));
}
function setView(v) {
  S.view = v;
  if (D.inspectorBody) D.inspectorBody.style.display = v === "inspector" ? "flex" : "none";
  if (D.soulBody) D.soulBody.style.display = v === "soul" ? "block" : "none";
  if (D.packsBody) D.packsBody.style.display = v === "packs" ? "flex" : "none";
  if (D.promptsBody) D.promptsBody.style.display = v === "prompts" ? "flex" : "none";
  paintNav();
  if (v === "soul") renderSoul();
  if (v === "packs") renderPacks();
  if (v === "prompts") renderPrompts();
}

// Reflect real auto-deposit status (plugin enabled + gateway running + recent hook).
const PILL_COLOR = { live: "var(--cat-fact)", enabled: "var(--human)", offline: "var(--text-4)" };
async function refreshStatus() {
  if (!D.pill) return;
  try {
    const s = await api.get("/status");
    const dot = el("span", { class: "loom-dot" + (s.state === "live" ? " loom-live" : ""), style: { background: PILL_COLOR[s.state] || "var(--text-4)" } });
    const plug = s.plugin.installed ? (s.plugin.enabled ? tr("status.pluginEnabled") : tr("status.pluginInstalledDisabled")) : tr("status.pluginNotInstalled");
    const gw = s.gateway.known ? (s.gateway.running ? tr("status.gwRunning") : tr("status.gwStopped")) : tr("status.gwUnknown");
    let tip = tr("status.pluginLabel") + plug + tr("status.gwLabel") + gw;
    tip += s.last_plugin_hook ? tr("status.lastHook", { rel: relTime(s.last_plugin_hook) }) : tr("status.noHook");
    D.pill.replaceChildren(dot, document.createTextNode(tr("status.state." + s.state)));
    D.pill.setAttribute("title", tip);
  } catch (e) {
    D.pill.replaceChildren(el("span", { class: "loom-dot", style: { background: "var(--text-4)" } }), document.createTextNode(tr("status.unknown")));
    D.pill.setAttribute("title", tr("status.fetchFailed", { msg: e.message }));
  }
}
function renderStats() {
  const live = S.records.length;
  const touched = S.records.filter(isTouched).length;
  D.stats.replaceChildren(
    document.createTextNode(tr("stats.total", { n: live })),
    el("span", { style: { color: "var(--human)" } }, tr("stats.touched", { n: touched })));
}
function paintThemeBtn() {
  const dark = document.body.classList.contains("dark");
  D.themeBtn.replaceChildren(icon(dark ? "moon" : "sun", { s: 14 }), dark ? tr("theme.dark") : tr("theme.light"));
}
function toggleTheme() {
  const dark = !document.body.classList.contains("dark");
  document.body.classList.toggle("dark", dark);
  try { localStorage.setItem("loom-theme", dark ? "dark" : "light"); } catch {}
  paintThemeBtn();
}

// ───────────────────────── rail ─────────────────────────
function buildRail() {
  const search = el("input", {
    class: "loom-input", style: { paddingLeft: "30px" }, placeholder: tr("rail.searchPlaceholder"),
    oninput: (e) => { S.query = e.target.value; renderRailList(); },
  });
  D.search = search;
  const chips = el("div", { style: { display: "flex", gap: "6px", flexWrap: "wrap" } });
  D.chips = chips;
  const statusRow = el("div", { style: { display: "flex", alignItems: "center", gap: "8px", marginTop: "11px", fontSize: "11px", color: "var(--text-3)" } });
  D.statusRow = statusRow;
  const list = el("div", { style: { flex: "1", overflow: "auto", padding: "7px 7px" } });
  D.list = list;
  return el("div", { style: { width: "296px", flex: "0 0 auto", borderRight: "1px solid var(--border)", background: "var(--surface)", display: "flex", flexDirection: "column", minHeight: "0" } },
    el("div", { style: { padding: "13px 14px 11px", borderBottom: "1px solid var(--border)" } },
      el("div", { style: { position: "relative", marginBottom: "11px" } },
        el("span", { style: { position: "absolute", left: "10px", top: "8px", color: "var(--text-4)" } }, icon("search", { s: 13 })),
        search),
      chips, statusRow),
    list);
}
function renderChips() {
  const chipDefs = [{ k: "all" }, ...S.cats.filter((c) => c.k !== "struct")];
  D.chips.replaceChildren(...chipDefs.map((c) => {
    const on = S.filter === c.k;
    return el("button", {
      class: "loom-tag",
      style: {
        height: "23px", padding: "0 9px", fontSize: "11px", cursor: "pointer",
        background: on ? "var(--accent-soft)" : "var(--surface-2)",
        color: on ? "var(--accent-ink)" : "var(--text-3)",
        border: "1px solid " + (on ? "var(--accent-line)" : "var(--border)"),
      },
      onclick: () => { S.filter = c.k; renderChips(); renderRailList(); },
    }, catLabel(c.k));
  }));
}
function listRow(r) {
  const sel = r.id === S.selId;
  return el("button", {
    class: "loom-lrow",
    style: {
      display: "flex", gap: "10px", padding: "10px 12px", borderRadius: "var(--r2)", cursor: "pointer",
      width: "100%", textAlign: "left", border: "none", font: "inherit",
      background: sel ? "var(--surface-3)" : "transparent",
      boxShadow: sel ? "inset 2px 0 0 var(--accent)" : "none",
    },
    onclick: () => { S.selId = r.id; S.mode = null; S.menuOpen = false; renderRailList(); renderDetail(); },
  },
    el("span", { style: { width: "7px", height: "7px", borderRadius: r.cat === "struct" ? "50%" : "2px", marginTop: "6px", flex: "0 0 auto", background: "var(--cat-" + r.cat + ")" } }),
    el("span", { style: { flex: "1", minWidth: "0" } },
      el("span", { style: { display: "-webkit-box", WebkitLineClamp: "2", WebkitBoxOrient: "vertical", overflow: "hidden", fontSize: "12.5px", fontWeight: sel ? "600" : "500", color: sel ? "var(--text)" : "var(--text-2)", lineHeight: "1.4" } }, activeValue(r)),
      el("span", { style: { display: "flex", alignItems: "center", gap: "6px", marginTop: "4px" } },
        provChip(r.provenance),
        el("span", { class: "loom-meta", style: { fontSize: "10.5px" } }, whenText(r)),
        r.pinned && icon("pin", { s: 10, color: "var(--accent)" }),
        isTouched(r) && el("span", { title: tr("tag.humanEdited"), style: { width: "5px", height: "5px", borderRadius: "50%", background: "var(--human)" } }))));
}
function renderRailList() {
  const vis = visibleRecords();
  const pinned = vis.filter((r) => r.pinned);
  const rest = vis.filter((r) => !r.pinned);
  const touchedCount = S.records.filter(isTouched).length;

  D.statusRow.replaceChildren(
    icon("filter", { s: 12 }), document.createTextNode(tr("rail.countByTime", { n: vis.length })),
    el("div", { style: { flex: "1" } }),
    el("button", {
      class: "loom-tag tag-human", title: tr("rail.onlyTouched"),
      style: { height: "20px", fontSize: "10px", cursor: "pointer", opacity: S.humanOnly ? "1" : ".55", outline: S.humanOnly ? "1.5px solid var(--human)" : "none" },
      onclick: () => { S.humanOnly = !S.humanOnly; renderRailList(); },
    }, icon("pencil", { s: 10 }), String(touchedCount)));

  const list = D.list; list.replaceChildren();
  if (pinned.length) {
    list.append(el("div", { class: "loom-mono", style: { fontSize: "9.5px", color: "var(--text-4)", textTransform: "uppercase", letterSpacing: ".06em", padding: "5px 10px 3px" } }, tr("rail.pinned")));
    pinned.forEach((r) => list.append(listRow(r)));
    list.append(el("div", { style: { height: "1px", background: "var(--border)", margin: "7px 10px" } }));
  }
  rest.forEach((r) => list.append(listRow(r)));
  if (!vis.length) {
    const msg = S.filter === "skill" ? tr("rail.noSkills") : tr("rail.noMatch");
    list.append(el("div", { style: { padding: "30px 14px", textAlign: "center", color: "var(--text-4)", fontSize: "12px" } }, msg));
  }
  // when viewing skills, show how many are shown vs how many exist in Hermes
  if (S.filter === "skill" && S.skillSummary) {
    const ss = S.skillSummary;
    list.append(el("div", { class: "loom-mono", style: { padding: "10px 12px 4px", fontSize: "10px", color: "var(--text-4)", lineHeight: "1.6" } },
      tr("rail.skillShown", { a: ss.agent_created, t: ss.total }),
      el("br"),
      tr("rail.skillRest", { official: ss.hermes_official, community: ss.community })));
  }
}

// ───────────────────────── detail ─────────────────────────
function renderDetail() {
  const host = D.detail; host.replaceChildren();
  const r = selected();
  if (!r) {
    host.append(el("div", { class: "loom-empty" },
      icon("flow", { s: 28, color: "var(--text-3)" }),
      el("div", { style: { fontSize: "13px" } }, tr("detail.empty"))));
    return;
  }
  // lazily load full SKILL.md so the detail can show + edit the whole content
  if (r.target_type === "skill" && r.skill_content === undefined) {
    ensureSkillContent(r).then(() => { if (selected() === r) renderDetail(); });
  }
  const val = activeValue(r);
  host.append(el("div", { style: { padding: "18px 26px 15px", borderBottom: "1px solid var(--border)", background: "var(--surface)" } },
    detailMetaRow(r),
    S.mode === "edit" ? editor(r, val) : el("div", { style: { fontSize: "18px", fontWeight: "600", letterSpacing: "-0.3px", lineHeight: "1.35", textWrap: "pretty" } }, val),
    S.mode !== "edit" && el("div", { style: { fontSize: "12.5px", color: "var(--text-2)", marginTop: "4px" } }, detailText(r)),
    S.mode === null && actionRow(r),
    S.mode === "recat" && recatComposer(r),
    S.mode === "anno" && annoComposer(r)));

  const body = el("div", { style: { flex: "1", overflow: "auto", padding: "20px 26px" } });
  if (r.annotation)
    body.append(el("div", { class: "loom-anno", style: { marginBottom: "18px" } },
      el("div", { class: "hd" }, icon("note", { s: 11 }), tr("detail.yourNote", { when: relTime(r.annotation.whenTs) })),
      el("div", { style: { fontSize: "12.5px", color: "var(--text)", lineHeight: "1.55" } }, r.annotation.text)));
  body.append(pipeline(r));
  host.append(body);
}

function detailMetaRow(r) {
  return el("div", { style: { display: "flex", alignItems: "center", gap: "10px", marginBottom: "10px" } },
    catChip(r.cat),
    touchedTag(isTouched(r)),
    r.target_type === "skill" && r.origin_type && originBadge(r),
    r.pinned && el("span", { class: "loom-tag", style: { height: "19px", background: "var(--accent-soft)", color: "var(--accent-ink)" } }, icon("pin", { s: 10 }), tr("tag.pinned")),
    el("span", { class: "loom-mono", style: { fontSize: "11px", color: "var(--text-4)" } }, r.id),
    el("div", { style: { flex: "1" } }),
    conf(r.conf));
}
function originBadge(r) {
  const map = {
    agent_created: { bg: "var(--accent-soft)", fg: "var(--accent-ink)", t: tr("origin.agent") },
    hermes_official: { bg: "var(--surface-3)", fg: "var(--text-2)", t: tr("origin.official") },
    community: { bg: "var(--surface-3)", fg: "var(--text-3)", t: tr("origin.community") },
  };
  const m = map[r.origin_type] || map.community;
  return el("span", { class: "loom-tag", style: { height: "19px", background: m.bg, color: m.fg }, title: r.author ? "author: " + r.author : "" },
    icon("spark", { s: 10 }), m.t);
}

function actionRow(r) {
  const isSkill = r.target_type === "skill";
  return el("div", { style: { display: "flex", gap: "8px", marginTop: "14px", position: "relative" } },
    el("button", { class: "loom-btn", onclick: () => enterEdit(r) }, icon("pencil", { s: 13 }), isSkill ? tr("action.editContent") : tr("action.edit")),
    !isSkill && el("button", { class: "loom-btn", onclick: () => { S.mode = "recat"; renderDetail(); } }, icon("flow", { s: 13 }), tr("action.recat")),
    el("button", { class: "loom-btn", onclick: () => enterAnno(r) }, icon("note", { s: 13 }), r.annotation ? tr("action.editNote") : tr("action.addNote")),
    el("div", { style: { flex: "1" } }),
    el("button", { class: "loom-btn", onclick: () => doPin(r) }, icon("pin", { s: 13 }), r.pinned ? tr("action.unpin") : tr("action.pin")),
    el("div", { style: { position: "relative" } },
      el("button", { class: "loom-btn", onclick: (e) => { e.stopPropagation(); S.menuOpen = !S.menuOpen; renderDetail(); } }, icon("dots", { s: 14 })),
      S.menuOpen && actionMenu(r)));
}
function actionMenu(r) {
  setTimeout(() => {
    const close = (e) => { if (!menu.contains(e.target)) { S.menuOpen = false; document.removeEventListener("mousedown", close); renderDetail(); } };
    document.addEventListener("mousedown", close);
  }, 0);
  const menu = el("div", { class: "loom-menu", style: { top: "38px", right: "0" } },
    el("button", { class: "loom-mi danger", onclick: () => { S.menuOpen = false; doDelete(r); } },
      icon("trash", { s: 13 }), tr("action.delete")));
  return menu;
}

async function enterEdit(r) {
  if (r.target_type === "skill") await ensureSkillContent(r);  // edit the full SKILL.md
  S.mode = "edit";
  S.draft = (r.target_type === "skill" && r.skill_content != null) ? r.skill_content : activeValue(r);
  renderDetail();
  if (D.editTa) { D.editTa.focus(); D.editTa.setSelectionRange(0, 0); }
}
function editor(r, val) {
  const isSkill = r.target_type === "skill";
  const base = (isSkill && r.skill_content != null) ? r.skill_content : val;
  const ta = el("textarea", {
    class: "loom-edit" + (isSkill ? " sm" : ""), rows: isSkill ? 16 : 2,
    oninput: () => { S.draft = ta.value; refreshDiff(); },
    onkeydown: (e) => {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) commitEdit(r, base);
      if (e.key === "Escape") { S.mode = null; renderDetail(); }
    },
  });
  ta.value = S.draft; D.editTa = ta;
  const diffBox = el("div", { style: { marginTop: "5px", padding: "8px 11px", border: "1px solid var(--border)", borderRadius: "8px", background: "var(--surface-2)", fontSize: "13px", minHeight: "20px", maxHeight: "180px", overflow: "auto" } });
  D.diffBox = diffBox; D.diffBase = base;
  const saveLabel = isSkill ? tr("editor.saveSkill") : tr("editor.saveNewVersion");
  const hint = isSkill
    ? tr("editor.hintSkill")
    : tr("editor.hintMem", { n: r.versions.length + 1 });
  const wrap = el("div", {},
    ta,
    el("div", { style: { marginTop: "9px", fontSize: "11px", color: "var(--text-3)", display: "flex", alignItems: "center", gap: "7px" } },
      icon("pencil", { s: 11, color: "var(--human)" }), tr("editor.livePreview")),
    diffBox,
    el("div", { style: { display: "flex", alignItems: "center", gap: "8px", marginTop: "11px" } },
      el("button", { class: "loom-btn primary", onclick: () => commitEdit(r, base) }, icon("check", { s: 13 }), saveLabel),
      el("button", { class: "loom-btn ghost", onclick: () => { S.mode = null; renderDetail(); } }, tr("common.cancel")),
      el("div", { style: { flex: "1" } }),
      el("span", { class: "loom-meta", html: hint })));
  setTimeout(refreshDiff, 0);
  return wrap;
}
function refreshDiff() {
  if (!D.diffBox) return;
  const base = D.diffBase || "", draft = (S.draft || "");
  if (draft === base) {
    D.diffBox.replaceChildren(el("span", { style: { color: "var(--text-4)", fontFamily: "IBM Plex Mono, monospace" } }, tr("editor.noChange")));
    return;
  }
  if (base.length > DIFF_MAX || draft.length > DIFF_MAX) {
    const delta = draft.length - base.length;
    D.diffBox.replaceChildren(el("span", { style: { color: "var(--text-3)", fontFamily: "IBM Plex Mono, monospace" } },
      tr("editor.tooLong", { n: draft.length, delta: (delta >= 0 ? "+" : "") + delta })));
    return;
  }
  D.diffBox.replaceChildren(diffEl(base, draft));
}
function commitEdit(r, base) {
  S.mode = null;
  if (r.target_type === "skill") {
    const v = S.draft || "";   // preserve formatting (no trim) for SKILL.md
    if (v && v !== base) doSkillEdit(r, v, base); else renderDetail();
  } else {
    const v = (S.draft || "").trim();
    if (v && v !== base) doEdit(r, v); else renderDetail();
  }
}

function enterAnno(r) {
  S.mode = "anno"; S.draft = r.annotation ? r.annotation.text : "";
  renderDetail();
  if (D.annoTa) D.annoTa.focus();
}
function recatComposer(r) {
  const movable = S.cats.filter((c) => c.k === "memory" || c.k === "pref" || c.k === "hold");
  return el("div", { class: "loom-composer", style: { marginTop: "14px" } },
    el("div", { style: { fontSize: "12px", color: "var(--text-2)", marginBottom: "10px" }, html: tr("recat.desc") }),
    el("div", { style: { display: "flex", gap: "7px", flexWrap: "wrap" } },
      ...movable.map((c) => {
        const cur = c.k === r.cat;
        return el("button", {
          class: "loom-tag", disabled: cur ? "" : null,
          style: { height: "28px", padding: "0 12px", cursor: cur ? "default" : "pointer",
            border: "1px solid " + (cur ? "var(--accent-line)" : "var(--border-2)"),
            background: cur ? "var(--accent-soft)" : "var(--surface)",
            color: cur ? "var(--accent-ink)" : "var(--text)", opacity: cur ? ".7" : "1" },
          onclick: cur ? null : () => doRecat(r, c.k),
        },
          el("span", { style: { width: "7px", height: "7px", borderRadius: c.k === "hold" ? "50%" : "2px", background: "var(--cat-" + c.k + ")", display: "inline-block", marginRight: "6px" } }),
          catLabel(c.k) + (cur ? tr("recat.current") : " → " + catFile(c.k)));
      })),
    el("div", { style: { display: "flex", marginTop: "11px" } },
      el("button", { class: "loom-btn ghost", onclick: () => { S.mode = null; renderDetail(); } }, tr("common.cancel"))));
}
function annoComposer(r) {
  const ta = el("textarea", {
    class: "loom-edit sm", rows: 2, placeholder: tr("anno.placeholder"),
    oninput: () => { S.draft = ta.value; },
    onkeydown: (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { doAnnotate(r, ta.value); S.mode = null; } if (e.key === "Escape") { S.mode = null; renderDetail(); } },
  });
  ta.value = S.draft; D.annoTa = ta;
  return el("div", { class: "loom-composer", style: { marginTop: "14px" } },
    el("div", { style: { fontSize: "12px", color: "var(--text-2)", marginBottom: "8px" }, html: tr("anno.desc") }),
    ta,
    el("div", { style: { display: "flex", gap: "8px", marginTop: "10px" } },
      el("button", { class: "loom-btn primary", onclick: () => { doAnnotate(r, ta.value); S.mode = null; } }, icon("check", { s: 13 }), tr("anno.save")),
      el("button", { class: "loom-btn ghost", onclick: () => { S.mode = null; renderDetail(); } }, tr("common.cancel"))));
}

// ───────────────────────── provenance + content (two sections) ─────────────
function sectionHead(iconName, title, right) {
  return el("div", { style: { display: "flex", alignItems: "center", gap: "8px", marginBottom: "12px" } },
    el("span", { style: { color: "var(--accent)", display: "flex" } }, icon(iconName, { s: 14 })),
    el("span", { style: { fontSize: "12.5px", fontWeight: "600", color: "var(--text-2)" } }, title),
    el("div", { style: { flex: "1" } }),
    right);
}
function versionRow(r, ver, idx) {
  const active = idx === r.active;
  return el("div", { style: { display: "flex", alignItems: "center", gap: "10px", fontSize: "12px", padding: "7px 11px", borderRadius: "var(--r2)", border: "1px solid " + (active ? "var(--accent-line)" : "var(--border)"), background: active ? "var(--accent-soft)" : "var(--inset)" } },
    el("span", { class: "loom-mono", style: { fontSize: "11px", fontWeight: "600", color: active ? "var(--accent-ink)" : "var(--text-3)" } }, ver.v),
    ver.kind === "human"
      ? el("span", { class: "loom-tag tag-human", style: { height: "19px" } }, icon("pencil", { s: 10 }), tr(ver.who))
      : el("span", { class: "loom-tag tag-auto", style: { height: "19px" } }, icon("spark", { s: 10 }), tr(ver.who)),
    el("span", { class: "loom-meta" }, relTime(ver.whenTs)),
    el("div", { style: { flex: "1" } }),
    active
      ? el("span", { class: "loom-meta", style: { color: "var(--accent-ink)", fontWeight: "600" } }, tr("version.current"))
      : el("button", { class: "loom-btn ghost", style: { height: "24px", padding: "0 8px", fontSize: "11px", color: "var(--accent-ink)" }, onclick: () => doEdit(r, ver.value, { restored: true }) }, icon("undo", { s: 11 }), tr("version.restore")));
}
// version diff: two pickers (從 / 到) over a full version timeline, rendered by
// `render(a,b)` and re-rendered on selection change. Shared by skills (line-level
// diff over a full SKILL.md) and memory/user entries (char-level diff).
function versionDiffView(vs, render) {
  const selStyle = { fontFamily: "IBM Plex Mono, ui-monospace, monospace", fontSize: "11.5px",
    padding: "3px 6px", borderRadius: "6px", border: "1px solid var(--border)",
    background: "var(--surface)", color: "var(--text)" };
  const label = (v) => { const w = relTime(v.whenTs); return v.v + " · " + tr(v.who) + (w ? " · " + w : ""); };
  const mkSelect = (cur, onpick) => el("select", { style: selStyle, onchange: (e) => onpick(+e.target.value) },
    ...vs.map((v, i) => el("option", { value: String(i), selected: i === cur ? "selected" : null }, label(v))));
  let bi = vs.length - 2, ti = vs.length - 1;
  const area = el("div", {});
  const draw = () => area.replaceChildren(render(vs[bi].value, vs[ti].value));
  const bSel = mkSelect(bi, (i) => { bi = i; draw(); });
  const tSel = mkSelect(ti, (i) => { ti = i; draw(); });
  draw();
  return el("div", {},
    el("div", { style: { display: "flex", alignItems: "center", gap: "8px", marginBottom: "10px", flexWrap: "wrap", fontSize: "12px", color: "var(--text-2)" } },
      tr("version.compare"), bSel, "→", tSel,
      el("span", { class: "loom-meta", style: { marginLeft: "2px" } }, tr("version.nVersions", { n: vs.length }))),
    area);
}
const skillDiffView = (r) => versionDiffView(r.skill_versions, lineDiffEl);
// memory/user entries are short free text → char-level diff reads best.
const memoryDiffView = (vs) => versionDiffView(vs, (a, b) =>
  el("div", { style: { padding: "2px 0" } }, diffEl(a, b)));

// ── source trace / provenance ──
// Confidence drives the colour: high = accent, medium = amber, low = grey.
const PROV_ICON = { exact_match: "check", window_match: "layers", imported: "pack", external: "link", inferred: "spark", missing: "x" };
function provTone(conf) {
  return conf === "high" ? { bg: "var(--accent-soft)", fg: "var(--accent-ink)" }
    : conf === "medium" ? { bg: "var(--human-soft)", fg: "var(--human)" }
    : { bg: "var(--surface-3)", fg: "var(--text-3)" };
}
function provBadge(p) {
  const t = provTone(p.confidence);
  return el("span", { class: "loom-tag", style: { height: "20px", background: t.bg, color: t.fg } },
    icon(PROV_ICON[p.status] || "spark", { s: 11 }), tr("provenance.status." + p.status));
}
// compact source-status chip shown on each rail row
function provChip(p) {
  if (!p) return null;
  const t = provTone(p.confidence);
  return el("span", { class: "loom-tag", style: { height: "16px", padding: "0 5px", fontSize: "9px", background: t.bg, color: t.fg }, title: tr("provenance.status." + p.status) }, tr("provenance.short." + p.status));
}
// Evidence, best-effort: exact snippet → session window → fallback explanation.
function provEvidence(p) {
  if (p.has_snippet && p.snippet) {
    return el("div", { class: "loom-quote" },
      el("span", { class: "who" }, tr(p.snippet_who || "who.user")),
      el("span", {}, p.snippet));
  }
  if (p.has_window && (p.window || []).length) {
    return el("div", {},
      el("div", { class: "loom-meta", style: { marginBottom: "6px" } }, tr("provenance.windowNote")),
      ...p.window.slice(-6).map((m) => el("div", { class: "loom-quote", style: { marginBottom: "6px", borderLeftColor: m.role === "user" ? "var(--accent-line)" : "var(--border-2)" } },
        el("span", { class: "who" }, (m.role || "") + (m.tool_name ? " · " + m.tool_name : "")),
        el("span", {}, (m.snippet || "") + (m.truncated ? " …" : "")))));
  }
  // no snippet, no window → explain *why* (an honest note, not a bare error)
  return el("div", { style: { fontSize: "12.5px", color: "var(--text-2)", lineHeight: "1.6", padding: "10px 12px", border: "1px dashed var(--border-2)", borderRadius: "8px", background: "var(--surface-2)" } },
    tr(p.fallback_reason || ("provenance.summary." + p.status)));
}

function pipeline(r) {
  const vs = r.versions, stored = vs[r.active];

  // ── Section A — source trace / provenance card ──
  const p = r.provenance || { status: "missing", confidence: "low" };
  const jumpBtn = r.session_id
    ? el("button", { class: "loom-btn ghost", style: { height: "26px", padding: "0 9px", fontSize: "11.5px", color: "var(--accent-ink)" }, onclick: () => viewSession(r.session_id) }, tr("detail.jumpToChat"))
    : null;
  const confChip = el("span", { class: "loom-meta", style: { display: "inline-flex", alignItems: "center", gap: "5px" } },
    tr("provenance.confidenceLabel"), el("b", { style: { color: provTone(p.confidence).fg } }, tr("provenance.confidence." + p.confidence)));
  const sectionA = el("div", {},
    sectionHead("link", tr("provenance.head"), jumpBtn),
    el("div", { style: { display: "flex", alignItems: "center", gap: "8px", marginBottom: "10px", flexWrap: "wrap" } },
      provBadge(p), confChip),
    el("div", { style: { fontSize: "12.5px", color: "var(--text-2)", lineHeight: "1.6", marginBottom: "10px" } }, tr(p.summary_key || ("provenance.summary." + p.status))),
    provEvidence(p),
    el("div", { style: { display: "flex", alignItems: "center", gap: "8px", marginTop: "10px", flexWrap: "wrap" } },
      el("span", { class: "loom-mono", style: { fontSize: "11px", color: "var(--text-3)" } }, p.session_title || r.originId || tr("common.dash")),
      el("span", { style: { color: "var(--text-4)" } }, "·"),
      el("span", { class: "loom-meta", style: { display: "inline-flex", alignItems: "center", gap: "5px" } }, icon("clock", { s: 12 }), whenText(r)),
      el("span", { style: { color: "var(--text-4)" } }, "·"),
      el("span", { class: "loom-meta" }, tr("detail.depositedAs", { cat: catLabel(r.cat) }))));

  // ── Section B — Hermes 沉澱的內容 ──
  let sectionB;
  if (r.target_type === "skill") {
    // skills: full SKILL.md, or a line-level diff across the version history
    const c = r.skill_content;
    const skillVersions = r.skill_versions || [];
    const canDiff = skillVersions.length >= 2;
    const fullView = () => c == null
      ? el("div", { class: "loom-meta" }, tr("skill.loading"))
      : el("pre", { style: { margin: "0", border: "1px solid var(--border)", borderRadius: "8px", padding: "12px 14px", background: "var(--surface)", fontSize: "12.5px", lineHeight: "1.6", color: "var(--text)", fontFamily: "IBM Plex Mono, ui-monospace, monospace", whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: "460px", overflow: "auto" } }, c || tr("skill.empty"));
    let mode = canDiff ? "diff" : "full";
    const area = el("div", {}, mode === "diff" ? skillDiffView(r) : fullView());
    const tab = (m, text) => el("button", { class: "loom-btn ghost",
      style: { height: "26px", padding: "0 9px", fontSize: "11.5px", fontWeight: mode === m ? "600" : "400", color: mode === m ? "var(--accent-ink)" : "var(--text-3)" },
      onclick: () => { if (mode === m) return; mode = m; area.replaceChildren(m === "diff" ? skillDiffView(r) : fullView()); rightCtl.replaceChildren(...controls()); } }, text);
    const editBtn = el("button", { class: "loom-btn ghost", style: { height: "26px", padding: "0 9px", fontSize: "11.5px", color: "var(--accent-ink)" }, onclick: () => enterEdit(r) }, icon("pencil", { s: 11 }), tr("action.editContent"));
    const controls = () => canDiff ? [tab("diff", tr("skill.tabDiff")), tab("full", tr("skill.tabFull")), editBtn] : [editBtn];
    const rightCtl = el("div", { style: { display: "flex", gap: "6px", alignItems: "center" } }, ...controls());
    sectionB = el("div", {},
      sectionHead("spark", tr("skill.contentHead"), rightCtl),
      area);
  } else {
    // ≥2 versions → full edit-chain diff picker (從→到 over every recorded
    // state, auto + manual). Single version → just show the value.
    const multi = vs.length > 1;
    const hasHuman = vs.some((v) => v.kind === "human");
    const storedContent = multi
      ? el("div", {},
          el("div", { style: { fontSize: "12px", color: "var(--text-2)", marginBottom: "8px" } }, tr("mem.changes")),
          el("div", { style: { border: "1px solid var(--border)", borderRadius: "8px", padding: "9px 12px", background: "var(--surface)", fontSize: "13px" } }, memoryDiffView(vs)))
      : el("div", { style: { border: "1px solid var(--border)", borderRadius: "8px", padding: "10px 13px", background: "var(--surface)", fontSize: "14px", color: "var(--text)", lineHeight: "1.5" } }, stored.value);
    sectionB = el("div", {},
      sectionHead("spark", hasHuman ? tr("mem.contentHeadEdited") : tr("mem.contentHead")),
      storedContent,
      multi && el("div", { style: { marginTop: "14px", display: "flex", flexDirection: "column", gap: "8px" } },
        el("div", { class: "loom-mono", style: { fontSize: "10.5px", textTransform: "uppercase", letterSpacing: ".05em", color: "var(--text-3)" } }, tr("mem.versionHistory", { n: vs.length })),
        ...vs.map((v, i) => versionRow(r, v, i)).reverse()));
  }

  return el("div", { style: { display: "flex", flexDirection: "column", gap: "22px" } }, sectionA, sectionB);
}

// session source viewer (modal)
async function viewSession(sid) {
  const overlay = el("div", { style: { position: "fixed", inset: "0", background: "rgba(0,0,0,.55)", zIndex: "200", display: "flex", alignItems: "center", justifyContent: "center" }, onclick: (e) => { if (e.target === overlay) overlay.remove(); } });
  const panel = el("div", { class: "loom-menu", style: { position: "static", width: "640px", maxWidth: "92vw", maxHeight: "82vh", overflow: "auto", padding: "16px 18px" } },
    el("div", { style: { display: "flex", alignItems: "center", gap: "8px", marginBottom: "10px" } },
      icon("link", { s: 14 }), el("b", {}, "Session " + sid),
      el("div", { style: { flex: "1" } }),
      el("button", { class: "loom-iconbtn", onclick: () => overlay.remove() }, icon("x", { s: 13 }))),
    el("div", { class: "loom-meta" }, tr("common.loading")));
  overlay.append(panel); document.body.append(overlay);
  try {
    const d = await api.get("/sessions/" + encodeURIComponent(sid) + "/context?limit=24");
    panel.replaceChildren(
      el("div", { style: { display: "flex", alignItems: "center", gap: "8px", marginBottom: "12px" } },
        icon("link", { s: 14 }), el("b", {}, "Session " + sid),
        d.meta && d.meta.source && el("span", { class: "loom-tag tag-auto" }, d.meta.source),
        el("div", { style: { flex: "1" } }),
        el("button", { class: "loom-iconbtn", onclick: () => overlay.remove() }, icon("x", { s: 13 }))),
      ...(d.messages || []).map((m) => el("div", { class: "loom-quote", style: { marginBottom: "8px", borderLeftColor: m.role === "user" ? "var(--accent-line)" : "var(--border-2)" } },
        el("span", { class: "who" }, (m.role || "") + (m.tool_name ? " · " + m.tool_name : "")),
        el("span", {}, (m.snippet || "") + (m.truncated ? " …" : "")))),
      !(d.messages || []).length && el("div", { class: "loom-meta" }, tr("session.noMessages")));
  } catch (e) {
    panel.append(el("div", { class: "banner err", style: { color: "var(--del)" } }, tr("common.loadFailed", { msg: e.message })));
  }
}

// ───────────────────────── SOUL editor ─────────────────────────
function soulDirty() {
  return !!(D.soulText && S.soul && D.soulText.value !== S.soul.content);
}
function soulStatusChildren() {
  const d = S.soul;
  if (!d) return [];
  const out = [];
  if (d.in_sync === true) out.push(el("span", { class: "loom-tag tag-auto", style: { height: "20px" } }, icon("check", { s: 11 }), tr("soul.synced")));
  else if (d.in_sync === false) out.push(el("span", { class: "loom-tag", style: { height: "20px", background: "var(--human-soft)", color: "var(--human)" } }, icon("spark", { s: 11 }), tr("soul.dbNewer")));
  if (!d.disk.exists) out.push(el("span", { class: "loom-tag", style: { height: "20px", background: "var(--human-soft)", color: "var(--human)" } }, tr("soul.noDisk")));
  if (d.updated_at) out.push(el("span", { class: "loom-meta", style: { display: "inline-flex", alignItems: "center", gap: "4px" } }, icon("clock", { s: 11 }), tr("soul.dbVersion", { when: fmtTime(d.updated_at) })));
  if (soulDirty()) out.push(el("span", { class: "loom-tag", style: { height: "20px", background: "var(--surface-3)", color: "var(--del)" } }, tr("soul.unsaved")));
  return out;
}
function paintSoulStatus() {
  if (D.soulStatus) D.soulStatus.replaceChildren(...soulStatusChildren());
}
async function renderSoul() {
  const host = D.soulBody;
  host.replaceChildren(el("div", { class: "loom-meta", style: { padding: "30px" } }, tr("soul.loading")));
  let data;
  try { data = await api.get("/soul"); }
  catch (e) { host.replaceChildren(el("div", { class: "banner err", style: { margin: "24px", color: "var(--del)" } }, tr("common.loadFailed", { msg: e.message }))); return; }
  S.soul = data;
  const ta = el("textarea", {
    class: "loom-input",
    style: { width: "100%", height: "auto", minHeight: "46vh", resize: "vertical", fontFamily: "IBM Plex Mono, ui-monospace, monospace", fontSize: "13px", lineHeight: "1.6", padding: "14px 16px", boxSizing: "border-box" },
    oninput: paintSoulStatus,
  });
  ta.value = data.content || "";
  D.soulText = ta;
  D.soulStatus = el("div", { style: { display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap", minHeight: "22px" } });

  host.replaceChildren(el("div", { style: { maxWidth: "880px", margin: "0 auto", padding: "26px 28px 40px", display: "flex", flexDirection: "column", gap: "14px" } },
    el("div", {},
      el("div", { style: { display: "flex", alignItems: "center", gap: "9px", flexWrap: "wrap" } },
        icon("spark", { s: 18, color: "var(--accent)" }),
        el("div", { style: { fontSize: "19px", fontWeight: "700", letterSpacing: "-.3px" } }, "SOUL.md"),
        el("span", { class: "loom-mono", style: { fontSize: "11px", color: "var(--text-4)" } }, data.disk.path)),
      el("div", { style: { fontSize: "12.5px", color: "var(--text-2)", marginTop: "5px", lineHeight: "1.6" } },
        tr("soul.desc"))),
    D.soulStatus,
    ta,
    el("div", { style: { display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" } },
      el("button", { class: "loom-btn primary", onclick: doSoulSave }, icon("check", { s: 14 }), tr("soul.saveToLoom")),
      el("button", { class: "loom-btn", onclick: doSoulCompile }, icon("flow", { s: 14 }), tr("soul.compile")),
      el("button", { class: "loom-btn ghost", onclick: () => renderSoul() }, icon("undo", { s: 13 }), tr("soul.reload")),
      el("div", { style: { flex: "1" } }),
      el("span", { class: "loom-meta" }, tr("soul.nVersions", { n: (data.history || []).length })))));
  paintSoulStatus();
}
const doSoulSave = guard(async function () {
  const res = await api.post("/soul/save", { content: D.soulText.value });
  pushToast({ tone: "human", text: res.unchanged ? tr("soul.unchanged") : tr("soul.saved") });
  await renderSoul();
});
const doSoulCompile = guard(async function () {
  if (soulDirty()) { pushToast({ tone: "err", text: tr("soul.mustSaveFirst") }); return; }
  const res = await api.post("/soul/compile", {});
  pushToast({ tone: "human", text: tr("soul.compiledTo", { path: res.path }) + (res.backup ? tr("soul.backedUp") : "") });
  await renderSoul();
});

// ───────────────────────── assembled prompt viewer ─────────────────────────
async function renderPrompts() {
  if (!D.promptList) {
    D.promptList = el("div", { style: { width: "266px", flex: "0 0 auto", borderRight: "1px solid var(--border)", overflow: "auto", background: "var(--surface)" } });
    D.promptDetail = el("div", { style: { flex: "1", overflow: "auto", background: "var(--bg)", minWidth: "0" } });
    D.promptsBody.replaceChildren(D.promptList, D.promptDetail);
  }
  D.promptList.replaceChildren(el("div", { class: "loom-meta", style: { padding: "16px" } }, tr("prompt.loadingList")));
  let data;
  try { data = await api.get("/prompts?limit=50"); }
  catch (e) { D.promptList.replaceChildren(el("div", { class: "banner err", style: { margin: "14px", color: "var(--del)" } }, tr("common.loadFailed", { msg: e.message }))); return; }
  S.promptList = data.sessions || [];
  if (!S.promptList.length) {
    D.promptList.replaceChildren(el("div", { class: "loom-empty", style: { padding: "30px 14px", textAlign: "center" } },
      el("div", {}, tr("prompt.noPrompts")),
      el("div", { class: "loom-meta", style: { marginTop: "6px" } }, tr("prompt.noPromptsDesc"))));
    D.promptDetail.replaceChildren();
    return;
  }
  if (!S.promptSel || !S.promptList.find((s) => s.id === S.promptSel)) S.promptSel = S.promptList[0].id;
  paintPromptList();
  loadPromptDetail(S.promptSel);
}
function paintPromptList() {
  D.promptList.replaceChildren(
    el("div", { class: "loom-mono", style: { fontSize: "9.5px", color: "var(--text-4)", textTransform: "uppercase", letterSpacing: ".06em", padding: "12px 12px 6px" } }, tr("prompt.recentChats")),
    ...S.promptList.map((s) => {
      const on = s.id === S.promptSel;
      return el("button", {
        style: { display: "block", width: "100%", textAlign: "left", border: "none", font: "inherit", cursor: "pointer", padding: "9px 12px", background: on ? "var(--surface-3)" : "transparent", boxShadow: on ? "inset 2px 0 0 var(--accent)" : "none" },
        onclick: () => { S.promptSel = s.id; paintPromptList(); loadPromptDetail(s.id); },
      },
        el("div", { style: { fontSize: "12.5px", fontWeight: on ? "600" : "500", color: on ? "var(--text)" : "var(--text-2)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" } }, s.title || tr("prompt.chatN", { id: (s.id || "").slice(0, 8) })),
        el("div", { style: { display: "flex", gap: "7px", alignItems: "center", marginTop: "3px", flexWrap: "wrap" } },
          el("span", { class: "loom-meta", style: { fontSize: "10px" } }, fmtTime(s.started_at)),
          s.model && el("span", { class: "loom-tag tag-auto", style: { height: "16px", padding: "0 5px", fontSize: "9px" } }, s.model),
          el("span", { class: "loom-meta", style: { fontSize: "10px" } }, tr("unit.chars", { n: fmtInt(s.prompt_chars) }))));
    }));
}
const fmtInt = (n) => (n == null ? "0" : Number(n).toLocaleString());
async function loadPromptDetail(sid) {
  D.promptDetail.replaceChildren(el("div", { class: "loom-meta", style: { padding: "30px" } }, tr("prompt.loadingDetail")));
  let d;
  try { d = await api.get("/prompts/" + encodeURIComponent(sid)); }
  catch (e) { D.promptDetail.replaceChildren(el("div", { class: "banner err", style: { margin: "24px", color: "var(--del)" } }, tr("common.loadFailed", { msg: e.message }))); return; }
  if (S.promptSel !== sid) return; // user switched away mid-load

  const lines = (d.system_prompt || "").split("\n");
  const offsets = []; let acc = 0;
  for (const ln of lines) { offsets.push(acc); acc += ln.length + 1; }
  const total = acc || 1;

  const pre = el("pre", { style: { margin: "0", padding: "16px 18px", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "10px", fontSize: "12.5px", lineHeight: "1.65", color: "var(--text)", fontFamily: "IBM Plex Mono, ui-monospace, monospace", whiteSpace: "pre-wrap", wordBreak: "break-word", overflow: "auto", maxHeight: "62vh" } }, d.system_prompt || tr("prompt.empty"));

  const jump = (line) => {
    const frac = (offsets[line] || 0) / total;
    pre.scrollTop = frac * (pre.scrollHeight - pre.clientHeight);
  };
  const outline = (d.outline || []).length
    ? el("div", { style: { border: "1px solid var(--border)", borderRadius: "10px", padding: "8px 6px", background: "var(--surface)", maxHeight: "62vh", overflow: "auto" } },
        el("div", { class: "loom-mono", style: { fontSize: "9.5px", color: "var(--text-4)", textTransform: "uppercase", letterSpacing: ".05em", padding: "4px 8px 7px" } }, tr("prompt.outline", { n: d.outline.length })),
        ...d.outline.map((h) => el("button", {
          style: { display: "block", width: "100%", textAlign: "left", border: "none", background: "transparent", cursor: "pointer", font: "inherit", color: "var(--text-2)", fontSize: "11.5px", padding: "3px 8px 3px " + (4 + (h.level - 1) * 12) + "px", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", borderRadius: "5px" },
          onmouseenter: (e) => e.target.style.background = "var(--surface-3)",
          onmouseleave: (e) => e.target.style.background = "transparent",
          onclick: () => jump(h.line),
        }, h.text)))
    : null;

  const meta = el("div", { style: { display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap", marginBottom: "10px" } },
    el("span", { class: "loom-tag tag-auto", style: { height: "20px" } }, icon("clock", { s: 11 }), fmtTime(d.started_at)),
    d.model && el("span", { class: "loom-tag tag-auto", style: { height: "20px" } }, d.model),
    d.source && el("span", { class: "loom-tag tag-auto", style: { height: "20px" } }, d.source),
    el("span", { class: "loom-meta" }, tr("prompt.metaSummary", { m: fmtInt(d.message_count), c: fmtInt(d.chars), l: fmtInt(d.lines) })),
    el("div", { style: { flex: "1" } }),
    el("button", { class: "loom-btn ghost", onclick: () => doCopyPrompt(d.system_prompt) }, icon("link", { s: 13 }), tr("common.copy")));

  const body = outline
    ? el("div", { style: { display: "grid", gridTemplateColumns: "minmax(0,1fr) 230px", gap: "16px", alignItems: "start" } }, pre, outline)
    : pre;

  D.promptDetail.replaceChildren(el("div", { style: { padding: "20px 22px 40px" } },
    el("div", { style: { display: "flex", alignItems: "center", gap: "9px", marginBottom: "4px" } },
      icon("layers", { s: 17, color: "var(--accent)" }),
      el("div", { style: { fontSize: "16px", fontWeight: "700" } }, d.title || tr("prompt.chatN", { id: (d.session_id || "").slice(0, 8) })),
      el("span", { class: "loom-mono", style: { fontSize: "10.5px", color: "var(--text-4)" } }, d.session_id)),
    el("div", { style: { fontSize: "12px", color: "var(--text-2)", marginBottom: "13px" } }, tr("prompt.desc")),
    meta,
    promptSectionHead("layers", tr("prompt.systemPrompt"), tr("prompt.charsLines", { c: fmtInt(d.chars), l: fmtInt(d.lines) })),
    body,
    promptRecallsSection(d),
    promptMessagesSection(d)));
}
function promptSectionHead(ic, title, sub) {
  return el("div", { style: { display: "flex", alignItems: "center", gap: "8px", margin: "26px 0 12px", paddingBottom: "7px", borderBottom: "1px solid var(--border)" } },
    icon(ic, { s: 14, color: "var(--accent)" }),
    el("div", { style: { fontSize: "13.5px", fontWeight: "700" } }, title),
    sub && el("span", { class: "loom-meta", style: { fontSize: "11px" } }, sub));
}
function promptRecallsSection(d) {
  const recalls = d.recalls || [];
  const head = promptSectionHead("flow", tr("prompt.recallsHead"), tr("prompt.nInjections", { n: recalls.length }));
  if (!recalls.length) {
    return el("div", {}, head, el("div", { class: "loom-meta", style: { fontSize: "12px", lineHeight: "1.6" } },
      tr("prompt.noRecalls")));
  }
  return el("div", {}, head,
    ...recalls.map((rc) => el("div", { class: "loom-quote", style: { marginBottom: "10px" } },
      el("div", { style: { display: "flex", alignItems: "center", gap: "7px", flexWrap: "wrap", marginBottom: "6px" } },
        el("span", { class: "loom-meta", style: { display: "inline-flex", alignItems: "center", gap: "4px" } }, icon("clock", { s: 11 }), fmtTime(rc.timestamp)),
        el("span", { class: "loom-tag " + (rc.method === "llm" ? "tag-human" : "tag-auto"), style: { height: "18px" } }, rc.method),
        ...(rc.tags || []).map((t) => el("span", { class: "loom-tag", style: { height: "18px", background: "var(--surface-3)", color: "var(--text-2)" } }, icon("tag", { s: 9 }), t)),
        el("span", { class: "loom-meta" }, tr("recall.injectedN", { n: rc.count }))),
      el("div", { class: "who", style: { marginBottom: "5px" } }, tr("prompt.matchedUser", { msg: rc.message || "" })),
      ...(rc.records || []).map((r) => el("div", { style: { fontSize: "12.5px", color: "var(--text)", padding: "1px 0", display: "flex", gap: "6px", flexWrap: "wrap" } },
        el("span", { style: { color: "var(--accent)" } }, "＋"),
        r.title && el("b", {}, "【" + r.title + "】"),
        el("span", {}, r.value),
        ...((r.tags || []).map((t) => el("span", { class: "loom-mono", style: { fontSize: "10px", color: "var(--text-4)" } }, "#" + t))))))));
}
const ROLE_STYLE = {
  user: { bg: "var(--accent-soft)", fg: "var(--accent-ink)", label: "USER" },
  assistant: { bg: "var(--surface-3)", fg: "var(--text)", label: "ASSISTANT" },
  tool: { bg: "var(--surface-2)", fg: "var(--text-2)", label: "TOOL" },
  system: { bg: "var(--human-soft)", fg: "var(--human)", label: "SYSTEM" },
};
function promptMessagesSection(d) {
  const msgs = d.messages || [];
  const head = promptSectionHead("link", tr("prompt.messagesHead"), tr("prompt.nMessages", { n: msgs.length }));
  if (!msgs.length) return el("div", {}, head, el("div", { class: "loom-meta", style: { fontSize: "12px" } }, tr("session.noMessages")));
  return el("div", {}, head,
    ...msgs.map((m) => {
      const rs = ROLE_STYLE[m.role] || { bg: "var(--surface-2)", fg: "var(--text-2)", label: (m.role || "?").toUpperCase() };
      return el("div", { style: { border: "1px solid var(--border)", borderRadius: "9px", marginBottom: "9px", overflow: "hidden", background: "var(--surface)" } },
        el("div", { style: { display: "flex", alignItems: "center", gap: "8px", padding: "7px 11px", background: rs.bg, flexWrap: "wrap" } },
          el("span", { class: "loom-mono", style: { fontSize: "10px", fontWeight: "700", letterSpacing: ".04em", color: rs.fg } }, rs.label),
          m.tool_name && el("span", { class: "loom-mono", style: { fontSize: "10.5px", color: "var(--text-3)" } }, m.tool_name),
          el("div", { style: { flex: "1" } }),
          m.token_count != null && el("span", { class: "loom-meta", style: { fontSize: "10px" } }, m.token_count + " tok"),
          m.timestamp && el("span", { class: "loom-meta", style: { fontSize: "10px" } }, fmtTime(m.timestamp))),
        m.content && el("div", { style: { padding: "9px 12px", fontSize: "12.5px", lineHeight: "1.6", color: "var(--text)", whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: "340px", overflow: "auto", fontFamily: m.role === "tool" ? "IBM Plex Mono, ui-monospace, monospace" : "inherit" } },
          m.content + (m.truncated ? tr("prompt.truncated") : "")),
        m.reasoning && el("details", { style: { padding: "0 12px 9px" } },
          el("summary", { class: "loom-meta", style: { cursor: "pointer", fontSize: "11px" } }, "reasoning"),
          el("div", { style: { fontSize: "12px", color: "var(--text-2)", whiteSpace: "pre-wrap", wordBreak: "break-word", marginTop: "5px", maxHeight: "240px", overflow: "auto" } }, m.reasoning)),
        ...(m.tool_calls || []).map((tc) => el("div", { style: { padding: "0 12px 9px" } },
          el("span", { class: "loom-tag tag-auto", style: { height: "18px" } }, icon("spark", { s: 10 }), "tool_call " + (tc.name || "")),
          tc.arguments && el("pre", { style: { margin: "5px 0 0", fontSize: "11.5px", color: "var(--text-2)", whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: "200px", overflow: "auto", fontFamily: "IBM Plex Mono, ui-monospace, monospace" } }, typeof tc.arguments === "string" ? tc.arguments : JSON.stringify(tc.arguments, null, 2)))));
    }));
}
const doCopyPrompt = guard(async function (text) {
  await navigator.clipboard.writeText(text || "");
  pushToast({ tone: "human", text: tr("prompt.copied") });
});

// ───────────────────────── packs (middle memory layer) ─────────────────────────
const parseTagsInput = (s) => (s || "").split(/[,，]/).map((x) => x.trim()).filter(Boolean);
function packTagChips(tags, opts) {
  return (tags || []).map((t) => el("span", { class: "loom-tag", style: Object.assign({ height: "17px", padding: "0 6px", fontSize: "10px", background: "var(--surface-3)", color: "var(--text-2)" }, opts || {}) }, icon("tag", { s: 9 }), t));
}
async function renderPacks() {
  if (!D.packList) {
    D.packList = el("div", { style: { width: "276px", flex: "0 0 auto", borderRight: "1px solid var(--border)", overflow: "auto", background: "var(--surface)" } });
    D.packDetail = el("div", { style: { flex: "1", overflow: "auto", background: "var(--bg)", minWidth: "0" } });
    D.packsBody.replaceChildren(D.packList, D.packDetail);
  }
  D.packList.replaceChildren(el("div", { class: "loom-meta", style: { padding: "16px" } }, tr("pack.loading")));
  let data;
  try { data = await api.get("/packs"); }
  catch (e) { D.packList.replaceChildren(el("div", { class: "banner err", style: { margin: "14px", color: "var(--del)" } }, tr("common.loadFailed", { msg: e.message }))); return; }
  S.packs = data.packs || [];
  if (S.packSel !== "new" && !S.packs.find((p) => p.id === S.packSel)) {
    S.packSel = S.packs.length ? S.packs[0].id : "new";
  }
  paintPackList();
  renderPackDetail();
}
function paintPackList() {
  const addOn = S.packSel === "new";
  const add = el("button", {
    class: "loom-btn" + (addOn ? " primary" : ""), style: { margin: "11px 12px", width: "calc(100% - 24px)", justifyContent: "center" },
    onclick: () => { S.packSel = "new"; paintPackList(); renderPackDetail(); },
  }, icon("plus", { s: 14 }), tr("pack.add"));
  const rows = S.packs.map((p) => {
    const on = p.id === S.packSel;
    return el("button", {
      style: { display: "block", width: "100%", textAlign: "left", border: "none", font: "inherit", cursor: "pointer", padding: "9px 12px", background: on ? "var(--surface-3)" : "transparent", boxShadow: on ? "inset 2px 0 0 var(--accent)" : "none", opacity: p.enabled ? "1" : ".5" },
      onclick: () => { S.packSel = p.id; paintPackList(); renderPackDetail(); },
    },
      el("div", { style: { display: "flex", alignItems: "center", gap: "6px" } },
        el("span", { style: { width: "6px", height: "6px", borderRadius: "50%", flex: "0 0 auto", background: p.enabled ? "var(--cat-fact, var(--accent))" : "var(--text-4)" }, title: p.enabled ? tr("pack.enabledTitle") : tr("pack.disabledTitle") }),
        el("div", { style: { fontSize: "12.5px", fontWeight: on ? "600" : "500", color: on ? "var(--text)" : "var(--text-2)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" } }, p.title || tr("pack.unnamed"))),
      (p.tags || []).length ? el("div", { style: { display: "flex", gap: "4px", flexWrap: "wrap", margin: "4px 0 0 12px" } }, ...packTagChips(p.tags.slice(0, 4), { height: "15px", fontSize: "9px" })) : null,
      p.when_to_use ? el("div", { style: { fontSize: "10px", color: "var(--text-3)", fontStyle: "italic", margin: "3px 0 0 12px", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }, title: p.when_to_use }, tr("pack.whenPrefix", { when: p.when_to_use })) : null,
      el("div", { class: "loom-meta", style: { fontSize: "10.5px", margin: "3px 0 0 12px", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" } }, (p.content || "").slice(0, 50)));
  });
  D.packList.replaceChildren(...[
    add,
    el("div", { class: "loom-mono", style: { fontSize: "9.5px", color: "var(--text-4)", textTransform: "uppercase", letterSpacing: ".06em", padding: "2px 12px 6px" } }, tr("pack.nPacks", { n: S.packs.length })),
    ...rows,
    S.packs.length ? null : el("div", { class: "loom-meta", style: { padding: "14px", fontSize: "11.5px", lineHeight: "1.6" } }, tr("pack.empty")),
  ].filter(Boolean));
}
function renderPackDetail() {
  const host = D.packDetail;
  const isNew = S.packSel === "new";
  const p = isNew ? { id: null, title: "", tags: [], content: "", enabled: true }
                  : (S.packs.find((x) => x.id === S.packSel) || null);
  if (!p) { host.replaceChildren(el("div", { class: "loom-empty", style: { padding: "44px" } }, icon("pack", { s: 26, color: "var(--text-3)" }), el("div", { style: { fontSize: "13px" } }, tr("pack.detailEmpty")))); return; }

  const title = el("input", { class: "loom-input", placeholder: tr("pack.titlePlaceholder"), value: p.title });
  const tags = el("input", { class: "loom-input", placeholder: tr("pack.tagsPlaceholder"), value: (p.tags || []).join(", ") });
  const whenTo = el("textarea", { class: "loom-input", style: { width: "100%", height: "auto", minHeight: "62px", resize: "vertical", padding: "10px 14px", lineHeight: "1.6", fontSize: "12.5px", boxSizing: "border-box" }, placeholder: tr("pack.whenPlaceholder") });
  whenTo.value = p.when_to_use || "";
  const content = el("textarea", { class: "loom-input", style: { width: "100%", height: "auto", minHeight: "34vh", resize: "vertical", padding: "12px 14px", lineHeight: "1.6", fontSize: "13px", boxSizing: "border-box" }, placeholder: tr("pack.contentPlaceholder") });
  content.value = p.content;
  const enabled = el("input", { type: "checkbox", style: { width: "15px", height: "15px", accentColor: "var(--accent)" } });
  enabled.checked = !!p.enabled;
  D.packTitle = title; D.packTags = tags; D.packWhen = whenTo; D.packContent = content; D.packEnabled = enabled;

  const field = (label, node, hint) => el("div", { style: { marginBottom: "13px" } },
    el("div", { style: { fontSize: "11px", fontWeight: "600", color: "var(--text-2)", marginBottom: "5px" } }, label),
    node,
    hint && el("div", { class: "loom-meta", style: { fontSize: "10.5px", marginTop: "4px" } }, hint));

  host.replaceChildren(el("div", { style: { maxWidth: "780px", margin: "0 auto", padding: "24px 26px 40px" } },
    el("div", { style: { display: "flex", alignItems: "center", gap: "9px", marginBottom: "14px" } },
      icon("pack", { s: 17, color: "var(--accent)" }),
      el("div", { style: { fontSize: "16px", fontWeight: "700" } }, isNew ? tr("pack.addHead") : tr("pack.editHead")),
      !isNew && el("span", { class: "loom-mono", style: { fontSize: "10.5px", color: "var(--text-4)" } }, "#" + p.id)),
    field(tr("pack.fieldTitle"), title, tr("pack.fieldTitleHint")),
    field(tr("pack.fieldTags"), tags, tr("pack.fieldTagsHint")),
    field(tr("pack.fieldWhen"), whenTo, tr("pack.fieldWhenHint")),
    field(tr("pack.fieldContent"), content),
    el("label", { style: { display: "flex", alignItems: "center", gap: "8px", marginBottom: "16px", cursor: "pointer", fontSize: "12.5px", color: "var(--text-2)" } },
      enabled, tr("pack.enableLabel")),
    el("div", { style: { display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" } },
      el("button", { class: "loom-btn primary", onclick: doPackSave }, icon("check", { s: 14 }), isNew ? tr("common.create") : tr("common.save")),
      !isNew && el("button", { class: "loom-btn ghost", style: { color: "var(--del)" }, onclick: doPackDelete }, icon("trash", { s: 13 }), tr("common.delete")),
      el("div", { style: { flex: "1" } })),
    packTestPanel()));
}
function packTestPanel() {
  const input = el("input", { class: "loom-input", placeholder: tr("pack.testPlaceholder"),
    onkeydown: (e) => { if (e.key === "Enter") doPackTest(); } });
  D.packTestInput = input;
  D.packTestOut = el("div", { style: { marginTop: "10px" } });
  return el("div", { style: { marginTop: "26px", paddingTop: "18px", borderTop: "1px solid var(--border)" } },
    el("div", { style: { display: "flex", alignItems: "center", gap: "8px", marginBottom: "9px" } },
      icon("flow", { s: 14, color: "var(--accent)" }),
      el("div", { style: { fontSize: "13px", fontWeight: "700" } }, tr("pack.testHead")),
      el("span", { class: "loom-meta", style: { fontSize: "11px" } }, tr("pack.testSub"))),
    el("div", { style: { display: "flex", gap: "8px" } }, input,
      el("button", { class: "loom-btn", style: { flex: "0 0 auto" }, onclick: doPackTest }, tr("pack.testBtn"))),
    D.packTestOut);
}
const doPackSave = guard(async function () {
  const body = { title: D.packTitle.value, tags: parseTagsInput(D.packTags.value), when_to_use: D.packWhen.value, content: D.packContent.value, enabled: D.packEnabled.checked };
  if (S.packSel !== "new") body.id = S.packSel;
  const res = await api.post("/packs/save", body);
  S.packSel = res.id;
  pushToast({ tone: "human", text: res.created ? tr("pack.created") : tr("pack.updated") });
  await renderPacks();
});
const doPackDelete = guard(async function () {
  if (S.packSel === "new") return;
  await api.post("/packs/delete", { id: S.packSel });
  S.packSel = null;
  pushToast({ tone: "human", text: tr("pack.deleted") });
  await renderPacks();
});
const doPackTest = guard(async function () {
  const msg = (D.packTestInput.value || "").trim();
  if (!msg) return;
  D.packTestOut.replaceChildren(el("span", { class: "loom-meta" }, tr("pack.testing")));
  const r = await api.post("/recall", { message: msg });
  const out = [];
  out.push(el("div", { style: { display: "flex", alignItems: "center", gap: "7px", flexWrap: "wrap", marginBottom: "8px" } },
    el("span", { class: "loom-tag " + (r.method === "llm" ? "tag-human" : "tag-auto"), style: { height: "18px" } }, r.method),
    (r.tags || []).length ? el("span", { class: "loom-meta", style: { fontSize: "11px" } }, tr("pack.matched")) : el("span", { class: "loom-meta", style: { fontSize: "11px" } }, tr("pack.noMatch")),
    ...packTagChips(r.tags || [])));
  (r.records || []).forEach((rec) => out.push(el("div", { class: "loom-quote", style: { marginBottom: "7px" } },
    el("div", { style: { fontWeight: "600", fontSize: "12.5px", marginBottom: "3px" } }, "【" + (rec.title || "") + "】"),
    el("div", { style: { fontSize: "12px", color: "var(--text-2)", whiteSpace: "pre-wrap" } }, rec.value))));
  D.packTestOut.replaceChildren(...out);
});

// ───────────────────────── boot ─────────────────────────
let _statusTimer = null;
function boot() {
  try { if (localStorage.getItem("loom-theme") === "dark") document.body.classList.add("dark"); } catch {}
  document.title = "Hermes Loom · " + tr("header.subtitle");
  const root = document.getElementById("root");
  const app = el("div", { class: "loom-app" });
  D.detail = el("div", { style: { flex: "1", overflow: "hidden", background: "var(--bg)", display: "flex", flexDirection: "column", minHeight: "0" } });
  D.toasts = el("div", { class: "loom-toasts" });
  D.inspectorBody = el("div", { style: { flex: "1", display: "flex", overflow: "hidden", minHeight: "0" } }, buildRail(), D.detail);
  D.soulBody = el("div", { style: { flex: "1", display: "none", overflow: "auto", background: "var(--bg)", minHeight: "0" } });
  D.promptsBody = el("div", { style: { flex: "1", display: "none", overflow: "hidden", minHeight: "0" } });
  D.packsBody = el("div", { style: { flex: "1", display: "none", overflow: "hidden", minHeight: "0" } });
  // packsBody/promptsBody are rebuilt above; drop their lazily-built children so
  // renderPacks/renderPrompts re-create them inside the new bodies. Otherwise the
  // stale refs point at detached nodes and the page renders blank after a
  // language switch (boot() reruns) until a full refresh.
  D.packList = D.packDetail = D.promptList = D.promptDetail = null;
  app.append(
    buildHeader(),
    el("div", { style: { flex: "1", display: "flex", overflow: "hidden", minHeight: "0" } }, D.inspectorBody, D.soulBody, D.packsBody, D.promptsBody),
    D.toasts);
  root.replaceChildren(app);
  loadRecords()
    .then(() => setView(S.view))   // restore the active view (e.g. after a language switch)
    .catch((e) => {
      D.detail.replaceChildren(el("div", { class: "loom-empty" }, el("div", { style: { color: "var(--del)" } }, tr("common.loadFailed", { msg: e.message }))));
    });
  refreshStatus();
  // keep the pill honest as gateway/plugin state changes — but only one timer,
  // since boot() also runs on every language switch.
  if (!_statusTimer) _statusTimer = setInterval(refreshStatus, 30000);
}
// Switching language re-localizes everything by rebuilding the UI in place
// (backend already returns i18n keys, so no re-fetch of meaning is needed).
window.LoomI18n.onChange(() => boot());
boot();
