#!/bin/sh
set -e

NGINX_PORT="${PORT:-80}"
export NGINX_PORT API_BACKEND_HOST API_AUTH_HOST

echo "Starting nginx on port ${NGINX_PORT}"
echo "  API backend: ${API_BACKEND_HOST}"
echo "  Auth host:   ${API_AUTH_HOST}"

envsubst '${NGINX_PORT} ${API_BACKEND_HOST} ${API_AUTH_HOST}' \
  < /etc/nginx/templates/default.conf.template \
  > /etc/nginx/conf.d/default.conf

cat /etc/nginx/conf.d/default.conf | head -3

exec nginx -g 'daemon off;'
