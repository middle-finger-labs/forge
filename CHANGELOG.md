# Changelog

All notable changes to the Forge pipeline are documented here.

## [0.1.0] - 2026-02-22

### Core Pipeline

- **Temporal workflow orchestration** (`workflows/pipeline.py`) — Durable `ForgePipeline` workflow with 9 stages: intake, business analysis, research, architecture, task decomposition, scaffold, coding, QA review, merge
- **Dual task queues** — `forge-pipeline` for orchestration, `forge-coding` for coding tasks (independent scaling)
- **Human-in-the-loop approval gates** — Temporal signals for approve/reject/abort from dashboard or API
- **Budget guardrails** (`config/budget.py`) — Per-pipeline cost ceiling with 50%/80%/100% thresholds, model downgrade on 80%, hard stop at 100%

### LangGraph Agents

- **Business Analyst** (`agents/stage_1_business_analyst.py`) — Analyzes business spec, produces `ProductSpec` with user stories and acceptance criteria
- **Researcher** (`agents/stage_2_researcher.py`) — Market research, competitor analysis, technology recommendations → `EnrichedSpec`
- **Architect** (`agents/stage_3_architect.py`) — System design with API contracts, database models, service topology → `TechSpec`
- **PM / Task Decomposition** (`agents/stage_4_pm.py`) — Breaks architecture into prioritized tickets with dependency ordering → `PRDBoard`
- **Engineer** (`agents/stage_5_engineer.py`) — Parallel coding in isolated git worktrees, one agent per ticket → `CodeArtifact`
- **QA** (`agents/stage_6_qa.py`) — Automated code review with severity-based verdicts → `QAReview`
- **CTO** (`agents/stage_7_cto.py`) — Conflict resolution, merge decisions, architectural oversight

### Parallel Execution

- **Swarm coordinator** (`agents/swarm_coordinator.py`) — Manages parallel coding groups with configurable concurrency
- **Git worktree isolation** (`agents/worktree_manager.py`) — Each agent works in a separate worktree; no file conflicts between parallel agents
- **Worktree reuse** — Reset and reuse worktrees across QA revision cycles instead of recreating
- **Backpressure monitoring** (`config/concurrency.py`) — System load tracking, configurable thresholds

### Model Routing

- **LiteLLM integration** (`config/model_router.py`) — Unified routing across Anthropic Claude and local Ollama models
- **Circuit breaker** — 5 failures in 2 minutes opens circuit for 60 seconds
- **Token-bucket rate limiting** (`config/rate_limiter.py`) — Per-model rate limits to avoid 429 errors
- **Automatic fallback** — Cloud → local (or vice versa) on provider failure
- **Cost tracking** — Per-request token counting and USD cost calculation

### Structured Error Handling

- **Typed exception hierarchy** (`config/errors.py`) — `ForgeError` base with subclasses: `LLMError`, `ContentPolicyError`, `ValidationError`, `BudgetExceededError`, `GitError`, `MergeConflictError`, `AgentTimeoutError`
- **Error classification** — `_classify_and_wrap()` inspects exceptions and maps them to the correct `ForgeError` subclass
- **Type-aware retry logic** — Workflow retries LLM timeouts (with backoff), aborts on budget exceeded, escalates git conflicts to CTO
- **Error reporting** — `ErrorReporter` with sliding-window frequency tracking and circuit-breaker detection
- **Temporal bridge** — Activities raise typed errors that the workflow catches via `ActivityError` → `ApplicationError` unwrapping

### Memory & Persistence

- **PostgreSQL state store** (`memory/state_store.py`) — Pipeline runs, ticket executions, agent events, CTO interventions
- **Redis working memory** (`memory/working_memory.py`) — Real-time event pub/sub, batched event emission (500ms flush)
- **Semantic memory** (`memory/semantic_memory.py`) — Vector similarity search for lessons and architectural decisions
- **Observability** (`memory/observability.py`) — Cost summaries, model usage tracking

### Dashboard API

- **FastAPI server** (`api/server.py`) — REST endpoints for pipeline management
- **Pipeline CRUD** — List, create, get details, events, tickets, state
- **Pipeline actions** — Approve, reject, abort via Temporal signals
- **WebSocket streaming** — Real-time event stream via Redis pub/sub
- **Admin endpoints** — System stats, model health, runtime config, error logs, cost breakdown, stage retry
- **Concurrency metrics** — Active agents, group progress, estimated remaining time

### Dashboard Frontend

- **Pipeline list** (`PipelineListPage.tsx`) — Status badges, stage indicators, cost tracking, relative timestamps
- **Pipeline detail** (`PipelineDetailPage.tsx`) — Live event log, ticket progress, approval buttons, cost panel, concurrency metrics
- **Admin page** (`AdminPage.tsx`) — System stats cards, model health table, config form, recent errors list
- **Real-time updates** — WebSocket connection with auto-reconnect, 10-second polling fallback

### Contracts & Schemas

- **Pydantic schemas** (`contracts/schemas.py`) — `ProductSpec`, `EnrichedSpec`, `TechSpec`, `PRDBoard`, `CodeArtifact`, `QAReview` with field-level validation
- **Workflow types** (`workflows/types.py`) — `PipelineInput`, `PipelineStage`, `StageResult`, `HumanApproval`, `RetryStageRequest`

### Testing

- **Unit tests** — Error hierarchy, agent mocks, worktree manager, semantic memory, state store, working memory
- **Temporal integration tests** — Full pipeline success, human rejection, budget exceeded, LLM error retry, budget abort
- **E2E production tests** (`tests/test_e2e_production.py`) — Full pipeline with real LLM calls, model routing, budget enforcement, dashboard API (gated behind `FORGE_E2E=1`)
- **E2E orchestration** (`scripts/run_e2e.sh`) — Docker compose lifecycle, service readiness, log capture, cleanup
- **Swarm simulation** (`scripts/simulate_swarm.py`) — Load testing with configurable ticket counts, failure rates, parallelism

### Infrastructure

- **Docker Compose** — PostgreSQL (pgvector), Redis, Temporal, Temporal UI; optional Ollama (GPU profile), Langfuse (observability profile), Dashboard (dashboard profile)
- **Database schema** (`infrastructure/init.sql`) — `forge_app` database with `pipeline_runs`, `ticket_executions`, `agent_events`, `cto_interventions`, `memory_store` tables

### Documentation & CI

- **README** — Architecture diagram, quick start, configuration reference, architecture walkthrough, cost estimation guide, development guide, troubleshooting, roadmap
- **CONTRIBUTING.md** — Dev environment setup, test running guide, code style (ruff + conventional commits), PR process
- **GitHub Actions** (`.github/workflows/ci.yml`) — Ruff lint + format check, pytest (unit), dashboard build + type check, optional pyright
- **CHANGELOG.md** — This file
