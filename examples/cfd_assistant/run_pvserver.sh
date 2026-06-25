#!/bin/bash
# Start pvserver + CFD Assistant together.
#
# Usage:
#   ./run_pvserver.sh [your_data.vtm] [extra args...]
#   ./run_pvserver.sh test.vtm
#   ./run_pvserver.sh --live test.vtm
#
# Starts pvserver on localhost:11111, waits until it is ready, then
# launches cfd_chat.py with --pvserver=localhost:11111.
# Kills pvserver when the assistant exits.

set -e

PVSERVER_PORT=11111
PVSERVER_HOST=localhost

# Find ParaView binaries
if [ -n "$PV_BUILD" ]; then
    PVPYTHON="$PV_BUILD/bin/pvpython"
    PVSERVER="$PV_BUILD/bin/pvserver"
else
    PVPYTHON="${PARAVIEW_BUILD:-/Users/jeff.lee/gitsync/paraview_build}/bin/pvpython"
    PVSERVER="${PARAVIEW_BUILD:-/Users/jeff.lee/gitsync/paraview_build}/bin/pvserver"
fi

if [ ! -f "$PVPYTHON" ]; then
    echo "Error: pvpython not found at $PVPYTHON"
    echo "Set PV_BUILD=/path/to/paraview_build"
    exit 1
fi

if [ ! -f "$PVSERVER" ]; then
    echo "Error: pvserver not found at $PVSERVER"
    exit 1
fi

# Start pvserver in background with offscreen rendering to avoid Cocoa windows
# on macOS. --force-offscreen-rendering makes pvserver render headless; the
# client (pvpython) communicates via JPEG streaming and never creates native windows.
echo "Starting pvserver on $PVSERVER_HOST:$PVSERVER_PORT ..."
"$PVSERVER" --server-port=$PVSERVER_PORT --force-offscreen-rendering &
PVSERVER_PID=$!

# Kill pvserver when this script exits (normal or ctrl-c)
trap "echo 'Stopping pvserver (pid $PVSERVER_PID)...'; kill $PVSERVER_PID 2>/dev/null; wait $PVSERVER_PID 2>/dev/null" EXIT

# Wait until pvserver is accepting connections (up to 30s)
echo -n "Waiting for pvserver..."
for i in $(seq 1 30); do
    if nc -z $PVSERVER_HOST $PVSERVER_PORT 2>/dev/null; then
        echo " ready."
        break
    fi
    if ! kill -0 $PVSERVER_PID 2>/dev/null; then
        echo ""
        echo "Error: pvserver exited unexpectedly."
        exit 1
    fi
    echo -n "."
    sleep 1
done

if ! nc -z $PVSERVER_HOST $PVSERVER_PORT 2>/dev/null; then
    echo ""
    echo "Error: pvserver did not become ready within 30s."
    exit 1
fi

echo "Using: $PVPYTHON"
echo ""

# Launch assistant, forwarding all args, injecting --pvserver
exec "$PVPYTHON" cfd_chat.py --pvserver=$PVSERVER_HOST:$PVSERVER_PORT "$@"
