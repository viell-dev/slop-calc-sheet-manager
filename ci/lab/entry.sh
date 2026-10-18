#!/usr/bin/env bash
set -euo pipefail
unset WAYLAND_DISPLAY
mkdir -p /results "$HOME"
/opt/lo/program/soffice --version > /results/office-version.txt
exec xvfb-run --auto-servernum --server-args='-screen 0 1600x1000x24 -nolisten tcp' \
    dbus-run-session -- bash /lab/desktop.sh "$@"
