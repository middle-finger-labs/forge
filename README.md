# Forge

AI-powered software delivery pipeline orchestrated by [Temporal](https://temporal.io). Give Forge a business specification and it autonomously produces a complete codebase — from product analysis through architecture, task decomposition, parallel coding, QA review, and merge.

## Architecture

```
                            ┌─────────────────────────────────────────────────────┐
                            │              Temporal Durable Workflow               │
                            │                                                     │
  Business    ┌──────────┐  │  ┌─────┐  ┌──────────┐  ┌───────────┐  ┌────────┐  │
  Spec ──────>│  Intake  │──┼─>│ BA  │─>│ Research  │─>│ Architect │─>│   PM   │  │
              └──────────┘  │  └─────┘  └──────────┘  └───────────┘  └───┬────┘  │
                            │                                            │        │
                            │  Human approval gate (optional)            │        │
                            │  ──────────────────────────────            │        │
                            │                                            ▼        │
                            │                                   Task Decomposition │
                            │                                       │    │    │   │
                            │                              ┌────────┘    │    └───┤
                            │                              ▼             ▼        ▼
                            │                          ┌───────┐   ┌───────┐ ┌───────┐
                            │                          │Coder 1│   │Coder 2│ │Coder N│
                            │                          └───┬───┘   └───┬───┘ └───┬───┘
                            │                              ▼           ▼         ▼
                            │                          ┌───────┐   ┌───────┐ ┌───────┐
                            │                          │ QA  1 │   │ QA  2 │ │ QA  N │
                            │                          └───┬───┘   └───┬───┘ └───┬───┘
                            │                              └─────┬─────┘         │
                            │                                    ▼               │
                            │                           ┌──────────────┐         │
                            │                           │  CTO Review  │<────────┘
                            │                           └──────┬───────┘
                            │                                  ▼
                            │                           ┌─────────────┐
                            │                           │    Merge    │
                            │                           └──────┬──────┘
                            │                                  ▼
                            │                              Complete
                            └─────────────────────────────────────────────────────┘

  ┌──────────────────┐   ┌────────────────┐   ┌──────────────────────────────────┐
  │   PostgreSQL     │   │     Redis      │   │         Dashboard (React)        │
  │  Pipeline state  │   │  Real-time     │   │  Pipeline list / detail / admin  │
  │  Agent events    │   │  event pub/sub │   │  WebSocket live event stream     │
  │  Ticket tracking │   │  Working mem   │   │  Cost & concurrency monitoring   │
  └──────────────────┘   └────────────────┘   └──────────────────────────────────┘
```

### Technology stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Orchestration | Temporal | Durable workflow execution, retries, human-in-the-loop signals |
| Agents | LangGraph | Structured tool-calling state machines per agent role |
| LLM | Anthropic Claude + LiteLLM | Primary inference; local Ollama fallback for coding |
| Storage | PostgreSQL (pgvector) | Pipeline runs, ticket executions, agent events, semantic memory |
| Pub/sub | Redis | Real-time event streaming, working memory, batch event buffering |
| API | FastAPI | REST endpoints, WebSocket streaming, admin tools |
| Dashboard | React + Vite + Tailwind | Pipeline monitoring, approval gates, admin panel |
| Desktop | Tauri v2 + React 19 | Native conversational UI — agent DMs, pipeline channels, tray |
| Isolation | Git worktrees | Each coding agent works in an isolated worktree — no conflicts |

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.12+ | Uses modern type syntax (`X \| None`, `type` statements) |
| Docker & Docker Compose | Latest | Runs PostgreSQL, Redis, Temporal |
| Node.js | 22+ | Dashboard build (optional if using Docker) |
| Anthropic API key | — | Required for LLM inference |
| Ollama + GPU | Optional | Local model inference for coding tasks (needs ~20 GB VRAM) |

---

## Quick Start

```bash
# 1. Start infrastructure
docker compose up -d

# 2. Install Python dependencies
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 3. Configure your API key
echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env

# 4. Start the worker + API server
python -m worker &
python -m api.run &

# 5. Run your first pipeline
curl -X POST http://localhost:8000/api/pipelines \
  -H "Content-Type: application/json" \
  -d '{"business_spec": "Build a URL shortener with click analytics", "project_name": "shortener"}'
```

Then open [http://localhost:8000/api/pipelines](http://localhost:8000/api/pipelines) to watch it progress, or start the dashboard:

```bash
cd dashboard && npm install && npm run dev
# Open http://localhost:5173
```

### Full-stack via Docker

```bash
docker compose --profile dashboard up
```

| Service | URL |
|---------|-----|
| Dashboard | [http://localhost:3000](http://localhost:3000) |
| API | [http://localhost:8000](http://localhost:8000) |
| Temporal UI | [http://localhost:8233](http://localhost:8233) |

---

## Configuration Reference

### Environment Variables

#### Required

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude inference |

#### Infrastructure

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://forge:forge_dev_password@localhost:5432/forge_app` | PostgreSQL connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `TEMPORAL_ADDRESS` | `localhost:7233` | Temporal server gRPC address |
| `TEMPORAL_NAMESPACE` | `default` | Temporal namespace |

#### Model Routing

| Variable | Default | Description |
|----------|---------|-------------|
| `FORGE_MODEL` | `claude-sonnet-4-5-20250929` | Default model for all agents |
| `FORGE_MODEL_OVERRIDE` | — | Override model for specific agents (JSON) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL for local inference |

#### Budget & Limits

| Variable | Default | Description |
|----------|---------|-------------|
| `FORGE_MAX_COST_USD` | `10.0` | Hard budget ceiling per pipeline |
| `FORGE_COST_ALERT_USD` | `5.0` | Cost threshold for alerts |

#### Application

| Variable | Default | Description |
|----------|---------|-------------|
| `FORGE_PROJECT_PATH` | `/tmp/forge/project` | Base path for generated projects |
| `FORGE_WORKTREES_DIR` | `/tmp/forge/{pipeline_id}/worktrees` | Git worktree storage |
| `FORGE_TEST_MODE` | — | Set to `1` to skip real LLM calls (testing) |
| `LOG_LEVEL` | `info` | Logging verbosity |

#### Observability (optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `LANGFUSE_PUBLIC_KEY` | — | Langfuse tracing public key |
| `LANGFUSE_SECRET_KEY` | — | Langfuse tracing secret key |
| `LANGFUSE_HOST` | `http://localhost:3001` | Langfuse server URL |

#### Dashboard (Vite)

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_API_URL` | `http://localhost:8000` | API base URL for the frontend |
| `VITE_WS_URL` | `ws://localhost:8000` | WebSocket URL for live streaming |

### Pipeline Configuration

Runtime defaults are set in `config/agent_config.py` via `PipelineConfig`:

| Setting | Default | Description |
|---------|---------|-------------|
| `max_concurrent_engineers` | 4 | Parallel coding agents per execution group |
| `max_qa_cycles` | 3 | Max QA revision loops before escalation |
| `auto_merge` | `False` | Auto-merge without human approval |
| `auto_approve_minor_only` | `True` | Skip revision for info/warning-only QA |
| `budget_usd` | 10.0 | Per-pipeline spending limit |
| `model_overrides` | `{}` | Per-agent model overrides |

These can also be changed at runtime via `POST /api/admin/config`.

#### GitHub Integration

| Variable | Default | Description |
|----------|---------|-------------|
| `GITHUB_TOKEN` | — | Fallback PAT for GitHub API calls |
| `GITHUB_TOKEN_{NAME}` | — | Identity-specific PAT (e.g. `GITHUB_TOKEN_WORK`) |
| `GITHUB_WEBHOOK_SECRET` | — | HMAC secret for verifying GitHub webhook payloads |
| `FORGE_DASHBOARD_URL` | `http://localhost:5173` | Dashboard URL posted in issue comments |
| `GITHUB_APP_ID` | — | GitHub App ID (for app-based auth) |
| `GITHUB_APP_KEY` | — | Path to GitHub App private key PEM file |
| `GITHUB_APP_INSTALLATION_ID` | — | GitHub App installation ID |

---

## GitHub Integration

Forge supports multi-account GitHub workflows — clone from one account, push PRs from another, and handle repos across personal, corporate, and client orgs simultaneously.

### Quick Start

```bash
# 1. Run the interactive setup wizard
bash scripts/setup_github.sh

# 2. Set your GitHub token
export GITHUB_TOKEN=ghp_your_token_here

# 3. Run a pipeline against a real repo
python run_pipeline.py start \
  --repo git@github.com:yourname/project.git \
  --spec "Add user authentication with JWT"

# 4. Or run from a GitHub issue
python run_pipeline.py start \
  --repo git@github.com:yourname/project.git \
  --issue 42
```

### How It Works

```
~/.forge/identities.yaml          ~/.ssh/config
┌──────────────────────────┐      ┌─────────────────────────────┐
│ - name: "personal"       │      │ Host github-personal        │
│   github_username: nate   │      │   HostName github.com       │
│   ssh_key_path: ~/.ssh/…  │◄────►│   IdentityFile ~/.ssh/…     │
│   ssh_host_alias:         │      │   IdentitiesOnly yes        │
│     github-personal       │      │                             │
│   default: true           │      │ Host github-work            │
│                           │      │   HostName github.com       │
│ - name: "work"            │      │   IdentityFile ~/.ssh/…     │
│   github_org: "MyCompany" │◄────►│   IdentitiesOnly yes        │
│   ssh_host_alias:         │      └─────────────────────────────┘
│     github-work           │
└──────────────────────────┘
             │
             ▼
  git@github.com:MyCompany/repo.git
  → resolves "work" identity (org match)
  → rewrites to git@github-work:MyCompany/repo.git
  → uses GITHUB_TOKEN_WORK for API calls
```

### Identity Resolution

When you run `forge start --repo <url>`, Forge picks the right identity:

1. **Explicit flag** — `--identity work` always wins
2. **Org match** — repo owner matches `github_org` or `extra_orgs`
3. **Username match** — repo owner matches `github_username`
4. **Default** — falls back to the identity with `default: true`

### CLI Commands

```bash
# Identity management
python run_pipeline.py identities list          # Show all configured identities
python run_pipeline.py identities test <name>   # Test SSH + API for an identity
python run_pipeline.py identities add           # Interactive identity creation

# Repo testing
python run_pipeline.py repos test <url>                      # Clone, inspect, cleanup
python run_pipeline.py repos test <url> --identity <name>    # Test with specific identity

# Pipeline with repo
python run_pipeline.py start --repo <url> --spec "..."       # Inline spec
python run_pipeline.py start --repo <url> --issue 42         # From GitHub issue
python run_pipeline.py start --repo <url> --spec-file req.md # From file
python run_pipeline.py start --repo <url> --spec "..." \
  --identity work --pr-strategy pr_per_ticket                # Full options
```

### PR Strategies

| Strategy | Description |
|----------|-------------|
| `single_pr` (default) | One branch + one PR with all changes |
| `pr_per_ticket` | Separate branch + PR per decomposed ticket |
| `direct_push` | Push directly to a target branch (no PR) |

### Webhook Automation

Forge includes a webhook receiver that auto-starts pipelines when GitHub issues are labeled `forge`:

```bash
# Set the webhook secret
export GITHUB_WEBHOOK_SECRET=$(openssl rand -hex 32)

# Configure in GitHub: repo > Settings > Webhooks
# Payload URL: https://your-forge-host/webhooks/github
# Events: Issues, Issue comments, Pull request reviews
```

Issue comment commands: `/forge approve`, `/forge abort`, `/forge status`.

### Documentation

| Document | Description |
|----------|-------------|
| [docs/github-setup.md](docs/github-setup.md) | Full setup guide: SSH keys, PATs, GitHub Apps, troubleshooting |
| [docs/workflow-examples.md](docs/workflow-examples.md) | Real-world usage examples and patterns |
| [identities.yaml.example](identities.yaml.example) | Commented config template for personal/work/client setups |

---

## Architecture Walkthrough

### 1. Temporal Workflow (`workflows/pipeline.py`)

The `ForgePipeline` workflow is a single durable execution that survives process restarts.
It runs each pipeline stage as a Temporal **activity** with configurable retry policies.
Human approval gates use Temporal **signals** — the workflow blocks until a signal arrives
from the dashboard or API.

Key concepts:
- **Two task queues**: `forge-pipeline` for orchestration activities, `forge-coding` for coding tasks (separate scaling)
- **Typed error handling**: Activities raise typed `ForgeError` subclasses that the workflow uses for intelligent retry decisions (retry LLM timeouts, abort on budget exceeded, escalate git conflicts to CTO)
- **Budget guardrails**: Cost is checked before every stage; the workflow aborts cleanly if the ceiling is hit

### 2. LangGraph Agents (`agents/`)

Each pipeline stage is powered by a LangGraph agent — a state machine with tool-calling nodes:

| Agent | Role | Output Schema |
|-------|------|---------------|
| `stage_1_business_analyst` | Analyze business spec | `ProductSpec` |
| `stage_2_researcher` | Market & technology research | `EnrichedSpec` |
| `stage_3_architect` | System design & API contracts | `TechSpec` |
| `stage_4_pm` | Task decomposition into tickets | `PRDBoard` |
| `stage_5_engineer` | Code implementation per ticket | `CodeArtifact` |
| `stage_6_qa` | Code review & testing | `QAReview` |
| `stage_7_cto` | Conflict resolution & final review | `MergeDecision` |

Agents use structured output validation via Pydantic schemas defined in `contracts/schemas.py`.

### 3. Model Routing (`config/model_router.py`)

The `ModelRouter` handles provider selection:

```
Request → Rate Limiter → Circuit Breaker → Provider (Anthropic / Ollama)
                                              ↓ failure
                                         Fallback Provider
```

- **Rate limiting**: Token-bucket per model to avoid 429s
- **Circuit breaker**: 5 failures in 2 min opens the circuit for 60s
- **Fallback**: Cloud → local (or vice versa) on provider failure
- **Cost tracking**: Every completion records input/output tokens and cost

### 4. Git Worktrees (`agents/worktree_manager.py`)

Each coding agent works in an isolated git worktree:

```
/tmp/forge/{pipeline_id}/
  main/                  ← scaffold (project skeleton)
  worktrees/
    ticket-001/          ← Coder #1's isolated workspace
    ticket-002/          ← Coder #2's isolated workspace
    ...
```

Worktrees are reused across QA revision cycles (reset, not recreated) for performance.
Merge happens via `git merge --no-ff` with automatic conflict resolution by the CTO agent.

---

## Cost Estimation Guide

Typical per-pipeline costs (using Claude Sonnet 4.5):

| Complexity | Tickets | Estimated Cost | Example |
|------------|---------|---------------|---------|
| Trivial | 1-3 | $0.10 - $0.50 | Hello world, single-file script |
| Simple | 3-8 | $0.50 - $2.00 | REST API with 3-4 endpoints |
| Medium | 8-15 | $2.00 - $5.00 | Full-stack app with auth, DB, tests |
| Complex | 15-30 | $5.00 - $10.00 | Microservice with multiple integrations |

Cost breakdown by stage (typical):

| Stage | % of Total | Why |
|-------|-----------|-----|
| Business Analysis | ~5% | Single prompt, structured output |
| Research | ~8% | Multiple search + synthesis passes |
| Architecture | ~10% | System design, API contracts |
| Task Decomposition | ~7% | Ticket generation |
| Coding | ~45% | Largest — one agent per ticket, revision loops |
| QA Review | ~20% | Code review + test generation per ticket |
| CTO / Merge | ~5% | Conflict resolution, final checks |

**Cost reduction strategies:**
- Use Ollama locally for coding tasks (free inference)
- Enable `auto_approve_minor_only` to skip unnecessary QA cycles
- Set tight budget limits via `FORGE_MAX_COST_USD`
- Use `claude-haiku-4-5-20241022` as a fallback model for lower-priority agents

---

## Development Guide

### Adding a New Agent Role

1. **Define the agent** in `agents/stage_N_<name>.py`:
   ```python
   async def run(spec: YourInputSchema) -> YourOutputSchema:
       graph = build_graph(...)
       result = await graph.ainvoke({"input": spec})
       return YourOutputSchema(**result)
   ```

2. **Add the output schema** to `contracts/schemas.py`:
   ```python
   class YourOutputSchema(BaseModel):
       field: str = Field(..., min_length=1)
   ```

3. **Register the agent config** in `config/agent_config.py`:
   ```python
   AgentRole.YOUR_ROLE: AgentConfig(
       role=AgentRole.YOUR_ROLE,
       display_name="Your Agent",
       model=MODEL_STRONG,
   ),
   ```

4. **Create the activity** in `activities/pipeline_activities.py`:
   ```python
   @activity.defn
   async def run_your_stage(input: YourStageInput) -> StageResult:
       ...
   ```

5. **Wire it into the workflow** in `workflows/pipeline.py` by adding a `_run_stage()` call in the `run()` method.

6. **Register the activity** in `worker.py` under the appropriate task queue.

### Modifying Prompts

Agent prompts live in the `agents/stage_*` files as string constants or f-strings.
Each agent follows the pattern:

```python
SYSTEM_PROMPT = """You are the {role} agent..."""

async def run(spec):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": format_input(spec)},
    ]
    ...
```

### Adding Pipeline Stages

1. Add the stage enum value to `PipelineStage` in `workflows/types.py`
2. Add stage-specific timeout to `_STAGE_TIMEOUTS` in `workflows/pipeline.py`
3. Add stage badge color to `stageBadge` in `dashboard/src/pages/PipelineListPage.tsx`
4. Update the dashboard stage display components as needed

---

## Project Structure

```
forge/
  activities/             # Temporal activity implementations
    pipeline_activities.py  # All stage activities + error handling
  agents/                 # LangGraph agent definitions
    stage_1_business_analyst.py
    stage_2_researcher.py
    stage_3_architect.py
    stage_4_pm.py
    stage_5_engineer.py
    stage_6_qa.py
    stage_7_cto.py
    worktree_manager.py   # Git worktree isolation
    swarm_coordinator.py  # Parallel ticket execution
  api/                    # FastAPI REST + WebSocket server
    server.py             # All endpoints + webhook router
    run.py                # Uvicorn entrypoint
  auth/                   # Authentication & multi-tenancy
    server.ts             # Better Auth service (Node.js)
    seed.ts               # Default org + admin seeder
    middleware.py          # FastAPI session validation middleware
    types.py              # ForgeUser dataclass
    secrets.py            # Fernet encryption, org secrets, settings, identities
  config/                 # Agent configuration, routing, budget
    agent_config.py       # Per-agent settings
    budget.py             # Cost guardrails
    concurrency.py        # Backpressure monitoring
    errors.py             # Typed exception hierarchy
    model_router.py       # LLM provider routing
    rate_limiter.py       # Token-bucket rate limiting
  contracts/              # Shared Pydantic schemas
    schemas.py            # ProductSpec, TechSpec, PRDBoard, etc.
  desktop/                # Tauri v2 native desktop app (see desktop/README.md)
  dashboard/              # React + Vite + Tailwind frontend
    src/pages/
      PipelineListPage.tsx
      PipelineDetailPage.tsx
      AdminPage.tsx
      SettingsPage.tsx        # Org settings, API keys, identities, members
      LoginPage.tsx           # Better Auth login
      SignupPage.tsx          # Better Auth signup
    src/components/
      OrgSwitcher.tsx         # Organization selector dropdown
      PresenceBar.tsx         # Real-time user presence avatars
      ChatPanel.tsx           # Multiplayer chat + approval interface
      MemoryPanel.tsx         # Org-scoped memory browser
    src/lib/
      auth.ts                 # Better Auth client SDK setup
  docs/                   # Documentation
    github-setup.md       # SSH, PAT, GitHub App setup guide
    workflow-examples.md  # Real-world usage patterns
  infrastructure/         # SQL schema, Docker configs
    init.sql              # Database initialization
  integrations/           # GitHub integration layer
    git_identity.py       # Multi-account SSH identity management
    github_client.py      # Async GitHub API client (PAT + App auth)
    issue_tracker.py      # Issue → spec conversion, status reporting
    repo_connector.py     # Clone, push, PR creation bridge
    webhook_server.py     # GitHub webhook receiver (FastAPI router)
  memory/                 # State persistence layer
    state_store.py        # PostgreSQL state store
    working_memory.py     # Redis working memory
    semantic_memory.py    # Vector similarity search
    observability.py      # Cost tracking
  scripts/                # Utility and simulation scripts
    run_e2e.sh            # E2E test orchestrator
    simulate_swarm.py     # Load simulation
    setup_local_models.sh # Ollama model setup
    setup_github.sh       # Interactive GitHub identity wizard
  tests/                  # Test suite
    test_errors.py        # Error hierarchy tests
    test_github_integration.py    # GitHub integration tests
    test_pipeline_integration.py  # Temporal integration tests
    test_e2e_production.py        # Full-stack E2E tests
  workflows/              # Temporal workflow definitions
    pipeline.py           # Main ForgePipeline workflow
    types.py              # Dataclasses for workflow I/O
  worker.py               # Temporal worker entrypoint
  run_pipeline.py         # CLI for pipeline, identity, and repo management
  identities.yaml.example # Sample identity config with comments
  docker-compose.yml      # Infrastructure services
```

## API Endpoints

### Pipeline Management

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Service health check (PG, Redis, Temporal) |
| `GET` | `/api/pipelines` | List all pipeline runs |
| `POST` | `/api/pipelines` | Start a new pipeline |
| `GET` | `/api/pipelines/:id` | Get pipeline details + artifacts |
| `GET` | `/api/pipelines/:id/events` | Get agent events |
| `GET` | `/api/pipelines/:id/tickets` | Get ticket executions |
| `GET` | `/api/pipelines/:id/state` | Query Temporal workflow state |
| `GET` | `/api/pipelines/:id/concurrency` | Concurrency metrics |
| `POST` | `/api/pipelines/:id/approve` | Send approval signal |
| `POST` | `/api/pipelines/:id/reject` | Send rejection signal |
| `POST` | `/api/pipelines/:id/abort` | Abort the pipeline |
| `WS` | `/ws/pipeline/:id` | Real-time event stream |

### Admin & Observability

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/admin/stats` | System-wide statistics |
| `GET` | `/api/admin/models` | Model availability and health |
| `GET` | `/api/admin/config` | Current runtime configuration |
| `POST` | `/api/admin/config` | Update pipeline defaults |
| `GET` | `/api/pipelines/:id/errors` | Error log for a pipeline |
| `GET` | `/api/pipelines/:id/cost-breakdown` | Detailed cost breakdown |
| `POST` | `/api/pipelines/:id/retry-stage` | Retry a failed stage |

### Memory

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/memory/lessons` | Retrieve stored lessons (org-scoped) |
| `POST` | `/api/memory/lessons` | Manually add a lesson |
| `GET` | `/api/memory/decisions` | Retrieve stored decisions (org-scoped) |
| `GET` | `/api/memory/stats` | Memory statistics (per-role, per-user) |
| `DELETE` | `/api/memory/lessons/:id` | Delete a lesson (admin only) |

### Org Settings & Secrets

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/settings` | Get org settings |
| `PUT` | `/api/settings` | Update org settings (admin) |
| `GET` | `/api/secrets` | List secret key names |
| `PUT` | `/api/secrets/:key` | Set an encrypted secret (admin) |
| `DELETE` | `/api/secrets/:key` | Delete a secret (admin) |
| `GET` | `/api/identities` | List GitHub identities |
| `POST` | `/api/identities` | Add a GitHub identity (admin) |
| `DELETE` | `/api/identities/:id` | Remove an identity (admin) |
| `POST` | `/api/identities/:id/test` | Test identity connection |

---

## Troubleshooting

### Pipeline stuck at "running" indefinitely

**Cause:** The Temporal worker is not running or cannot connect to Temporal.

```bash
# Check worker is running
ps aux | grep "python -m worker"

# Check Temporal is reachable
docker compose ps temporal
curl -sf http://localhost:7233 || echo "Temporal unreachable"
```

### "Budget exceeded" error immediately

**Cause:** A previous pipeline consumed the budget and the cost wasn't reset.

Each pipeline has its own budget tracked in the workflow state. Check:
```bash
curl http://localhost:8000/api/pipelines/{id}/cost-breakdown
```

### Worker crashes with "cannot import module"

**Cause:** Missing dependency or wrong Python version.

```bash
python --version  # Must be 3.12+
pip install -e ".[dev]"
```

### Dashboard shows "Failed to load pipelines"

**Cause:** API server isn't running or CORS issue.

```bash
# Check API health
curl http://localhost:8000/api/health

# If running dashboard on a different port, ensure VITE_API_URL matches
echo "VITE_API_URL=http://localhost:8000" >> dashboard/.env
```

### Coding agents produce empty files

**Cause:** Model rate limiting or content policy blocking.

Check the pipeline errors:
```bash
curl http://localhost:8000/api/pipelines/{id}/errors
```

If you see `ContentPolicyError`, the prompt may need adjustment. If `rate_limit`, reduce `max_concurrent_engineers` in the admin config.

### Ollama model not being used

**Cause:** Ollama not running, model not pulled, or no GPU detected.

```bash
# Check Ollama
curl http://localhost:11434/api/tags

# Pull the model
scripts/setup_local_models.sh

# Check worker logs for "local model ready" or warnings
```

### Git merge conflicts during merge stage

**Cause:** Parallel coding agents modified overlapping files.

The CTO agent handles conflicts automatically. If it fails:
1. Check `GET /api/pipelines/{id}/errors` for `MergeConflictError`
2. Use `POST /api/pipelines/{id}/retry-stage` with `{"stage": "merge"}` to retry
3. Reduce `max_concurrent_engineers` if conflicts are frequent

---

## Performance Tuning

### Concurrency

`PipelineConfig` in `config/agent_config.py` controls parallelism:

- `max_concurrent_engineers` (default 4) — parallel coding agents per group
- Backpressure managed by `ConcurrencyConfig` in `config/concurrency.py`

### Connection Pools

| Service | Pool size | Config location |
|---------|-----------|-----------------|
| Redis | 20 connections | `memory/working_memory.py` |
| PostgreSQL | 2-10 connections | `memory/state_store.py` |
| Anthropic (httpx) | 20 max / 10 keepalive | `config/agent_config.py` |

### Stress Testing

```bash
# 20 tickets, reproducible randomness
python -m scripts.simulate_swarm --tickets 20 --seed 42

# 50 tickets, 8 parallel agents, 30% QA failure rate
python -m scripts.simulate_swarm --tickets 50 --max-parallel 8 --failure-rate 0.3
```

---

## Multiplayer

Forge supports multiplayer collaboration — multiple team members can run pipelines, share memory, and coordinate approvals within an organization.

### Architecture

```
Browser ──► nginx (dashboard) ──► React SPA
                │
                ├── /api/auth/* ──► forge-auth (Better Auth, port 3100)
                │                      │
                │                      ▼
                ├── /api/*     ──► forge-api (FastAPI, port 8000)
                │                      │
                │                      ├── PostgreSQL (pgvector)
                │                      ├── Redis (presence, pub/sub)
                │                      └── Temporal (workflow orchestration)
                │
                └── /ws/*      ──► forge-api (WebSocket rooms)
```

| Component | Technology | Role |
|-----------|-----------|------|
| Auth | Better Auth + organization plugin | Login, signup, sessions, org membership, RBAC |
| API | FastAPI | Session validation via auth middleware, org-scoped queries |
| Dashboard | React + Better Auth client SDK | Login/signup UI, org switcher, real-time presence |
| WebSocket | FastAPI + Redis pub/sub | Room-based event streaming scoped to pipeline + org |
| Secrets | Fernet symmetric encryption | Per-org encrypted storage for API keys and tokens |
| Memory | pgvector + sentence-transformers | Org-scoped semantic memory shared across all members |

### Quick start

```bash
# 1. Start the full stack
./scripts/setup.sh

# 2. Open the dashboard
open http://localhost:3000

# 3. Log in with the default admin account
#    Email:    admin@example.com (or FORGE_ADMIN_EMAIL from .env)
#    Password: changeme123       (or FORGE_ADMIN_PASSWORD from .env)

# 4. Invite your partner from Settings → Members → Invite
```

### How auth works

1. **Better Auth** handles signup, login, password hashing, and session tokens
2. The React dashboard uses Better Auth's client SDK (`useSession`, `signIn`, `signUp`)
3. FastAPI middleware (`auth/middleware.py`) validates session cookies/tokens by calling Better Auth's `/api/auth/get-session` endpoint
4. Validated sessions are cached in Redis (60s TTL) to avoid per-request auth service calls
5. Every API endpoint receives a `ForgeUser` with `user_id`, `org_id`, `role` via dependency injection

### How multi-tenancy works

- Every database record (pipelines, events, tickets, secrets, memory) includes an `org_id` column
- API queries filter by `WHERE org_id = $user.org_id` — users only see their org's data
- Pipeline creation stamps `org_id` from the authenticated user's active organization
- Org settings, secrets, and GitHub identities are all scoped per-org

### How presence works

- Each pipeline has a Redis hash (`presence:{pipeline_id}`) tracking connected users
- WebSocket connections send heartbeats every 30 seconds
- The dashboard shows real-time avatar indicators for all active viewers
- Typing indicators in the chat panel broadcast via WebSocket to the room

### How shared memory works

- All pipeline runs within an org contribute lessons and decisions to a shared memory store
- Memory is stored in PostgreSQL with pgvector embeddings for semantic search
- `memory_sharing_mode` (org setting): **shared** (all members see everything) or **private** (each member sees only their own)
- Admins can view contributor statistics and delete individual memories from the dashboard

### Documentation

| Document | Description |
|----------|-------------|
| [docs/multiplayer-setup.md](docs/multiplayer-setup.md) | Detailed multiplayer setup guide |
| [docs/github-setup.md](docs/github-setup.md) | GitHub SSH, PAT, and App auth setup |

---

## Deployment

### Docker Compose (recommended)

```bash
# First-time setup (generates secrets, builds images, runs migrations, seeds DB)
./scripts/setup.sh

# Subsequent starts
docker compose up -d

# Update after code changes
./scripts/deploy.sh
```

| Service | URL | Description |
|---------|-----|-------------|
| Dashboard | http://localhost:3000 | React app (nginx) |
| API | http://localhost:8000 | FastAPI REST + WebSocket |
| Auth | http://localhost:3100 | Better Auth service |
| Temporal UI | http://localhost:8088 | Workflow monitoring |
| Langfuse | http://localhost:3001 | LLM observability (optional) |

### Docker profiles

```bash
docker compose up -d                         # Core stack
docker compose --profile gpu up -d           # + Ollama local LLM
docker compose --profile observability up -d # + Langfuse tracing
```

---

## Desktop App

Forge Desktop is a native conversational interface where **AI agents are teammates you chat with** — not dashboards you stare at. Instead of monitoring pipeline stages on a web UI, you interact with agents via direct messages and pipeline channels, just like Slack.

```
┌──────────┬──────────────────────────────────┬──────────────────┐
│          │  #auth-redesign                  │                  │
│ Agents   │                                  │   DAG Minimap    │
│ 🔍 idle  │  🏗️ Architect  10:32 AM          │   ┌──┐  ┌──┐    │
│ 📐 working│  Here's the system design...     │   │BA│→│RS│    │
│ 📋 idle  │                                  │   └──┘  └──┘    │
│ 🔧 idle  │  📋 PM  10:34 AM                 │      ↓          │
│          │  I've decomposed this into 4      │   ┌──┐  ┌──┐   │
│ Channels │  tickets. Ready for approval:     │   │AR│→│PM│    │
│ #auth    │  ┌─────────────────────┐          │   └──┘  └──┘   │
│ #dash-v2 │  │ ✅ Approve  ❌ Reject │          │                │
│          │  └─────────────────────┘          │                 │
├──────────┴──────────────────────────────────┴──────────────────┤
│ ● Connected to forge.example.com  ⚡ 1 pipeline running  $0.42│
└───────────────────────────────────────────────────────────────-┘
```

### Key features

- **Agent DMs** — Chat directly with any agent (BA, Researcher, Architect, PM, Engineer, QA, CTO). Each has personality, quick actions, and thinking indicators.
- **Pipeline channels** — Real-time multi-agent conversations with DAG visualization, approval cards, and cost tracking.
- **Quick Switcher** — `Cmd+K` fuzzy search across agents, conversations, and commands.
- **Activity Feed** — Unified "All Unreads" view with filters for pipelines, DMs, and approvals.
- **Native integration** — System tray with live status, native notifications for approvals, global `Cmd+Shift+F` hotkey, "Open in VS Code" button, close-to-tray, window state persistence.
- **Theming** — Dark and light modes with dynamic CSS variable system.

### Install

Download the latest release for your platform from [GitHub Releases](../../releases):

| Platform | File |
|----------|------|
| macOS (Apple Silicon) | `Forge_x.x.x_aarch64.dmg` |
| macOS (Intel) | `Forge_x.x.x_x86_64.dmg` |
| Windows | `Forge_x.x.x_x64-setup.exe` |
| Linux (Debian/Ubuntu) | `forge_x.x.x_amd64.deb` |
| Linux (Other) | `forge_x.x.x_amd64.AppImage` |

On first launch, enter your Forge server URL and log in with your credentials.

### Development

```bash
cd desktop
pnpm install
pnpm tauri dev
```

See the [Desktop README](desktop/README.md) for full documentation on architecture, IPC, WebSocket management, and native feature wiring.

### Tech stack

| Layer | Technology |
|-------|-----------|
| Native shell | Tauri v2 (Rust) |
| Frontend | React 19 + TypeScript 5.9 |
| Build | Vite 7 |
| Styling | Tailwind CSS 4 |
| State | Zustand 5 |

---

## Roadmap

- ~~**Multi-repository support**~~ — Clone, push, and create PRs across personal, corporate, and client repos with multi-account SSH identities
- ~~**CI/CD integration**~~ — Auto-create GitHub PRs from pipeline results, webhook-triggered pipelines from GitHub issues, issue comment commands
- ~~**Team collaboration**~~ — Multi-user dashboards, org-scoped data, role-based access, shared approvals, real-time presence, org-scoped memory
- ~~**Desktop app**~~ — Native Tauri v2 desktop client with conversational agent UI, system tray, notifications, and cross-platform builds
- **Incremental builds** — Modify existing codebases instead of generating from scratch (partial: `--repo` clones an existing repo as the starting point)
- **Plugin agents** — User-defined agent roles with custom tools and prompts
- **Cost optimization** — Adaptive model selection based on task complexity scoring
- **Streaming output** — Real-time code generation visible in the dashboard as agents type
- **Test execution** — Run generated tests in sandboxed containers and feed results back to QA

---

## License

See [LICENSE](LICENSE) for details.
