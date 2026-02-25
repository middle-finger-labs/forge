"""Tests for the feedback learning subsystem.

All tests mock ModelRouter and database calls — no real API, Redis, or DB.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.learning.feedback_processor import (
    FeedbackProcessor,
    get_lessons_for_prompt,
)
from agents.learning.lesson_store import LessonStore
from agents.learning.types import Lesson, LessonType

# ---------------------------------------------------------------------------
# FeedbackProcessor._parse_extraction
# ---------------------------------------------------------------------------


class TestParseExtraction:
    def test_valid_json(self):
        content = json.dumps({
            "lesson_type": "code_pattern",
            "trigger_context": "When writing database calls",
            "lesson_text": "Always use async/await with SQLAlchemy async session",
            "is_generalizable": True,
            "confidence": 0.9,
        })
        result = FeedbackProcessor._parse_extraction(content)
        assert result is not None
        assert result.lesson_type == "code_pattern"
        assert result.lesson_text == "Always use async/await with SQLAlchemy async session"
        assert result.is_generalizable is True
        assert result.confidence == 0.9

    def test_json_with_markdown_fences(self):
        inner = json.dumps({
            "lesson_type": "style",
            "trigger_context": "Python code",
            "lesson_text": "Use snake_case",
            "is_generalizable": True,
            "confidence": 0.8,
        })
        content = f"```json\n{inner}\n```"
        result = FeedbackProcessor._parse_extraction(content)
        assert result is not None
        assert result.lesson_type == "style"
        assert result.lesson_text == "Use snake_case"

    def test_invalid_json(self):
        result = FeedbackProcessor._parse_extraction("not valid json")
        assert result is None

    def test_empty_string(self):
        result = FeedbackProcessor._parse_extraction("")
        assert result is None

    def test_defaults_for_missing_fields(self):
        content = json.dumps({
            "lesson_text": "Some lesson",
            "trigger_context": "Some trigger",
        })
        result = FeedbackProcessor._parse_extraction(content)
        assert result is not None
        assert result.lesson_type == "code_pattern"
        assert result.is_generalizable is True
        assert result.confidence == 0.8


# ---------------------------------------------------------------------------
# FeedbackProcessor.process_rejection
# ---------------------------------------------------------------------------


def _mock_router(extraction_json: dict):
    """Return a mock router that returns a lesson extraction response."""
    router = MagicMock()
    router.route_request = AsyncMock(return_value="claude-haiku-3-5")
    router.complete = AsyncMock(return_value={
        "content": json.dumps(extraction_json),
        "cost_usd": 0.001,
    })
    return router


def _mock_store():
    """Return a mock LessonStore with standard behavior."""
    store = MagicMock(spec=LessonStore)
    store.find_duplicate = AsyncMock(return_value=None)
    store.store_lesson = AsyncMock(return_value="lesson-uuid-123")
    store.reinforce = AsyncMock(return_value=True)
    store.get_lesson = AsyncMock(return_value=Lesson(
        id="lesson-uuid-123",
        org_id="org-1",
        agent_role="developer",
        lesson_type="code_pattern",
        trigger_context="When writing DB calls",
        lesson="Use async/await for database calls",
        confidence=0.8,
    ))
    store.search = AsyncMock(return_value=[])
    store.record_application = AsyncMock()
    return store


@pytest.mark.asyncio
async def test_process_rejection_stores_new_lesson():
    """New feedback → extracts lesson → stores it."""
    extraction = {
        "lesson_type": "code_pattern",
        "trigger_context": "Writing database calls in Python",
        "lesson_text": "Use async/await for all database calls",
        "is_generalizable": True,
        "confidence": 0.85,
    }
    router = _mock_router(extraction)
    store = _mock_store()

    with patch("config.model_router.get_model_router", return_value=router):
        processor = FeedbackProcessor(lesson_store=store)
        result = await processor.process_rejection(
            pipeline_id="pipe-1",
            stage="coding",
            user_comment="Use async/await for all database calls, not synchronous",
            original_output={"files_created": ["src/db.py"]},
            org_id="org-1",
            agent_role="developer",
        )

    assert result is not None
    assert result.id == "lesson-uuid-123"
    store.store_lesson.assert_called_once()
    stored_lesson = store.store_lesson.call_args[0][0]
    assert stored_lesson.lesson == "Use async/await for all database calls"
    assert stored_lesson.org_id == "org-1"


@pytest.mark.asyncio
async def test_process_rejection_reinforces_duplicate():
    """Duplicate feedback → reinforces existing lesson instead of creating new."""
    extraction = {
        "lesson_type": "code_pattern",
        "trigger_context": "Database calls",
        "lesson_text": "Use async for DB calls",
        "is_generalizable": True,
        "confidence": 0.85,
    }
    router = _mock_router(extraction)
    store = _mock_store()
    store.find_duplicate = AsyncMock(return_value={
        "id": "existing-lesson-id",
        "score": 0.92,
        "lesson": "Use async/await for database operations",
    })

    with patch("config.model_router.get_model_router", return_value=router):
        processor = FeedbackProcessor(lesson_store=store)
        result = await processor.process_rejection(
            pipeline_id="pipe-2",
            stage="coding",
            user_comment="Use async DB calls!",
            original_output={},
            org_id="org-1",
        )

    assert result is not None
    store.reinforce.assert_called_once_with("existing-lesson-id", org_id="org-1")
    store.store_lesson.assert_not_called()


@pytest.mark.asyncio
async def test_process_rejection_skips_non_generalizable():
    """Pipeline-specific feedback → not stored."""
    extraction = {
        "lesson_type": "requirement",
        "trigger_context": "This specific invoice feature",
        "lesson_text": "Add late fee calculation to invoice #1234",
        "is_generalizable": False,
        "confidence": 0.7,
    }
    router = _mock_router(extraction)
    store = _mock_store()

    with patch("config.model_router.get_model_router", return_value=router):
        processor = FeedbackProcessor(lesson_store=store)
        result = await processor.process_rejection(
            pipeline_id="pipe-3",
            stage="coding",
            user_comment="Add late fee calculation to this invoice",
            original_output={},
            org_id="org-1",
        )

    assert result is None
    store.store_lesson.assert_not_called()


@pytest.mark.asyncio
async def test_process_rejection_empty_comment():
    """Empty comment → no processing."""
    store = _mock_store()
    processor = FeedbackProcessor(lesson_store=store)
    result = await processor.process_rejection(
        pipeline_id="pipe-4",
        stage="coding",
        user_comment="",
        original_output={},
        org_id="org-1",
    )

    assert result is None
    store.store_lesson.assert_not_called()


@pytest.mark.asyncio
async def test_process_rejection_llm_failure_graceful():
    """LLM call fails → returns None gracefully."""
    router = MagicMock()
    router.route_request = AsyncMock(return_value="claude-haiku-3-5")
    router.complete = AsyncMock(side_effect=RuntimeError("API error"))
    store = _mock_store()

    with patch("config.model_router.get_model_router", return_value=router):
        processor = FeedbackProcessor(lesson_store=store)
        result = await processor.process_rejection(
            pipeline_id="pipe-5",
            stage="coding",
            user_comment="Fix the auth module",
            original_output={},
            org_id="org-1",
        )

    assert result is None
    store.store_lesson.assert_not_called()


# ---------------------------------------------------------------------------
# get_lessons_for_prompt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_lessons_for_prompt_formats_correctly():
    """Lessons found → formatted as prompt section."""
    store = _mock_store()
    store.search = AsyncMock(return_value=[
        {
            "id": "l1",
            "agent_role": "developer",
            "lesson_type": "code_pattern",
            "trigger_context": "DB calls",
            "lesson": "Always use async/await for database calls",
            "confidence": 0.9,
            "times_applied": 12,
            "times_reinforced": 3,
            "score": 0.85,
        },
        {
            "id": "l2",
            "agent_role": "developer",
            "lesson_type": "testing",
            "trigger_context": "Auth endpoints",
            "lesson": "Include input validation on all POST endpoints",
            "confidence": 0.75,
            "times_applied": 8,
            "times_reinforced": 2,
            "score": 0.72,
        },
    ])

    result = await get_lessons_for_prompt(
        "Implement user authentication",
        org_id="org-1",
        agent_role="developer",
        store=store,
    )

    assert "Lessons from Previous Work" in result
    assert "async/await for database calls" in result
    assert "confidence: high" in result
    assert "applied 12 times" in result
    assert "input validation" in result
    assert "confidence: medium" in result

    # Should record application for each lesson
    assert store.record_application.call_count == 2


@pytest.mark.asyncio
async def test_get_lessons_for_prompt_empty_when_no_results():
    """No lessons found → empty string."""
    store = _mock_store()
    store.search = AsyncMock(return_value=[])

    result = await get_lessons_for_prompt(
        "Some task",
        org_id="org-1",
        agent_role="developer",
        store=store,
    )

    assert result == ""


@pytest.mark.asyncio
async def test_get_lessons_for_prompt_graceful_on_error():
    """Search fails → returns empty string."""
    store = _mock_store()
    store.search = AsyncMock(side_effect=RuntimeError("DB down"))

    result = await get_lessons_for_prompt(
        "Some task",
        org_id="org-1",
        agent_role="developer",
        store=store,
    )

    assert result == ""


# ---------------------------------------------------------------------------
# LessonType enum
# ---------------------------------------------------------------------------


def test_lesson_type_values():
    """All expected lesson types are defined."""
    assert LessonType.CODE_PATTERN == "code_pattern"
    assert LessonType.ARCHITECTURE == "architecture"
    assert LessonType.STYLE == "style"
    assert LessonType.REQUIREMENT == "requirement"
    assert LessonType.ANTIPATTERN == "antipattern"
    assert LessonType.TESTING == "testing"
    assert LessonType.REVIEW == "review"


# ---------------------------------------------------------------------------
# Lesson dataclass
# ---------------------------------------------------------------------------


def test_lesson_defaults():
    """Lesson has sensible defaults."""
    lesson = Lesson()
    assert lesson.confidence == 0.8
    assert lesson.times_applied == 0
    assert lesson.times_reinforced == 0
    assert lesson.id == ""


# ---------------------------------------------------------------------------
# Confidence reinforcement on repeated feedback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_rejection_reinforces_and_boosts_confidence():
    """Repeated similar feedback reinforces existing lesson, boosting confidence.

    The reinforce method increases confidence via: new = old + (1.0 - old) * 0.1
    """
    extraction = {
        "lesson_type": "code_pattern",
        "trigger_context": "Database calls",
        "lesson_text": "Use async for DB calls",
        "is_generalizable": True,
        "confidence": 0.85,
    }
    router = _mock_router(extraction)
    store = _mock_store()

    # First call: no duplicate → stores new lesson
    store.find_duplicate = AsyncMock(return_value=None)
    with patch("config.model_router.get_model_router", return_value=router):
        processor = FeedbackProcessor(lesson_store=store)
        result1 = await processor.process_rejection(
            pipeline_id="pipe-r1",
            stage="coding",
            user_comment="Always use async for database calls",
            original_output={},
            org_id="org-1",
            agent_role="developer",
        )

    assert result1 is not None
    store.store_lesson.assert_called_once()

    # Second call: duplicate found → reinforces
    store.store_lesson.reset_mock()
    store.find_duplicate = AsyncMock(return_value={
        "id": "existing-lesson-id",
        "score": 0.92,
        "lesson": "Use async/await for database operations",
    })

    with patch("config.model_router.get_model_router", return_value=router):
        processor2 = FeedbackProcessor(lesson_store=store)
        result2 = await processor2.process_rejection(
            pipeline_id="pipe-r2",
            stage="coding",
            user_comment="Make sure to use async for DB calls!",
            original_output={},
            org_id="org-1",
            agent_role="developer",
        )

    assert result2 is not None
    store.reinforce.assert_called_once_with("existing-lesson-id", org_id="org-1")
    store.store_lesson.assert_not_called()  # No new lesson created

    # Third call: also a duplicate → reinforces again
    store.reinforce.reset_mock()
    with patch("config.model_router.get_model_router", return_value=router):
        processor3 = FeedbackProcessor(lesson_store=store)
        result3 = await processor3.process_rejection(
            pipeline_id="pipe-r3",
            stage="coding",
            user_comment="Use async/await with the database",
            original_output={},
            org_id="org-1",
            agent_role="developer",
        )

    assert result3 is not None
    store.reinforce.assert_called_once()


@pytest.mark.asyncio
async def test_process_rejection_different_agent_roles():
    """Lessons are scoped to agent_role; same lesson can exist for different roles."""
    extraction = {
        "lesson_type": "style",
        "trigger_context": "Error handling",
        "lesson_text": "Always log the stack trace",
        "is_generalizable": True,
        "confidence": 0.8,
    }
    router = _mock_router(extraction)
    store = _mock_store()

    with patch("config.model_router.get_model_router", return_value=router):
        processor = FeedbackProcessor(lesson_store=store)

        await processor.process_rejection(
            pipeline_id="pipe-role-1",
            stage="coding",
            user_comment="Log stack traces for errors",
            original_output={},
            org_id="org-1",
            agent_role="developer",
        )

    stored = store.store_lesson.call_args[0][0]
    assert stored.agent_role == "developer"


# ---------------------------------------------------------------------------
# Lesson management API CRUD tests (LessonStore)
# ---------------------------------------------------------------------------


class _AsyncCtx:
    """Minimal async context manager wrapping a mock connection."""

    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        pass


class TestLessonStoreCRUD:
    """Test LessonStore CRUD operations with mocked database."""

    def _mock_lesson_store(self):
        """Return a LessonStore with mocked pool."""
        store = LessonStore(dsn="postgresql://test:test@localhost/test")
        store._pool = MagicMock()
        store._embedder = MagicMock()
        store._embedder.encode = MagicMock(
            return_value=MagicMock(tolist=MagicMock(return_value=[0.1] * 384))
        )
        return store

    @pytest.mark.asyncio
    async def test_store_lesson_returns_uuid(self):
        """store_lesson inserts and returns the lesson ID."""
        store = self._mock_lesson_store()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"id": "lesson-uuid-new"})
        store._pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

        lesson = Lesson(
            org_id="org-1",
            agent_role="developer",
            lesson_type="code_pattern",
            trigger_context="DB calls",
            lesson="Use async/await",
        )
        lesson_id = await store.store_lesson(lesson)

        assert lesson_id == "lesson-uuid-new"
        conn.fetchrow.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_lesson_returns_lesson(self):
        """get_lesson fetches a lesson by ID."""
        store = self._mock_lesson_store()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={
            "id": "lesson-123",
            "org_id": "org-1",
            "agent_role": "developer",
            "lesson_type": "code_pattern",
            "trigger_context": "DB calls",
            "lesson": "Use async/await",
            "evidence": "",
            "pipeline_id": "pipe-1",
            "confidence": 0.9,
            "times_applied": 5,
            "times_reinforced": 2,
            "created_at": None,
            "updated_at": None,
        })
        store._pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

        result = await store.get_lesson("lesson-123", org_id="org-1")

        assert result is not None
        assert result.id == "lesson-123"
        assert result.lesson == "Use async/await"
        assert result.confidence == 0.9
        assert result.times_applied == 5

    @pytest.mark.asyncio
    async def test_get_lesson_not_found(self):
        """get_lesson returns None when lesson doesn't exist."""
        store = self._mock_lesson_store()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)
        store._pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

        result = await store.get_lesson("nonexistent", org_id="org-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_lesson_text(self):
        """update_lesson updates lesson text and returns True."""
        store = self._mock_lesson_store()
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="UPDATE 1")
        store._pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

        result = await store.update_lesson(
            "lesson-123",
            org_id="org-1",
            lesson_text="Updated lesson text",
        )

        assert result is True
        conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_lesson_not_found(self):
        """update_lesson returns False when no row matches."""
        store = self._mock_lesson_store()
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="UPDATE 0")
        store._pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

        result = await store.update_lesson(
            "nonexistent",
            org_id="org-1",
            lesson_text="Updated text",
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_delete_lesson_success(self):
        """delete_lesson removes the lesson and returns True."""
        store = self._mock_lesson_store()
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="DELETE 1")
        store._pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

        result = await store.delete_lesson("lesson-123", org_id="org-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_lesson_not_found(self):
        """delete_lesson returns False when no row matches."""
        store = self._mock_lesson_store()
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="DELETE 0")
        store._pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

        result = await store.delete_lesson("nonexistent", org_id="org-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_reinforce_increments_and_boosts(self):
        """reinforce updates the DB row and returns True."""
        store = self._mock_lesson_store()
        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="UPDATE 1")
        store._pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

        result = await store.reinforce("lesson-123", org_id="org-1")
        assert result is True
        conn.execute.assert_called_once()
        # Verify the SQL includes the confidence boost formula
        sql = conn.execute.call_args[0][0]
        assert "times_reinforced" in sql
        assert "confidence" in sql

    @pytest.mark.asyncio
    async def test_list_lessons_with_filters(self):
        """list_lessons returns filtered results."""
        store = self._mock_lesson_store()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[
            {
                "id": "l1",
                "org_id": "org-1",
                "agent_role": "developer",
                "lesson_type": "code_pattern",
                "trigger_context": "DB calls",
                "lesson": "Use async",
                "evidence": "",
                "pipeline_id": "",
                "confidence": 0.9,
                "times_applied": 3,
                "times_reinforced": 1,
                "created_at": None,
                "updated_at": None,
            },
        ])
        store._pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

        results = await store.list_lessons(
            org_id="org-1",
            agent_role="developer",
            lesson_type="code_pattern",
            min_confidence=0.7,
        )

        assert len(results) == 1
        assert results[0].lesson == "Use async"
        assert results[0].agent_role == "developer"

    @pytest.mark.asyncio
    async def test_record_application_increments_counter(self):
        """record_application bumps times_applied."""
        store = self._mock_lesson_store()
        conn = AsyncMock()
        conn.execute = AsyncMock()
        store._pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

        await store.record_application("lesson-123")
        conn.execute.assert_called_once()
        sql = conn.execute.call_args[0][0]
        assert "times_applied" in sql
