"""Hermes Loom CLI — bootstrap, sync, and run the local API.

Usage:
  python -m hermes_loom.cli bootstrap     # import current memory + skills
  python -m hermes_loom.cli ingest        # backfill growth events from state.db
  python -m hermes_loom.cli reconcile     # run snapshot-diff fallback now
  python -m hermes_loom.cli sync          # ingest + reconcile (full refresh)
  python -m hermes_loom.cli serve [--host H] [--port P]
  python -m hermes_loom.cli status        # show counts
"""

from __future__ import annotations

import argparse
import logging
import sys

from . import api, compiler, config, ingest, snapshot
from .ledger import Ledger


def _cmd_bootstrap(args):
    led = Ledger()
    print(snapshot.bootstrap(led, force=args.force))
    led.close()


def _cmd_ingest(args):
    led = Ledger()
    print(ingest.ingest_state_db(led))
    led.close()


def _cmd_reconcile(args):
    led = Ledger()
    res = snapshot.reconcile_all(led)
    print({k: len(v) for k, v in res.items()})
    led.close()


def _cmd_sync(args):
    led = Ledger()
    snapshot.bootstrap(led)
    ing = ingest.ingest_state_db(led)
    rec = snapshot.reconcile_all(led)
    print({"ingest": ing, "reconcile": {k: len(v) for k, v in rec.items()}})
    led.close()


def _cmd_status(args):
    led = Ledger()
    c = led.conn.execute("SELECT count(*) FROM growth_events").fetchone()[0]
    by_kind = led.conn.execute(
        "SELECT kind, count(*) FROM growth_events GROUP BY kind ORDER BY 2 DESC"
    ).fetchall()
    print(f"ledger: {led.db_path}")
    print(f"growth_events: {c}")
    for k, n in by_kind:
        print(f"  {k}: {n}")
    led.close()


def _cmd_compile(args):
    from pathlib import Path
    led = Ledger()
    try:
        as_of = compiler.parse_as_of(args.as_of)
        # Refresh snapshots from the live files first so compile reflects the
        # latest state. Skipped for historical (--as-of) compiles or --no-sync.
        if not args.no_sync and as_of is None:
            snapshot.bootstrap(led)
            ingest.ingest_state_db(led)
            snapshot.reconcile_all(led)
            print("synced (refreshed snapshots from current Hermes files)")
        if args.in_place:
            res = compiler.compile_in_place(led, as_of=as_of)
        else:
            res = compiler.compile_to_dir(led, Path(args.out), as_of=as_of)
    finally:
        led.close()
    print(f"compiled {res['files']} file(s) [{res['mode']}]")
    if res["mode"] == "dir":
        print(f"  -> {res['out_dir']}")
    if res.get("backups"):
        print(f"  backed up {len(res['backups'])} existing file(s) to {config.file_backup_dir()}")
    if res["missing"]:
        print(f"  missing (no snapshot): {len(res['missing'])} — {', '.join(res['missing'][:5])}"
              + (" …" if len(res['missing']) > 5 else ""))


def _cmd_serve(args):
    api.serve(host=args.host, port=args.port)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config.load_hermes_dotenv()   # pick up LOOM_LLM_* etc. from ~/.hermes/.env
    p = argparse.ArgumentParser(prog="hermes-loom")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("bootstrap"); b.add_argument("--force", action="store_true"); b.set_defaults(fn=_cmd_bootstrap)
    sub.add_parser("ingest").set_defaults(fn=_cmd_ingest)
    sub.add_parser("reconcile").set_defaults(fn=_cmd_reconcile)
    sub.add_parser("sync").set_defaults(fn=_cmd_sync)
    sub.add_parser("status").set_defaults(fn=_cmd_status)
    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(fn=_cmd_serve)

    cp = sub.add_parser("compile", help="rebuild MEMORY.md/USER.md/SKILL.md from the ledger snapshots")
    cp.add_argument("--out", default="./loom-export", help="output dir (default; safe, never touches ~/.hermes)")
    cp.add_argument("--in-place", action="store_true", help="overwrite the real Hermes files (backs up each first)")
    cp.add_argument("--as-of", default=None, help="compile historical state: epoch or 'YYYY-MM-DD[ HH:MM]'")
    cp.add_argument("--no-sync", action="store_true", help="skip the pre-compile sync (don't refresh snapshots first)")
    cp.set_defaults(fn=_cmd_compile)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main(sys.argv[1:])
