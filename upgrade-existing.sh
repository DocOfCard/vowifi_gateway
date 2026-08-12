#!/bin/sh
set -eu

SRC=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TARGET=${1:-"$HOME/vowifi_gateway"}

[ -f "$TARGET/install.sh" ] || { echo "target does not look like vowifi_gateway: $TARGET" >&2; exit 1; }
command -v rsync >/dev/null 2>&1 || { echo "rsync is required" >&2; exit 1; }

STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="$TARGET/local-upgrade-backup-$STAMP.tar.gz"

tar -C "$TARGET" -czf "$BACKUP" \
  install.sh host control/app/config.py control/app/lpa.py control/app/sim.py control/app/main.py \
  control/Dockerfile webui/src/views/SimConfig.jsx webui/src/views/Dashboard.jsx \
  engine/swu_ike.py engine/render.py engine/entrypoint.sh 2>/dev/null || true

echo "backup: $BACKUP"
rsync -a \
  --exclude '.git/' \
  --exclude 'data/' \
  --exclude 'webui/node_modules/' \
  --exclude 'control/.venv/' \
  "$SRC/" "$TARGET/"
chmod +x "$TARGET/install.sh" "$TARGET/host/modem_sim_bridge.py"

echo "source update complete"
echo "next:"
echo "  cd $TARGET"
echo "  sudo ./install.sh reload --mode docker --engines"
echo "  sudo ./install.sh modem-bridge 0"
