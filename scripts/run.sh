#!/bin/bash
set -e
cd "$(dirname "$0")/.."

# Run the BioBot desktop application.
# Requires the local .venv to exist with project dependencies installed.

./.venv/Scripts/python.exe main.py
