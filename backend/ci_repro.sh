#!/usr/bin/env bash
# Reproduce el job backend-tests de CI lo más fielmente posible: Mongo local,
# DB_NAME fresca y vacía, seeds, uvicorn propio en 8011, make test-critical.
set -uo pipefail
cd /app/backend

export MONGO_URL="mongodb://localhost:27017"
export DB_NAME="resilience_ci_repro"
export REACT_APP_BACKEND_URL="http://localhost:8011"
export EMERGENT_LLM_KEY="ci-placeholder"
export TOTP_MASTER_KEY="DCsJczEUBaU7PrVwn3qe7HIM0yaOaQwxc2a2STel5Ps="
export JWT_SECRET="ci_jwt_secret_change_me"
export APP_PUBLIC_URL="http://localhost:8011"
export CORS_ORIGINS="http://localhost:8011,http://localhost:3000"
export RATE_LIMIT_ENABLED="false"
export APP_AUTO_BLOCK_ENABLED="false"
export COOKIE_SECURE="false"
export GOOGLE_CLIENT_ID="ci-placeholder.apps.googleusercontent.com"
export GOOGLE_CLIENT_SECRET="ci-placeholder"
export RESEND_API_KEY="re_ci_placeholder"
export STORAGE_PROVIDER="none"
export VAPID_PUBLIC_KEY="BJD0_ci_placeholder"
export VAPID_PRIVATE_KEY="ci_placeholder"
export VAPID_SUBJECT="mailto:ci@example.com"
export SENTRY_DSN=""

echo "=== drop fresh DB ==="
python -c "from pymongo import MongoClient; MongoClient('$MONGO_URL').drop_database('$DB_NAME'); print('dropped $DB_NAME')"

echo "=== seed users + rates ==="
python scripts/seed_test_users.py && python scripts/seed_test_rates.py || { echo "SEED FAILED"; exit 1; }

echo "=== start uvicorn :8011 ==="
pkill -f "uvicorn server:app --host 0.0.0.0 --port 8011" 2>/dev/null
nohup uvicorn server:app --host 0.0.0.0 --port 8011 > /tmp/ci_repro_uvicorn.log 2>&1 &
UV_PID=$!
for i in $(seq 1 40); do
  if curl -fsS http://localhost:8011/api/ > /dev/null 2>&1; then echo "FastAPI up"; break; fi
  sleep 1
done
if ! curl -fsS http://localhost:8011/api/ > /dev/null 2>&1; then
  echo "FastAPI never came up"; tail -n 40 /tmp/ci_repro_uvicorn.log; kill $UV_PID 2>/dev/null; exit 1
fi

echo "=== make test-critical (fresh DB) ==="
make -C /app test-critical
RC=$?
echo "=== pytest RC=$RC ==="
kill $UV_PID 2>/dev/null
exit $RC
