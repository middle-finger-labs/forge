"""Tests for the coding agent's API fallback mode.

Mocks the Anthropic API so no real LLM calls are made.  Uses real git
repos (via tmp_path) to verify file writes and commits.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.worktree_manager import WorktreeManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TECH_SPEC = {
    "file_structure": {
        "src/index.ts": "entry point",
        "src/routes/": "route handlers",
    },
    "coding_standards": [
        "Use strict TypeScript",
        "All functions must have return types",
    ],
}

TICKET = {
    "ticket_key": "FORGE-1",
    "title": "Create hello route",
    "description": "Implement GET /hello returning JSON.",
    "acceptance_criteria": ["GET /hello returns 200"],
    "files_owned": ["src/routes/hello.ts"],
}

# The JSON payload the mocked LLM will return
_LLM_RESPONSE_FILES = {
    "src/routes/hello.ts": (
        "import { Router } from 'express';\n"
        "\n"
        "const router = Router();\n"
        "\n"
        "router.get('/hello', (_req, res) => {\n"
        "  res.json({ message: 'Hello, World!' });\n"
        "});\n"
        "\n"
        "export default router;\n"
    ),
}

_LLM_RESPONSE_JSON = json.dumps(
    {
        "files": _LLM_RESPONSE_FILES,
        "commit_message": "feat(FORGE-1): create hello route",
        "test_commands": [],
        "notes": "Simple Express route implementation",
    }
)


@dataclass
class _FakeUsage:
    input_tokens: int = 500
    output_tokens: int = 200


@dataclass
class _FakeTextBlock:
    type: str = "text"
    text: str = ""


@dataclass
class _FakeResponse:
    content: list = field(default_factory=list)
    usage: _FakeUsage = field(default_factory=_FakeUsage)


def _make_mock_client(response_text: str = _LLM_RESPONSE_JSON):
    """Return a mock AsyncAnthropic whose messages.create returns the given text."""
    response = _FakeResponse(
        content=[_FakeTextBlock(text=response_text)],
        usage=_FakeUsage(input_tokens=500, output_tokens=200),
    )
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(return_value=response)
    return client


@pytest.fixture
async def worktree(tmp_path):
    """Provide a worktree path inside a fresh git repo."""
    repo_path = str(tmp_path / "project")
    wt_dir = str(tmp_path / "worktrees")
    mgr = WorktreeManager(repo_path, worktrees_dir=wt_dir)
    await mgr.setup_repo(TECH_SPEC)
    wt_path = await mgr.create_worktree("FORGE-1", "forge/forge-1")
    return wt_path


async def _git(cwd: str, *args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    return out.decode().strip()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_api_fallback_writes_file(worktree: str):
    """The API fallback should write the file returned by the LLM."""
    from agents.coding_agent import _run_api_fallback

    mock_client = _make_mock_client()

    with patch("agents.coding_agent.get_anthropic_client", return_value=mock_client):
        artifact, cost = await _run_api_fallback(
            TICKET,
            TECH_SPEC,
            worktree,
            "forge/forge-1",
            timeout=60,
        )

    assert artifact is not None

    # File was written
    hello_path = os.path.join(worktree, "src", "routes", "hello.ts")
    assert os.path.exists(hello_path)
    with open(hello_path) as f:
        content = f.read()
    assert "Hello, World!" in content


async def test_api_fallback_creates_git_commit(worktree: str):
    """The API fallback should create a git commit in the worktree."""
    from agents.coding_agent import _run_api_fallback

    mock_client = _make_mock_client()

    with patch("agents.coding_agent.get_anthropic_client", return_value=mock_client):
        await _run_api_fallback(
            TICKET,
            TECH_SPEC,
            worktree,
            "forge/forge-1",
            timeout=60,
        )

    # At least 2 commits: the initial scaffold + the new one
    count = await _git(worktree, "rev-list", "--count", "HEAD")
    assert int(count) >= 2

    # Latest commit message contains the ticket key
    log_msg = await _git(worktree, "log", "-1", "--format=%s")
    assert "FORGE-1" in log_msg


async def test_api_fallback_artifact_structure(worktree: str):
    """The returned artifact should have the correct CodeArtifact fields."""
    from agents.coding_agent import _run_api_fallback

    mock_client = _make_mock_client()

    with patch("agents.coding_agent.get_anthropic_client", return_value=mock_client):
        artifact, cost = await _run_api_fallback(
            TICKET,
            TECH_SPEC,
            worktree,
            "forge/forge-1",
            timeout=60,
        )

    assert artifact is not None
    assert artifact["ticket_key"] == "FORGE-1"
    assert artifact["git_branch"] == "forge/forge-1"
    assert isinstance(artifact["files_created"], list)
    assert "src/routes/hello.ts" in artifact["files_created"]
    assert isinstance(artifact["files_modified"], list)
    assert isinstance(artifact["notes"], str)
    assert cost > 0


async def test_api_fallback_timeout(worktree: str):
    """A timeout from the API should return (None, 0.0)."""
    from agents.coding_agent import _run_api_fallback

    mock_client = MagicMock()
    mock_client.messages = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=TimeoutError("timed out"))

    with patch("agents.coding_agent.get_anthropic_client", return_value=mock_client):
        artifact, cost = await _run_api_fallback(
            TICKET,
            TECH_SPEC,
            worktree,
            "forge/forge-1",
            timeout=1,
        )

    assert artifact is None
    assert cost == 0.0


async def test_api_fallback_invalid_json(worktree: str):
    """If the LLM returns invalid JSON, the agent should return (None, cost)."""
    from agents.coding_agent import _run_api_fallback

    mock_client = _make_mock_client(response_text="this is not json {{{")

    with patch("agents.coding_agent.get_anthropic_client", return_value=mock_client):
        artifact, cost = await _run_api_fallback(
            TICKET,
            TECH_SPEC,
            worktree,
            "forge/forge-1",
            timeout=60,
        )

    assert artifact is None
    # Cost should still be tracked (tokens were consumed)
    assert cost > 0


async def test_run_coding_agent_task_nonexistent_path():
    """Passing a nonexistent worktree path should return (None, 0.0)."""
    from agents.coding_agent import run_coding_agent_task

    artifact, cost = await run_coding_agent_task(
        ticket=TICKET,
        tech_spec_context=TECH_SPEC,
        worktree_path="/tmp/does-not-exist-forge-test",
        branch_name="forge/nope",
    )

    assert artifact is None
    assert cost == 0.0
