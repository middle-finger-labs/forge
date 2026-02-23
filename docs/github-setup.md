# GitHub Integration Setup Guide

This guide walks through configuring Forge to work with one or more GitHub accounts. Forge uses SSH keys for git operations (clone, push) and either a Personal Access Token (PAT) or a GitHub App installation token for API calls (creating PRs, commenting on issues).

---

## Table of Contents

1. [SSH Key Setup](#1-ssh-key-setup)
2. [Personal Access Token (PAT)](#2-personal-access-token-pat)
3. [GitHub App (for organizations)](#3-github-app-for-organizations)
4. [Identity Configuration (`identities.yaml`)](#4-identity-configuration)
5. [Testing the Connection](#5-testing-the-connection)
6. [Troubleshooting](#6-troubleshooting)

---

## 1. SSH Key Setup

Each GitHub account needs its own SSH key. Forge routes git commands through SSH host aliases so that `git push` always uses the correct key — even when multiple accounts access `github.com`.

### Generate a key per account

```bash
# Personal account
ssh-keygen -t ed25519 -C "you@personal.com" -f ~/.ssh/id_ed25519_personal

# Work account
ssh-keygen -t ed25519 -C "you@company.com" -f ~/.ssh/id_ed25519_work

# Client / contract account
ssh-keygen -t ed25519 -C "you@client.com" -f ~/.ssh/id_ed25519_client
```

Use a passphrase when prompted (recommended), then add the key to your SSH agent:

```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519_personal
ssh-add ~/.ssh/id_ed25519_work
```

### Add the public key to GitHub

For each account:

1. Copy the public key: `cat ~/.ssh/id_ed25519_personal.pub`
2. Log in to the corresponding GitHub account
3. Go to **Settings > SSH and GPG keys > New SSH key**
4. Paste the public key and save

### Configure SSH host aliases

Add a block to `~/.ssh/config` for each identity. The **Host** alias is what Forge uses to route git commands to the right key:

```
# --- Personal GitHub ---
Host github-personal
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_personal
    IdentitiesOnly yes

# --- Work GitHub ---
Host github-work
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_work
    IdentitiesOnly yes

# --- Client GitHub ---
Host github-client
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_client
    IdentitiesOnly yes
```

The `IdentitiesOnly yes` line prevents SSH from trying other keys, which is critical when you have multiple keys for the same host.

> **Tip:** The setup wizard (`bash scripts/setup_github.sh`) can write these blocks automatically.

### Verify each key

```bash
ssh -T git@github-personal
# Hi your-personal-username! You've successfully authenticated...

ssh -T git@github-work
# Hi your-work-username! You've successfully authenticated...
```

---

## 2. Personal Access Token (PAT)

Forge uses a PAT for GitHub API calls: creating PRs, commenting on issues, reading repo metadata. SSH handles git operations (clone/push).

### Create a fine-grained PAT

1. Go to **GitHub > Settings > Developer settings > Personal access tokens > Fine-grained tokens**
2. Click **Generate new token**
3. Set:
   - **Token name:** `forge-pipeline` (or similar)
   - **Expiration:** 90 days (recommended)
   - **Repository access:** Select the repos Forge will work with, or "All repositories" for broad access
4. Under **Permissions**, enable:

| Permission | Access Level | Why |
|-----------|-------------|-----|
| **Contents** | Read and write | Clone repos, push branches |
| **Issues** | Read and write | Read issue specs, post status comments, create sub-issues |
| **Pull requests** | Read and write | Create and update PRs |
| **Metadata** | Read | Required by GitHub for all fine-grained tokens |

5. Click **Generate token** and copy it immediately

### Set environment variables

Forge checks for identity-specific tokens first, then falls back to a generic token:

```bash
# Identity-specific tokens (recommended for multi-account)
export GITHUB_TOKEN_PERSONAL=ghp_xxxx_personal_token
export GITHUB_TOKEN_WORK=ghp_xxxx_work_token
export GITHUB_TOKEN_CLIENT=ghp_xxxx_client_token

# Fallback token (used if no identity-specific token is found)
export GITHUB_TOKEN=ghp_xxxx_default_token
```

The token env var name is derived from the identity name: `GITHUB_TOKEN_{NAME}` where `{NAME}` is the identity name uppercased with hyphens replaced by underscores. For example:

| Identity name | Env var checked first |
|---------------|-----------------------|
| `personal` | `GITHUB_TOKEN_PERSONAL` |
| `work` | `GITHUB_TOKEN_WORK` |
| `my-client` | `GITHUB_TOKEN_MY_CLIENT` |
| `draftkings` | `GITHUB_TOKEN_DRAFTKINGS` |

Add these to your `.env` file or shell profile. Never commit tokens to version control.

---

## 3. GitHub App (for Organizations)

For org-managed repos, a GitHub App provides better security: tokens auto-rotate (~1 hour), permissions are scoped to the app installation, and you don't need to manage individual PATs.

### Create the GitHub App

1. Go to your org's **Settings > Developer settings > GitHub Apps > New GitHub App**
2. Configure:
   - **App name:** `Forge Pipeline` (must be globally unique)
   - **Homepage URL:** Your Forge dashboard URL
   - **Webhook:** Uncheck "Active" (Forge uses its own webhook receiver)
3. Set **Permissions**:

| Permission | Access | Why |
|-----------|--------|-----|
| Contents | Read & write | Clone, push branches |
| Issues | Read & write | Read specs, post comments |
| Pull requests | Read & write | Create PRs |
| Metadata | Read | Required |

4. Under **Where can this GitHub App be installed?**, select "Only on this account"
5. Click **Create GitHub App**

### Generate a private key

1. On the App settings page, scroll to **Private keys**
2. Click **Generate a private key** — a `.pem` file downloads
3. Store it securely:

```bash
mkdir -p ~/.forge/keys
mv ~/Downloads/forge-pipeline.*.private-key.pem ~/.forge/keys/forge-app.pem
chmod 600 ~/.forge/keys/forge-app.pem
```

### Install the App

1. On the App settings page, click **Install App** in the sidebar
2. Choose your organization
3. Select "All repositories" or specific repos
4. Click **Install**
5. Note the **Installation ID** from the URL: `https://github.com/settings/installations/{INSTALLATION_ID}`

### Set environment variables

```bash
# App credentials (identity-specific or global)
export GITHUB_APP_ID=123456
export GITHUB_APP_KEY=~/.forge/keys/forge-app.pem
export GITHUB_APP_INSTALLATION_ID=78901234

# Or identity-specific:
export GITHUB_APP_ID_WORK=123456
export GITHUB_APP_KEY_WORK=~/.forge/keys/forge-app.pem
export GITHUB_APP_INSTALLATION_ID_WORK=78901234
```

### Use App auth in Forge

```bash
# When starting a pipeline, the identity's auth_method is auto-detected
# based on available env vars. Or specify explicitly:
python run_pipeline.py start \
  --repo git@github.com:MyOrg/service.git \
  --spec "Add caching layer" \
  --identity work
```

The `GitHubClient` auto-refreshes the installation token before it expires (~55 min refresh cycle).

---

## 4. Identity Configuration

Forge stores identity configuration in `~/.forge/identities.yaml`. Each identity ties together a GitHub account, SSH key, and host alias.

### File location

```
~/.forge/identities.yaml
```

### Recommended setup methods

**Option A: Interactive wizard** (easiest)

```bash
bash scripts/setup_github.sh
```

The wizard walks you through each account, tests SSH connections, writes the YAML, and optionally configures `~/.ssh/config`.

**Option B: CLI**

```bash
python run_pipeline.py identities add
```

Interactive prompts for a single identity.

**Option C: Manual**

Create or edit `~/.forge/identities.yaml` directly. See [identities.yaml.example](../identities.yaml.example) for a fully-commented template.

### File format

```yaml
identities:
  - name: "personal"
    github_username: "your-github-handle"
    email: "you@personal.com"
    ssh_key_path: "~/.ssh/id_ed25519_personal"
    ssh_host_alias: "github-personal"
    default: true

  - name: "work"
    github_username: "your-work-handle"
    email: "you@company.com"
    ssh_key_path: "~/.ssh/id_ed25519_work"
    ssh_host_alias: "github-work"
    github_org: "YourCompany"
    extra_orgs:
      - "CompanySubsidiary"
      - "CompanyOpenSource"
```

### Field reference

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Short identifier (used in CLI flags and env var names) |
| `github_username` | Yes | GitHub login for this account |
| `email` | Yes | Commit author email |
| `ssh_key_path` | Yes | Path to the SSH private key (`~` is expanded) |
| `ssh_host_alias` | Yes | Matches a `Host` block in `~/.ssh/config` |
| `default` | No | If `true`, used when no identity matches a repo URL |
| `github_org` | No | Primary GitHub org — repos under this org use this identity |
| `extra_orgs` | No | Additional orgs covered by this identity |

### How identity resolution works

When you run `forge start --repo git@github.com:SomeOrg/repo.git`, Forge resolves the identity by:

1. **Explicit flag** — `--identity work` always wins
2. **Org match** — If `SomeOrg` matches an identity's `github_org` or `extra_orgs`, use it
3. **Username match** — If the repo owner matches `github_username`, use it
4. **Default** — Fall back to the identity with `default: true`

---

## 5. Testing the Connection

### Test a specific identity

```bash
python run_pipeline.py identities test personal
```

Output:
```
Identity: personal
  SSH key: ~/.ssh/id_ed25519_personal .............. found
  SSH connection: ............................... OK
  GitHub user: your-github-handle
```

### Test all identities

```bash
python run_pipeline.py identities list
```

### Test repo access

```bash
python run_pipeline.py repos test git@github.com:YourOrg/your-repo.git
```

This clones the repo to a temp directory, prints metadata (default branch, language, visibility), shows recent commits, and cleans up.

### Test with identity override

```bash
python run_pipeline.py repos test git@github.com:YourOrg/repo.git --identity work
```

---

## 6. Troubleshooting

### "Permission denied (publickey)"

**Symptom:** `git clone` or SSH test fails with `Permission denied (publickey)`.

**Causes and fixes:**

1. **SSH key not added to GitHub:**
   ```bash
   cat ~/.ssh/id_ed25519_personal.pub
   # Copy this and add it to GitHub > Settings > SSH and GPG keys
   ```

2. **SSH key not in the agent:**
   ```bash
   ssh-add -l                                # List loaded keys
   ssh-add ~/.ssh/id_ed25519_personal        # Add if missing
   ```

3. **Wrong key being used (multiple keys for github.com):**
   ```bash
   # Test with the explicit key
   ssh -T git@github.com -i ~/.ssh/id_ed25519_personal -o IdentitiesOnly=yes
   ```
   If this works but `ssh -T git@github.com` doesn't, your `~/.ssh/config` is routing to the wrong key. Verify your `Host` blocks and make sure Forge uses the alias (e.g. `github-personal`), not `github.com` directly.

4. **File permissions too open:**
   ```bash
   chmod 600 ~/.ssh/id_ed25519_personal
   chmod 644 ~/.ssh/id_ed25519_personal.pub
   chmod 600 ~/.ssh/config
   ```

5. **macOS Keychain not configured:**
   ```bash
   # Add to ~/.ssh/config under each Host block:
   Host github-personal
       ...
       AddKeysToAgent yes
       UseKeychain yes
   ```

### Wrong account pushing

**Symptom:** Commits appear under a different GitHub account than expected.

**Causes and fixes:**

1. **Identity not resolving correctly:**
   ```bash
   # Check which identity Forge picks for a URL:
   python -m integrations.git_identity resolve git@github.com:Org/repo.git
   ```

2. **Missing `github_org` in config:** If the repo is under `MyOrg` but your identity doesn't list `github_org: "MyOrg"`, Forge can't match it. Update `~/.forge/identities.yaml`.

3. **Global git config overriding:** Check if `~/.gitconfig` has `[user]` settings that override Forge's per-repo config:
   ```bash
   git config --global --list | grep user
   ```
   Forge sets `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME`, and `GIT_COMMITTER_EMAIL` as environment variables, which take precedence over git config.

4. **SSH host alias not in config:** If `~/.ssh/config` doesn't have a block for your `ssh_host_alias`, SSH falls back to default key resolution:
   ```bash
   grep "Host github-work" ~/.ssh/config
   # Should show a block with IdentityFile pointing to the correct key
   ```

### Token expired or revoked

**Symptom:** API calls fail with `401 Unauthorized` or `403 Forbidden`.

**Fixes:**

1. **PAT expired:** Fine-grained PATs have an expiration date. Generate a new one and update the env var:
   ```bash
   export GITHUB_TOKEN_WORK=ghp_new_token_here
   ```

2. **PAT permissions insufficient:** If you see `403` on specific operations (e.g., creating PRs), the token may be missing a permission. Regenerate with the correct scopes (Contents, Issues, Pull requests, Metadata).

3. **GitHub App token not refreshing:** Check that all three App env vars are set:
   ```bash
   echo $GITHUB_APP_ID $GITHUB_APP_KEY $GITHUB_APP_INSTALLATION_ID
   ```
   The private key file must exist and be readable:
   ```bash
   ls -la $(echo $GITHUB_APP_KEY | sed "s|~|$HOME|")
   ```

4. **Org SSO not authorized:** If your org uses SAML SSO, you must authorize the token:
   - Go to **Settings > Developer settings > Personal access tokens**
   - Find your token and click **Configure SSO**
   - Authorize the token for your organization

### Webhook not triggering

**Symptom:** Creating a "forge"-labeled issue doesn't start a pipeline.

**Fixes:**

1. **Webhook not configured:** Verify at **repo Settings > Webhooks** that a webhook points to your Forge instance.

2. **Secret mismatch:** The `GITHUB_WEBHOOK_SECRET` env var must match the secret in GitHub's webhook settings:
   ```bash
   echo $GITHUB_WEBHOOK_SECRET
   ```

3. **Endpoint not reachable:** GitHub must be able to reach your Forge server. For local development, use a tunnel:
   ```bash
   ngrok http 8000
   # Or
   cloudflared tunnel --url http://localhost:8000
   ```
   Update the webhook URL to the tunnel URL + `/webhooks/github`.

4. **Wrong events selected:** The webhook must be subscribed to **Issues**, **Issue comments**, and optionally **Pull request reviews**.

5. **Check delivery log:** In GitHub's webhook settings, click **Recent Deliveries** to see payloads and response codes.

### Rate limiting

**Symptom:** Intermittent `403` errors with "rate limit" in the message.

**Fixes:**

1. **Primary rate limit (5,000 req/hr for PAT):** Forge handles this automatically with backoff. If you hit it frequently, consider using a GitHub App (15,000 req/hr per installation).

2. **Secondary rate limit (abuse detection):** Triggered by creating too many resources too quickly. Forge handles `retry-after` headers automatically. Reduce `max_concurrent_engineers` if this happens often.

3. **Check current limit:**
   ```bash
   curl -H "Authorization: Bearer $GITHUB_TOKEN" \
     -s https://api.github.com/rate_limit | python -m json.tool
   ```
