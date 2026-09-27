#!/bin/bash
# Lanzador idempotente: jamás dos suites en paralelo (contaminan cashbox/TOTP)
if pgrep -f "make test-critical" > /dev/null; then
  echo "already-running"
  exit 0
fi
cd /app
set -a; . ./backend/.env; set +a
nohup make test-critical > /tmp/test_critical_304.log 2>&1 &
echo "started $!"
