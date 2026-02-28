#!/usr/bin/env sh
set -eu

cd /var/www/html

if [ "${DB_CONNECTION:-sqlite}" = "sqlite" ]; then
  mkdir -p database
  touch database/database.sqlite
fi

if [ -z "${APP_KEY:-}" ]; then
  echo "APP_KEY is missing. Load it from ./app/.env via docker compose env_file." >&2
  exit 1
fi

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
  php artisan migrate --force --no-interaction || true
fi

exec "$@"
