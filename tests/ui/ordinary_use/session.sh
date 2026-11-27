#!/usr/bin/env bash
# The container's entry: ci/linux-session.sh's display, with this harness as the runner.
set -euo pipefail
unset WAYLAND_DISPLAY
mkdir -p /results "$HOME"
cp /opt/ci-metadata/* /results/
/opt/lo/program/soffice --version > /results/office-version.txt
exec xvfb-run --auto-servernum --server-args='-screen 0 1600x1000x24 -nolisten tcp' \
    env SHEET_MANAGER_PRIVATE_DISPLAY=1 dbus-run-session -- bash /harness/desktop.sh "$@"
