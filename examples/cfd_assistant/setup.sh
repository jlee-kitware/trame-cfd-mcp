#!/bin/bash
# Setup script for CFD Assistant with local ParaView build
#
# Usage:
#   source setup.sh
#   python app.py

# Path to your ParaView build
export PV_BUILD=/Users/jeff.lee/gitsync/paraview_build
export PVPYTHON=$PV_BUILD/bin/pvpython

# Create venv if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate
source .venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -q trame-llm
pip install -q -e /Users/jeff.lee/gitsync/paraview_llm[openai]

# Instructions
echo ""
echo "Setup complete!"
echo ""
echo "To run with local ParaView build:"
echo "  $PVPYTHON --venv $PWD/.venv app.py"
echo ""
echo "Or if trame-components is installed in your ParaView:"
echo "  python app.py"
echo ""
echo "Make sure to set OPENAI_API_KEY or use llm_provider='mock'"
