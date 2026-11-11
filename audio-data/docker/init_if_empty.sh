#!/bin/sh
set -eu
if uv run --no-sync python -c "from app.database import fetch_one; r=fetch_one('SELECT COUNT(*) AS n FROM audio_album'); raise SystemExit(0 if r and r['n'] >= 1000 else 1)"; then
  echo 'audio_data already contains the full sample set; keeping the persistent database.'
else
  uv run --no-sync python init_db.py
  uv run --no-sync -m generate.main --profile full
fi
