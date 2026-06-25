#!/bin/bash
# Setup script for CFD Assistant (development mode)
#
# Usage:
#   export PV_BUILD=/path/to/paraview_build
#   source setup.sh

if [ -z "$PV_BUILD" ]; then
    echo "Error: PV_BUILD not set."
    echo "  export PV_BUILD=/path/to/paraview_build"
    return 1
fi

export PVPYTHON="$PV_BUILD/bin/pvpython"

if [ ! -f "$PVPYTHON" ]; then
    echo "Error: pvpython not found at $PVPYTHON"
    return 1
fi

# Create venv if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate

echo "Installing dependencies..."
pip install -q trame trame-vuetify trame-vtk trame-plotly python-dotenv fastmcp openai

# trame-llm: install from pip (when published) or from local clone
if [ -n "$TRAME_LLM_SRC" ]; then
    pip install -q -e "$TRAME_LLM_SRC"
else
    echo ""
    echo "Note: trame-llm not found. Either:"
    echo "  pip install trame-llm"
    echo "  or set TRAME_LLM_SRC=/path/to/trame-llm and re-run setup.sh"
fi

echo ""
echo "Setup complete. To run:"
echo "  \$PVPYTHON cfd_chat.py [your_data.vtm]"
echo ""
echo "Copy .env.example to .env and set your API key (or use Ollama)."
