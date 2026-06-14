// Hermes Loom — minimal hash-routed SPA (vanilla JS, no build step).
// Pages: Recent Growth, Event Detail, Current Memory, Skills Overview,
// Skill Detail, Session Context Viewer. Talks only to the Local API.

const api = {
  async get(path) {
    const r = await fetch("/api" + path);
    if (!r.ok) throw new Error((await r.json()).error || r.statusText);
    return r.json();
  },
  async post(path, body) {
    const r = await fetch("/api" + path, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const data = await r.json();
    if (!r.ok || data.ok === false) throw new Error(data.error || r.statusText);
    return data;
  },
};

const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k === "html") e.innerHTML = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) e.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid == null) continue;
    e.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return e;
};
const app = () => document.getElementById("app");
const fmtTime = (ts) => ts ? new Date(ts * 1000).toLocaleString() : "—";
const esc = (s) => (s == null ? "" : String(s));
const setStatus = (t) => (document.getElementById("status").textContent = t || "");

const KIND_TAG = {
  memory_added: "added", memory_replaced: "replaced", memory_removed: "removed",
  skill_created: "added", skill_edited: "replaced", skill_patched: "replaced",
  skill_deleted: "removed", memory_snapshot_imported: "historical",
  skill_snapshot_imported: "historical",
};
const kindTag = (k) => el("span", { class: "tag " + (KIND_TAG[k] || "") }, k);

// ---- Router ----------------------------------------------------------------
const routes = [];
const route = (re, fn) => routes.push([re, fn]);
async function render() {
  const hash = location.hash.replace(/^#/, "") || "/growth";
  for (const [re, fn] of routes) {
    const m = hash.match(re);
    if (m) {
      app().textContent = "Loading…";
      try { await fn(...m.slice(1)); }
      catch (e) { app().replaceChildren(el("div", { class: "banner err" }, "Error: " + e.message)); }
      return;
    }
  }
  app().textContent = "Not found";
}
window.addEventListener("hashchange", render);
window.addEventListener("load", render);

// ---- Page: Recent Growth ---------------------------------------------------
route(/^\/growth$/, async () => {
  const q = new URLSearchParams(location.hash.split("?")[1] || "");
  const params = new URLSearchParams();
  for (const k of ["target_type", "kind", "status", "recent_days"]) {
    if (q.get(k)) params.set(k, q.get(k));
  }
  const data = await api.get("/events?" + params.toString());

  const mkSelect = (name, opts, cur) =>
    el("select", { onchange: (e) => navFilter(name, e.target.value) },
      ...[["", "(all " + name + ")"], ...opts.map((o) => [o, o])].map(([v, l]) =>
        el("option", { value: v, ...(v === (cur || "") ? { selected: "" } : {}) }, l)));

  const filters = el("div", { class: "filters" },
    mkSelect("target_type", ["memory", "user", "skill"], q.get("target_type")),
    mkSelect("kind", Object.keys(KIND_TAG), q.get("kind")),
    mkSelect("status", ["observed", "reviewed", "edited", "reverted", "ignored"], q.get("status")),
    mkSelect("recent_days", ["1", "7", "30", "90"], q.get("recent_days")),
    el("span", { class: "muted" }, data.count + " events"));

  const rows = data.events.map((e) =>
    el("tr", { class: "clickable", onclick: () => (location.hash = "/event/" + e.id) },
      el("td", {}, fmtTime(e.timestamp)),
      el("td", {}, kindTag(e.kind),
        e.historical ? el("span", { class: "tag historical", title: "import before plugin" }, "history") : null,
        e.inferred ? el("span", { class: "tag inferred", title: "from snapshot diff" }, "inferred") : null),
      el("td", {}, el("span", { class: "tag " + e.target_type }, e.target_type)),
      el("td", {}, esc(e.target_key) || el("span", { class: "muted" }, "—")),
      el("td", {}, e.source_session_id
        ? el("a", { class: "link", onclick: (ev) => { ev.stopPropagation(); location.hash = "/session/" + e.source_session_id; } }, e.source_session_id)
        : el("span", { class: "muted" }, "—")),
      el("td", {}, el("span", { class: "muted" }, e.source_hint)),
      el("td", {}, e.status)));

  app().replaceChildren(
    el("h2", {}, "Recent Growth"),
    el("p", { class: "muted" }, "Hermes 成長了什麼，從哪裡來。點一列看 before/after 與來源。"),
    filters,
    el("table", {},
      el("thead", {}, el("tr", {},
        ...["time", "kind", "target", "key", "source session", "via", "status"].map((h) => el("th", {}, h)))),
      el("tbody", {}, ...rows)));
});

function navFilter(name, value) {
  const q = new URLSearchParams(location.hash.split("?")[1] || "");
  if (value) q.set(name, value); else q.delete(name);
  location.hash = "/growth?" + q.toString();
}

// ---- Page: Event Detail ----------------------------------------------------
route(/^\/event\/(\d+)$/, async (id) => {
  const d = await api.get("/events/" + id);
  const e = d.event;
  const win = d.source_message_window || [];
  app().replaceChildren(
    el("div", { class: "crumbs" }, el("a", { class: "link", href: "#/growth" }, "← Recent Growth")),
    el("h2", {}, kindTag(e.kind), " ", esc(e.target_key) || "(memory)"),
    el("div", { class: "card" },
      el("div", { class: "kv" },
        kv("event id", e.id), kv("time", fmtTime(e.timestamp)),
        kv("target", e.target_type + " / " + esc(e.target_key)),
        kv("path", esc(e.target_path)), kv("action", esc(e.action)),
        kv("via (source_hint)", esc(e.source_hint)), kv("tool", esc(e.tool_name)),
        kv("status", esc(e.status)),
        kv("session", e.source_session_id
          ? el("a", { class: "link", href: "#/session/" + e.source_session_id }, e.source_session_id)
          : "—"))),
    el("h3", {}, "Before / After"),
    el("div", { class: "diff" },
      el("div", { class: "before" }, d.before == null ? "(none)" : d.before),
      el("div", { class: "after" }, d.after == null ? "(none)" : d.after)),
    win.length ? el("h3", {}, "Source message window") : null,
    win.length ? el("div", { class: "card" }, ...win.map(msgEl)) : null,
    (d.metadata ? el("details", {}, el("summary", {}, "metadata"),
      el("pre", {}, JSON.stringify(d.metadata, null, 2))) : null),
    (d.related_overrides && d.related_overrides.length
      ? el("div", { class: "card" }, el("h3", {}, "Related manual overrides"),
          ...d.related_overrides.map((o) =>
            el("div", { class: "muted" }, `${fmtTime(o.applied_at)} · ${o.override_type} · ${esc(o.reason) || ""}`)))
      : null));
});

const kv = (k, v) => [el("div", { class: "k" }, k), el("div", { class: "v" }, v)].reduce((f, n) => (f.append(n), f), document.createDocumentFragment());
const msgEl = (m) => el("div", { class: "msg" },
  el("div", {}, el("span", { class: "role " + (m.role === "tool" ? "tool" : "") }, m.role + (m.tool_name ? " · " + m.tool_name : "")),
    " ", el("span", { class: "muted" }, fmtTime(m.timestamp))),
  el("div", { class: "snippet" }, esc(m.snippet) + (m.truncated ? " …" : "")));

// ---- Page: Current Memory --------------------------------------------------
route(/^\/memory$/, async () => {
  const d = await api.get("/memory/current");
  const section = (store, label) => {
    const s = d[store];
    if (!s.exists) return el("div", { class: "card" }, el("h3", {}, label), el("p", { class: "muted" }, "(file does not exist)"));
    const entries = s.entries.map((en) =>
      el("div", { class: "entry" },
        el("div", {}, esc(en.text)),
        el("div", { class: "actions" },
          el("button", { class: "secondary", onclick: () => editMemory(store, en) }, "Edit"),
          el("button", { class: "danger", onclick: () => delMemory(store, en) }, "Delete"),
          el("span", { class: "muted", title: "stable entry key" }, en.key))));
    return el("div", {}, el("h3", {}, label + " ", el("span", { class: "muted" }, `(${s.entries.length} entries)`)), ...entries);
  };
  app().replaceChildren(
    el("h2", {}, "Current Memory"),
    el("p", { class: "muted" }, "Hermes 目前實際使用的 MEMORY.md / USER.md，切成條目。編輯會真的寫回底層檔案（並先 snapshot）。"),
    section("memory", "MEMORY.md"),
    section("user", "USER.md"));
});

async function editMemory(store, entry) {
  const next = await modalEdit("Edit entry", entry.text);
  if (next == null) return;
  const reason = prompt("Reason (optional)?") || null;
  await api.post("/overrides/memory/edit", { store_type: store, entry_key: entry.key, new_text: next, reason });
  setStatus("memory entry edited");
  render();
}
async function delMemory(store, entry) {
  if (!confirm("Delete this entry from " + store + "? A snapshot + backup is kept.")) return;
  const reason = prompt("Reason (optional)?") || null;
  await api.post("/overrides/memory/delete", { store_type: store, entry_key: entry.key, reason });
  setStatus("memory entry deleted");
  render();
}

// ---- Page: Skills Overview -------------------------------------------------
route(/^\/skills$/, async () => {
  const d = await api.get("/skills");
  const rows = d.skills.map((s) =>
    el("tr", { class: "clickable", onclick: () => (location.hash = "/skill/" + encodeURIComponent(s.name)) },
      el("td", {}, s.name),
      el("td", {}, el("span", { class: "muted" }, s.category)),
      el("td", {}, esc(s.description).slice(0, 80)),
      el("td", {}, fmtTime(s.mtime)),
      el("td", {}, s.last_event ? kindTag(s.last_event.kind) : el("span", { class: "muted" }, "—")),
      el("td", {}, s.event_count)));
  app().replaceChildren(
    el("h2", {}, "Skills"),
    el("p", { class: "muted" }, `${d.count} skills · 點一列查看內容、最近 growth events、可編輯`),
    el("table", {},
      el("thead", {}, el("tr", {}, ...["name", "category", "description", "updated", "last event", "#events"].map((h) => el("th", {}, h)))),
      el("tbody", {}, ...rows)));
});

// ---- Page: Skill Detail ----------------------------------------------------
route(/^\/skill\/(.+)$/, async (name) => {
  name = decodeURIComponent(name);
  const d = await api.get("/skills/" + encodeURIComponent(name));
  const s = d.skill;
  app().replaceChildren(
    el("div", { class: "crumbs" }, el("a", { class: "link", href: "#/skills" }, "← Skills")),
    el("h2", {}, s.name, " ", el("span", { class: "muted" }, s.category)),
    el("p", { class: "muted" }, esc(s.description)),
    el("div", { class: "actions", style: "display:flex;gap:8px;margin-bottom:12px" },
      el("button", { onclick: () => saveSkill(name) }, "Save changes"),
      el("button", { class: "danger", onclick: () => disableSkill(name) }, "Disable skill")),
    el("textarea", { id: "skill-content", style: "min-height:340px" }, s.content),
    el("h3", {}, "Recent growth events"),
    d.events.length
      ? el("table", {}, el("tbody", {}, ...d.events.map((e) =>
          el("tr", { class: "clickable", onclick: () => (location.hash = "/event/" + e.id) },
            el("td", {}, fmtTime(e.timestamp)), el("td", {}, kindTag(e.kind)),
            el("td", {}, el("span", { class: "muted" }, e.source_hint))))))
      : el("p", { class: "muted" }, "(no recorded events)"));
});
async function saveSkill(name) {
  const content = document.getElementById("skill-content").value;
  const reason = prompt("Reason (optional)?") || null;
  await api.post("/overrides/skill/edit", { name, new_content: content, reason });
  setStatus("skill saved to underlying SKILL.md");
  render();
}
async function disableSkill(name) {
  if (!confirm("Disable " + name + "? Renames SKILL.md -> SKILL.md.disabled (reversible).")) return;
  const reason = prompt("Reason (optional)?") || null;
  await api.post("/overrides/skill/delete", { name, hard: false, reason });
  setStatus("skill disabled");
  location.hash = "/skills";
}

// ---- Page: Session Context Viewer ------------------------------------------
route(/^\/session\/(.+)$/, async (sid) => {
  sid = decodeURIComponent(sid);
  const d = await api.get("/sessions/" + encodeURIComponent(sid) + "/context");
  app().replaceChildren(
    el("div", { class: "crumbs" }, el("a", { class: "link", href: "#/growth" }, "← Recent Growth")),
    el("h2", {}, "Session ", sid),
    d.available
      ? el("div", { class: "card" },
          el("div", { class: "kv" },
            kv("source", esc(d.meta && d.meta.source)), kv("title", esc(d.meta && d.meta.title) || "—"),
            kv("started", fmtTime(d.meta && d.meta.started_at))))
      : el("div", { class: "banner err" }, "session not found in state.db"),
    el("h3", {}, "Conversation (recent)"),
    el("div", { class: "card" }, ...(d.messages || []).map(msgEl)),
    (d.events && d.events.length
      ? el("div", {}, el("h3", {}, "Growth from this session"),
          el("table", {}, el("tbody", {}, ...d.events.map((e) =>
            el("tr", { class: "clickable", onclick: () => (location.hash = "/event/" + e.id) },
              el("td", {}, fmtTime(e.timestamp)), el("td", {}, kindTag(e.kind)),
              el("td", {}, esc(e.target_key)))))))
      : null));
});

// ---- modal edit ------------------------------------------------------------
function modalEdit(title, initial) {
  return new Promise((resolve) => {
    const ta = el("textarea", {}, initial);
    const overlay = el("div", {
      style: "position:fixed;inset:0;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;z-index:50",
    }, el("div", { class: "card", style: "width:600px;max-width:90vw" },
      el("h3", {}, title), ta,
      el("div", { style: "display:flex;gap:8px;margin-top:10px;justify-content:flex-end" },
        el("button", { class: "secondary", onclick: () => { overlay.remove(); resolve(null); } }, "Cancel"),
        el("button", { onclick: () => { overlay.remove(); resolve(ta.value); } }, "Save"))));
    document.body.append(overlay);
    ta.focus();
  });
}

// ---- Sync button -----------------------------------------------------------
document.getElementById("btn-sync").addEventListener("click", async () => {
  setStatus("syncing…");
  try {
    await api.post("/maintenance/ingest", {});
    await api.post("/maintenance/reconcile", {});
    setStatus("synced");
    render();
  } catch (e) { setStatus("sync failed: " + e.message); }
});
