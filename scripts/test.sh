#!/bin/bash
set -e
cd "$(dirname "$0")/.."

# Run the repository test suite.
# Requires the local .venv to exist with project dependencies installed.

export QT_QPA_PLATFORM=offscreen

echo "Running tests..."
./.venv/Scripts/python.exe -m pytest
echo "Tests completed."
