#!/bin/bash
# ─────────────────────────────────────────
# Toolbox Launcher
# Double-click this file to start Toolbox.
# ─────────────────────────────────────────

# cd to the directory where this script lives
cd "$(dirname "$0")"

echo ""
echo "  ⚡ Toolbox — Starting up…"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "  ❌ Python 3 not found. Install it from python.org."
    echo "  Press any key to close."
    read -n 1
    exit 1
fi

# Install dependencies if needed
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "  📦 Installing dependencies…"
    pip3 install -r requirements.txt --break-system-packages 2>/dev/null || \
    pip3 install -r requirements.txt
    echo ""
fi

# Launch
echo "  🚀 Opening http://localhost:8400 in your browser…"
echo "  Press Ctrl+C to stop the server."
echo ""

# Open browser after a short delay
(sleep 2 && open "http://localhost:8400") &

# Start the server
python3 server.py
