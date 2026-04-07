#!/bin/bash
# Run CFD Assistant example
#
# Prerequisites:
#   - ParaView 6 build with pvpython
#   - Set PV_BUILD to your ParaView build directory, or add pvpython to PATH
#   - trame-llm installed or TRAME_LLM_SRC set (see README)
#
# Usage:
#   export PV_BUILD=/path/to/paraview_build
#   ./run.sh [your_data.vtm]
#   ./run.sh --pvserver=localhost:11111 [your_data.vtm]
#   ./run.sh --live

set -e

# Find pvpython
if [ -n "$PV_BUILD" ]; then
    PVPYTHON="$PV_BUILD/bin/pvpython"
elif command -v pvpython &>/dev/null; then
    PVPYTHON="pvpython"
else
    echo "Error: pvpython not found."
    echo "Set PV_BUILD=/path/to/paraview_build or add pvpython to PATH."
    exit 1
fi

if [ ! -f "$PVPYTHON" ] && [ "$PVPYTHON" != "pvpython" ]; then
    echo "Error: pvpython not found at $PVPYTHON"
    exit 1
fi

echo "Using: $PVPYTHON"
echo ""

exec "$PVPYTHON" cfd_chat.py "$@"
