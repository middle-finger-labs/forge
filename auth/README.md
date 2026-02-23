# Forge Auth Service

Lightweight Node.js service that handles authentication, sessions, and organization management for the Forge multiplayer platform using [Better Auth](https://www.better-auth.com/).

## Architecture

```
┌──────────────┐     ┌───────────────┐     ┌──────────────┐
│  React       │────▶│  forge-auth   │────▶│  PostgreSQL   │
│  Dashboard   │     │  (port 3100)  │     │  forge_app DB │
│  (port 3000) │     └───────────────┘     └──────────────┘
└──────┬───────┘             ▲                     ▲
       │                     │                     │
       │              session/token           org_id scoped
       │              validation              queries
       ▼                     │                     │
┌──────────────┐     ┌───────────────┐             │
│  FastAPI     │────▶│  Better Auth  │─────────────┘
│  (port 8000) │     │  session API  │
└──────────────┘     └───────────────┘
```

### How it works

| Component | Role |
|-----------|------|
| **Better Auth** (this service) | Handles signup, login, sessions, org CRUD, invitations, and role management. Stores its own tables (`user`, `session`, `account`, `organization`, `member`, `invitation`) in the `forge_app` database. |
| **FastAPI** | Validates session tokens by calling Better Auth's session endpoint. Scopes all queries by `org_id` from the authenticated session. |
| **React Dashboard** | Uses the Better Auth client SDK (`@better-auth/react`) for login/signup flows, session management, and org switching. Sends session cookies or Bearer tokens with every API request. |

### Tables managed by Better Auth

These are auto-created by Better Auth's migration system:

- `user` — user accounts (email, name, hashed password)
- `session` — active sessions (token, expiry, userId)
- `account` — auth provider accounts (email/password, OAuth, etc.)
- `organization` — orgs with name, slug, metadata
- `member` — org membership (userId, orgId, role: owner/admin/member)
- `invitation` — pending org invites

### Tables extended by Forge

Forge's existing tables gain an `org_id` column for multi-tenancy:

- `pipeline_runs.org_id`
- `agent_events.org_id`
- `ticket_executions.org_id`
- `cto_interventions.org_id`
- `memory_store.org_id`

## Quick start

```bash
# Install dependencies
cd auth && npm install

# Run the migration to create Better Auth tables
npm run migrate

# Start the auth server (development with hot reload)
npm run dev

# Seed initial org + admin user
FORGE_ADMIN_EMAIL=admin@middlefingerlabs.com \
FORGE_ADMIN_PASSWORD=changeme123 \
npm run seed
```

## Docker

The auth service runs as part of the `dashboard` profile:

```bash
docker compose --profile dashboard up
```

## Environment variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://forge:forge_dev_password@localhost:5432/forge_app` |
| `BETTER_AUTH_SECRET` | Secret for signing sessions/tokens | (required in production) |
| `BETTER_AUTH_URL` | Public URL of the auth service | `http://localhost:3100` |
| `PORT` | HTTP port | `3100` |
| `FORGE_ADMIN_EMAIL` | Admin email (seed script) | — |
| `FORGE_ADMIN_PASSWORD` | Admin password (seed script) | — |

## API routes

All Better Auth routes are mounted at `/api/auth/*`:

- `POST /api/auth/sign-up/email` — register
- `POST /api/auth/sign-in/email` — login
- `POST /api/auth/sign-out` — logout
- `GET  /api/auth/get-session` — validate session
- `POST /api/auth/organization/create` — create org
- `POST /api/auth/organization/invite-member` — invite member
- `GET  /api/auth/organization/list` — list user's orgs

Plus `/health` for liveness checks.

## Validating tokens from FastAPI

The FastAPI server validates tokens by forwarding the session cookie or Bearer token to Better Auth:

```python
async def get_current_user(request: Request) -> dict:
    """Validate session with Better Auth and return user + org context."""
    cookie = request.cookies.get("better-auth.session_token")
    bearer = request.headers.get("Authorization", "").removeprefix("Bearer ")
    token = cookie or bearer

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "http://forge-auth:3100/api/auth/get-session",
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code != 200:
            raise HTTPException(401, "Invalid session")
        return resp.json()
```
