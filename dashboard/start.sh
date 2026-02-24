#!/bin/sh
set -e

NGINX_PORT="${PORT:-80}"

# Detect DNS resolver from /etc/resolv.conf (works on Railway + Docker)
NGINX_RESOLVER=$(awk '/^nameserver/{print $2; exit}' /etc/resolv.conf || echo "8.8.8.8")

export NGINX_PORT API_BACKEND_HOST API_AUTH_HOST NGINX_RESOLVER

echo "Starting nginx on port ${NGINX_PORT}"
echo "  API backend: ${API_BACKEND_HOST}"
echo "  Auth host:   ${API_AUTH_HOST}"
echo "  Resolver:    ${NGINX_RESOLVER}"

envsubst '${NGINX_PORT} ${API_BACKEND_HOST} ${API_AUTH_HOST} ${NGINX_RESOLVER}' \
  < /etc/nginx/templates/default.conf.template \
  > /etc/nginx/conf.d/default.conf

cat /etc/nginx/conf.d/default.conf | head -3

exec nginx -g 'daemon off;'
