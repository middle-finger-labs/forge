# Workflow Examples

Real-world usage patterns for Forge's GitHub integration. Each example is self-contained — copy the commands and adapt them to your setup.

---

## Table of Contents

1. [Run Forge against a personal project](#1-run-forge-against-a-personal-project)
2. [Connect to a client's repo with a separate SSH key](#2-connect-to-a-clients-repo-with-a-separate-ssh-key)
3. [Auto-trigger pipelines from GitHub issues via webhook](#3-auto-trigger-pipelines-from-github-issues-via-webhook)
4. [Use Forge with a GitHub org that requires SSO](#4-use-forge-with-a-github-org-that-requires-sso)
5. [Run a pipeline from a GitHub issue number](#5-run-a-pipeline-from-a-github-issue-number)
6. [Create per-ticket PRs instead of a single PR](#6-create-per-ticket-prs-instead-of-a-single-pr)

---

## 1. Run Forge against a personal project

The simplest case: you have one GitHub account and want Forge to clone your repo, implement a feature, and open a PR.

### Prerequisites

- One SSH key added to your GitHub account
- A `GITHUB_TOKEN` with Contents, Issues, Pull requests, and Metadata permissions

### Setup (one-time)

```bash
# Generate SSH key (skip if you already have one)
ssh-keygen -t ed25519 -C "you@example.com" -f ~/.ssh/id_ed25519

# Run the setup wizard
bash scripts/setup_github.sh
```

When prompted:
- **Name:** `personal`
- **GitHub username:** your GitHub handle
- **Email:** your commit email
- **SSH key:** `~/.ssh/id_ed25519` (or wherever your key is)
- **SSH host alias:** `github-personal`

Set your token:

```bash
export GITHUB_TOKEN=ghp_your_token_here
```

### Run a pipeline

```bash
# With an inline spec
python run_pipeline.py start \
  --repo git@github.com:yourname/my-project.git \
  --spec "Add a REST API with user authentication using JWT tokens"

# With a spec file
python run_pipeline.py start \
  --repo git@github.com:yourname/my-project.git \
  --spec-file requirements.md

# From a GitHub issue
python run_pipeline.py start \
  --repo git@github.com:yourname/my-project.git \
  --issue 15
```

### What happens

1. Forge resolves your identity from the repo URL (`yourname` matches `github_username`)
2. Clones the repo using your SSH key
3. Reads the issue (if `--issue`) or uses your spec text
4. Runs the full pipeline: BA > Research > Architecture > PM > Coding > QA > Merge
5. Pushes a `forge/{pipeline-id}` branch
6. Opens a draft PR against `main`
7. Posts a status comment on the issue (if `--issue`)

### Monitor progress

```bash
# CLI
python run_pipeline.py status <pipeline-id>

# Dashboard
open http://localhost:5173
```

---

## 2. Connect to a client's repo with a separate SSH key

You're contracting for Acme Corp. They've added your work SSH key to their org. You need to push code under your work email, not your personal one.

### Setup

```bash
# 1. Generate a dedicated key for this client
ssh-keygen -t ed25519 -C "you@acmecorp.com" -f ~/.ssh/id_ed25519_acme

# 2. Give Acme the public key
cat ~/.ssh/id_ed25519_acme.pub
# They add it to the acme-corp GitHub org

# 3. Add identity to Forge
python run_pipeline.py identities add
```

When prompted:
- **Name:** `acme`
- **GitHub username:** your GitHub handle (same account, different key)
- **Email:** `you@acmecorp.com`
- **SSH key:** `~/.ssh/id_ed25519_acme`
- **SSH host alias:** `github-acme`
- **GitHub org:** `acme-corp`

The wizard will test the SSH connection and optionally add the `~/.ssh/config` block.

Set a token with access to Acme's repos:

```bash
export GITHUB_TOKEN_ACME=ghp_acme_scoped_token
```

### Verify access

```bash
# Test the identity
python run_pipeline.py identities test acme

# Test repo access
python run_pipeline.py repos test git@github.com:acme-corp/backend.git --identity acme
```

### Run a pipeline

```bash
python run_pipeline.py start \
  --repo git@github.com:acme-corp/backend.git \
  --spec "Migrate the auth module from session-based to JWT" \
  --identity acme
```

The `--identity acme` flag forces Forge to use the Acme identity. Without it, Forge auto-resolves based on the `github_org: "acme-corp"` match.

### Verify commits are attributed correctly

After the pipeline completes, check the PR:
- Commits should show `you@acmecorp.com` as the author
- The push used `~/.ssh/id_ed25519_acme`, not your personal key

---

## 3. Auto-trigger pipelines from GitHub issues via webhook

Instead of running `python run_pipeline.py start` manually, configure GitHub to notify Forge whenever a "forge"-labeled issue is created. Forge starts a pipeline automatically.

### Prerequisites

- Forge API server running and reachable from GitHub
- `GITHUB_WEBHOOK_SECRET` env var set
- `GITHUB_TOKEN` (or identity-specific token) available

### Step 1: Set a webhook secret

```bash
# Generate a random secret
export GITHUB_WEBHOOK_SECRET=$(openssl rand -hex 32)
echo "GITHUB_WEBHOOK_SECRET=$GITHUB_WEBHOOK_SECRET" >> .env
```

Restart the API server so it picks up the new secret.

### Step 2: Expose your Forge instance

For production, Forge needs a public URL. For local development:

```bash
# Option A: ngrok
ngrok http 8000
# Note the https://xxxx.ngrok.io URL

# Option B: cloudflared
cloudflared tunnel --url http://localhost:8000
```

### Step 3: Configure the webhook in GitHub

1. Go to **your repo > Settings > Webhooks > Add webhook**
2. Fill in:
   - **Payload URL:** `https://your-forge-host/webhooks/github`
   - **Content type:** `application/json`
   - **Secret:** paste the value of `GITHUB_WEBHOOK_SECRET`
3. Under **Which events would you like to trigger this webhook?**, select **Let me select individual events** and check:
   - **Issues** — triggers pipeline on new forge-labeled issues
   - **Issue comments** — enables `/forge approve`, `/forge abort`, `/forge status` commands
   - **Pull request reviews** — (future) auto-respond to PR review comments
4. Click **Add webhook**

### Step 4: Create a "forge" label

In your repo, create a label named `forge` (any color). This is the trigger label.

### Usage

1. **Start a pipeline:** Create a new issue with the `forge` label:
   - Title: "Add dark mode support"
   - Body: Describe what you want built
   - Label: `forge`

   Forge automatically starts a pipeline and posts a comment linking to the dashboard.

2. **Check status:** Comment `/forge status` on the issue to get a summary of the pipeline's current stage, cost, and progress.

3. **Approve:** When the pipeline reaches a human approval gate, comment `/forge approve` on the issue.

4. **Abort:** Comment `/forge abort` to cancel the pipeline.

### How it works

```
GitHub Issue (labeled "forge")
    │
    ▼
GitHub sends POST /webhooks/github
    │
    ▼
Forge webhook server:
  1. Verifies HMAC-SHA256 signature
  2. Extracts owner/repo/issue from payload
  3. Resolves identity for the repo
  4. Starts a Temporal workflow (ForgePipeline)
  5. Posts a tracking comment on the issue
    │
    ▼
Pipeline runs normally
    │
    ▼
Comments on the issue with status updates
```

---

## 4. Use Forge with a GitHub org that requires SSO

Many enterprise orgs enforce SAML SSO. SSH keys and PATs need extra authorization before they work with SSO-protected repos.

### Authorize your SSH key for SSO

1. Go to **GitHub > Settings > SSH and GPG keys**
2. Find the key you use for the org
3. Click **Configure SSO** next to it
4. Click **Authorize** next to your organization name

Without this step, `git clone` will fail with `ERROR: The 'YourOrg' organization has enabled or enforced SAML SSO`.

### Authorize your PAT for SSO

1. Go to **GitHub > Settings > Developer settings > Personal access tokens**
2. Find your token
3. Click **Configure SSO**
4. Click **Authorize** next to your organization

Without this, API calls return `403` with an SSO-related error message.

### Alternative: Use a GitHub App

GitHub Apps are automatically authorized for the org where they're installed — no SSO authorization step needed. This is often simpler for teams.

See [GitHub App setup](github-setup.md#3-github-app-for-organizations) for instructions.

### Identity config for SSO orgs

```yaml
identities:
  - name: "enterprise"
    github_username: "your-handle"
    email: "you@enterprise.com"
    ssh_key_path: "~/.ssh/id_ed25519_enterprise"
    ssh_host_alias: "github-enterprise"
    github_org: "EnterpriseOrg"
    extra_orgs:
      - "EnterpriseOrg-Internal"
      - "EnterpriseOrg-OSS"
```

### Verify

```bash
python run_pipeline.py identities test enterprise
python run_pipeline.py repos test git@github.com:EnterpriseOrg/service.git
```

If the test fails with an SSO error, revisit the authorization steps above.

---

## 5. Run a pipeline from a GitHub issue number

Instead of writing a spec by hand, point Forge at an existing GitHub issue. Forge fetches the title, body, labels, and non-bot comments, then formats them as a business spec for the BA agent.

### Usage

```bash
python run_pipeline.py start \
  --repo git@github.com:myorg/app.git \
  --issue 42
```

### What Forge extracts from the issue

| Issue field | How it's used |
|------------|---------------|
| Title | Becomes the spec heading |
| Body | Main requirement text |
| Labels | Mapped to a type prefix (e.g., "bug" > "Bug fix", "feature" > "New feature request") and used for priority sorting |
| Comments (non-bot) | Included as "Additional Context" in the spec |
| URL | Referenced as the source |

Bot comments (from GitHub Actions, Forge itself, etc.) are automatically filtered out.

### Combining issue + extra context

```bash
# Use the issue as the base spec but add more detail from a file
python run_pipeline.py start \
  --repo git@github.com:myorg/app.git \
  --issue 42 \
  --spec "Additional context: use PostgreSQL, not SQLite. Deploy target is AWS ECS."
```

When both `--issue` and `--spec` are provided, the issue content is used as the primary spec. The `--spec` text can supplement it (this behavior depends on your pipeline configuration).

---

## 6. Create per-ticket PRs instead of a single PR

By default, Forge creates one branch and one PR with all changes. For larger projects or teams that prefer granular PRs, use the `pr_per_ticket` strategy.

### Usage

```bash
python run_pipeline.py start \
  --repo git@github.com:myorg/app.git \
  --spec "Build a notification system with email and Slack support" \
  --pr-strategy pr_per_ticket
```

### PR strategies

| Strategy | Branches | PRs | Best for |
|----------|----------|-----|----------|
| `single_pr` (default) | 1 (`forge/{pipeline-id}`) | 1 | Small features, solo projects |
| `pr_per_ticket` | N (one per ticket) | N | Large features, team review |
| `direct_push` | 0 (pushes to current branch) | 0 | Trusted automation, staging branches |

### Per-ticket PR example

If Forge decomposes "Build a notification system" into 3 tickets:

```
PR #1: [NOTIF-001] Email notification service
  Branch: forge/notif-001
  Files: notifications/email.py, tests/test_email.py

PR #2: [NOTIF-002] Slack integration
  Branch: forge/notif-002
  Files: notifications/slack.py, tests/test_slack.py

PR #3: [NOTIF-003] Notification preferences API
  Branch: forge/notif-003
  Files: api/preferences.py, tests/test_preferences.py
```

Each PR is created as a draft and includes:
- A summary of the ticket's scope
- Test results (passed/failed)
- QA review verdict
- File change list
- Link back to the pipeline run
