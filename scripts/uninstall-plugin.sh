#!/usr/bin/env bash
# Uninstall the Hermes Loom plugin from a Hermes install.
#
# The reverse of install-plugin.sh: disable the plugin (best-effort, if the
# `hermes` CLI is available) and remove $HERMES_HOME/plugins/<name>/. Your Loom
# ledger in $LOOM_HOME is left untouched.
#
# Usage:
#   scripts/uninstall-plugin.sh                 # remove from local ~/.hermes
#   scripts/uninstall-plugin.sh <ssh-host>      # remove from a remote (e.g. rpi)
#   HERMES_HOME=/custom/.hermes scripts/uninstall-plugin.sh
#
# Env:
#   PLUGIN_NAME   directory name under plugins/ (default: hermes-loom)
set -euo pipefail

PLUGIN_NAME="${PLUGIN_NAME:-hermes-loom}"
SSH_HOST="${1:-}"

if [[ -z "$SSH_HOST" ]]; then
  DEST="${HERMES_HOME:-$HOME/.hermes}/plugins/$PLUGIN_NAME"
  # Safety: only ever remove a .../plugins/<PLUGIN_NAME> directory.
  case "$DEST" in
    */plugins/"$PLUGIN_NAME") ;;
    *) echo "Refusing to remove unexpected path: $DEST" >&2; exit 1 ;;
  esac
  if [[ ! -d "$DEST" ]]; then
    echo "Not installed: $DEST not found — nothing to do."
    exit 0
  fi
  echo "Removing $DEST"
  if command -v hermes >/dev/null 2>&1; then
    hermes plugins disable "$PLUGIN_NAME" || true
  fi
  rm -rf "$DEST"
  echo "Removed. Restart the gateway to unload it:"
  echo "  hermes gateway restart   # or restart however you run Hermes"
else
  REMOTE_HOME='${HERMES_HOME:-$HOME/.hermes}'
  DEST="$REMOTE_HOME/plugins/$PLUGIN_NAME"
  echo "Removing $SSH_HOST:$DEST"
  # shellcheck disable=SC2029
  ssh "$SSH_HOST" "
    set -e
    DEST=\"$DEST\"
    case \"\$DEST\" in
      */plugins/$PLUGIN_NAME) ;;
      *) echo \"Refusing to remove unexpected path: \$DEST\" >&2; exit 1 ;;
    esac
    if [ ! -d \"\$DEST\" ]; then echo \"Not installed: \$DEST not found — nothing to do.\"; exit 0; fi
    command -v hermes >/dev/null 2>&1 && hermes plugins disable \"$PLUGIN_NAME\" || true
    rm -rf \"\$DEST\"
    echo \"Removed \$DEST\"
  "
  echo "Done. On $SSH_HOST, restart the gateway:"
  echo "  ssh $SSH_HOST 'hermes gateway restart'"
fi
