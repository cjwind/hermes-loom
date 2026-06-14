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
  plus: '<path d="M8 3v10M3 8h10"/>',
  check: '<path d="M3 8.5l3.2 3L13 4.5"/>',
  x: '<path d="M4 4l8 8M12 4l-8 8"/>',
  note: '<g><path d="M3 3.5h10v6l-3 3H3v-9z"/><path d="M13 9.5h-3v3"/></g>',
  dots: '<circle cx="3.5" cy="8" r="1.3"/><circle cx="8" cy="8" r="1.3"/><circle cx="12.5" cy="8" r="1.3"/>',
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

// ───────────────────────── state ─────────────────────────
const S = {
  records: [], cats: [], selId: null, skillSummary: null,
  filter: "all", query: "", humanOnly: false,
  toasts: [], mode: null, draft: "", menuOpen: false,
};
const D = {}; // persistent DOM refs

const DIFF_MAX = 4000; // skip live char-diff above this (O(n·m) LCS would hang)
const catLabel = (k) => (S.cats.find((c) => c.k === k) || {}).label || k;
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
    .filter((r) => !q || (activeValue(r) + r.detail + r.origin).toLowerCase().includes(q));
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
    const toneBg = t.tone === "del" ? "var(--del-soft)" : t.tone === "human" ? "var(--human-soft)" : "var(--accent-soft)";
    const toneFg = t.tone === "del" ? "var(--del)" : t.tone === "human" ? "var(--human)" : "var(--accent-ink)";
    const tIcon = t.tone === "del" ? "trash" : t.tone === "undo" ? "undo" : "check";
    host.append(el("div", { class: "loom-toast" },
      el("span", { class: "ic", style: { background: toneBg, color: toneFg } }, icon(tIcon, { s: 13 })),
      el("span", {}, t.text),
      t.onUndo && el("button", { class: "undo", onclick: () => { closeToast(t.id); t.onUndo(); } }, icon("undo", { s: 12 }), "復原"),
      el("button", { class: "loom-iconbtn", style: { width: "26px", height: "26px" }, onclick: () => closeToast(t.id) }, icon("x", { s: 12 }))));
  }
}

// ───────────────────────── mutations ─────────────────────────
async function doEdit(r, value, { restored } = {}) {
  const prev = activeValue(r);
  if (!value || value === prev) return;
  await api.post("/records/edit", { target_type: r.target_type, target_key: r.target_key, new_value: value });
  await loadRecords((x) => x.target_type === r.target_type && activeValue(x) === value);
  pushToast({
    tone: restored ? "undo" : "human",
    text: restored ? "已還原並設為生效（存成新版本）" : "已存成新版本，Hermes 的自動版本仍保留",
    onUndo: async () => { await api.post("/records/edit", { target_type: r.target_type, target_key: entryKeyOf(value, r), new_value: prev }).catch(() => {}); await loadRecords((x) => x.target_type === r.target_type && activeValue(x) === prev); },
  });
}
// memory keys change after edit; for undo we look up the record by current value instead.
function entryKeyOf(value, r) {
  const m = S.records.find((x) => x.target_type === r.target_type && activeValue(x) === value);
  return m ? m.target_key : r.target_key;
}

async function doDelete(r) {
  const val = activeValue(r);
  await api.post("/records/delete", { target_type: r.target_type, target_key: r.target_key });
  const canUndo = r.target_type !== "skill";
  await loadRecords();
  pushToast({
    tone: "del",
    text: "已刪除「" + val.slice(0, 14) + (val.length > 14 ? "…" : "") + "」" + (canUndo ? "" : "（技能已停用，檔案已備份）"),
    onUndo: canUndo ? async () => {
      await api.post("/records/add", { store_type: r.target_type, text: val }).catch(() => {});
      await loadRecords((x) => x.target_type === r.target_type && activeValue(x) === val);
    } : undefined,
  });
}

async function doAnnotate(r, text) {
  const prev = r.annotation ? r.annotation.text : "";
  await api.post("/records/annotate", { target_type: r.target_type, target_key: r.target_key, text });
  await loadRecords((x) => x.id === r.id);
  pushToast({
    tone: "human", text: text.trim() ? "已加上你的註解" : "已移除註解",
    onUndo: async () => { await api.post("/records/annotate", { target_type: r.target_type, target_key: r.target_key, text: prev }).catch(() => {}); await loadRecords((x) => x.id === r.id); },
  });
}

async function doPin(r) {
  await api.post("/records/pin", { target_type: r.target_type, target_key: r.target_key, pinned: !r.pinned });
  await loadRecords((x) => x.id === r.id);
}

// Skill records carry only their description in the list; the full SKILL.md is
// fetched lazily on demand (and cached on the record).
function ensureSkillContent(r) {
  if (r.target_type !== "skill" || r.skill_content !== undefined) return Promise.resolve();
  r.skill_content = null; // sentinel: loading
  return api.get("/records/" + encodeURIComponent(r.id))
    .then((d) => { r.skill_content = (d && d.skill_content) || ""; })
    .catch(() => { r.skill_content = ""; });
}

async function doSkillEdit(r, newContent, oldContent) {
  if (newContent === oldContent) { S.mode = null; renderDetail(); return; }
  await api.post("/records/edit", { target_type: "skill", target_key: r.target_key, new_value: newContent });
  await loadRecords((x) => x.target_type === "skill" && x.target_key === r.target_key);
  pushToast({
    tone: "human", text: "已更新 SKILL.md 內容",
    onUndo: async () => {
      await api.post("/records/edit", { target_type: "skill", target_key: r.target_key, new_value: oldContent }).catch(() => {});
      await loadRecords((x) => x.target_type === "skill" && x.target_key === r.target_key);
    },
  });
}

// ───────────────────────── atoms ─────────────────────────
function catChip(cat) {
  return el("span", { class: "loom-cat cat-" + cat }, el("span", { class: "cd" }), catLabel(cat));
}
function touchedTag(human) {
  return human
    ? el("span", { class: "loom-tag tag-human" }, icon("pencil", { s: 10 }), "人工調整過")
    : el("span", { class: "loom-tag tag-auto" }, icon("spark", { s: 10 }), "Hermes 自動沉澱");
}
function conf(n) {
  return el("span", { class: "loom-conf", title: "可信度 " + n + "/3" },
    ...[1, 2, 3].map((i) => el("i", { class: i <= n ? "on" : "" })));
}

// ───────────────────────── header ─────────────────────────
function buildHeader() {
  const stats = el("span", { class: "loom-meta", style: { marginRight: "4px" } });
  D.stats = stats;
  const themeBtn = el("button", { class: "loom-btn", onclick: toggleTheme });
  D.themeBtn = themeBtn; paintThemeBtn();
  const pill = el("span", { class: "loom-pill" }, el("span", { class: "loom-dot" }), "檢查狀態中…");
  D.pill = pill;
  return el("div", { class: "loom-top" },
    el("div", { class: "loom-brand" },
      el("div", { class: "loom-logo" }),
      el("div", { class: "loom-name", html: 'Hermes Loom <span class="sub">/ 檢視台</span>' })),
    pill,
    el("div", { class: "loom-top-spacer" }),
    stats, themeBtn);
}

// Reflect real auto-deposit status (plugin enabled + gateway running + recent hook).
const PILL_COLOR = { live: "var(--cat-fact)", enabled: "var(--human)", offline: "var(--text-4)" };
async function refreshStatus() {
  if (!D.pill) return;
  try {
    const s = await api.get("/status");
    const dot = el("span", { class: "loom-dot" + (s.state === "live" ? " loom-live" : ""), style: { background: PILL_COLOR[s.state] || "var(--text-4)" } });
    let tip = `plugin：${s.plugin.installed ? (s.plugin.enabled ? "已啟用" : "已安裝但停用") : "未安裝"}`;
    tip += ` · gateway：${s.gateway.known ? (s.gateway.running ? "運作中" : "未運作") : "未知"}`;
    tip += s.last_plugin_hook_rel ? ` · 最近即時觀測：${s.last_plugin_hook_rel}` : " · 尚無即時觀測";
    D.pill.replaceChildren(dot, document.createTextNode(s.label));
    D.pill.setAttribute("title", tip);
  } catch (e) {
    D.pill.replaceChildren(el("span", { class: "loom-dot", style: { background: "var(--text-4)" } }), document.createTextNode("狀態未知"));
    D.pill.setAttribute("title", "無法取得狀態：" + e.message);
  }
}
function renderStats() {
  const live = S.records.length;
  const touched = S.records.filter(isTouched).length;
  D.stats.replaceChildren(
    document.createTextNode(live + " 筆 · "),
    el("span", { style: { color: "var(--human)" } }, touched + " 筆你動過"));
}
function paintThemeBtn() {
  const dark = document.body.classList.contains("dark");
  D.themeBtn.replaceChildren(icon(dark ? "moon" : "sun", { s: 14 }), dark ? "深色" : "淺色");
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
    class: "loom-input", style: { paddingLeft: "30px" }, placeholder: "搜尋成長紀錄…",
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
  const chipDefs = [{ k: "all", label: "全部" }, ...S.cats.filter((c) => c.k !== "struct")];
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
    }, c.label);
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
        el("span", { class: "loom-meta", style: { fontSize: "10.5px" } }, r.when || "—"),
        r.pinned && icon("pin", { s: 10, color: "var(--accent)" }),
        isTouched(r) && el("span", { title: "人工調整過", style: { width: "5px", height: "5px", borderRadius: "50%", background: "var(--human)" } }))));
}
function renderRailList() {
  const vis = visibleRecords();
  const pinned = vis.filter((r) => r.pinned);
  const rest = vis.filter((r) => !r.pinned);
  const touchedCount = S.records.filter(isTouched).length;

  D.statusRow.replaceChildren(
    icon("filter", { s: 12 }), document.createTextNode(vis.length + " 筆 · 依時間"),
    el("div", { style: { flex: "1" } }),
    el("button", {
      class: "loom-tag tag-human", title: "只看你動過的",
      style: { height: "20px", fontSize: "10px", cursor: "pointer", opacity: S.humanOnly ? "1" : ".55", outline: S.humanOnly ? "1.5px solid var(--human)" : "none" },
      onclick: () => { S.humanOnly = !S.humanOnly; renderRailList(); },
    }, icon("pencil", { s: 10 }), String(touchedCount)));

  const list = D.list; list.replaceChildren();
  if (pinned.length) {
    list.append(el("div", { class: "loom-mono", style: { fontSize: "9.5px", color: "var(--text-4)", textTransform: "uppercase", letterSpacing: ".06em", padding: "5px 10px 3px" } }, "已釘選"));
    pinned.forEach((r) => list.append(listRow(r)));
    list.append(el("div", { style: { height: "1px", background: "var(--border)", margin: "7px 10px" } }));
  }
  rest.forEach((r) => list.append(listRow(r)));
  if (!vis.length) {
    const msg = S.filter === "skill" ? "目前沒有新沉澱的 skills" : "沒有符合的沉澱";
    list.append(el("div", { style: { padding: "30px 14px", textAlign: "center", color: "var(--text-4)", fontSize: "12px" } }, msg));
  }
  // when viewing skills, show how many are shown vs how many exist in Hermes
  if (S.filter === "skill" && S.skillSummary) {
    const ss = S.skillSummary;
    list.append(el("div", { class: "loom-mono", style: { padding: "10px 12px 4px", fontSize: "10px", color: "var(--text-4)", lineHeight: "1.6" } },
      `顯示 ${ss.agent_created} / ${ss.total} 個技能（只列新沉澱）`,
      el("br"),
      `其餘：Hermes 官方 ${ss.hermes_official} · 社群 ${ss.community}（已隱藏）`));
  }
}

// ───────────────────────── detail ─────────────────────────
function renderDetail() {
  const host = D.detail; host.replaceChildren();
  const r = selected();
  if (!r) {
    host.append(el("div", { class: "loom-empty" },
      icon("flow", { s: 28, color: "var(--text-3)" }),
      el("div", { style: { fontSize: "13px" } }, "從左側選一筆沉澱，看它從哪來、怎麼長成的")));
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
    S.mode !== "edit" && el("div", { style: { fontSize: "12.5px", color: "var(--text-2)", marginTop: "4px" } }, r.detail),
    S.mode === null && actionRow(r),
    S.mode === "anno" && annoComposer(r)));

  const body = el("div", { style: { flex: "1", overflow: "auto", padding: "20px 26px" } });
  if (r.annotation)
    body.append(el("div", { class: "loom-anno", style: { marginBottom: "18px" } },
      el("div", { class: "hd" }, icon("note", { s: 11 }), "你的註解 · " + r.annotation.when),
      el("div", { style: { fontSize: "12.5px", color: "var(--text)", lineHeight: "1.55" } }, r.annotation.text)));
  body.append(pipeline(r));
  host.append(body);
}

function detailMetaRow(r) {
  return el("div", { style: { display: "flex", alignItems: "center", gap: "10px", marginBottom: "10px" } },
    catChip(r.cat),
    touchedTag(isTouched(r)),
    r.target_type === "skill" && r.origin_type && originBadge(r),
    r.pinned && el("span", { class: "loom-tag", style: { height: "19px", background: "var(--accent-soft)", color: "var(--accent-ink)" } }, icon("pin", { s: 10 }), "已釘選"),
    el("span", { class: "loom-mono", style: { fontSize: "11px", color: "var(--text-4)" } }, r.id),
    el("div", { style: { flex: "1" } }),
    conf(r.conf));
}
function originBadge(r) {
  const map = {
    agent_created: { bg: "var(--accent-soft)", fg: "var(--accent-ink)", t: "新沉澱 · agent 產生" },
    hermes_official: { bg: "var(--surface-3)", fg: "var(--text-2)", t: "Hermes 官方 / 原生" },
    community: { bg: "var(--surface-3)", fg: "var(--text-3)", t: "外部 / 社群" },
  };
  const m = map[r.origin_type] || map.community;
  return el("span", { class: "loom-tag", style: { height: "19px", background: m.bg, color: m.fg }, title: r.author ? "author: " + r.author : "" },
    icon("spark", { s: 10 }), m.t);
}

function actionRow(r) {
  const isSkill = r.target_type === "skill";
  return el("div", { style: { display: "flex", gap: "8px", marginTop: "14px", position: "relative" } },
    el("button", { class: "loom-btn", onclick: () => enterEdit(r) }, icon("pencil", { s: 13 }), isSkill ? "編輯內容" : "編輯"),
    el("button", { class: "loom-btn", onclick: () => enterAnno(r) }, icon("note", { s: 13 }), r.annotation ? "編輯註解" : "加註解"),
    el("div", { style: { flex: "1" } }),
    el("button", { class: "loom-btn", onclick: () => doPin(r) }, icon("pin", { s: 13 }), r.pinned ? "取消釘選" : "釘選"),
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
      icon("trash", { s: 13 }), "刪除這筆沉澱"));
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
  const saveLabel = isSkill ? "儲存 SKILL.md" : "存成新版本";
  const hint = isSkill
    ? "會寫回 SKILL.md（先自動備份） · <span class='loom-kbd'>⌘↵</span>"
    : "會新增 v" + (r.versions.length + 1) + "，自動版仍保留 · <span class='loom-kbd'>⌘↵</span>";
  const wrap = el("div", {},
    ta,
    el("div", { style: { marginTop: "9px", fontSize: "11px", color: "var(--text-3)", display: "flex", alignItems: "center", gap: "7px" } },
      icon("pencil", { s: 11, color: "var(--human)" }), "即時預覽改動："),
    diffBox,
    el("div", { style: { display: "flex", alignItems: "center", gap: "8px", marginTop: "11px" } },
      el("button", { class: "loom-btn primary", onclick: () => commitEdit(r, base) }, icon("check", { s: 13 }), saveLabel),
      el("button", { class: "loom-btn ghost", onclick: () => { S.mode = null; renderDetail(); } }, "取消"),
      el("div", { style: { flex: "1" } }),
      el("span", { class: "loom-meta", html: hint })));
  setTimeout(refreshDiff, 0);
  return wrap;
}
function refreshDiff() {
  if (!D.diffBox) return;
  const base = D.diffBase || "", draft = (S.draft || "");
  if (draft === base) {
    D.diffBox.replaceChildren(el("span", { style: { color: "var(--text-4)", fontFamily: "IBM Plex Mono, monospace" } }, "尚未改動"));
    return;
  }
  if (base.length > DIFF_MAX || draft.length > DIFF_MAX) {
    const delta = draft.length - base.length;
    D.diffBox.replaceChildren(el("span", { style: { color: "var(--text-3)", fontFamily: "IBM Plex Mono, monospace" } },
      `內容較長，略過即時字元 diff（${draft.length} 字，${delta >= 0 ? "+" : ""}${delta}）`));
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
function annoComposer(r) {
  const ta = el("textarea", {
    class: "loom-edit sm", rows: 2, placeholder: "例如：這條只在工作情境適用，私人聚餐不算…",
    oninput: () => { S.draft = ta.value; },
    onkeydown: (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { doAnnotate(r, ta.value); S.mode = null; } if (e.key === "Escape") { S.mode = null; renderDetail(); } },
  });
  ta.value = S.draft; D.annoTa = ta;
  return el("div", { class: "loom-composer", style: { marginTop: "14px" } },
    el("div", { style: { fontSize: "12px", color: "var(--text-2)", marginBottom: "8px" }, html: "加一段給自己的註解 — <b style='color:var(--text)'>不會改動沉澱內容</b>，只是備註。" }),
    ta,
    el("div", { style: { display: "flex", gap: "8px", marginTop: "10px" } },
      el("button", { class: "loom-btn primary", onclick: () => { doAnnotate(r, ta.value); S.mode = null; } }, icon("check", { s: 13 }), "儲存註解"),
      el("button", { class: "loom-btn ghost", onclick: () => { S.mode = null; renderDetail(); } }, "取消")));
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
      ? el("span", { class: "loom-tag tag-human", style: { height: "19px" } }, icon("pencil", { s: 10 }), ver.who)
      : el("span", { class: "loom-tag tag-auto", style: { height: "19px" } }, icon("spark", { s: 10 }), ver.who),
    el("span", { class: "loom-meta" }, ver.when),
    el("div", { style: { flex: "1" } }),
    active
      ? el("span", { class: "loom-meta", style: { color: "var(--accent-ink)", fontWeight: "600" } }, "目前生效")
      : el("button", { class: "loom-btn ghost", style: { height: "24px", padding: "0 8px", fontSize: "11px", color: "var(--accent-ink)" }, onclick: () => doEdit(r, ver.value, { restored: true }) }, icon("undo", { s: 11 }), "還原此版"));
}
function pipeline(r) {
  const vs = r.versions, stored = vs[r.active], prev = r.active > 0 ? vs[r.active - 1] : null;
  const edited = vs.length > 1;

  // ── Section A — 來自這次對話 (provenance) ──
  const jumpBtn = r.session_id
    ? el("button", { class: "loom-btn ghost", style: { height: "26px", padding: "0 9px", fontSize: "11.5px", color: "var(--accent-ink)" }, onclick: () => viewSession(r.session_id) }, "跳到對話 ›")
    : null;
  const sectionA = el("div", {},
    sectionHead("link", "來自這次對話", jumpBtn),
    el("div", { class: "loom-quote" },
      el("span", { class: "who" }, r.raw.who + " · " + r.origin),
      ...r.raw.parts.map((p) => typeof p === "string" ? el("span", {}, p) : el("em", {}, p.hl))),
    el("div", { style: { display: "flex", alignItems: "center", gap: "8px", marginTop: "9px", flexWrap: "wrap" } },
      el("span", { class: "loom-mono", style: { fontSize: "11px", color: "var(--text-3)" } }, r.originId),
      el("span", { style: { color: "var(--text-4)" } }, "·"),
      el("span", { class: "loom-meta", style: { display: "inline-flex", alignItems: "center", gap: "5px" } }, icon("clock", { s: 12 }), r.when || "—"),
      el("span", { style: { color: "var(--text-4)" } }, "·"),
      el("span", { class: "loom-meta" }, "Hermes 從這段沉澱為 " + catLabel(r.cat))));

  // ── Section B — Hermes 沉澱的內容 ──
  let sectionB;
  if (r.target_type === "skill") {
    // skills: show the full SKILL.md (lazily loaded), editable via 編輯內容
    const c = r.skill_content;
    const body = c == null
      ? el("div", { class: "loom-meta" }, "載入 SKILL.md 內容中…")
      : el("pre", { style: { margin: "0", border: "1px solid var(--border)", borderRadius: "8px", padding: "12px 14px", background: "var(--surface)", fontSize: "12.5px", lineHeight: "1.6", color: "var(--text)", fontFamily: "IBM Plex Mono, ui-monospace, monospace", whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: "460px", overflow: "auto" } }, c || "（此 skill 沒有內容）");
    sectionB = el("div", {},
      sectionHead("spark", "Hermes 沉澱的內容（SKILL.md）",
        el("button", { class: "loom-btn ghost", style: { height: "26px", padding: "0 9px", fontSize: "11.5px", color: "var(--accent-ink)" }, onclick: () => enterEdit(r) }, icon("pencil", { s: 11 }), "編輯內容")),
      body);
  } else {
    const storedContent = prev
      ? el("div", {},
          el("div", { style: { fontSize: "12px", color: "var(--text-2)", marginBottom: "8px" }, html: "從 <span class='loom-mono'>" + prev.v + "</span> → <span class='loom-mono'>" + stored.v + "</span> 的變化：" }),
          el("div", { style: { border: "1px solid var(--border)", borderRadius: "8px", padding: "9px 12px", background: "var(--surface)", fontSize: "13px" } }, diffEl(prev.value, stored.value)))
      : el("div", { style: { border: "1px solid var(--border)", borderRadius: "8px", padding: "10px 13px", background: "var(--surface)", fontSize: "14px", color: "var(--text)", lineHeight: "1.5" } }, stored.value);
    sectionB = el("div", {},
      sectionHead("spark", edited ? "Hermes 沉澱的內容 · 含你的調整" : "Hermes 沉澱的內容"),
      storedContent,
      edited && el("div", { style: { marginTop: "14px", display: "flex", flexDirection: "column", gap: "8px" } },
        el("div", { class: "loom-mono", style: { fontSize: "10.5px", textTransform: "uppercase", letterSpacing: ".05em", color: "var(--text-3)" } }, "版本歷史 · " + vs.length + " 版 · Hermes 的自動版本永遠保留"),
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
    el("div", { class: "loom-meta" }, "載入中…"));
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
      !(d.messages || []).length && el("div", { class: "loom-meta" }, "（此 session 沒有可顯示的訊息）"));
  } catch (e) {
    panel.append(el("div", { class: "banner err", style: { color: "var(--del)" } }, "讀取失敗：" + e.message));
  }
}

// ───────────────────────── boot ─────────────────────────
function boot() {
  try { if (localStorage.getItem("loom-theme") === "dark") document.body.classList.add("dark"); } catch {}
  const root = document.getElementById("root");
  const app = el("div", { class: "loom-app" });
  D.detail = el("div", { style: { flex: "1", overflow: "hidden", background: "var(--bg)", display: "flex", flexDirection: "column", minHeight: "0" } });
  D.toasts = el("div", { class: "loom-toasts" });
  app.append(
    buildHeader(),
    el("div", { style: { flex: "1", display: "flex", overflow: "hidden", minHeight: "0" } }, buildRail(), D.detail),
    D.toasts);
  root.replaceChildren(app);
  loadRecords().catch((e) => {
    D.detail.replaceChildren(el("div", { class: "loom-empty" }, el("div", { style: { color: "var(--del)" } }, "載入失敗：" + e.message)));
  });
  refreshStatus();
  setInterval(refreshStatus, 30000); // keep the pill honest as gateway/plugin state changes
}
boot();
