// Component test: the Inspector rail must show only agent_created skills.
// Runs ui/app.js under a minimal DOM shim. Run: node tests/ui_filter_test.js
// (kept separate from the Python unittest suite; exits non-zero on failure.)
const fs = require("fs");
const path = require("path");

function mkEl(t, ns) {
  const e = {
    tag: t, ns, nodeType: 1, children: [], style: {}, attrs: {}, className: "",
    _html: "", value: "",
    setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k]; },
    addEventListener() {}, removeEventListener() {},
    append(...k) { for (const x of k) this.children.push(x); },
    appendChild(k) { this.children.push(k); return k; },
    replaceChildren(...k) { this.children = k; },
    contains() { return false; }, focus() {}, setSelectionRange() {},
    get innerHTML() { return this._html; }, set innerHTML(v) { this._html = v; },
    classList: { _s: new Set(), contains(c) { return this._s.has(c); }, add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); }, toggle(c, o) { o ? this._s.add(c) : this._s.delete(c); } },
  };
  return e;
}
global.document = {
  createElement: (t) => mkEl(t), createElementNS: (ns, t) => mkEl(t, ns),
  createTextNode: (s) => ({ nodeType: 3, text: String(s) }),
  getElementById: () => global.__root, body: mkEl("body"),
  addEventListener() {}, removeEventListener() {},
};
global.__root = mkEl("root");
global.localStorage = { getItem: () => null, setItem() {} };
global.setInterval = () => 0; // no-op so the 30s status poll doesn't hang the process

const skill = (name, origin, agent) => ({
  id: "skill:" + name, target_type: "skill", target_key: name, cat: "skill",
  detail: "技能", conf: 2, when: "今天", originId: "—", origin: "Hermes", session_id: null,
  raw: { who: "Hermes", parts: ["x"] }, extract: [name], classify: ["技能", "x"],
  active: 0, versions: [{ v: "v1", kind: "auto", who: "H", when: "今天", value: name }],
  pinned: false, annotation: null, is_agent_created: agent, origin_type: origin,
});
const RECS = {
  count: 4,
  cats: [{ k: "memory", label: "記憶" }, { k: "skill", label: "技能" }, { k: "pref", label: "偏好" }],
  skill_summary: { total: 3, agent_created: 1, hermes_official: 1, community: 1 },
  records: [
    { id: "user:e1", target_type: "user", target_key: "e1", cat: "pref", detail: "d", conf: 3,
      when: "今天", originId: "—", origin: "memory", session_id: null,
      raw: { who: "你", parts: ["x"] }, extract: ["pref"], classify: ["偏好", "x"], active: 0,
      versions: [{ v: "v1", kind: "auto", who: "H", when: "今天", value: "PREF_ENTRY" }],
      pinned: false, annotation: null },
    skill("AGENT_SKILL", "agent_created", true),
    skill("OFFICIAL_SKILL", "hermes_official", false),
    skill("COMMUNITY_SKILL", "community", false),
  ],
};
global.fetch = async (u) => ({
  ok: true, statusText: "OK",
  json: async () => (u.includes("/status")
    ? { state: "live", label: "live", plugin: { installed: true, enabled: true }, gateway: { known: true, running: true }, last_plugin_hook: null, last_plugin_hook_rel: null }
    : RECS),
});

function allText(node, acc = []) {
  if (!node) return acc;
  if (node.nodeType === 3) { acc.push(node.text); return acc; }
  if (node._html) acc.push(node._html);
  for (const c of node.children || []) allText(c, acc);
  return acc;
}

const code = fs.readFileSync(path.join(__dirname, "..", "ui", "app.js"), "utf8");
const checks = [];
function assert(cond, msg) { checks.push([cond, msg]); }

const harness = `
;(async function(){
  // wait for loadRecords() (async fetch) to populate state + render
  await new Promise(function(r){ setTimeout(r, 30); });
  // default filter = all → skills shown must be only agent-created
  S.filter = "all"; renderRailList();
  const t1 = TEXT(D.list);
  ASSERT(t1.includes("AGENT_SKILL"), "agent skill visible under 全部");
  ASSERT(!t1.includes("OFFICIAL_SKILL"), "official skill hidden under 全部");
  ASSERT(!t1.includes("COMMUNITY_SKILL"), "community skill hidden under 全部");
  ASSERT(t1.includes("PREF_ENTRY"), "memory/pref entry still visible");
  // 技能 filter → only agent skill + summary hint
  S.filter = "skill"; renderRailList();
  const t2 = TEXT(D.list);
  ASSERT(t2.includes("AGENT_SKILL"), "agent skill visible under 技能");
  ASSERT(!t2.includes("OFFICIAL_SKILL") && !t2.includes("COMMUNITY_SKILL"), "non-agent skills hidden under 技能");
  ASSERT(t2.join("").includes("1 / 3"), "summary shows 1/3");
  // empty-state when no agent skills
  S.records = S.records.filter(function(r){return r.target_type!=="skill" || !r.is_agent_created;});
  renderRailList();
  const t3 = TEXT(D.list);
  ASSERT(t3.join("").includes("目前沒有新沉澱的 skills"), "empty state message shown");
  DONE();
})();
`;

global.TEXT = (n) => allText(n);
global.ASSERT = assert;
let done = false;
global.DONE = () => { done = true;
  const fails = checks.filter(([c]) => !c);
  for (const [c, m] of checks) console.log((c ? "  ok  " : " FAIL ") + m);
  if (fails.length) { console.error("\n" + fails.length + " checks FAILED"); process.exit(1); }
  console.log("\nAll " + checks.length + " UI-filter checks passed.");
};

try { eval(code + harness); } catch (e) { console.error("ERROR:", e); process.exit(1); }
setTimeout(() => { if (!done) { console.error("harness did not complete"); process.exit(1); } }, 100);
