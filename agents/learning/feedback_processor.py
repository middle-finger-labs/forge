"""Processes user feedback on agent outputs and extracts reusable lessons.

When a user rejects a pipeline stage or requests changes, this module:
1. Extracts the specific issue from user feedback (via a small LLM call)
2. Determines if the lesson is generalizable or pipeline-specific
3. Checks for existing duplicate lessons (reinforcement vs. new)
4. Stores the lesson with a semantic embedding for future retrieval
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from agents.learning.lesson_store import LessonStore
from agents.learning.types import Lesson, LessonExtractionResult

log = structlog.get_logger().bind(component="feedback_processor")

_EXTRACTION_SYSTEM_PROMPT = """\
You extract reusable engineering lessons from user feedback on AI-generated code.

Given a user's rejection comment and the original output, produce a JSON object:

{
  "lesson_type": "code_pattern|architecture|style|requirement|antipattern|testing|review",
  "trigger_context": "Brief description of WHEN this lesson applies (the situation)",
  "lesson_text": "The actual rule/guideline to follow in future",
  "is_generalizable": true,
  "confidence": 0.8
}

Rules:
- lesson_type meanings:
  - code_pattern: coding patterns to follow ("use dependency injection")
  - architecture: tech stack / structural decisions ("use PostgreSQL not MongoDB")
  - style: naming, formatting ("use snake_case in Python")
  - requirement: domain-specific business rules ("always calculate late fees")
  - antipattern: things to avoid ("don't use global state in FastAPI")
  - testing: test coverage rules ("always test auth endpoints")
  - review: review preferences ("CTO wants error handling on external calls")
- is_generalizable: true if the lesson applies across projects, false if specific \
to this one pipeline/ticket
- confidence: 0.6 for vague feedback, 0.8 for clear feedback, 0.95 for very explicit
- trigger_context: describe the SITUATION, not the lesson itself
- lesson_text: describe the ACTION to take, not the situation

Return ONLY the JSON object.\
"""


class FeedbackProcessor:
    """Processes user feedback on agent outputs and extracts reusable lessons."""

    def __init__(
        self,
        lesson_store: LessonStore | None = None,
        duplicate_threshold: float = 0.85,
    ) -> None:
        self._store = lesson_store or LessonStore()
        self._duplicate_threshold = duplicate_threshold

    async def process_rejection(
        self,
        pipeline_id: str,
        stage: str,
        user_comment: str,
        original_output: dict[str, Any],
        *,
        org_id: str,
        agent_role: str = "developer",
        revised_output: dict[str, Any] | None = None,
    ) -> Lesson | None:
        """Extract a lesson from a user's rejection feedback.

        Steps:
        1. Call a small LLM to extract the lesson from the feedback
        2. Check for existing duplicate lessons (reinforce if found)
        3. Store as new lesson if novel

        Returns the stored/reinforced ``Lesson``, or ``None`` on failure.
        """
        if not user_comment or not user_comment.strip():
            log.debug("empty rejection comment, skipping lesson extraction")
            return None

        # 1. Extract lesson via LLM
        extraction = await self._extract_lesson(
            user_comment, original_output, revised_output, stage,
        )
        if extraction is None:
            return None

        # 2. Skip pipeline-specific lessons
        if not extraction.is_generalizable:
            log.info(
                "lesson is pipeline-specific, skipping storage",
                trigger=extraction.trigger_context,
            )
            return None

        # 3. Check for duplicates → reinforce existing lesson
        duplicate = await self._store.find_duplicate(
            extraction.lesson_text,
            org_id=org_id,
            agent_role=agent_role,
            threshold=self._duplicate_threshold,
        )
        if duplicate:
            await self._store.reinforce(duplicate["id"], org_id=org_id)
            log.info(
                "existing lesson reinforced",
                lesson_id=duplicate["id"],
                similarity=duplicate["score"],
            )
            reinforced = await self._store.get_lesson(
                duplicate["id"], org_id=org_id,
            )
            return reinforced

        # 4. Store new lesson
        lesson = Lesson(
            org_id=org_id,
            agent_role=agent_role,
            lesson_type=extraction.lesson_type,
            trigger_context=extraction.trigger_context,
            lesson=extraction.lesson_text,
            evidence=user_comment,
            pipeline_id=pipeline_id,
            confidence=extraction.confidence,
        )

        lesson_id = await self._store.store_lesson(lesson)
        lesson.id = lesson_id

        log.info(
            "new lesson stored",
            lesson_id=lesson_id,
            lesson_type=extraction.lesson_type,
            confidence=extraction.confidence,
        )
        return lesson

    async def _extract_lesson(
        self,
        user_comment: str,
        original_output: dict[str, Any],
        revised_output: dict[str, Any] | None,
        stage: str,
    ) -> LessonExtractionResult | None:
        """Use a small LLM call to extract a structured lesson from feedback."""
        # Build user message with context
        parts = [f"Stage: {stage}", f"User feedback: {user_comment}"]

        # Include a summary of original output (truncated)
        output_summary = json.dumps(original_output, default=str)[:2000]
        parts.append(f"Original output (summary): {output_summary}")

        if revised_output:
            revision_summary = json.dumps(revised_output, default=str)[:1000]
            parts.append(f"Revised output (summary): {revision_summary}")

        messages = [
            {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": "\n\n".join(parts)},
        ]

        try:
            from config.model_router import get_model_router

            router = get_model_router()
            # Use a small/fast model for extraction
            model = await router.route_request("developer", task_complexity="small")

            result = await router.complete(
                model, messages, max_tokens=500, temperature=0.2,
            )

            content = result.get("content", "")
            return self._parse_extraction(content)

        except Exception as exc:
            log.warning("lesson extraction LLM call failed", error=str(exc))
            return None

    @staticmethod
    def _parse_extraction(content: str) -> LessonExtractionResult | None:
        """Parse the LLM's JSON response into a LessonExtractionResult."""
        try:
            # Strip markdown fences if present
            text = content.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:])
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            data = json.loads(text)
            return LessonExtractionResult(
                lesson_type=data.get("lesson_type", "code_pattern"),
                trigger_context=data.get("trigger_context", ""),
                lesson_text=data.get("lesson_text", ""),
                is_generalizable=data.get("is_generalizable", True),
                confidence=float(data.get("confidence", 0.8)),
            )
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            log.warning("failed to parse lesson extraction", error=str(exc))
            return None


# ---------------------------------------------------------------------------
# Convenience function for prompt injection
# ---------------------------------------------------------------------------


async def get_lessons_for_prompt(
    task_description: str,
    *,
    org_id: str,
    agent_role: str,
    min_confidence: float = 0.6,
    limit: int = 10,
    store: LessonStore | None = None,
) -> str:
    """Retrieve relevant lessons and format as a prompt section.

    Returns a formatted string to inject into an agent's context, or ``""``.
    """
    lesson_store = store or LessonStore()
    try:
        results = await lesson_store.search(
            query=task_description,
            org_id=org_id,
            agent_role=agent_role,
            min_confidence=min_confidence,
            limit=limit,
        )
    except Exception as exc:
        log.debug("lesson search failed", error=str(exc))
        return ""

    if not results:
        return ""

    # Record application for each lesson (best-effort, non-blocking)
    for r in results:
        try:
            await lesson_store.record_application(r["id"])
        except Exception:
            pass

    # Format as prompt section
    lines = [
        "## Lessons from Previous Work",
        "Based on past feedback, keep these guidelines in mind:",
    ]
    for i, r in enumerate(results, 1):
        conf_label = (
            "high" if r["confidence"] >= 0.85
            else "medium" if r["confidence"] >= 0.7
            else "low"
        )
        applied = r["times_applied"]
        lines.append(
            f"{i}. {r['lesson']} "
            f"(confidence: {conf_label}, applied {applied} times)"
        )

    return "\n".join(lines)
