# Demo: the full growth → observe → tune loop (sandboxed)

This reproduces the README end-to-end example against a throwaway sandbox, so your
real `~/.hermes` is never touched.

```bash
# 0. Sandbox dirs
export HERMES_HOME=/tmp/demo/hermes LOOM_HOME=/tmp/demo/loom LOOM_DB=/tmp/demo/loom/ledger.db
rm -rf /tmp/demo && mkdir -p $HERMES_HOME/memories $HERMES_HOME/skills

# 1. Simulate "Hermes grew": Hermes writes USER.md natively AND logs a `memory`
#    tool call in state.db. (In reality Hermes does this for you.)
python3 - <<'PY'
import os, sqlite3, json
home=os.environ["HERMES_HOME"]
con=sqlite3.connect(home+"/state.db")
con.executescript("""
CREATE TABLE sessions(id TEXT PRIMARY KEY, source TEXT, user_id TEXT, title TEXT,
  started_at REAL, ended_at REAL, message_count INTEGER, cwd TEXT);
CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT,
  content TEXT, tool_call_id TEXT, tool_calls TEXT, tool_name TEXT, timestamp REAL);
""")
con.execute("INSERT INTO sessions(id,source,title,started_at) VALUES('sess-demo','api_server','Tea chat',100)")
tc=json.dumps([{"call_id":"c1","function":{"name":"memory",
  "arguments":json.dumps({"action":"add","target":"user","content":"User likes oolong tea."})}}])
con.execute("INSERT INTO messages(session_id,role,content,timestamp) VALUES('sess-demo','user','remember I like oolong tea',101)")
con.execute("INSERT INTO messages(session_id,role,content,tool_calls,timestamp) VALUES('sess-demo','assistant','',?,102)",(tc,))
con.execute("INSERT INTO messages(session_id,role,content,tool_call_id,tool_name,timestamp) VALUES('sess-demo','tool',?,'c1','memory',102.5)",
            (json.dumps({"success":True,"message":"Entry added."}),))
con.commit(); con.close()
open(home+"/memories/USER.md","w").write("User likes oolong tea.")
print("seeded")
PY

# 2. Loom records the growth event (with provenance)
python3 -m hermes_loom.cli sync
python3 -m hermes_loom.cli status

# 3. Serve + open the UI
python3 -m hermes_loom.cli serve --port 8765 &
# open http://127.0.0.1:8765/  -> Recent Growth -> click the event

# 4. Tune it (what the UI's Edit button does)
python3 - <<'PY'
from hermes_loom.ledger import Ledger
from hermes_loom import service
l=Ledger()
key=service.current_memory(l)["user"]["entries"][0]["key"]
print(service.apply_memory_edit(l,"user",key,"User loves oolong and pu-erh tea.",reason="more specific"))
PY

# 5. Confirm the underlying file really changed
cat $HERMES_HOME/memories/USER.md
#   -> User loves oolong and pu-erh tea.
```

Expected `status` after step 2:

```
growth_events: 2
  memory_snapshot_imported: 1   # USER.md imported as historical
  memory_added: 1               # the real growth, source_hint=statedb_ingest
```

After step 4 a `memory_replaced` event (`source_hint=manual_override`) and a
`manual_overrides` row are added, and a backup lands in `$LOOM_HOME/backups/`.
