#!/bin/bash
# Start the enquiry backend. Used by Supervisor (deploy/prakd-backend.supervisor.conf).
# Optional settings (Telegram) come from deploy/local.env, which is not in git.
cd "$(dirname "$0")"
if [ -f ../deploy/local.env ]; then set -a; . ../deploy/local.env; set +a; fi
export PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
exec .venv/bin/uvicorn main:app --host 127.0.0.1 --port "${PORT:-8788}" --no-access-log
