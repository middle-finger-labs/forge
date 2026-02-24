import { betterAuth } from "better-auth";
import { organization, bearer } from "better-auth/plugins";
import { Pool } from "pg";

// ---------------------------------------------------------------------------
// Database
// ---------------------------------------------------------------------------
export const pool = new Pool({
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

export type Auth = typeof auth;
