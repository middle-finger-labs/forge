# Forge Dashboard

Real-time multiplayer monitoring dashboard for the Forge AI pipeline. Built with React 19, Vite, TypeScript, and Tailwind CSS v4.

## Features

### Authentication & Multi-tenancy

- **Login / Signup** — Email + password auth via Better Auth client SDK
- **Organization Switcher** — Switch between orgs, create new orgs, accept invitations
- **Role-based access** — Owner, admin, and member roles with scoped permissions
- **Settings page** — Org configuration, API key management, GitHub identities, member management

### Pipeline Management

- **Pipeline List** — View all pipeline runs with status badges, start new pipelines from the UI
- **DAG Visualization** — Interactive stage graph with React Flow, real-time status updates per node
- **Live Log Panel** — Virtualized event stream with filtering, search, and auto-scroll
- **Chat/Approval Panel** — Multiplayer chat with approval buttons, typing indicators, and message history
- **Artifact Viewer** — Rich formatted views for specs, PRD boards, code artifacts, QA reviews
- **Cost Tracker** — Budget tracking with per-stage cost breakdown bar chart

### Multiplayer

- **Real-time Presence** — See who else is viewing the same pipeline (avatar bar with initials)
- **Multiplayer Chat** — In-pipeline chat between team members with message attribution
- **Shared Approvals** — Any org member can approve or reject pipeline stages
- **Org Memory** — Browse team-contributed lessons and decisions, with per-user contribution stats

### GitHub Integration

- **Repo-connected pipelines** — Displays target repo, branch, and PR link
- **Issue-linked pipelines** — Shows source issue number with direct link
- **PR status** — Created PR URL, branch name, and draft/open state
- **Webhook-triggered runs** — Pipelines from forge-labeled issues appear in the list

### Admin Panel

- **Runtime config** — Adjust concurrency, budget limits, and model overrides
- **Model health** — Provider availability and circuit breaker state
- **System stats** — Pipeline counts, success rates, cost totals
- **Memory browser** — View and manage stored lessons and decisions

## Pages

| Page | Route | Description |
|------|-------|-------------|
| Login | `/login` | Email + password sign in |
| Signup | `/signup` | New user registration |
| Pipeline List | `/` | Pipeline table with create dialog |
| Pipeline Detail | `/pipeline/:id` | 3-panel monitoring view with presence |
| Settings | `/settings` | 4-tab org management (General, API Keys, Identities, Members) |
| Admin | `/admin` | Runtime config, model health, system stats |

## Components

### New (Multiplayer)

| Component | Description |
|-----------|-------------|
| `OrgSwitcher.tsx` | Org selector dropdown with create/invite/switch actions |
| `PresenceBar.tsx` | Horizontal avatar strip showing active pipeline viewers |
| `UserMenu.tsx` | User avatar dropdown with sign-out |
| `ChatPanel.tsx` | Real-time multiplayer chat with typing indicators and approval buttons |
| `MemoryPanel.tsx` | Org-scoped memory browser (Lessons, Decisions, Team tabs) |

### Core

| Component | Description |
|-----------|-------------|
| `PipelineDAG.tsx` | React Flow stage visualization with live status |
| `LogPanel.tsx` | Virtualized real-time event log |
| `ArtifactViewer.tsx` | Modal for viewing pipeline artifacts |
| `CostTracker.tsx` | Budget tracking bar chart |
| `StageFeed.tsx` | Per-stage event timeline |

## Development

### Prerequisites

- Node.js 22+
- The Forge infrastructure running (PostgreSQL, Redis, Temporal)
- The API server running on port 8000
- The auth service running on port 3100

### Setup

```bash
npm install
npm run dev
```

The dashboard starts at [http://localhost:5173](http://localhost:5173).

### Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_API_URL` | `http://localhost:8000` | FastAPI backend URL |
| `VITE_AUTH_URL` | `http://localhost:3100` | Better Auth service URL |
| `VITE_WS_URL` | `ws://localhost:8000` | WebSocket endpoint for real-time events |

These are configured in `src/lib/api.ts` and `src/lib/auth.ts`.

### Build

```bash
npm run build     # TypeScript check + Vite production build
npm run preview   # Preview the production build locally
```

### Docker

```bash
# From the project root — starts the full stack including dashboard on port 3000
docker compose up -d
```

The nginx configuration (`nginx.conf`) handles:
- `/api/auth/*` → proxied to `forge-auth:3100`
- `/api/*` → proxied to `forge-api:8000`
- `/ws/*` → proxied to `forge-api:8000` (WebSocket upgrade)
- All other routes → serve static React build with SPA fallback

## Project Structure

```
src/
  components/
    ArtifactViewer.tsx   # Modal for viewing pipeline artifacts
    ChatPanel.tsx        # Multiplayer chat + approval interface
    CostTracker.tsx      # Budget tracking bar chart
    LogPanel.tsx         # Virtualized real-time event log
    MemoryPanel.tsx      # Org-scoped memory browser
    OrgSwitcher.tsx      # Organization selector dropdown
    PipelineDAG.tsx      # React Flow stage visualization
    PresenceBar.tsx      # Real-time presence avatars
    StageFeed.tsx        # Per-stage event timeline
    UserMenu.tsx         # User avatar with sign-out
  hooks/
    usePresence.ts       # Presence tracking hook
    useWebSocket.ts      # WebSocket hook with reconnection
  lib/
    api.ts               # Typed fetch wrappers for all API endpoints
    auth.ts              # Better Auth client SDK configuration
  pages/
    AdminPage.tsx        # Runtime config, model health, stats
    LoginPage.tsx        # Better Auth login
    PipelineDetailPage.tsx # 3-panel pipeline monitoring
    PipelineListPage.tsx # Pipeline list + create dialog
    SettingsPage.tsx     # Org settings (4 tabs)
    SignupPage.tsx       # Better Auth signup
  types/
    pipeline.ts          # TypeScript interfaces for API data
  App.tsx                # Router setup with auth guards
  main.tsx               # Entry point
```
