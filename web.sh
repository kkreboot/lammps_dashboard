#!/usr/bin/env bash
# Launch LAMMPS Dashboard — browser version
cd "$(dirname "$(realpath "$0")")"
PORT="${1:-5000}"
echo "LAMMPS Dashboard (web) → http://localhost:$PORT"
echo "Open this URL in your browser. Press Ctrl+C to stop."
exec "$(dirname "$(realpath "$0")")/venv/bin/python" app.py
