#!/usr/bin/env bash
# Install the Hermes Loom plugin into a Hermes install.
#
# `hermes plugins install` only accepts a Git URL / owner-repo, so for a local
# checkout the reliable path is to place this repo into $HERMES_HOME/plugins/<name>/
# and let Hermes discover it via plugin.yaml. This script does that, locally or
# over SSH, then enables it.
#
# Usage:
#   scripts/install-plugin.sh                 # install into local ~/.hermes
#   scripts/install-plugin.sh <ssh-host>      # install onto a remote (e.g. rpi)
#   HERMES_HOME=/custom/.hermes scripts/install-plugin.sh
#
# Env:
#   PLUGIN_NAME   directory name under plugins/ (default: hermes-loom)
set -euo pipefail

PLUGIN_NAME="${PLUGIN_NAME:-hermes-loom}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SSH_HOST="${1:-}"

# Files the plugin needs at runtime (exclude tests/ui/docs/git to stay lean).
INCLUDE=(plugin.yaml __init__.py hermes_loom)

if [[ -z "$SSH_HOST" ]]; then
  DEST="${HERMES_HOME:-$HOME/.hermes}/plugins/$PLUGIN_NAME"
  echo "Installing into $DEST"
  mkdir -p "$DEST"
  for f in "${INCLUDE[@]}"; do
    cp -r "$REPO_DIR/$f" "$DEST/"
  done
  echo "Copied. Now enable + restart the gateway:"
  echo "  hermes plugins enable $PLUGIN_NAME"
  echo "  hermes gateway restart   # or restart however you run Hermes"
else
  REMOTE_HOME='${HERMES_HOME:-$HOME/.hermes}'
  DEST="$REMOTE_HOME/plugins/$PLUGIN_NAME"
  echo "Installing onto $SSH_HOST:$DEST"
  # shellcheck disable=SC2029
  ssh "$SSH_HOST" "mkdir -p \"$DEST\""
  TARBALL="$(mktemp -t loom-plugin-XXXX.tgz)"
  tar -C "$REPO_DIR" -czf "$TARBALL" "${INCLUDE[@]}"
  # shellcheck disable=SC2029
  ssh "$SSH_HOST" "tar -xzf - -C \"$DEST\"" < "$TARBALL"
  rm -f "$TARBALL"
  echo "Copied. On $SSH_HOST, enable + restart the gateway:"
  echo "  ssh $SSH_HOST 'hermes plugins enable $PLUGIN_NAME && hermes gateway restart'"
fi
