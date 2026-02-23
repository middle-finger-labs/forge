"""Integration tests for parallel execution, conflict detection, and dependency analysis.

Tests use real git operations in temporary directories.  The coding agent
itself is mocked — we're testing coordination, not code generation.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from agents.conflict_resolver import auto_resolve_trivial
from agents.dependency_analyzer import (
    detect_file_ownership_conflicts,
    optimize_execution_order,
    validate_execution_order,
)
from agents.swarm_coordinator import SwarmCoordinator
from agents.worktree_manager import WorktreeManager
from workflows.types import CodingTaskResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def temp_repo(tmp_path):
    """Create a temp dir structure for a real git repo + worktrees dir."""
    repo_path = str(tmp_path / "project")
    wt_dir = str(tmp_path / "worktrees")
    return repo_path, wt_dir


@pytest.fixture()
async def git_repo(temp_repo):
    """Initialise a real git repo with a basic scaffold and return the
    WorktreeManager ready for use.
    """
    repo_path, wt_dir = temp_repo
    wm = WorktreeManager(repo_path, worktrees_dir=wt_dir)

    tech_spec = {
        "file_structure": {
            "src/main.ts": {"description": "entry point"},
            "src/utils.ts": {"description": "helpers"},
            "src/index.ts": {"description": "barrel"},
        },
    }
    await wm.setup_repo(tech_spec)

    # Configure git user for commits in this repo
    await wm._run_git("config", "user.email", "test@forge.dev")
    await wm._run_git("config", "user.name", "Forge Tests")

    yield wm

    # Cleanup
    await wm.cleanup_all()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _write_commit(
    wm: WorktreeManager,
    worktree_path: str,
    file_path: str,
    content: str,
    message: str,
) -> None:
    """Write a file in a worktree, stage, and commit."""
    full = os.path.join(worktree_path, file_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(content)
    await wm._run_git("-C", worktree_path, "add", "-A", cwd=worktree_path)
    await wm._run_git(
        "-C",
        worktree_path,
        "commit",
        "-m",
        message,
        cwd=worktree_path,
    )


def _mock_working_memory():
    """Return a mock WorkingMemory that stubs out Redis calls."""
    wm = AsyncMock()
    wm.set_ticket_lock = AsyncMock(return_value=True)
    wm.release_ticket_lock = AsyncMock()
    return wm


# ---------------------------------------------------------------------------
# Test 1 — SwarmCoordinator.execute_group with 3 non-conflicting tickets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_group_three_non_conflicting(git_repo):
    """All 3 tickets should complete successfully when there are no conflicts."""
    wm = git_repo
    wmem = _mock_working_memory()

    tickets = [
        {
            "ticket_key": "FORGE-1",
            "branch_name": "forge/FORGE-1",
            "title": "Create auth module",
            "files_owned": ["src/auth.ts"],
        },
        {
            "ticket_key": "FORGE-2",
            "branch_name": "forge/FORGE-2",
            "title": "Create API module",
            "files_owned": ["src/api.ts"],
        },
        {
            "ticket_key": "FORGE-3",
            "branch_name": "forge/FORGE-3",
            "title": "Create DB module",
            "files_owned": ["src/db.ts"],
        },
    ]

    # Mock the coding agent to create unique files in each worktree
    async def fake_coding_agent(*, ticket, tech_spec_context, worktree_path, branch_name):
        tk = ticket["ticket_key"]
        filename = ticket["files_owned"][0]
        full = os.path.join(worktree_path, filename)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(f"// {tk} implementation\nexport function {tk.replace('-', '_')}() {{}}\n")
        await wm._run_git("-C", worktree_path, "add", "-A", cwd=worktree_path)
        await wm._run_git(
            "-C",
            worktree_path,
            "commit",
            "-m",
            f"Implement {tk}",
            cwd=worktree_path,
        )
        return (
            {
                "ticket_key": tk,
                "git_branch": branch_name,
                "files_created": [filename],
                "files_modified": [],
            },
            0.01,
        )

    coord = SwarmCoordinator(
        pipeline_id="test-001",
        max_concurrent=3,
        worktree_manager=wm,
        working_memory=wmem,
    )

    with patch(
        "agents.swarm_coordinator.run_coding_agent_task",
        side_effect=fake_coding_agent,
    ):
        results = await coord.execute_group(tickets, tech_spec_context={})

    # All 3 should succeed
    assert len(results) == 3
    for r in results:
        assert r.success, f"Ticket {r.ticket_id} failed: {r.error}"
        assert r.code_artifact is not None
        assert r.code_artifact["git_branch"].startswith("forge/")

    # Each ticket ID is represented
    result_ids = {r.ticket_id for r in results}
    assert result_ids == {"FORGE-1", "FORGE-2", "FORGE-3"}


# ---------------------------------------------------------------------------
# Test 2 — pre_merge_conflict_check detects same-file conflicts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conflict_detection_same_file(git_repo):
    """Two branches modifying the same file should be detected as a conflict."""
    wm = git_repo

    # Write some initial content so main has the file
    init_utils = os.path.join(wm.base_project_path, "src/utils.ts")
    with open(init_utils, "w") as f:
        f.write("// Shared utils\nexport function shared() { return true }\n")
    await wm._run_git("add", "-A")
    await wm._run_git("commit", "-m", "Add initial utils content")

    # Worktree A: rewrite utils.ts with function A
    wt_a = await wm.create_worktree("TICKET-A", "forge/TICKET-A")
    await _write_commit(
        wm,
        wt_a,
        "src/utils.ts",
        "// Shared utils (rewritten by A)\n"
        "export function shared() { return 'A' }\n"
        "export function helperA() { return 1 }\n",
        "Add helperA to utils",
    )

    # Worktree B: rewrite utils.ts with function B (conflicts with A)
    wt_b = await wm.create_worktree("TICKET-B", "forge/TICKET-B")
    await _write_commit(
        wm,
        wt_b,
        "src/utils.ts",
        "// Shared utils (rewritten by B)\n"
        "export function shared() { return 'B' }\n"
        "export function helperB() { return 2 }\n",
        "Add helperB to utils",
    )

    # Build CodingTaskResults to feed into pre_merge_conflict_check
    results = [
        CodingTaskResult(
            ticket_id="TICKET-A",
            success=True,
            code_artifact={"git_branch": "forge/TICKET-A", "files_created": ["src/utils.ts"]},
        ),
        CodingTaskResult(
            ticket_id="TICKET-B",
            success=True,
            code_artifact={"git_branch": "forge/TICKET-B", "files_created": ["src/utils.ts"]},
        ),
    ]

    wmem = _mock_working_memory()
    coord = SwarmCoordinator(
        pipeline_id="test-conflict",
        worktree_manager=wm,
        working_memory=wmem,
    )

    conflicts = await coord.pre_merge_conflict_check(results)

    # Should detect at least one conflict between the two tickets
    assert len(conflicts) >= 1

    report = conflicts[0]
    assert {report["ticket_a"], report["ticket_b"]} == {"TICKET-A", "TICKET-B"}
    assert "src/utils.ts" in report["conflicting_files"]


# ---------------------------------------------------------------------------
# Test 3 — auto_resolve_trivial resolves index file conflicts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_resolve_trivial_index_file(git_repo):
    """Barrel file (index.ts) with additive exports from both sides
    should be auto-resolved with both exports present.
    """
    wm = git_repo

    # Write initial barrel content
    index_path = os.path.join(wm.base_project_path, "src/index.ts")
    with open(index_path, "w") as f:
        f.write("// barrel file\nexport { shared } from './utils'\n")
    await wm._run_git("add", "-A")
    await wm._run_git("commit", "-m", "Initial barrel")

    # Worktree A: add export { A } from './a'
    wt_a = await wm.create_worktree("TK-A", "forge/TK-A")
    await _write_commit(
        wm,
        wt_a,
        "src/index.ts",
        "// barrel file\nexport { shared } from './utils'\nexport { A } from './a'\n",
        "Add A export",
    )
    # Also create the module
    await _write_commit(
        wm,
        wt_a,
        "src/a.ts",
        "export const A = 'alpha'\n",
        "Create a.ts",
    )

    # Worktree B: add export { B } from './b'
    wt_b = await wm.create_worktree("TK-B", "forge/TK-B")
    await _write_commit(
        wm,
        wt_b,
        "src/index.ts",
        "// barrel file\nexport { shared } from './utils'\nexport { B } from './b'\n",
        "Add B export",
    )
    await _write_commit(
        wm,
        wt_b,
        "src/b.ts",
        "export const B = 'beta'\n",
        "Create b.ts",
    )

    # First merge A into main (succeeds cleanly)
    merge_a = await wm.merge_worktree("TK-A", "forge/TK-A")
    assert merge_a["success"], "Merge of A should succeed"

    # Now attempt auto-resolve of the trivial conflict for B
    resolved = await auto_resolve_trivial(
        worktree_manager=wm,
        ticket_a_id="TK-A",
        ticket_b_id="TK-B",
        branch_a="forge/TK-A",
        branch_b="forge/TK-B",
        conflict_files=["src/index.ts"],
    )

    assert resolved, "auto_resolve_trivial should succeed for barrel files"

    # Read the resolved index.ts from the repo
    with open(os.path.join(wm.base_project_path, "src/index.ts")) as f:
        content = f.read()

    assert "export { A } from './a'" in content, f"Missing A export in:\n{content}"
    assert "export { B } from './b'" in content, f"Missing B export in:\n{content}"


# ---------------------------------------------------------------------------
# Test 4 — merge_group merges non-conflicting and flags conflicting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_group_mixed_branches(git_repo):
    """merge_group should merge clean branches and flag conflicting ones."""
    wm = git_repo

    # Add initial content to main for utils.ts so conflicts are possible
    utils_path = os.path.join(wm.base_project_path, "src/utils.ts")
    with open(utils_path, "w") as f:
        f.write("// utils\nexport function original() {}\n")
    await wm._run_git("add", "-A")
    await wm._run_git("commit", "-m", "Add utils content")

    # FORGE-1: creates a NEW file (non-conflicting)
    wt1 = await wm.create_worktree("FORGE-1", "forge/FORGE-1")
    await _write_commit(
        wm,
        wt1,
        "src/auth.ts",
        "export function login() { return true }\n",
        "Add auth module",
    )

    # FORGE-2: rewrites utils.ts
    wt2 = await wm.create_worktree("FORGE-2", "forge/FORGE-2")
    await _write_commit(
        wm,
        wt2,
        "src/utils.ts",
        "// utils rewritten by FORGE-2\nexport function helperV2() {}\n",
        "Rewrite utils (FORGE-2)",
    )

    # FORGE-3: also rewrites utils.ts (conflicts with FORGE-2)
    wt3 = await wm.create_worktree("FORGE-3", "forge/FORGE-3")
    await _write_commit(
        wm,
        wt3,
        "src/utils.ts",
        "// utils rewritten by FORGE-3\nexport function helperV3() {}\n",
        "Rewrite utils (FORGE-3)",
    )

    completed = [
        CodingTaskResult(
            ticket_id="FORGE-1",
            success=True,
            code_artifact={
                "ticket_key": "FORGE-1",
                "git_branch": "forge/FORGE-1",
                "files_created": ["src/auth.ts"],
            },
            cost_usd=0.01,
        ),
        CodingTaskResult(
            ticket_id="FORGE-2",
            success=True,
            code_artifact={
                "ticket_key": "FORGE-2",
                "git_branch": "forge/FORGE-2",
                "files_created": ["src/utils.ts"],
            },
            cost_usd=0.01,
        ),
        CodingTaskResult(
            ticket_id="FORGE-3",
            success=True,
            code_artifact={
                "ticket_key": "FORGE-3",
                "git_branch": "forge/FORGE-3",
                "files_created": ["src/utils.ts"],
            },
            cost_usd=0.01,
        ),
    ]

    wmem = _mock_working_memory()
    coord = SwarmCoordinator(
        pipeline_id="test-merge",
        worktree_manager=wm,
        working_memory=wmem,
    )

    # Mock the conflict_resolver functions so we don't call real LLM
    with (
        patch(
            "agents.swarm_coordinator.analyze_conflict",
            new_callable=AsyncMock,
            return_value={
                "severity": "moderate",
                "strategy": "llm_rewrite",
                "affected_files": ["src/utils.ts"],
                "trivial_files": [],
                "non_trivial_files": ["src/utils.ts"],
                "rationale": "Mock analysis",
                "conflict_report": {},
            },
        ),
        patch(
            "agents.swarm_coordinator.resolve_conflict",
            new_callable=AsyncMock,
            return_value={
                "strategy": "llm_rewrite",
                "success": False,
                "cost_usd": 0.0,
            },
        ),
    ):
        result = await coord.merge_group(completed)

    # FORGE-1 should merge cleanly (new file, no conflict)
    assert "FORGE-1" in result["merged"]

    # FORGE-2 and FORGE-3 conflict with each other on utils.ts
    # At least one of them should be in conflicted since the mock
    # resolver returns success=False
    conflicted_set = set(result["conflicted"])
    merged_set = set(result["merged"])

    # FORGE-1 is clean, should be merged
    assert "FORGE-1" in merged_set

    # At least one of FORGE-2/FORGE-3 should be flagged as conflicted
    # (the conflict detector may detect them as conflicting, or one may
    # merge first and the other fails against main)
    assert "FORGE-2" in conflicted_set or "FORGE-3" in conflicted_set, (
        f"Expected at least one of FORGE-2/FORGE-3 in conflicted, got: {result}"
    )


# ---------------------------------------------------------------------------
# Test 5 — validate_execution_order catches file ownership conflicts
# ---------------------------------------------------------------------------


def test_validate_execution_order_catches_conflicts():
    """Tickets sharing files_owned in the same parallel group should be flagged."""
    prd_board = {
        "tickets": [
            {
                "ticket_key": "T-1",
                "title": "Setup models",
                "dependencies": [],
                "files_owned": ["src/models.py", "src/db.py"],
            },
            {
                "ticket_key": "T-2",
                "title": "Build API",
                "dependencies": [],
                "files_owned": ["src/api.py", "src/models.py"],  # conflict!
            },
            {
                "ticket_key": "T-3",
                "title": "Tests",
                "dependencies": ["T-1", "T-2"],
                "files_owned": ["tests/test_all.py"],
            },
        ],
        "execution_order": [
            ["T-1", "T-2"],  # BAD: same group, shared file
            ["T-3"],
        ],
    }

    errors = validate_execution_order(prd_board)

    # Should report the file ownership conflict
    file_errors = [e for e in errors if "src/models.py" in e]
    assert len(file_errors) >= 1, f"Expected file conflict error, got: {errors}"

    # Should also detect that T-2's dependency on T-1 is in the same group
    # (T-2 doesn't explicitly depend on T-1 in this example, so only file
    # conflict is expected)
    assert any("models.py" in e for e in errors)


def test_validate_execution_order_catches_dependency_ordering():
    """A ticket depending on another in the same or later group should fail."""
    prd_board = {
        "tickets": [
            {
                "ticket_key": "A",
                "dependencies": [],
                "files_owned": ["a.py"],
            },
            {
                "ticket_key": "B",
                "dependencies": ["A"],
                "files_owned": ["b.py"],
            },
        ],
        "execution_order": [
            ["A", "B"],  # BAD: B depends on A but they're in the same group
        ],
    }

    errors = validate_execution_order(prd_board)
    dep_errors = [e for e in errors if "depends on" in e]
    assert len(dep_errors) >= 1, f"Expected dependency ordering error, got: {errors}"


def test_validate_execution_order_catches_missing_tickets():
    """All tickets must appear in the execution order."""
    prd_board = {
        "tickets": [
            {"ticket_key": "A", "dependencies": [], "files_owned": []},
            {"ticket_key": "B", "dependencies": [], "files_owned": []},
            {"ticket_key": "C", "dependencies": [], "files_owned": []},
        ],
        "execution_order": [
            ["A", "B"],
            # C is missing!
        ],
    }

    errors = validate_execution_order(prd_board)
    missing_errors = [e for e in errors if "missing" in e.lower()]
    assert len(missing_errors) >= 1, f"Expected missing ticket error, got: {errors}"
    assert any("C" in e for e in missing_errors)


# ---------------------------------------------------------------------------
# Test 6 — optimize_execution_order increases parallelism
# ---------------------------------------------------------------------------


def test_optimize_execution_order_increases_parallelism():
    """Given 5 tickets put sequentially by the PM where only 2 have real
    dependencies, the optimizer should produce fewer groups with more
    tickets running in parallel.
    """
    prd_board = {
        "tickets": [
            {
                "ticket_key": "T-1",
                "title": "Database models",
                "dependencies": [],
                "files_owned": ["models.py"],
            },
            {
                "ticket_key": "T-2",
                "title": "Auth module",
                "dependencies": [],
                "files_owned": ["auth.py"],
            },
            {
                "ticket_key": "T-3",
                "title": "API endpoints",
                "dependencies": ["T-1"],
                "files_owned": ["api.py"],
            },
            {
                "ticket_key": "T-4",
                "title": "Logging utility",
                "dependencies": [],
                "files_owned": ["logger.py"],
            },
            {
                "ticket_key": "T-5",
                "title": "Integration tests",
                "dependencies": ["T-3"],
                "files_owned": ["tests.py"],
            },
        ],
        # PM put everything sequential (worst case)
        "execution_order": [["T-1"], ["T-2"], ["T-3"], ["T-4"], ["T-5"]],
    }

    original_groups = len(prd_board["execution_order"])
    optimised = optimize_execution_order(prd_board)
    optimised_groups = len(optimised)

    # Should reduce the number of groups
    assert optimised_groups < original_groups, (
        f"Expected fewer groups: original={original_groups}, "
        f"optimised={optimised_groups}, result={optimised}"
    )

    # All tickets must still be present
    all_tickets = {tk for group in optimised for tk in group}
    assert all_tickets == {"T-1", "T-2", "T-3", "T-4", "T-5"}

    # T-1, T-2, T-4 have no dependencies on each other and no shared files
    # so they should all be in the first group
    first_group = set(optimised[0])
    assert {"T-1", "T-2", "T-4"}.issubset(first_group), (
        f"T-1, T-2, T-4 should be parallelised in group 0, got: {optimised}"
    )

    # T-3 depends on T-1, so must come after T-1
    t3_group = next(i for i, g in enumerate(optimised) if "T-3" in g)
    t1_group = next(i for i, g in enumerate(optimised) if "T-1" in g)
    assert t3_group > t1_group, "T-3 must come after T-1"

    # T-5 depends on T-3, so must come after T-3
    t5_group = next(i for i, g in enumerate(optimised) if "T-5" in g)
    assert t5_group > t3_group, "T-5 must come after T-3"


def test_optimize_handles_file_ownership_edges():
    """Tickets sharing the same file should be serialised even without
    explicit dependencies.
    """
    prd_board = {
        "tickets": [
            {
                "ticket_key": "A",
                "dependencies": [],
                "files_owned": ["shared.py"],
            },
            {
                "ticket_key": "B",
                "dependencies": [],
                "files_owned": ["shared.py"],
            },
            {
                "ticket_key": "C",
                "dependencies": [],
                "files_owned": ["other.py"],
            },
        ],
        "execution_order": [["A"], ["B"], ["C"]],
    }

    optimised = optimize_execution_order(prd_board)

    # C has no dependency and doesn't share files → should be in group 0
    # A and B share shared.py → must be in different groups
    a_group = next(i for i, g in enumerate(optimised) if "A" in g)
    b_group = next(i for i, g in enumerate(optimised) if "B" in g)
    assert a_group != b_group, f"A and B share shared.py and must not be parallel: {optimised}"


# ---------------------------------------------------------------------------
# Test 7 — detect_file_ownership_conflicts
# ---------------------------------------------------------------------------


def test_detect_file_ownership_conflicts():
    """Should identify all files owned by more than one ticket."""
    tickets = [
        {"ticket_key": "T-1", "files_owned": ["a.py", "shared.py"]},
        {"ticket_key": "T-2", "files_owned": ["b.py", "shared.py"]},
        {"ticket_key": "T-3", "files_owned": ["a.py", "c.py"]},
    ]

    conflicts = detect_file_ownership_conflicts(tickets)

    conflict_files = {c["file_path"] for c in conflicts}
    assert "shared.py" in conflict_files
    assert "a.py" in conflict_files
    assert "b.py" not in conflict_files
    assert "c.py" not in conflict_files

    # Check ticket_ids for shared.py
    shared_conflict = next(c for c in conflicts if c["file_path"] == "shared.py")
    assert set(shared_conflict["ticket_ids"]) == {"T-1", "T-2"}
