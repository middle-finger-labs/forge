# Prompt Version Management

## Overview

Forge provides a multi-org prompt versioning system that allows organizations to customize, test, and manage the system prompts used by each agent stage. The system tracks version history, evaluation metrics, and enables A/B comparison between prompt versions.

## Architecture

```
  ┌──────────────┐
  │  Admin UI     │
  │ (Desktop App) │
  └───────┬───────┘
          │
  ┌───────▼───────┐
  │  Prompts API   │  (FastAPI routes)
  └───────┬───────┘
          │
  ┌───────▼───────┐
  │ PromptRegistry │  (version management)
  └───────┬───────┘
          │
  ┌───────▼───────┐
  │  PostgreSQL    │
  │ prompt_versions│
  │ prompt_evals   │
  └───────────────┘
```

## Pipeline Stages

Forge has 7 pipeline stages, each with a dedicated agent role:

| Stage | Role | Description |
|-------|------|-------------|
| 1 | Business Analyst | Requirements analysis |
| 2 | Architect | System design |
| 3 | Tech Lead | Technical planning |
| 4 | Senior Developer | Code architecture |
| 5 | Developer | Implementation |
| 6 | QA Engineer | Testing and review |
| 7 | CTO | Final approval |

## Version Management

### Creating Versions

```python
registry = PromptRegistry(dsn="postgresql://...")

version = await registry.create_version(
    org_id="org-1",
    stage=5,
    system_prompt="You are a developer agent focused on clean code...",
    change_summary="Added emphasis on error handling",
    created_by="user-123",
    activate=False,  # Create without activating
)
```

### Activating Versions

```python
# Deactivates current active version for this stage, activates the new one
success = await registry.activate_version("ver-123", org_id="org-1")
```

### Version History

```python
history = await registry.get_version_history(
    org_id="org-1",
    stage=5,
    limit=10,
)
# Returns newest-first list of PromptVersion objects
```

### Prompt Resolution

During pipeline execution, the system resolves which prompt to use:

```python
prompt, version_id = await registry.resolve_prompt(
    org_id="org-1",
    stage=5,
    default_prompt="You are a developer agent...",
)
# Returns custom prompt if org has an active version, otherwise the default
```

## Evaluation Tracking

### Recording Evaluations

After each agent stage completes, an evaluation is recorded:

```python
eval_id = await registry.record_evaluation(
    org_id="org-1",
    prompt_version_id="ver-123",
    pipeline_id="pipe-456",
    stage=5,
    agent_role="developer",
    verdict="approved",      # approved | rejected | error
    cost_usd=0.08,
    duration_seconds=25.0,
)
```

### Version Statistics

```python
stats = await registry.get_version_stats("ver-123", org_id="org-1")
# Returns:
#   total_runs: 20
#   approval_rate: 0.85  (approved_count / total_runs)
#   avg_cost_usd: 0.06
#   avg_duration_seconds: 18.5
#   avg_attempts: 1.2
#   error_count: 1
```

### Stats History

Daily aggregated metrics for trend analysis:

```python
history = await registry.get_version_stats_history("ver-123", org_id="org-1")
# Returns:
# [
#   {"date": "2025-01-01", "run_count": 5, "approval_rate": 0.8, "avg_cost_usd": 0.04},
#   {"date": "2025-01-02", "run_count": 10, "approval_rate": 0.9, "avg_cost_usd": 0.035},
# ]
```

### Version Comparison

Compare two versions side-by-side:

```python
comparison = await registry.compare_versions(
    "ver-old", "ver-new", org_id="org-1"
)
# Returns:
# {
#   "version_a": {"prompt": "...", "stats": {...}},
#   "version_b": {"prompt": "...", "stats": {...}},
# }
```

## Test Runs

Before activating a new prompt version, you can test it:

```
POST /api/prompts/test
{
    "stage": 5,
    "system_prompt": "You are a developer agent..."
}
```

Response:
```json
{
    "output": {...},
    "cost_usd": 0.05,
    "duration_seconds": 12.3,
    "error": null
}
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/prompts/versions` | POST | Create a new prompt version |
| `/api/prompts/versions/:id/activate` | POST | Activate a version |
| `/api/prompts/versions` | GET | List version history (query: org_id, stage) |
| `/api/prompts/versions/:id/stats` | GET | Get version statistics |
| `/api/prompts/versions/:id/stats/history` | GET | Get daily stats history |
| `/api/prompts/compare` | POST | Compare two versions |
| `/api/prompts/test` | POST | Run a test with custom prompt |
| `/api/pipelines/:id/summary` | GET | Pipeline execution summary |

## Data Model

### PromptVersion

```python
@dataclass
class PromptVersion:
    id: str
    org_id: str
    stage: int
    agent_role: str
    version: int
    system_prompt: str
    change_summary: str
    is_active: bool
    created_by: str
    created_at: datetime
```

### PromptVersionStats

```python
@dataclass
class PromptVersionStats:
    total_runs: int
    approval_rate: float
    avg_cost_usd: float
    avg_duration_seconds: float
    avg_attempts: float
    error_count: int
```

## Best Practices

1. **Always test before activating** - Use the `/api/prompts/test` endpoint to verify changes
2. **Write clear change summaries** - Document why the prompt was changed
3. **Monitor approval rates** - Use stats history to track prompt effectiveness over time
4. **Compare before switching** - Use version comparison to understand trade-offs
5. **Keep versions** - Don't delete old versions; the history is valuable for understanding what works
