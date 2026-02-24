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

# Copy the template and startup script
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY start.sh /start.sh
RUN chmod +x /start.sh

# Runtime env vars (defaults match Docker Compose service names;
# override in Railway service settings for private networking)
ENV API_BACKEND_HOST=forge-api:8000
ENV API_AUTH_HOST=forge-auth:3100

EXPOSE 80

CMD ["/start.sh"]
