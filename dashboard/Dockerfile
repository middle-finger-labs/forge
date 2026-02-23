# Stage 1: Build the React app
FROM node:22-alpine AS build
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

# Build-time env vars for Vite (baked into the JS bundle)
ARG VITE_API_URL=""
ARG VITE_AUTH_URL=""
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_AUTH_URL=$VITE_AUTH_URL

COPY . .
RUN npm run build

# Stage 2: Serve with nginx
FROM nginx:1.27-alpine

# Copy built assets
COPY --from=build /app/dist /usr/share/nginx/html

# Copy both configs: static for Docker Compose, template for Railway
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

# Runtime env vars for nginx template (envsubst at startup)
# Docker Compose defaults — override these in Railway service settings
ENV NGINX_PORT=80
ENV API_BACKEND_HOST=forge-api:8000
ENV API_AUTH_HOST=forge-auth:3100

EXPOSE ${NGINX_PORT}

# If RAILWAY_ENVIRONMENT is set, use the template (envsubst).
# Otherwise use the static config for Docker Compose.
CMD ["/bin/sh", "-c", \
  "if [ -n \"$RAILWAY_ENVIRONMENT\" ]; then \
     envsubst '${NGINX_PORT} ${API_BACKEND_HOST} ${API_AUTH_HOST}' \
       < /etc/nginx/templates/default.conf.template \
       > /etc/nginx/conf.d/default.conf; \
   fi && nginx -g 'daemon off;'"]
