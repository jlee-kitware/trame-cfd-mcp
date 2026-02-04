#!/bin/bash
# Setup and run CFD Assistant example
#
# Prerequisites:
#   - ParaView 6 build at $PV_BUILD (or modify path below)
#   - Python 3.10+ matching ParaView's Python
#
# Usage:
#   ./run.sh              # Run with mock LLM
#   ./run.sh --openai     # Run with OpenAI (needs OPENAI_API_KEY)

set -e

# Configuration - adjust these paths as needed
PV_BUILD="${PV_BUILD:-/Users/jeff.lee/gitsync/paraview_build}"
PVPYTHON="$PV_BUILD/bin/pvpython"

# Check pvpython exists
if [ ! -f "$PVPYTHON" ]; then
    echo "Error: pvpython not found at $PVPYTHON"
    echo "Set PV_BUILD environment variable to your ParaView build directory"
    exit 1
fi

# Create venv if needed (matching ParaView's Python version)
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    PY_VERSION=$($PVPYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    python$PY_VERSION -m venv .venv
    
    echo "Installing dependencies..."
    source .venv/bin/activate
    pip install -q trame trame-vuetify trame-vtk
    pip install -q /Users/jeff.lee/gitsync/trame-llm
    pip install -q -e /Users/jeff.lee/gitsync/paraview_llm[openai]
    deactivate
fi

# Run the test
echo ""
echo "Running integration test..."
echo "ParaView: $PV_BUILD"
echo "Python venv: .venv"
echo ""

$PVPYTHON --venv .venv test_integration.py
