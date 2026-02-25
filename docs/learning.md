# Feedback Learning System

## Overview

Forge learns from user feedback to improve agent outputs over time. When a user rejects an agent's output and provides correction feedback, the system extracts generalizable lessons and injects them into future prompts, creating a continuous improvement loop.

## Architecture

```
  ┌──────────────┐
  │ User Rejects  │
  │ Agent Output   │
  └───────┬───────┘
          │ feedback comment
  ┌───────▼───────┐
  │  Feedback      │
  │  Processor     │  (LLM-based extraction)
  └───────┬───────┘
          │ Lesson
  ┌───────▼───────┐
  │ Deduplication  │  (semantic similarity check, threshold: 0.85)
  └───┬───────┬───┘
      │       │
  ┌───▼──┐ ┌─▼──────┐
  │ New  │ │Reinforce│
  │Lesson│ │Existing │
  └──┬───┘ └────┬───┘
     │          │
  ┌──▼──────────▼──┐
  │  LessonStore    │  (pgvector storage)
  └────────┬───────┘
           │ on next pipeline run
  ┌────────▼───────┐
  │ get_lessons_   │
  │ for_prompt()   │  (semantic search + injection)
  └────────┬───────┘
           │
  ┌────────▼───────┐
  │  Agent Prompt   │  (lesson section appended)
  └────────────────┘
```

## Lesson Extraction

### Process

1. User rejects output with a comment (e.g., "Always hash passwords with bcrypt")
2. `FeedbackProcessor.process_rejection()` sends the comment + original output to an LLM
3. LLM extracts structured lesson data:
   - `lesson_type`: code_pattern, architecture, style, requirement, antipattern, testing, review
   - `trigger_context`: When this lesson applies
   - `lesson_text`: The actual lesson
   - `is_generalizable`: Whether this applies beyond the current pipeline
   - `confidence`: Initial confidence score (0.0 - 1.0)

4. Non-generalizable lessons (specific to one pipeline) are discarded
5. Empty comments skip processing entirely

### Deduplication

Before storing a new lesson, the system checks for semantic duplicates:

```python
duplicate = await store.find_duplicate(
    lesson_text,
    org_id=org_id,
    agent_role=agent_role,
    threshold=0.85,  # cosine similarity threshold
)
```

- If a duplicate is found (similarity >= 0.85): **reinforce** the existing lesson
- If no duplicate: **store** as a new lesson

### Reinforcement

When a lesson is reinforced (user gives similar feedback again):
- `times_reinforced` is incremented
- Confidence is boosted asymptotically toward 1.0:
  ```
  new_confidence = old_confidence + (1.0 - old_confidence) * 0.1
  ```
- Example: 0.8 → 0.82 → 0.838 → 0.854 → ...

## Lesson Types

| Type | Description | Example |
|------|-------------|---------|
| `code_pattern` | Coding patterns and practices | "Always use async/await for DB calls" |
| `architecture` | Architectural decisions | "Use hexagonal architecture for services" |
| `style` | Code style preferences | "Use snake_case for Python variables" |
| `requirement` | Business requirements | "All API responses must include request_id" |
| `antipattern` | Things to avoid | "Never use string concatenation for SQL" |
| `testing` | Testing practices | "Mock external services in unit tests" |
| `review` | Code review standards | "All public methods need docstrings" |

## Lesson Storage (LessonStore)

### CRUD Operations

```python
store = LessonStore()

# Create
lesson_id = await store.store_lesson(lesson, embedding=None)

# Read
lesson = await store.get_lesson(lesson_id, org_id="org-1")
lessons = await store.list_lessons(
    org_id="org-1",
    agent_role="developer",
    lesson_type="code_pattern",
    min_confidence=0.7,
    limit=50,
)

# Update
await store.update_lesson(
    lesson_id,
    org_id="org-1",
    lesson_text="Updated lesson text",
    confidence=0.95,
)

# Delete
await store.delete_lesson(lesson_id, org_id="org-1")

# Reinforce
await store.reinforce(lesson_id, org_id="org-1")

# Track application
await store.record_application(lesson_id)
```

### Semantic Search

```python
results = await store.search(
    "How should I handle database connections?",
    org_id="org-1",
    agent_role="developer",
    min_confidence=0.6,
    limit=10,
)
# Returns: [{"id", "lesson", "score", "confidence", ...}]
```

## Prompt Injection

When an agent runs, `get_lessons_for_prompt()` searches for relevant lessons and formats them as a prompt section:

```python
section = await get_lessons_for_prompt(
    "Implement user authentication",
    org_id="org-1",
    agent_role="developer",
    store=store,
)
```

Output format:
```
## Lessons from Previous Work

1. [code_pattern] (confidence: high, applied 12 times)
   When: Database calls
   Lesson: Always use async/await for database calls

2. [testing] (confidence: medium, applied 8 times)
   When: Auth endpoints
   Lesson: Include input validation on all POST endpoints
```

Confidence labels:
- **high**: >= 0.8
- **medium**: 0.6 - 0.8
- **low**: < 0.6

## Error Handling

The learning system is designed to be fault-tolerant:
- LLM extraction failures return `None` (no lesson stored)
- Empty feedback comments are skipped
- Search failures return empty results (no crash)
- Missing embedder falls back to recency-based retrieval

## Data Model

```sql
CREATE TABLE lessons (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id            TEXT NOT NULL,
    agent_role        TEXT NOT NULL,
    lesson_type       TEXT NOT NULL,
    trigger_context   TEXT NOT NULL,
    lesson            TEXT NOT NULL,
    evidence          TEXT,
    pipeline_id       TEXT,
    confidence        FLOAT NOT NULL DEFAULT 0.8,
    times_applied     INT NOT NULL DEFAULT 0,
    times_reinforced  INT NOT NULL DEFAULT 0,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    embedding         vector(384)
);
```
