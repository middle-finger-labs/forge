"""Lessons management API — CRUD + reinforcement for org-scoped lessons.

Endpoints:
    GET    /api/lessons              — list lessons (filterable by role, type)
    GET    /api/lessons/{id}         — get a single lesson
    PUT    /api/lessons/{id}         — update a lesson
    DELETE /api/lessons/{id}         — delete a lesson
    POST   /api/lessons/{id}/reinforce — confirm a lesson is correct
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth.middleware import get_current_user
from auth.types import ForgeUser

log = structlog.get_logger().bind(component="api.lessons")

lessons_router = APIRouter(prefix="/api", tags=["lessons"])

# ---------------------------------------------------------------------------
# Shared store instance (lazy)
# ---------------------------------------------------------------------------

_store = None


def _get_store():
    global _store  # noqa: PLW0603
    if _store is None:
        from agents.learning.lesson_store import LessonStore

        _store = LessonStore()
    return _store


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class UpdateLessonRequest(BaseModel):
    lesson: str | None = None
    trigger_context: str | None = None
    lesson_type: str | None = None
    confidence: float | None = None


class LessonResponse(BaseModel):
    id: str
    org_id: str
    agent_role: str
    lesson_type: str
    trigger_context: str
    lesson: str
    evidence: str | None = None
    pipeline_id: str | None = None
    confidence: float
    times_applied: int
    times_reinforced: int
    created_at: str | None = None
    updated_at: str | None = None


def _lesson_to_response(lesson) -> dict[str, Any]:
    return {
        "id": lesson.id,
        "org_id": lesson.org_id,
        "agent_role": lesson.agent_role,
        "lesson_type": lesson.lesson_type,
        "trigger_context": lesson.trigger_context,
        "lesson": lesson.lesson,
        "evidence": lesson.evidence or None,
        "pipeline_id": lesson.pipeline_id or None,
        "confidence": lesson.confidence,
        "times_applied": lesson.times_applied,
        "times_reinforced": lesson.times_reinforced,
        "created_at": (
            lesson.created_at.isoformat() if lesson.created_at else None
        ),
        "updated_at": (
            lesson.updated_at.isoformat() if lesson.updated_at else None
        ),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@lessons_router.get("/lessons")
async def list_lessons(
    agent_role: str | None = Query(None),
    lesson_type: str | None = Query(None),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: ForgeUser = Depends(get_current_user),
):
    """List lessons for the current org, filterable by agent role and type."""
    store = _get_store()
    lessons = await store.list_lessons(
        org_id=user.org_id,
        agent_role=agent_role,
        lesson_type=lesson_type,
        min_confidence=min_confidence,
        limit=limit,
        offset=offset,
    )
    return [_lesson_to_response(ls) for ls in lessons]


@lessons_router.get("/lessons/{lesson_id}")
async def get_lesson(
    lesson_id: str,
    user: ForgeUser = Depends(get_current_user),
):
    """Get a single lesson by ID."""
    store = _get_store()
    lesson = await store.get_lesson(lesson_id, org_id=user.org_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="Lesson not found")
    return _lesson_to_response(lesson)


@lessons_router.put("/lessons/{lesson_id}")
async def update_lesson(
    lesson_id: str,
    req: UpdateLessonRequest,
    user: ForgeUser = Depends(get_current_user),
):
    """Update a lesson's text, trigger context, type, or confidence."""
    store = _get_store()

    updated = await store.update_lesson(
        lesson_id,
        org_id=user.org_id,
        lesson_text=req.lesson,
        trigger_context=req.trigger_context,
        lesson_type=req.lesson_type,
        confidence=req.confidence,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Lesson not found")

    lesson = await store.get_lesson(lesson_id, org_id=user.org_id)
    return _lesson_to_response(lesson)


@lessons_router.delete("/lessons/{lesson_id}")
async def delete_lesson(
    lesson_id: str,
    user: ForgeUser = Depends(get_current_user),
):
    """Delete a lesson."""
    store = _get_store()
    deleted = await store.delete_lesson(lesson_id, org_id=user.org_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Lesson not found")
    return {"deleted": True, "id": lesson_id}


@lessons_router.post("/lessons/{lesson_id}/reinforce")
async def reinforce_lesson(
    lesson_id: str,
    user: ForgeUser = Depends(get_current_user),
):
    """Explicitly confirm a lesson is correct — boosts confidence."""
    store = _get_store()
    reinforced = await store.reinforce(lesson_id, org_id=user.org_id)
    if not reinforced:
        raise HTTPException(status_code=404, detail="Lesson not found")

    lesson = await store.get_lesson(lesson_id, org_id=user.org_id)
    return _lesson_to_response(lesson)
