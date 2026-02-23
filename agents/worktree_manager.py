"""Git worktree lifecycle manager for parallel coding tasks.

Each coding ticket gets an isolated worktree so multiple agents can write files
concurrently without conflicts.  This module wraps all git operations behind
async helpers that the coding and merge activities consume.

Production-hardened features:
  - Per-worktree asyncio.Lock to prevent concurrent git ops on the same tree
  - Automatic ``git gc --auto`` after every N merges
  - Repository integrity checks via ``git fsck``
  - Post-merge test runner with bisect-style bad-merge detection + revert
  - Checkpoint/restore via lightweight git tags
  - ``.gitattributes`` written during repo scaffold
"""

from __future__ import annotations

import asyncio
import functools
import os
import shutil

import structlog

log = structlog.get_logger().bind(component="worktree_manager")

# How many merges between automatic ``git gc --auto`` runs.
_GC_INTERVAL = 10

# Default .gitattributes content for scaffolded repos.
_GITATTRIBUTES = """\
# Auto-detect text files and normalise line endings
* text=auto

# Lock files — treat as binary (no merge)
*.lock binary
package-lock.json merge=ours
yarn.lock merge=ours
pnpm-lock.yaml merge=ours

# Common binary formats
*.png binary
*.jpg binary
*.jpeg binary
*.gif binary
*.ico binary
*.woff binary
*.woff2 binary
*.ttf binary
*.eot binary
*.pdf binary
*.zip binary
*.gz binary
*.tar binary
"""


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class WorktreeError(Exception):
    """Raised when a git operation fails."""


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class WorktreeManager:
    """Create, inspect, merge, and tear-down git worktrees."""

    def __init__(self, base_project_path: str, worktrees_dir: str | None = None) -> None:
        self.base_project_path = base_project_path
        self.worktrees_dir = worktrees_dir or os.path.join("/tmp", "forge", "worktrees")
        self._file_cache: dict[str, str] = {}

        # Per-worktree locks keyed by ticket_id (or "main" for the base repo).
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

        # Merge counter for periodic gc.
        self._merge_count: int = 0

    # -- internal helpers ---------------------------------------------------

    async def _get_lock(self, key: str) -> asyncio.Lock:
        """Return an asyncio.Lock for *key*, creating it lazily."""
        async with self._locks_guard:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
            return self._locks[key]

    async def _run_git(self, *args: str, cwd: str | None = None) -> tuple[str, str]:
        """Run ``git <args>`` and return *(stdout, stderr)*.

        Raises ``WorktreeError`` on non-zero exit.
        """
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd or self.base_project_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        stdout = stdout_bytes.decode().strip()
        stderr = stderr_bytes.decode().strip()

        if proc.returncode != 0:
            raise WorktreeError(stderr or stdout)
        return stdout, stderr

    async def _run_cmd(
        self,
        cmd: str,
        cwd: str | None = None,
        timeout: float = 120.0,
    ) -> tuple[str, str, int]:
        """Run an arbitrary shell command.  Returns *(stdout, stderr, returncode)*."""
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=cwd or self.base_project_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            return "", f"Command timed out after {timeout}s: {cmd}", -1
        return (
            stdout_bytes.decode().strip(),
            stderr_bytes.decode().strip(),
            proc.returncode or 0,
        )

    async def _maybe_gc(self) -> None:
        """Run ``git gc --auto`` if the merge counter has hit the interval."""
        self._merge_count += 1
        if self._merge_count % _GC_INTERVAL != 0:
            return
        try:
            log.info("running git gc", merge_count=self._merge_count)
            await self._run_git("gc", "--auto")
            log.info("git gc complete")
        except WorktreeError as exc:
            log.warning("git gc failed", error=str(exc)[:200])

    # -- public API ---------------------------------------------------------

    async def setup_repo(self, tech_spec: dict) -> str:
        """Initialise a git repo at *base_project_path* if one doesn't exist.

        Creates the directory scaffold described by ``tech_spec["file_structure"]``,
        writes a ``.gitattributes`` with merge strategies, and makes an initial
        commit.  Returns the repo path.
        """
        git_dir = os.path.join(self.base_project_path, ".git")
        if os.path.isdir(git_dir):
            log.info("repo already initialised", path=self.base_project_path)
            return self.base_project_path

        os.makedirs(self.base_project_path, exist_ok=True)
        await self._run_git("init")
        await self._run_git("checkout", "-b", "main")

        # Write .gitattributes
        gitattributes_path = os.path.join(self.base_project_path, ".gitattributes")
        with open(gitattributes_path, "w") as f:
            f.write(_GITATTRIBUTES)

        # Scaffold directory tree from tech_spec
        file_structure: dict = tech_spec.get("file_structure", {})
        for file_path in file_structure:
            full = os.path.join(self.base_project_path, file_path)
            dir_path = os.path.dirname(full)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            # Create a .gitkeep so empty dirs are tracked, or touch the file
            if file_path.endswith("/"):
                os.makedirs(full, exist_ok=True)
                gitkeep = os.path.join(full, ".gitkeep")
                if not os.path.exists(gitkeep):
                    open(gitkeep, "w").close()  # noqa: SIM115
            else:
                if not os.path.exists(full):
                    open(full, "w").close()  # noqa: SIM115

        await self._run_git("add", "-A")
        await self._run_git("commit", "-m", "Initial scaffold")

        log.info("repo initialised", path=self.base_project_path)
        return self.base_project_path

    async def create_worktree(self, ticket_id: str, branch_name: str) -> str:
        """Create an isolated worktree for *ticket_id*.

        Returns the absolute path to the new worktree.
        """
        lock = await self._get_lock(ticket_id)
        async with lock:
            path = os.path.join(self.worktrees_dir, ticket_id)

            if os.path.exists(path):
                log.info("worktree path exists, cleaning up first", ticket_id=ticket_id)
                await self._cleanup_worktree_unlocked(ticket_id)

            os.makedirs(self.worktrees_dir, exist_ok=True)
            await self._run_git("worktree", "add", "-b", branch_name, path, "main")

            log.info("worktree created", ticket_id=ticket_id, branch=branch_name, path=path)
            return path

    async def reset_worktree(self, ticket_id: str, new_branch_name: str) -> str:
        """Reset an existing worktree for reuse on a new revision cycle.

        If the worktree doesn't exist, falls back to ``create_worktree``.
        Otherwise discards uncommitted changes, switches to main, deletes
        the old branch, and creates *new_branch_name* from main — avoiding
        the overhead of ``git worktree add`` / ``remove``.

        Returns the worktree path.
        """
        lock = await self._get_lock(ticket_id)
        async with lock:
            path = os.path.join(self.worktrees_dir, ticket_id)

            if not os.path.exists(path):
                log.info("worktree missing, creating fresh", ticket_id=ticket_id)
                # Release lock, delegate to create_worktree which acquires it.
                # We call the unlocked inner logic directly instead.
                os.makedirs(self.worktrees_dir, exist_ok=True)
                await self._run_git("worktree", "add", "-b", new_branch_name, path, "main")
                log.info(
                    "worktree created (via reset fallback)",
                    ticket_id=ticket_id,
                    branch=new_branch_name,
                    path=path,
                )
                return path

            # Discard uncommitted changes
            await self._run_git("checkout", "--", ".", cwd=path)
            await self._run_git("clean", "-fd", cwd=path)

            # Discover current branch
            current_branch, _ = await self._run_git(
                "branch",
                "--show-current",
                cwd=path,
            )

            # Switch to main, delete old branch, create new branch
            if current_branch != "main":
                await self._run_git("checkout", "main", cwd=path)
                try:
                    await self._run_git("branch", "-D", current_branch, cwd=path)
                except WorktreeError:
                    pass  # branch may already be gone

            # Pull latest main into the worktree
            await self._run_git("reset", "--hard", "main", cwd=path)

            # Create the new branch
            await self._run_git("checkout", "-b", new_branch_name, cwd=path)

            self.invalidate_cache(path)

            log.info(
                "worktree reset for reuse",
                ticket_id=ticket_id,
                branch=new_branch_name,
                path=path,
            )
            return path

    # -- file content cache -------------------------------------------------

    async def read_file_cached(
        self,
        worktree_path: str,
        relative_path: str,
    ) -> str | None:
        """Read a file's contents with in-memory caching.

        Returns the file content as a string, or ``None`` if the file
        doesn't exist.  Subsequent calls for the same file return the
        cached value without hitting disk.
        """
        cache_key = os.path.join(worktree_path, relative_path)

        if cache_key in self._file_cache:
            return self._file_cache[cache_key]

        full_path = cache_key
        if not os.path.isfile(full_path):
            return None

        loop = asyncio.get_running_loop()
        content = await loop.run_in_executor(
            None,
            functools.partial(self._read_file_sync, full_path),
        )
        self._file_cache[cache_key] = content
        return content

    @staticmethod
    def _read_file_sync(path: str) -> str:
        with open(path) as f:
            return f.read()

    def invalidate_cache(self, worktree_path: str | None = None) -> None:
        """Clear cached file contents.

        If *worktree_path* is given, only entries under that prefix are
        removed.  Otherwise the entire cache is cleared.
        """
        if worktree_path is None:
            self._file_cache.clear()
            return

        prefix = worktree_path
        keys = [k for k in self._file_cache if k.startswith(prefix)]
        for k in keys:
            del self._file_cache[k]

    # -- cleanup ------------------------------------------------------------

    async def cleanup_worktree(self, ticket_id: str) -> None:
        """Remove the worktree for *ticket_id* and delete its branch."""
        lock = await self._get_lock(ticket_id)
        async with lock:
            await self._cleanup_worktree_unlocked(ticket_id)

    async def _cleanup_worktree_unlocked(self, ticket_id: str) -> None:
        """Inner cleanup logic — caller must hold the lock for *ticket_id*."""
        path = os.path.join(self.worktrees_dir, ticket_id)

        # Discover the branch before removing the worktree
        branch_name: str | None = None
        try:
            stdout, _ = await self._run_git("worktree", "list", "--porcelain")
            lines = stdout.splitlines()
            for i, line in enumerate(lines):
                if line.startswith("worktree ") and line.endswith(path):
                    # The branch line follows: "branch refs/heads/<name>"
                    for j in range(i + 1, min(i + 4, len(lines))):
                        if lines[j].startswith("branch refs/heads/"):
                            branch_name = lines[j].removeprefix("branch refs/heads/")
                            break
                    break
        except WorktreeError:
            pass

        # Remove the worktree
        try:
            await self._run_git("worktree", "remove", "--force", path)
        except WorktreeError as exc:
            log.warning("worktree remove failed", ticket_id=ticket_id, error=str(exc))
            # Fallback: manually delete the directory
            if os.path.exists(path):
                shutil.rmtree(path)
            try:
                await self._run_git("worktree", "prune")
            except WorktreeError:
                pass

        # Delete the branch
        if branch_name:
            try:
                await self._run_git("branch", "-D", branch_name)
            except WorktreeError:
                pass

        log.info("worktree cleaned up", ticket_id=ticket_id)

    async def get_worktree_status(self, ticket_id: str) -> dict:
        """Return status info for the worktree belonging to *ticket_id*."""
        path = os.path.join(self.worktrees_dir, ticket_id)

        branch_out, _ = await self._run_git("-C", path, "branch", "--show-current")

        count_out, _ = await self._run_git("-C", path, "rev-list", "main..HEAD", "--count")

        diff_out, _ = await self._run_git("-C", path, "diff", "--name-only", "main")
        changed = [f for f in diff_out.splitlines() if f]

        return {
            "branch": branch_out,
            "commits_ahead": int(count_out),
            "changed_files": changed,
        }

    # -- merge with locking, gc, and post-merge testing ---------------------

    async def merge_worktree(
        self,
        ticket_id: str,
        branch_name: str,
        *,
        test_command: str | None = None,
    ) -> dict:
        """Merge *branch_name* into main in the base repo.

        Acquires the ``"main"`` lock to serialise merges.  After a successful
        merge, optionally runs *test_command* and reverts if tests fail.

        Returns a dict with ``success``, ``merge_commit``, ``conflicts``,
        and optionally ``test_passed`` / ``reverted``.
        """
        main_lock = await self._get_lock("main")
        async with main_lock:
            try:
                await self._run_git(
                    "merge",
                    "--no-ff",
                    branch_name,
                    "-m",
                    f"Merge {branch_name}",
                )
                # Grab the merge commit hash
                hash_out, _ = await self._run_git("rev-parse", "HEAD")
                self.invalidate_cache()
                log.info("merge succeeded", ticket_id=ticket_id, branch=branch_name)

                result: dict = {
                    "success": True,
                    "merge_commit": hash_out,
                    "conflicts": [],
                }

                # Post-merge test
                if test_command:
                    passed = await self._run_post_merge_test(
                        test_command,
                        ticket_id,
                        hash_out,
                    )
                    result["test_passed"] = passed
                    if not passed:
                        result["reverted"] = True
                        result["success"] = False

                # Periodic garbage collection
                await self._maybe_gc()

                return result

            except WorktreeError as exc:
                log.warning("merge conflict", ticket_id=ticket_id, error=str(exc))
                try:
                    await self._run_git("merge", "--abort")
                except WorktreeError:
                    pass
                return {
                    "success": False,
                    "merge_commit": None,
                    "conflicts": [str(exc)],
                }

    async def _run_post_merge_test(
        self,
        test_command: str,
        ticket_id: str,
        merge_commit: str,
    ) -> bool:
        """Run *test_command* after a merge.  Reverts the merge on failure."""
        log.info(
            "running post-merge test",
            ticket_id=ticket_id,
            command=test_command,
        )
        stdout, stderr, rc = await self._run_cmd(
            test_command,
            cwd=self.base_project_path,
        )

        if rc == 0:
            log.info("post-merge test passed", ticket_id=ticket_id)
            return True

        log.warning(
            "post-merge test failed — reverting merge",
            ticket_id=ticket_id,
            merge_commit=merge_commit,
            stderr=stderr[:300],
        )

        # Revert the merge commit (first-parent keeps main's history)
        try:
            await self._run_git(
                "revert",
                "-m",
                "1",
                "--no-edit",
                merge_commit,
            )
            log.info("merge reverted", ticket_id=ticket_id, commit=merge_commit)
        except WorktreeError as exc:
            log.error(
                "failed to revert merge — manual intervention needed",
                ticket_id=ticket_id,
                error=str(exc)[:200],
            )

        return False

    async def merge_group(
        self,
        branches: list[tuple[str, str]],
        *,
        test_command: str | None = None,
        checkpoint_label: str | None = None,
    ) -> list[dict]:
        """Merge a list of *(ticket_id, branch_name)* into main.

        If *checkpoint_label* is given, creates a checkpoint before merging.
        If *test_command* is given, runs tests after each merge and reverts
        on failure (bisect-style isolation of the bad merge).

        Returns a list of per-branch merge results.
        """
        if checkpoint_label:
            await self.create_checkpoint(checkpoint_label)

        results: list[dict] = []
        for ticket_id, branch_name in branches:
            result = await self.merge_worktree(
                ticket_id,
                branch_name,
                test_command=test_command,
            )
            results.append(result)

            if result.get("reverted"):
                log.warning(
                    "bad merge detected in group — ticket isolated",
                    ticket_id=ticket_id,
                    branch=branch_name,
                )

        return results

    # -- repository integrity -----------------------------------------------

    async def verify_repo_integrity(self) -> bool:
        """Run ``git fsck`` on the base repo and return ``True`` if healthy."""
        main_lock = await self._get_lock("main")
        async with main_lock:
            try:
                stdout, stderr = await self._run_git("fsck", "--no-dangling")
                log.info("repo integrity check passed")
                return True
            except WorktreeError as exc:
                log.error(
                    "repo integrity check FAILED",
                    error=str(exc)[:500],
                )
                return False

    # -- checkpoints --------------------------------------------------------

    async def create_checkpoint(self, label: str) -> str:
        """Create a lightweight git tag as a named checkpoint.

        Returns the commit hash that was tagged.
        """
        main_lock = await self._get_lock("main")
        async with main_lock:
            tag_name = f"forge-checkpoint/{label}"
            hash_out, _ = await self._run_git("rev-parse", "HEAD")

            # Delete existing tag with same name (idempotent)
            try:
                await self._run_git("tag", "-d", tag_name)
            except WorktreeError:
                pass

            await self._run_git("tag", tag_name, hash_out)
            log.info("checkpoint created", label=label, tag=tag_name, commit=hash_out)
            return hash_out

    async def restore_checkpoint(self, label: str) -> None:
        """Hard-reset main to the commit tagged by *label*.

        This is the nuclear option — discards all merges after the checkpoint.
        """
        main_lock = await self._get_lock("main")
        async with main_lock:
            tag_name = f"forge-checkpoint/{label}"
            try:
                hash_out, _ = await self._run_git("rev-parse", tag_name)
            except WorktreeError:
                raise WorktreeError(f"checkpoint not found: {label}")

            await self._run_git("reset", "--hard", hash_out)
            self.invalidate_cache()
            log.warning(
                "restored checkpoint — all subsequent commits discarded",
                label=label,
                tag=tag_name,
                commit=hash_out,
            )

    async def delete_checkpoint(self, label: str) -> None:
        """Remove a checkpoint tag."""
        tag_name = f"forge-checkpoint/{label}"
        try:
            await self._run_git("tag", "-d", tag_name)
            log.info("checkpoint deleted", label=label)
        except WorktreeError:
            pass

    # -- cleanup all --------------------------------------------------------

    async def cleanup_all(self) -> None:
        """Remove every worktree and delete the worktrees directory."""
        main_real = os.path.realpath(self.base_project_path)
        try:
            stdout, _ = await self._run_git("worktree", "list", "--porcelain")
            for line in stdout.splitlines():
                if not line.startswith("worktree "):
                    continue
                wt_path = line.removeprefix("worktree ")
                if os.path.realpath(wt_path) == main_real:
                    continue
                try:
                    await self._run_git("worktree", "remove", "--force", wt_path)
                except WorktreeError:
                    if os.path.exists(wt_path):
                        shutil.rmtree(wt_path)
        except WorktreeError:
            pass

        try:
            await self._run_git("worktree", "prune")
        except WorktreeError:
            pass

        if os.path.exists(self.worktrees_dir):
            shutil.rmtree(self.worktrees_dir)

        log.info("all worktrees cleaned up")


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------


async def _main() -> None:
    """End-to-end smoke test using a temp directory."""
    import tempfile

    base = tempfile.mkdtemp(prefix="forge-wt-test-")
    repo_path = os.path.join(base, "project")
    wt_dir = os.path.join(base, "worktrees")

    mgr = WorktreeManager(repo_path, worktrees_dir=wt_dir)

    tech_spec = {
        "file_structure": {
            "src/main.py": {"description": "entry point"},
            "src/utils.py": {"description": "helpers"},
            "tests/": {"description": "test directory"},
        }
    }

    # 1. Setup repo (now includes .gitattributes)
    print("--- setup_repo ---")
    await mgr.setup_repo(tech_spec)
    ga = os.path.join(repo_path, ".gitattributes")
    assert os.path.isfile(ga), ".gitattributes missing"
    print(f"  .gitattributes exists: {os.path.isfile(ga)}")

    # 2. Verify repo integrity
    print("\n--- verify_repo_integrity ---")
    healthy = await mgr.verify_repo_integrity()
    print(f"  healthy: {healthy}")
    assert healthy

    # 3. Create checkpoint
    print("\n--- create_checkpoint ---")
    cp_hash = await mgr.create_checkpoint("before-tickets")
    print(f"  checkpoint: {cp_hash}")

    # 4. Create two worktrees
    print("\n--- create worktrees ---")
    wt1 = await mgr.create_worktree("ticket-1", "forge/ticket-1")
    wt2 = await mgr.create_worktree("ticket-2", "forge/ticket-2")
    print(f"  wt1={wt1}\n  wt2={wt2}")

    # 5. Make changes in each worktree
    print("\n--- make changes ---")
    for wt, name in [(wt1, "ticket-1"), (wt2, "ticket-2")]:
        filepath = os.path.join(wt, f"src/{name}.py")
        with open(filepath, "w") as f:
            f.write(f"# Code for {name}\nprint('hello from {name}')\n")
        await mgr._run_git("-C", wt, "add", "-A", cwd=wt)
        await mgr._run_git("-C", wt, "commit", "-m", f"Implement {name}", cwd=wt)

    # 6. Check status
    print("\n--- worktree status ---")
    for tid in ("ticket-1", "ticket-2"):
        status = await mgr.get_worktree_status(tid)
        print(f"  {tid}: {status}")

    # 7. Merge group with checkpoint and test command
    print("\n--- merge_group ---")
    results = await mgr.merge_group(
        [("ticket-1", "forge/ticket-1"), ("ticket-2", "forge/ticket-2")],
        checkpoint_label="group-1",
        test_command="true",  # always-passing test
    )
    for r in results:
        print(f"  result: {r}")

    # 8. Verify integrity after merges
    print("\n--- verify after merge ---")
    healthy = await mgr.verify_repo_integrity()
    print(f"  healthy: {healthy}")
    assert healthy

    # 9. Cleanup
    print("\n--- cleanup_all ---")
    await mgr.cleanup_all()
    shutil.rmtree(base)
    print("done.")


if __name__ == "__main__":
    asyncio.run(_main())
