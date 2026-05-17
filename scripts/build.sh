#!/bin/bash
set -e
cd "$(dirname "$0")/.."

# Build check for the current Python desktop workspace application.
# Requires the local .venv to exist with project dependencies installed.

echo "Running Python compile checks..."
./.venv/Scripts/python.exe -m compileall main.py gui myconfig tests
echo "Build check completed."
