# Multiplayer Setup Guide

Step-by-step guide for setting up Forge for team collaboration.

## Prerequisites

- Docker and Docker Compose installed
- A terminal and web browser
- (Optional) An Anthropic API key for running actual pipelines

---

## 1. Initial Setup

```bash
# Clone the repo and run first-time setup
git clone <your-forge-repo-url>
cd forge
./scripts/setup.sh
```

This will:
- Generate encryption keys (`BETTER_AUTH_SECRET`, `FORGE_ENCRYPTION_KEY`)
- Build and start all Docker services
- Run database migrations
- Create the default organization ("Middle Finger Labs") and admin account

**Default credentials** (set in `.env`):
- Email: `admin@example.com` (or `FORGE_ADMIN_EMAIL`)
- Password: `changeme123` (or `FORGE_ADMIN_PASSWORD`)

---

## 2. Create Your Organization

1. Open the dashboard at **http://localhost:3000**
2. Log in with the admin credentials
3. Click the **org switcher** (top-right dropdown) to see your current org
4. To create a new org: use the org switcher → "Create Organization"

---

## 3. Invite Your Partner

1. Go to **Settings** (gear icon in the top nav)
2. Click the **Members** tab
3. Click **Invite Member**
4. Enter your partner's email and select their role:
   - **Member** — can run pipelines, approve stages, view everything
   - **Admin** — can also manage settings, secrets, and identities
   - **Owner** — full control including member management

Your partner will receive an invitation that they can accept after signing up.

### Partner signup flow

1. Partner opens **http://localhost:3000/signup**
2. Creates their account (email + password)
3. Accepts the org invitation from the org switcher
4. Selects the org as their active organization

---

## 4. Configure API Keys

API keys are encrypted and stored per-org. All team members share the org's keys.

1. Go to **Settings → API Keys**
2. Click **Add Key**
3. Select the key type (e.g., `ANTHROPIC_API_KEY`) or enter a custom name
4. Paste the API key value
5. Click **Save**

The key is encrypted with Fernet (AES-128-CBC) using the `FORGE_ENCRYPTION_KEY` from your `.env`. Only the key name is visible after saving — the actual value is never exposed in the UI.

### Supported keys

| Key | Required | Description |
|-----|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API key for LLM inference |
| `OPENAI_API_KEY` | No | GPT fallback or embedding models |
| `GITHUB_TOKEN` | No | GitHub API access for repo operations |
| Custom keys | No | Any key your pipeline needs |

---

## 5. Set Up GitHub Identities

GitHub identities let your org push code and create PRs under team members' accounts.

1. Go to **Settings → GitHub Identities**
2. Click **Add Identity**
3. Fill in:
   - **Name** — friendly label (e.g., "Alice's Work Account")
   - **GitHub Username** — the GitHub username
   - **Email** — git commit email
   - **GitHub Token** — personal access token (encrypted on save)
   - **SSH Key** — (optional) private key for SSH git operations
   - **GitHub Org** — (optional) auto-match repos from this org
   - **Default** — check to make this the default identity

4. Click **Test Connection** to verify the token works

### Multiple identities

You can add multiple identities — Forge auto-selects the right one based on:
1. Explicit `--identity` flag on pipeline start
2. GitHub org match (repo owner matches `github_org`)
3. Username match
4. Default identity

---

## 6. How Presence Works

When multiple team members view the same pipeline:

- **Real-time avatars** appear at the top of the pipeline detail page
- Each user's initials and name are shown with a colored indicator
- **Typing indicators** in the chat panel show when someone is composing a message
- Presence data is stored in Redis with a 60-second heartbeat expiry

### Technical details

- WebSocket connection established on pipeline detail page open
- Client sends `heartbeat` messages every 30 seconds
- Server tracks presence in Redis hash `presence:{pipeline_id}`
- On disconnect or heartbeat timeout, user is removed from the room

---

## 7. How Approvals Work

Forge pipelines have human-in-the-loop approval gates. Any org member can approve:

1. A pipeline reaches an approval gate (e.g., after architecture stage)
2. The dashboard shows a **yellow "Pending Approval"** banner
3. Any team member viewing the pipeline can click **Approve** or **Reject**
4. The approval event is recorded with the approver's name and timestamp
5. All connected users see the approval in real-time via WebSocket

### Approval stages

| Stage | What's being reviewed |
|-------|----------------------|
| `architecture` | System design and tech spec |
| `task_decomposition` | PRD board and ticket breakdown |

Configure auto-approve in **Settings → General → Auto-Approve Stages** to skip manual review for specific stages.

---

## 8. Shared Memory

All team members' pipeline runs contribute to a shared knowledge base:

- **Lessons** — patterns learned by agents (e.g., "Always add input validation")
- **Decisions** — architectural choices made during pipelines

### Memory sharing modes

Set in **Settings → General → Memory Sharing Mode**:

| Mode | Behavior |
|------|----------|
| **Shared** (default) | All members see all org memories |
| **Private** | Each member only sees memories from their own pipelines |

### Viewing memory

- Open any pipeline detail page → **Org Memory** panel at the bottom
- **Lessons tab** — browse all lessons, add new ones manually
- **Decisions tab** — browse architectural decisions
- **Team tab** — see contribution counts per team member

### Admin controls

Admins and owners can:
- Delete individual memories
- View per-user contribution statistics
- Change the memory sharing mode

---

## Troubleshooting

### "Session expired" / redirected to login

**Cause:** Your Better Auth session token has expired (default: 7 days).

**Fix:** Log in again. Sessions are automatically refreshed on active use.

### Can't see partner's pipelines

**Cause:** You're in different organizations, or your partner hasn't accepted the invitation.

**Fix:**
1. Check the org switcher — make sure both users have the same org selected
2. Ask your partner to check Settings → Members to verify they appear in the list
3. Check if there are pending invitations in the org switcher dropdown

### WebSocket disconnects

**Cause:** Network interruption or nginx proxy timeout.

**Fix:**
- The dashboard auto-reconnects WebSocket connections with exponential backoff
- If persistent, check: `docker compose logs forge-api` for errors
- Verify the nginx WebSocket timeout: `proxy_read_timeout 86400s;` in `dashboard/nginx.conf`

### "Authentication service unavailable" (503)

**Cause:** The forge-auth container is down or unreachable from forge-api.

**Fix:**
```bash
docker compose ps forge-auth        # Check status
docker compose logs forge-auth      # Check logs
docker compose restart forge-auth   # Restart
```

### Secrets not working / "FORGE_ENCRYPTION_KEY is not set"

**Cause:** The encryption key isn't configured or doesn't match the key used to encrypt existing secrets.

**Fix:**
1. Check `.env` has `FORGE_ENCRYPTION_KEY` set
2. If you regenerate the key, existing secrets become unreadable — you'll need to re-enter them
3. Run: `docker compose restart forge-api forge-worker` after changing the key

### Invitation email not received

Better Auth's default configuration doesn't send emails — invitations are accepted via the API/UI directly. The invited user:
1. Signs up at `/signup`
2. Opens the org switcher
3. Sees and accepts pending invitations
