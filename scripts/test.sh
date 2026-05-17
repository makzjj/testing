#!/bin/bash
set -e
cd "$(dirname "$0")/.."

# Run the repository unit tests.
# Requires the local .venv to exist with project dependencies installed.

export QT_QPA_PLATFORM=offscreen

echo "Running unit tests..."
./.venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py"
echo "Tests completed."
