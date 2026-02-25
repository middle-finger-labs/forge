# Connection Setup Guide

Step-by-step instructions for connecting each supported service.

## General Setup Flow

1. Open **Settings > Connections** in the desktop app
2. Click **Connect** on the service you want to add
3. Follow the service-specific authentication steps below
4. Test the connection — the system will discover available tools
5. Configure permissions for each agent role
6. Enable/disable automation flags as needed

---

## Notion

**Transport:** Streamable HTTP
**Auth:** OAuth or internal integration token

### Option A: OAuth (Recommended)

1. Click **Connect with Notion**
2. A popup opens to `notion.so` — authorize Forge to access your workspace
3. Select the pages/databases you want Forge to access
4. The popup closes automatically on success
5. Test the connection to verify

### Option B: Internal Integration Token

1. Go to [notion.so/profile/integrations](https://www.notion.so/profile/integrations)
2. Click **New integration**
3. Give it a name (e.g., "Forge Pipeline")
4. Copy the **Internal Integration Secret**
5. Share the relevant Notion pages/databases with your integration
6. Paste the token in the setup wizard

### What Agents Can Do

| Agent | Default | Tools |
|-------|---------|-------|
| BA | Write | Search docs, create spec pages |
| Researcher | Read | Search for existing documentation |
| Architect | Read | Reference architecture docs |
| PM | Write | Create project pages, update status |
| Engineer | Read | Check coding standards, API docs |
| QA | Read | Check test requirements |
| CTO | Read | Full situational awareness |

---

## Linear

**Transport:** SSE (Server-Sent Events)
**Auth:** OAuth or personal API key

### Option A: OAuth (Recommended)

1. Click **Connect with Linear**
2. Authorize Forge in the Linear OAuth popup
3. The popup closes automatically on success

### Option B: Personal API Key

1. Go to **Linear Settings > API**
2. Click **Create key**
3. Copy the key and paste it in the setup wizard

### What Agents Can Do

| Agent | Default | Tools |
|-------|---------|-------|
| BA | Read | Search for related issues |
| Researcher | Read | Find prior art |
| Architect | Read | Check technical decisions |
| PM | Write | Create tickets, update status |
| Engineer | Read | Reference ticket details |
| QA | Write | Create bug tickets |
| CTO | Read | Verify ticket scope |

---

## Figma

**Transport:** Streamable HTTP
**Auth:** OAuth or personal access token

### Option A: OAuth

1. Click **Connect with Figma**
2. Authorize in the Figma popup
3. Grant "Read files" scope

### Option B: Personal Access Token

1. Go to **Figma Settings > Personal access tokens**
2. Generate a new token with file read access
3. Paste it in the setup wizard

### What Agents Can Do

| Agent | Default | Tools |
|-------|---------|-------|
| Architect | Read | Reference designs for component structure |
| Engineer | Read | Match design specs (spacing, colors, typography) |
| QA | Read | Verify visual correctness |

Note: Figma is read-only by default. No agents have write access.

---

## Jira

**Transport:** stdio (local subprocess)
**Auth:** API token + email

### Setup

1. Go to [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens)
2. Click **Create API token**
3. In the setup wizard, enter:
   - **Email**: Your Atlassian account email
   - **API Token**: The token you just created
   - **Domain**: Your Jira instance (e.g., `yourcompany.atlassian.net`)

### Environment Variables

The Jira MCP server requires these environment variables:

```
ATLASSIAN_USER_EMAIL=you@company.com
ATLASSIAN_API_TOKEN=your-token
ATLASSIAN_SITE_URL=https://yourcompany.atlassian.net
```

These are set automatically by the connection setup.

### What Agents Can Do

Same as Linear — Jira is an alternative issue tracker with the same permission model.

---

## Google Drive

**Transport:** stdio (local subprocess)
**Auth:** OAuth

### Setup

1. You need Google Cloud credentials:
   - Go to **Google Cloud Console > APIs & Services > Credentials**
   - Create an **OAuth 2.0 Client ID** (type: Web Application)
   - Set the redirect URI to your Forge server's callback URL
2. Set these environment variables on your server:
   ```
   OAUTH_GOOGLE_CLIENT_ID=your-client-id
   OAUTH_GOOGLE_CLIENT_SECRET=your-client-secret
   ```
3. In the Forge UI, click **Connect with Google Drive**
4. Authorize read-only access in the Google popup

### What Agents Can Do

| Agent | Default | Tools |
|-------|---------|-------|
| All agents | Read | Search and read documents |

Google Drive is read-only for all agents by default.

---

## Troubleshooting

### "Connection failed" error

- Check that the MCP server is reachable (for HTTP/SSE transports)
- Verify your credentials haven't expired
- For stdio transports, ensure `npx` is available and the package can be installed

### "No tools discovered"

- The MCP server may be running but returning an empty tool list
- Check that your credentials have the right scopes/permissions
- For Notion: make sure pages are shared with your integration

### OAuth popup doesn't close

- Check that your browser allows popups from the Forge domain
- The callback URL must match exactly (including protocol and port)
- Check the server logs for OAuth callback errors

### Tools appear but agents can't use them

- Check the permission configuration in Settings > Connections > (service) > Permissions
- The agent's permission level must match the tool classification (read/write/admin)
- Check for tool-level overrides that may be blocking specific tools
