# Forge Auth service (Better Auth + Hono)
FROM node:20-slim

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install --production=false

COPY . .

# Railway sets PORT dynamically; default 3100 for local Docker Compose
ENV PORT=3100
EXPOSE ${PORT}

CMD ["npx", "tsx", "server.ts"]
