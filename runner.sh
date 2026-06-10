#!/bin/bash
# Runner script for Call Agent UI

cd "$(dirname "${BASH_SOURCE[0]}")"

# Ensure venv exists
if [ ! -d ".venv" ]; then
    echo "Virtual environment not found. Please run the setup instructions."
    exit 1
fi

source .venv/bin/activate
export $(grep -v '^#' .env | xargs)

# Execute the UI
python ui_main.py
