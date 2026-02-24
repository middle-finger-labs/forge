import { auth } from "./auth.js";
import { Hono } from "hono";
import { cors } from "hono/cors";
import { serve } from "@hono/node-server";

// Re-export for any module that was importing from server.ts
export { auth };
export type { Auth } from "./auth.js";

// ---------------------------------------------------------------------------
// Hono HTTP server
// ---------------------------------------------------------------------------
const app = new Hono();

// CORS — allow dashboard origins
app.use(
  "/*",
  cors({
    origin: [
      "http://localhost:3000",
      "http://localhost:5173",
    ],
    credentials: true,
    allowHeaders: ["Content-Type", "Authorization"],
    allowMethods: ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
  }),
);

// Health check
app.get("/health", (c) =>
  c.json({
    status: "ok",
    service: "forge-auth",
    timestamp: new Date().toISOString(),
  }),
);

// Mount Better Auth handler — catches all /api/auth/* routes
app.on(["POST", "GET"], "/api/auth/**", (c) => {
  return auth.handler(c.req.raw);
});

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------
const port = Number(process.env.PORT ?? 3100);

serve({ fetch: app.fetch, port }, () => {
  console.log(`forge-auth listening on http://0.0.0.0:${port}`);
});
