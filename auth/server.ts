import { betterAuth } from "better-auth";
import { organization, bearer } from "better-auth/plugins";
import { Pool } from "pg";
import { Hono } from "hono";
import { cors } from "hono/cors";
import { serve } from "@hono/node-server";

// ---------------------------------------------------------------------------
// Database
// ---------------------------------------------------------------------------
const pool = new Pool({
  connectionString:
    process.env.DATABASE_URL ??
    "postgresql://forge:forge_dev_password@localhost:5432/forge_app",
});

// ---------------------------------------------------------------------------
// Better Auth instance
// ---------------------------------------------------------------------------
export const auth = betterAuth({
  database: pool,

  emailAndPassword: {
    enabled: true,
  },

  session: {
    expiresIn: 60 * 60 * 24 * 7, // 7 days (seconds)
    cookieCache: {
      enabled: true,
      maxAge: 5 * 60, // cache for 5 min to reduce DB lookups
    },
  },

  plugins: [
    organization(),
    bearer(),
  ],

  trustedOrigins: [
    "http://localhost:3000",
    "http://localhost:5173",
    process.env.BETTER_AUTH_URL ?? "http://localhost:3100",
  ],

  baseURL: process.env.BETTER_AUTH_URL ?? "http://localhost:3100",
  secret: process.env.BETTER_AUTH_SECRET,
});

// Export the type so other modules can reference it
export type Auth = typeof auth;

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
