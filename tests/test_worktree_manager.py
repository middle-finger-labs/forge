"""Tests for the git worktree manager.

All tests use real git operations against temp directories — no mocking.
"""

from __future__ import annotations

import os

import pytest

from agents.worktree_manager import WorktreeManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SIMPLE_TECH_SPEC = {
    "file_structure": {
        "src/main.py": "entry point",
        "src/utils.py": "helpers",
        "tests/": "test directory",
    }
}


@pytest.fixture
async def repo(tmp_path):
    """Provide a WorktreeManager with a fully initialised repo."""
    repo_path = str(tmp_path / "project")
    wt_dir = str(tmp_path / "worktrees")
    mgr = WorktreeManager(repo_path, worktrees_dir=wt_dir)
    await mgr.setup_repo(SIMPLE_TECH_SPEC)
    return mgr


async def _git(cwd: str, *args: str) -> str:
    """Run a git command and return stdout."""
    import asyncio

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


async def test_setup_repo_creates_valid_git_repo(tmp_path):
    """setup_repo should create a git repo with an initial commit."""
    repo_path = str(tmp_path / "project")
    wt_dir = str(tmp_path / "worktrees")
    mgr = WorktreeManager(repo_path, worktrees_dir=wt_dir)

    result = await mgr.setup_repo(SIMPLE_TECH_SPEC)

    # Returns the repo path
    assert result == repo_path

    # .git directory exists
    assert os.path.isdir(os.path.join(repo_path, ".git"))

    # On the main branch
    branch = await _git(repo_path, "branch", "--show-current")
    assert branch == "main"

    # Has exactly one commit
    log_output = await _git(repo_path, "rev-list", "--count", "HEAD")
    assert log_output == "1"

    # File structure was created
    assert os.path.exists(os.path.join(repo_path, "src", "main.py"))
    assert os.path.exists(os.path.join(repo_path, "src", "utils.py"))
    assert os.path.isdir(os.path.join(repo_path, "tests"))


async def test_setup_repo_is_idempotent(repo: WorktreeManager):
    """Calling setup_repo on an existing repo should return early."""
    path1 = await repo.setup_repo(SIMPLE_TECH_SPEC)
    path2 = await repo.setup_repo(SIMPLE_TECH_SPEC)
    assert path1 == path2

    # Still one commit
    log_output = await _git(repo.base_project_path, "rev-list", "--count", "HEAD")
    assert log_output == "1"


async def test_create_worktree(repo: WorktreeManager):
    """create_worktree should create an isolated worktree on a new branch."""
    wt_path = await repo.create_worktree("FORGE-1", "forge/forge-1")

    # Worktree directory exists
    assert os.path.isdir(wt_path)

    # On the correct branch
    branch = await _git(wt_path, "branch", "--show-current")
    assert branch == "forge/forge-1"

    # Contains the scaffolded files from main
    assert os.path.exists(os.path.join(wt_path, "src", "main.py"))


async def test_worktree_isolation(repo: WorktreeManager):
    """Changes in one worktree should not appear in another."""
    wt1 = await repo.create_worktree("FORGE-1", "forge/forge-1")
    wt2 = await repo.create_worktree("FORGE-2", "forge/forge-2")

    # Write a file in wt1
    new_file = os.path.join(wt1, "src", "feature_1.py")
    with open(new_file, "w") as f:
        f.write("# feature 1\n")
    await _git(wt1, "add", "-A")
    await _git(wt1, "commit", "-m", "add feature 1")

    # The file should NOT exist in wt2
    assert not os.path.exists(os.path.join(wt2, "src", "feature_1.py"))

    # Or in the base repo
    assert not os.path.exists(os.path.join(repo.base_project_path, "src", "feature_1.py"))


async def test_merge_worktree_success(repo: WorktreeManager):
    """merge_worktree should successfully merge a branch with commits."""
    wt_path = await repo.create_worktree("FORGE-1", "forge/forge-1")

    # Make a commit in the worktree
    new_file = os.path.join(wt_path, "src", "new_feature.py")
    with open(new_file, "w") as f:
        f.write("print('hello')\n")
    await _git(wt_path, "add", "-A")
    await _git(wt_path, "commit", "-m", "add new feature")

    result = await repo.merge_worktree("FORGE-1", "forge/forge-1")

    assert result["success"] is True
    assert result["merge_commit"] is not None
    assert result["conflicts"] == []

    # File now exists on main
    assert os.path.exists(os.path.join(repo.base_project_path, "src", "new_feature.py"))


async def test_merge_worktree_conflict(repo: WorktreeManager):
    """Conflicting changes in two worktrees should produce a merge conflict."""
    wt1 = await repo.create_worktree("FORGE-1", "forge/forge-1")
    wt2 = await repo.create_worktree("FORGE-2", "forge/forge-2")

    # Both worktrees modify the same file with different content
    for wt, content, msg in [
        (wt1, "version_a = True\n", "change A"),
        (wt2, "version_b = True\n", "change B"),
    ]:
        with open(os.path.join(wt, "src", "main.py"), "w") as f:
            f.write(content)
        await _git(wt, "add", "-A")
        await _git(wt, "commit", "-m", msg)

    # Merge the first — should succeed
    r1 = await repo.merge_worktree("FORGE-1", "forge/forge-1")
    assert r1["success"] is True

    # Merge the second — should conflict
    r2 = await repo.merge_worktree("FORGE-2", "forge/forge-2")
    assert r2["success"] is False
    assert r2["merge_commit"] is None
    assert len(r2["conflicts"]) > 0

    # Main should still have version_a (conflict was aborted)
    with open(os.path.join(repo.base_project_path, "src", "main.py")) as f:
        assert "version_a" in f.read()


async def test_cleanup_worktree(repo: WorktreeManager):
    """cleanup_worktree should remove the directory and branch."""
    wt_path = await repo.create_worktree("FORGE-1", "forge/forge-1")
    assert os.path.isdir(wt_path)

    await repo.cleanup_worktree("FORGE-1")

    # Directory is gone
    assert not os.path.exists(wt_path)

    # Branch is gone
    branches = await _git(repo.base_project_path, "branch", "--list")
    assert "forge/forge-1" not in branches


async def test_cleanup_all(repo: WorktreeManager):
    """cleanup_all should remove all worktrees and the worktrees directory."""
    wt1 = await repo.create_worktree("FORGE-1", "forge/forge-1")
    wt2 = await repo.create_worktree("FORGE-2", "forge/forge-2")

    assert os.path.isdir(wt1)
    assert os.path.isdir(wt2)

    await repo.cleanup_all()

    # Both worktree directories are gone
    assert not os.path.exists(wt1)
    assert not os.path.exists(wt2)

    # Worktrees dir itself is gone
    assert not os.path.exists(repo.worktrees_dir)

    # Base repo still exists and is intact
    assert os.path.isdir(repo.base_project_path)
    assert os.path.isdir(os.path.join(repo.base_project_path, ".git"))


async def test_get_worktree_status(repo: WorktreeManager):
    """get_worktree_status should report branch, commits ahead, and changed files."""
    wt_path = await repo.create_worktree("FORGE-1", "forge/forge-1")

    # Before any changes
    status = await repo.get_worktree_status("FORGE-1")
    assert status["branch"] == "forge/forge-1"
    assert status["commits_ahead"] == 0
    assert status["changed_files"] == []

    # Make a commit
    with open(os.path.join(wt_path, "src", "new.py"), "w") as f:
        f.write("x = 1\n")
    await _git(wt_path, "add", "-A")
    await _git(wt_path, "commit", "-m", "add new.py")

    status = await repo.get_worktree_status("FORGE-1")
    assert status["commits_ahead"] == 1
    assert "src/new.py" in status["changed_files"]


# ---------------------------------------------------------------------------
# Hardened git operations
# ---------------------------------------------------------------------------


async def test_setup_repo_creates_gitattributes(tmp_path):
    """setup_repo should create .gitattributes with merge strategies."""
    repo_path = str(tmp_path / "project")
    wt_dir = str(tmp_path / "worktrees")
    mgr = WorktreeManager(repo_path, worktrees_dir=wt_dir)
    await mgr.setup_repo(SIMPLE_TECH_SPEC)

    ga_path = os.path.join(repo_path, ".gitattributes")
    assert os.path.isfile(ga_path)

    with open(ga_path) as f:
        content = f.read()

    assert "*.lock binary" in content
    assert "package-lock.json merge=ours" in content


async def test_verify_repo_integrity(repo: WorktreeManager):
    """verify_repo_integrity should return True on a healthy repo."""
    healthy = await repo.verify_repo_integrity()
    assert healthy is True


async def test_checkpoint_create_and_restore(repo: WorktreeManager):
    """create_checkpoint/restore_checkpoint should tag and reset correctly."""
    # Create checkpoint
    cp_hash = await repo.create_checkpoint("test-cp")
    head_before = await _git(repo.base_project_path, "rev-parse", "HEAD")
    assert cp_hash == head_before

    # Tag exists
    tags = await _git(repo.base_project_path, "tag", "--list")
    assert "forge-checkpoint/test-cp" in tags

    # Make a new commit on main
    with open(os.path.join(repo.base_project_path, "src", "extra.py"), "w") as f:
        f.write("x = 1\n")
    await _git(repo.base_project_path, "add", "-A")
    await _git(repo.base_project_path, "commit", "-m", "extra commit")

    head_after = await _git(repo.base_project_path, "rev-parse", "HEAD")
    assert head_after != head_before

    # Restore checkpoint
    await repo.restore_checkpoint("test-cp")
    head_restored = await _git(repo.base_project_path, "rev-parse", "HEAD")
    assert head_restored == head_before

    # The extra file should be gone
    assert not os.path.exists(os.path.join(repo.base_project_path, "src", "extra.py"))


async def test_checkpoint_restore_missing_raises(repo: WorktreeManager):
    """restore_checkpoint should raise WorktreeError for non-existent labels."""
    from agents.worktree_manager import WorktreeError

    with pytest.raises(WorktreeError, match="checkpoint not found"):
        await repo.restore_checkpoint("no-such-checkpoint")


async def test_delete_checkpoint(repo: WorktreeManager):
    """delete_checkpoint should remove the tag."""
    await repo.create_checkpoint("to-delete")
    tags = await _git(repo.base_project_path, "tag", "--list")
    assert "forge-checkpoint/to-delete" in tags

    await repo.delete_checkpoint("to-delete")
    tags = await _git(repo.base_project_path, "tag", "--list")
    assert "forge-checkpoint/to-delete" not in tags


async def test_merge_with_passing_test(repo: WorktreeManager):
    """merge_worktree with test_command='true' should pass and not revert."""
    wt_path = await repo.create_worktree("FORGE-1", "forge/forge-1")
    with open(os.path.join(wt_path, "src", "feat.py"), "w") as f:
        f.write("pass\n")
    await _git(wt_path, "add", "-A")
    await _git(wt_path, "commit", "-m", "feat")

    result = await repo.merge_worktree(
        "FORGE-1",
        "forge/forge-1",
        test_command="true",
    )
    assert result["success"] is True
    assert result["test_passed"] is True
    assert "reverted" not in result


async def test_merge_with_failing_test_reverts(repo: WorktreeManager):
    """merge_worktree with a failing test_command should revert the merge."""
    wt_path = await repo.create_worktree("FORGE-1", "forge/forge-1")
    new_file = os.path.join(wt_path, "src", "bad_feat.py")
    with open(new_file, "w") as f:
        f.write("broken\n")
    await _git(wt_path, "add", "-A")
    await _git(wt_path, "commit", "-m", "bad feat")

    result = await repo.merge_worktree(
        "FORGE-1",
        "forge/forge-1",
        test_command="false",
    )

    assert result["success"] is False
    assert result["test_passed"] is False
    assert result["reverted"] is True

    # The bad file should not be present on main (reverted)
    assert not os.path.exists(os.path.join(repo.base_project_path, "src", "bad_feat.py"))


async def test_merge_group_with_checkpoint(repo: WorktreeManager):
    """merge_group should create checkpoint and merge multiple branches."""
    wt1 = await repo.create_worktree("FORGE-1", "forge/forge-1")
    wt2 = await repo.create_worktree("FORGE-2", "forge/forge-2")

    for wt, name in [(wt1, "feat1"), (wt2, "feat2")]:
        with open(os.path.join(wt, f"src/{name}.py"), "w") as f:
            f.write(f"# {name}\n")
        await _git(wt, "add", "-A")
        await _git(wt, "commit", "-m", f"add {name}")

    results = await repo.merge_group(
        [("FORGE-1", "forge/forge-1"), ("FORGE-2", "forge/forge-2")],
        checkpoint_label="group-test",
        test_command="true",
    )

    assert len(results) == 2
    assert all(r["success"] for r in results)

    # Checkpoint tag exists
    tags = await _git(repo.base_project_path, "tag", "--list")
    assert "forge-checkpoint/group-test" in tags


async def test_gc_runs_after_interval(repo: WorktreeManager):
    """Merge counter should trigger gc after _GC_INTERVAL merges."""
    from agents.worktree_manager import _GC_INTERVAL

    # Set counter to one less than the interval
    repo._merge_count = _GC_INTERVAL - 1

    wt_path = await repo.create_worktree("FORGE-1", "forge/forge-1")
    with open(os.path.join(wt_path, "src", "gc_test.py"), "w") as f:
        f.write("pass\n")
    await _git(wt_path, "add", "-A")
    await _git(wt_path, "commit", "-m", "gc trigger test")

    await repo.merge_worktree("FORGE-1", "forge/forge-1")

    # Counter should now be at the interval
    assert repo._merge_count == _GC_INTERVAL
