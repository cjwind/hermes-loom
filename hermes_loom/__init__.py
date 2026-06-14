"""Hermes Loom — a local growth-observability & tuning sidecar for Hermes Agent.

See README.md. Public surface:
  * ledger.Ledger          — the append-only growth ledger
  * observer.Observer      — turns "Hermes changed X" into ledger events
  * plugin.register        — Hermes plugin entrypoint
  * api.serve              — local HTTP API + UI
"""

__version__ = "0.1.0"
