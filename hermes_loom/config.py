"""Central configuration for Hermes Loom.

Everything is resolved from environment variables so the whole stack can be
pointed at a temporary sandbox during tests. Defaults target a real local
Hermes install under ``~/.hermes``.

Three clearly-separated data domains (see README):

  * **Hermes native state** — read (and, for overrides, carefully written) under
    ``HERMES_HOME``. Never owned by Loom.
  * **Hermes Loom ledger** — an independent SQLite DB at ``LOOM_DB``. Owned by Loom.
  * **UI / review layer** — talks only to the Local API, never to Hermes directly.
"""

from __future__ import annotations

import os
from pathlib import Path


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw).expanduser() if raw else default


def hermes_home() -> Path:
    """Root of the Hermes native install (``~/.hermes`` by default)."""
    return _env_path("HERMES_HOME", Path.home() / ".hermes")


def memories_dir() -> Path:
    return hermes_home() / "memories"


def memory_md_path() -> Path:
    """``MEMORY.md`` — assistant's persistent memory. May not exist yet."""
    return memories_dir() / "MEMORY.md"


def user_md_path() -> Path:
    """``USER.md`` — facts about the user."""
    return memories_dir() / "USER.md"


def skills_dir() -> Path:
    return hermes_home() / "skills"


def state_db_path() -> Path:
    """Hermes session store (read-only from Loom's perspective)."""
    return hermes_home() / "state.db"


def loom_dir() -> Path:
    """Where Loom keeps its own ledger + snapshots."""
    return _env_path("LOOM_HOME", Path.home() / ".hermes-loom")


def loom_db_path() -> Path:
    raw = os.environ.get("LOOM_DB")
    if raw:
        return Path(raw).expanduser()
    return loom_dir() / "ledger.db"


def file_backup_dir() -> Path:
    """Pre-override backups of native Hermes files live here."""
    return loom_dir() / "backups"


# Entry separator used inside MEMORY.md / USER.md (observed in real installs).
MEMORY_ENTRY_SEPARATOR = "§"  # § on its own line


def ui_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "ui"


def load_hermes_dotenv() -> int:
    """Load ``~/.hermes/.env`` into os.environ (stdlib, no python-dotenv).

    So Loom's own `serve`/CLI see the same vars (e.g. LOOM_LLM_*) that the Hermes
    gateway already loads for the plugin. Existing env vars are NOT overridden, so
    an explicit export still wins. Best-effort: never raises.
    """
    import os
    path = hermes_home() / ".env"
    if not path.exists():
        return 0
    loaded = 0
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[7:]
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
                loaded += 1
    except OSError:
        pass
    return loaded
