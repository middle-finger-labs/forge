"""Types for the learning subsystem."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class LessonType(StrEnum):
    """Categories of lessons extracted from user feedback."""

    CODE_PATTERN = "code_pattern"
    ARCHITECTURE = "architecture"
    STYLE = "style"
    REQUIREMENT = "requirement"
    ANTIPATTERN = "antipattern"
    TESTING = "testing"
    REVIEW = "review"


@dataclass
class Lesson:
    """A single lesson extracted from user feedback."""

    id: str = ""
    org_id: str = ""
    agent_role: str = ""
    lesson_type: str = ""
    trigger_context: str = ""
    lesson: str = ""
    evidence: str = ""
    pipeline_id: str = ""
    confidence: float = 0.8
    times_applied: int = 0
    times_reinforced: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class LessonExtractionResult:
    """Result of the LLM-based lesson extraction from user feedback."""

    lesson_type: str = ""
    trigger_context: str = ""
    lesson_text: str = ""
    is_generalizable: bool = True
    confidence: float = 0.8
