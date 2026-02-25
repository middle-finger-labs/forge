import { betterAuth } from "better-auth";
import { organization, bearer, magicLink } from "better-auth/plugins";
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
    magicLink({
      expiresIn: 900, // 15 minutes
      disableSignUp: false, // invites can create new users
      rateLimit: {
        window: 60,
        max: 10, // generous — Python enforces the real 3/15min limit
      },
      sendMagicLink: async ({ email, token, url }) => {
        const internalUrl =
          process.env.FORGE_API_INTERNAL_URL ?? "http://forge-api:8000";
        const secret = process.env.INTERNAL_API_SECRET ?? "";
        try {
          await fetch(
            `${internalUrl}/api/internal/send-magic-email`,
            {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "X-Internal-Secret": secret,
              },
              body: JSON.stringify({ email, token, url }),
            },
          );
        } catch {
          // Swallow errors — matches existing behavior where email
          // failures don't surface to the caller.
        }
      },
    }),
  ],

  trustedOrigins: [
    "http://localhost:3000",
    "http://localhost:5173",
    process.env.BETTER_AUTH_URL ?? "http://localhost:3100",
    // Trust any Railway-generated domain
    "https://*.up.railway.app",
  ],

  baseURL: process.env.BETTER_AUTH_URL ?? "http://localhost:3100",
  secret: process.env.BETTER_AUTH_SECRET,
});

export type Auth = typeof auth;
