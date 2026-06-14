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

from . import api, ingest, snapshot
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


def _cmd_serve(args):
    api.serve(host=args.host, port=args.port)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
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

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main(sys.argv[1:])
