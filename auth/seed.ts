/**
 * seed.ts — Create the initial organization and admin user.
 *
 * Idempotent: safe to run multiple times. Existing records are skipped.
 *
 * Usage:
 *   FORGE_ADMIN_EMAIL=admin@example.com \
 *   FORGE_ADMIN_PASSWORD=changeme123 \
 *   tsx seed.ts
 */

import { auth } from "./server.js";
import { Pool } from "pg";

const ORG_NAME = "Middle Finger Labs";
const ORG_SLUG = "middle-finger-labs";

const adminEmail = process.env.FORGE_ADMIN_EMAIL;
const adminPassword = process.env.FORGE_ADMIN_PASSWORD;

if (!adminEmail || !adminPassword) {
  console.error(
    "FORGE_ADMIN_EMAIL and FORGE_ADMIN_PASSWORD are required.\n" +
      "Example:\n" +
      "  FORGE_ADMIN_EMAIL=admin@example.com FORGE_ADMIN_PASSWORD=changeme123 tsx seed.ts",
  );
  process.exit(1);
}

const pool = new Pool({
  connectionString:
    process.env.DATABASE_URL ??
    "postgresql://forge:forge_dev_password@localhost:5432/forge_app",
});

async function seed() {
  console.log("--- forge-auth seed ---");

  // 1. Sign up admin user (or skip if already exists)
  let userId: string;
  try {
    const signupRes = await auth.api.signUpEmail({
      body: {
        email: adminEmail!,
        password: adminPassword!,
        name: "Forge Admin",
      },
    });
    userId = signupRes.user.id;
    console.log(`Created admin user: ${adminEmail} (${userId})`);
  } catch (err: any) {
    // User may already exist — look them up
    const existing = await pool.query(
      `SELECT id FROM "user" WHERE email = $1`,
      [adminEmail],
    );
    if (existing.rows.length > 0) {
      userId = existing.rows[0].id;
      console.log(`Admin user already exists: ${adminEmail} (${userId})`);
    } else {
      console.error("Failed to create admin user:", err.message ?? err);
      process.exit(1);
    }
  }

  // 2. Create organization (or skip if slug exists)
  let orgId: string;
  const existingOrg = await pool.query(
    `SELECT id FROM "organization" WHERE slug = $1`,
    [ORG_SLUG],
  );

  if (existingOrg.rows.length > 0) {
    orgId = existingOrg.rows[0].id;
    console.log(`Organization already exists: ${ORG_NAME} (${orgId})`);
  } else {
    // Use the API to create the org — this respects all Better Auth hooks
    const createRes = await auth.api.createOrganization({
      body: {
        name: ORG_NAME,
        slug: ORG_SLUG,
      },
      headers: await getSessionHeaders(userId),
    });
    orgId = createRes!.id;
    console.log(`Created organization: ${ORG_NAME} (${orgId})`);
  }

  // 3. Ensure the admin is an owner of the org
  const existingMember = await pool.query(
    `SELECT id, role FROM "member" WHERE "organizationId" = $1 AND "userId" = $2`,
    [orgId, userId],
  );

  if (existingMember.rows.length > 0) {
    if (existingMember.rows[0].role !== "owner") {
      await pool.query(`UPDATE "member" SET role = 'owner' WHERE id = $1`, [
        existingMember.rows[0].id,
      ]);
      console.log(`Updated admin role to owner.`);
    } else {
      console.log(`Admin is already org owner.`);
    }
  } else {
    // The createOrganization API call should have added the creator as owner,
    // but if the org already existed we may need to add membership manually.
    await pool.query(
      `INSERT INTO "member" (id, "organizationId", "userId", role, "createdAt")
       VALUES (gen_random_uuid(), $1, $2, 'owner', now())`,
      [orgId, userId],
    );
    console.log(`Added admin as org owner.`);
  }

  console.log("\n--- seed complete ---");
  console.log(`  Organization: ${ORG_NAME} (${orgId})`);
  console.log(`  Admin:        ${adminEmail} (${userId})`);

  await pool.end();
  process.exit(0);
}

/**
 * Create a temporary session for the admin user so we can call
 * authenticated Better Auth API methods during seeding.
 */
async function getSessionHeaders(userId: string): Promise<Headers> {
  // Create a session directly in the DB for seeding purposes
  const sessionToken = crypto.randomUUID();
  const expiresAt = new Date(Date.now() + 60 * 60 * 1000); // 1 hour

  await pool.query(
    `INSERT INTO "session" (id, "userId", token, "expiresAt", "createdAt", "updatedAt")
     VALUES (gen_random_uuid(), $1, $2, $3, now(), now())
     ON CONFLICT DO NOTHING`,
    [userId, sessionToken, expiresAt],
  );

  const headers = new Headers();
  headers.set("Authorization", `Bearer ${sessionToken}`);
  return headers;
}

seed().catch((err) => {
  console.error("Seed failed:", err);
  process.exit(1);
});
