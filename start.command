#!/bin/bash
# macOS: double-click to start SpecForge locally and open the browser. Close this window to stop.
cd "$(dirname "$0")"
[ -f frontend/dist/index.html ] || (cd frontend && npm install && npm run build)
[ -f examples/sdtm/spec_final.xlsx ] || python3 examples/make_examples.py
(sleep 3 && open "http://127.0.0.1:8000") &
python3 -m uvicorn specforge.api.app:app --app-dir backend --port 8000
