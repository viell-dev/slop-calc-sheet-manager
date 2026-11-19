#!/usr/bin/env bash
# The #294 probe's container entry point: `ci/linux-session.sh` and `ci/desktop-session.sh`,
# with the probe's runner in place of the UI suite. Measurement only.
set -euo pipefail
if [[ "${1:-}" != "--inner" ]]; then
    unset WAYLAND_DISPLAY
    mkdir -p /results "$HOME"
    cp /opt/ci-metadata/* /results/
    /opt/lo/program/soffice --version | tee /results/office-version.txt
    exec xvfb-run --auto-servernum --server-args='-screen 0 1600x1000x24 -nolisten tcp' \
        env SHEET_MANAGER_PRIVATE_DISPLAY=1 dbus-run-session -- bash "$0" --inner "$@"
fi
shift
openbox > /results/window-manager.log 2>&1 &
manager=$!
trap 'kill "$manager" 2>/dev/null || true; wait "$manager" 2>/dev/null || true' EXIT
for attempt in {1..100}; do
    if xprop -root _NET_SUPPORTING_WM_CHECK | grep -q 'window id'; then
        break
    fi
    sleep 0.1
done
/opt/lo/program/python "$(dirname "$0")/runner.py" \
    --program /opt/lo/program --oxt /packages/extension.oxt --output /results "$@"
