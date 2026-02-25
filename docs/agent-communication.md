# Agent Communication

## Overview

Forge agents communicate through the `AgentBus`, a structured message-passing system that enables agents to ask each other questions, broadcast status updates, and coordinate work within a pipeline. All communication is logged, cost-tracked, and subject to guardrails.

## Architecture

```
  ┌──────────┐    ask()     ┌──────────┐
  │ Developer├──────────────►│ Architect│
  │  Agent   │◄──────────────┤  Agent   │
  └──────────┘   response    └──────────┘
       │                          │
       │      ┌──────────┐        │
       └──────► AgentBus ◄────────┘
              │          │
              │ • Routing│
              │ • Limits │
              │ • Logging│
              │ • Cost   │
              └────┬─────┘
                   │
         ┌─────────▼─────────┐
         │  Pipeline Context  │
         │  (exchanges log)   │
         └───────────────────┘
```

## Core API

### AgentBus

```python
bus = AgentBus(
    pipeline_id="pipe-123",
    max_questions_per_agent=3,  # default: 3
    question_timeout=120.0,     # default: 120 seconds
)
```

### Asking Questions

```python
response = await bus.ask(
    from_role=AgentRole.DEVELOPER,
    to_role=AgentRole.ARCHITECT,
    question="Should I use the repository pattern for data access?"
)

if not response.timed_out and not response.hit_limit:
    print(response.response)  # "Yes, use the repository pattern..."
    print(response.cost_usd)  # 0.02
```

### Broadcasting

```python
await bus.broadcast(
    from_role=AgentRole.CTO,
    message="Pipeline checkpoint: all stages healthy"
)
```

### Accessing Exchange History

```python
exchanges = bus.exchanges  # Returns a copy of all recorded exchanges
total_cost = bus.total_cost_usd
```

## Guardrails

### Question Limits

Each agent has a maximum number of questions it can ask per pipeline run (default: 3). This prevents infinite loops and controls costs.

When the limit is hit:
- The `ask()` call returns immediately with `hit_limit=True`
- No LLM call is made
- The response text explains the limit was reached
- The exchange is still recorded in the log

### Circular Dependency Detection

The bus tracks active ask operations. If Agent A is waiting for Agent B, and Agent B tries to ask Agent A, the circular dependency is detected:

- The second `ask()` returns immediately with `circular=True`
- The response instructs the agent to resolve independently
- No deadlock occurs

### Timeout

Each question has a timeout (default: 120 seconds):
- If the LLM doesn't respond in time, `timed_out=True` is returned
- A graceful fallback message is provided
- Cost is recorded as $0.00

## Response Types

```python
@dataclass
class AgentResponse:
    from_role: AgentRole
    to_role: AgentRole
    question: str
    response: str
    cost_usd: float = 0.0
    timed_out: bool = False
    hit_limit: bool = False
    circular: bool = False
```

## Briefing Helpers

### Architect Briefing

```python
from agents.communication.briefing import get_architect_briefing

briefing = await get_architect_briefing(bus, ticket, tech_spec_context)
# Returns XML-tagged briefing: <architect_briefing>...</architect_briefing>
```

### QA Clarification

```python
from agents.communication.briefing import get_qa_clarification

clarification = await get_qa_clarification(bus, ticket, qa_review, code_artifact)
# Returns XML-tagged response: <engineer_clarification>...</engineer_clarification>
```

## Pipeline Visibility

All inter-agent exchanges are recorded and visible in the pipeline conversation:

- Each exchange includes: `from_role`, `to_role`, `question`, `response`, `timestamp`, `cost_usd`
- Failed exchanges (timeout, limit, circular) are also recorded with their status
- The desktop app renders these as special message types in the pipeline chat view
- Total communication cost is tracked via `bus.total_cost_usd`

## Cost Tracking

Every LLM call made through the bus is cost-tracked:
- Individual response costs are in `response.cost_usd`
- Aggregate cost is in `bus.total_cost_usd`
- Broadcasts (no LLM call) have zero cost
- Timed-out requests have zero cost
- Limit-hit requests have zero cost (no LLM call made)
