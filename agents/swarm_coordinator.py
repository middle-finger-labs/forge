"""Swarm coordinator — orchestrates parallel coding agents within an execution group.

Manages the lifecycle of concurrent ticket execution: semaphore-bounded
concurrency, Redis ticket locks, git worktree creation, coding agent
dispatch, pre-merge conflict detection, and sequential merging.

Usage::

    coord = SwarmCoordinator(
        pipeline_id="abc123",
        max_concurrent=4,
        worktree_manager=wm,
        working_memory=wmem,
    )
    results = await coord.execute_group(tickets, tech_spec_context)
    merge_summary = await coord.merge_group(results)
"""

from __future__ import annotations

import asyncio
import uuid
from itertools import combinations

import structlog

from agents.coding_agent import run_coding_agent_task
from agents.conflict_resolver import analyze_conflict, resolve_conflict
from agents.worktree_manager import WorktreeError, WorktreeManager
from memory.working_memory import WorkingMemory
from workflows.types import CodingTaskResult

log = structlog.get_logger().bind(component="swarm_coordinator")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOCK_RETRY_ATTEMPTS = 3
_LOCK_RETRY_DELAY = 5.0  # seconds


# ---------------------------------------------------------------------------
# SwarmCoordinator
# ---------------------------------------------------------------------------


class SwarmCoordinator:
    """Orchestrate parallel coding agents for a single execution-order group."""

    def __init__(
        self,
        pipeline_id: str,
        *,
        max_concurrent: int = 4,
        worktree_manager: WorktreeManager,
        working_memory: WorkingMemory,
    ) -> None:
        self.pipeline_id = pipeline_id
        self.max_concurrent = max_concurrent
        self.wm = worktree_manager
        self.wmem = working_memory
        self._log = log.bind(pipeline_id=pipeline_id)

    # -- Public API ---------------------------------------------------------

    async def execute_group(
        self,
        tickets: list[dict],
        tech_spec_context: dict,
    ) -> list[CodingTaskResult]:
        """Execute all tickets in a group with bounded concurrency.

        Returns results in the same order as *tickets*.
        """
        if not tickets:
            return []

        semaphore = asyncio.Semaphore(self.max_concurrent)
        self._log.info(
            "executing group",
            ticket_count=len(tickets),
            max_concurrent=self.max_concurrent,
        )

        tasks: list[asyncio.Task[CodingTaskResult]] = []
        for ticket in tickets:
            task = asyncio.create_task(
                self._execute_single_ticket(ticket, tech_spec_context, semaphore),
                name=f"ticket-{ticket.get('ticket_key', 'unknown')}",
            )
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to failed results
        final: list[CodingTaskResult] = []
        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                ticket_id = tickets[i].get("ticket_key", f"unknown-{i}")
                self._log.error(
                    "ticket task raised exception",
                    ticket_id=ticket_id,
                    error=str(result),
                )
                final.append(
                    CodingTaskResult(
                        ticket_id=ticket_id,
                        success=False,
                        error=str(result),
                    )
                )
            else:
                final.append(result)

        succeeded = sum(1 for r in final if r.success)
        self._log.info(
            "group execution complete",
            total=len(final),
            succeeded=succeeded,
            failed=len(final) - succeeded,
        )

        return final

    async def pre_merge_conflict_check(
        self,
        completed_tickets: list[CodingTaskResult],
    ) -> list[dict]:
        """Simulate merges between all branch pairs to detect conflicts.

        Uses ``git merge-tree`` to perform a three-way merge in memory
        without touching the working tree.

        Returns a list of conflict reports::

            {
                "ticket_a": str,
                "ticket_b": str,
                "conflicting_files": [str, ...],
                "conflict_details": str,
            }
        """
        # Only check branches that actually produced code
        branches: list[tuple[str, str]] = []
        for result in completed_tickets:
            if not result.success or not result.code_artifact:
                continue
            branch = result.code_artifact.get("git_branch", "")
            if branch:
                branches.append((result.ticket_id, branch))

        if len(branches) < 2:
            return []

        self._log.info(
            "running pre-merge conflict check",
            branch_count=len(branches),
        )

        conflicts: list[dict] = []

        for (id_a, branch_a), (id_b, branch_b) in combinations(branches, 2):
            tlog = self._log.bind(ticket_a=id_a, ticket_b=id_b)
            try:
                # Find merge base
                merge_base_out, _ = await self.wm._run_git(
                    "merge-base",
                    "main",
                    branch_a,
                )
                merge_base = merge_base_out.strip()

                # Simulate the three-way merge
                try:
                    tree_out, tree_err = await self.wm._run_git(
                        "merge-tree",
                        merge_base,
                        branch_a,
                        branch_b,
                    )
                except WorktreeError as exc:
                    # merge-tree exits non-zero on conflict
                    tree_out = ""
                    tree_err = str(exc)

                # Parse conflict markers from output
                combined = f"{tree_out}\n{tree_err}"
                conflicting_files = _parse_conflict_files(combined)

                if conflicting_files:
                    report = {
                        "ticket_a": id_a,
                        "ticket_b": id_b,
                        "conflicting_files": conflicting_files,
                        "conflict_details": combined[:1000],
                    }
                    conflicts.append(report)
                    tlog.warning(
                        "conflict detected",
                        files=conflicting_files,
                    )

            except WorktreeError as exc:
                tlog.warning(
                    "conflict check failed for pair",
                    error=str(exc),
                )

        self._log.info(
            "conflict check complete",
            conflicts_found=len(conflicts),
        )
        return conflicts

    async def merge_group(
        self,
        completed_tickets: list[CodingTaskResult],
        *,
        tech_spec: dict | None = None,
        tech_spec_context: dict | None = None,
        tickets: list[dict] | None = None,
        pipeline_state: dict | None = None,
    ) -> dict:
        """Merge completed branches into main.

        Runs ``pre_merge_conflict_check`` first, then merges non-conflicting
        branches sequentially with ``--no-ff``.  Detected conflicts are
        routed through the conflict resolver (auto-resolve, LLM rewrite,
        or CTO escalation) before a merge retry.

        Parameters
        ----------
        completed_tickets:
            Results from ``execute_group``.
        tech_spec:
            Architecture tech spec (for conflict analysis).
        tech_spec_context:
            Full tech spec context (for LLM rewrite calls).
        tickets:
            Original ticket dicts (for conflict resolver context).
        pipeline_state:
            Current pipeline state (for CTO escalation).

        Returns::

            {
                "merged": [ticket_id, ...],
                "conflicted": [ticket_id, ...],
                "conflict_details": [{...}, ...],
                "resolutions": [{...}, ...],
                "resolution_cost_usd": float,
            }
        """
        successful = [r for r in completed_tickets if r.success and r.code_artifact]

        if not successful:
            self._log.info("no successful tickets to merge")
            return {
                "merged": [],
                "conflicted": [],
                "conflict_details": [],
                "resolutions": [],
                "resolution_cost_usd": 0.0,
            }

        # Build ticket lookup for conflict resolver
        tickets_by_id: dict[str, dict] = {}
        if tickets:
            for t in tickets:
                tid = t.get("ticket_key", "")
                if tid:
                    tickets_by_id[tid] = t
        # Also inject branch names from code_artifacts
        for r in successful:
            if r.ticket_id not in tickets_by_id:
                tickets_by_id[r.ticket_id] = {}
            if r.code_artifact:
                branch = r.code_artifact.get("git_branch", "")
                if branch:
                    tickets_by_id[r.ticket_id]["branch_name"] = branch
                    tickets_by_id[r.ticket_id]["ticket_key"] = r.ticket_id

        # 1. Pre-merge conflict check
        conflict_reports = await self.pre_merge_conflict_check(successful)

        # Build set of ticket IDs involved in conflicts
        conflicted_ids: set[str] = set()
        for report in conflict_reports:
            conflicted_ids.add(report["ticket_a"])
            conflicted_ids.add(report["ticket_b"])

        # 2. Separate into safe and conflicted
        safe_to_merge = [r for r in successful if r.ticket_id not in conflicted_ids]

        self._log.info(
            "merge plan",
            safe=len(safe_to_merge),
            conflicted=len(conflicted_ids),
        )

        # 3. Merge safe branches sequentially
        merged_ids: list[str] = []
        for result in safe_to_merge:
            branch = result.code_artifact.get("git_branch", "")  # type: ignore[union-attr]
            if not branch:
                continue

            tlog = self._log.bind(ticket_id=result.ticket_id, branch=branch)

            merge_result = await self.wm.merge_worktree(result.ticket_id, branch)

            if merge_result["success"]:
                merged_ids.append(result.ticket_id)
                tlog.info("merged", commit=merge_result["merge_commit"])
            else:
                # Unexpected conflict during actual merge — add to conflicted
                conflicted_ids.add(result.ticket_id)
                conflict_reports.append(
                    {
                        "ticket_a": result.ticket_id,
                        "ticket_b": "main",
                        "conflicting_files": [],
                        "conflict_details": "; ".join(merge_result["conflicts"]),
                    }
                )
                tlog.warning("unexpected merge conflict")

        # 4. Resolve detected conflicts via conflict_resolver
        resolutions: list[dict] = []
        resolution_cost = 0.0

        for report in conflict_reports:
            # Skip reports for tickets already merged or not in conflicted set
            report_tickets = {report["ticket_a"], report["ticket_b"]}
            if not report_tickets & conflicted_ids:
                continue

            self._log.info(
                "resolving conflict",
                ticket_a=report["ticket_a"],
                ticket_b=report["ticket_b"],
            )

            # Analyse
            analysis = await analyze_conflict(report, tech_spec or {})

            # Resolve
            resolution = await resolve_conflict(
                analysis=analysis,
                conflict_report=report,
                worktree_manager=self.wm,
                tickets_by_id=tickets_by_id,
                tech_spec_context=tech_spec_context or {},
                pipeline_state=pipeline_state,
            )
            resolutions.append(resolution)
            resolution_cost += resolution.get("cost_usd", 0.0)

        # 5. Retry merge for conflicted branches after resolution
        still_conflicted: set[str] = set()
        for tid in sorted(conflicted_ids):
            ticket_data = tickets_by_id.get(tid, {})
            branch = ticket_data.get("branch_name", f"forge/{tid}")

            tlog = self._log.bind(ticket_id=tid, branch=branch)
            tlog.info("retrying merge after conflict resolution")

            merge_result = await self.wm.merge_worktree(tid, branch)
            if merge_result["success"]:
                merged_ids.append(tid)
                tlog.info("post-resolution merge succeeded")
            else:
                still_conflicted.add(tid)
                tlog.warning("post-resolution merge still failed — needs manual intervention")

        self._log.info(
            "merge group complete",
            merged=len(merged_ids),
            conflicted=len(still_conflicted),
            resolution_cost=resolution_cost,
        )

        return {
            "merged": merged_ids,
            "conflicted": sorted(still_conflicted),
            "conflict_details": conflict_reports,
            "resolutions": resolutions,
            "resolution_cost_usd": resolution_cost,
        }

    # -- Internal -----------------------------------------------------------

    async def _execute_single_ticket(
        self,
        ticket: dict,
        tech_spec_context: dict,
        semaphore: asyncio.Semaphore,
    ) -> CodingTaskResult:
        """Execute one ticket: lock, create worktree, code, clean up."""
        ticket_id = ticket.get("ticket_key", f"unknown-{uuid.uuid4().hex[:6]}")
        branch_name = ticket.get("branch_name", f"forge/{ticket_id}")
        agent_id = f"swarm-{self.pipeline_id}-{ticket_id}"
        tlog = self._log.bind(ticket_id=ticket_id, branch=branch_name)

        async with semaphore:
            tlog.info("semaphore acquired, starting ticket")

            # 1. Acquire ticket lock with retry
            lock_acquired = await self._acquire_lock_with_retry(
                ticket_id,
                agent_id,
                tlog,
            )
            if not lock_acquired:
                tlog.error("failed to acquire ticket lock after retries")
                return CodingTaskResult(
                    ticket_id=ticket_id,
                    success=False,
                    error="Could not acquire ticket lock — another agent may hold it",
                )

            try:
                # 2. Create worktree
                tlog.info("creating worktree")
                try:
                    worktree_path = await self.wm.create_worktree(
                        ticket_id,
                        branch_name,
                    )
                except WorktreeError as exc:
                    tlog.error("worktree creation failed", error=str(exc))
                    return CodingTaskResult(
                        ticket_id=ticket_id,
                        success=False,
                        error=f"Worktree creation failed: {exc}",
                    )

                # 3. Run coding agent
                tlog.info("launching coding agent", worktree=worktree_path)
                try:
                    code_artifact, cost_usd = await run_coding_agent_task(
                        ticket=ticket,
                        tech_spec_context=tech_spec_context,
                        worktree_path=worktree_path,
                        branch_name=branch_name,
                    )
                except Exception as exc:
                    tlog.error("coding agent failed", error=str(exc))
                    return CodingTaskResult(
                        ticket_id=ticket_id,
                        success=False,
                        error=f"Coding agent error: {exc}",
                    )

                if code_artifact is None:
                    tlog.warning("coding agent returned no artifact")
                    return CodingTaskResult(
                        ticket_id=ticket_id,
                        success=False,
                        error="Coding agent produced no output",
                        cost_usd=cost_usd,
                    )

                tlog.info(
                    "ticket completed",
                    files_created=len(code_artifact.get("files_created", [])),
                    cost=cost_usd,
                )

                return CodingTaskResult(
                    ticket_id=ticket_id,
                    success=True,
                    code_artifact=code_artifact,
                    cost_usd=cost_usd,
                )

            finally:
                # 4. Always release lock
                try:
                    await self.wmem.release_ticket_lock(
                        self.pipeline_id,
                        ticket_id,
                    )
                    tlog.info("ticket lock released")
                except Exception as exc:
                    tlog.warning(
                        "failed to release ticket lock",
                        error=str(exc),
                    )

    async def _acquire_lock_with_retry(
        self,
        ticket_id: str,
        agent_id: str,
        tlog: structlog.BoundLogger,
    ) -> bool:
        """Try to acquire the ticket lock, retrying up to 3 times."""
        for attempt in range(1, _LOCK_RETRY_ATTEMPTS + 1):
            try:
                acquired = await self.wmem.set_ticket_lock(
                    self.pipeline_id,
                    ticket_id,
                    agent_id,
                )
                if acquired:
                    tlog.info("ticket lock acquired", attempt=attempt)
                    return True
            except Exception as exc:
                tlog.warning(
                    "lock acquisition error",
                    attempt=attempt,
                    error=str(exc),
                )

            if attempt < _LOCK_RETRY_ATTEMPTS:
                tlog.info(
                    "lock held by another agent, retrying",
                    attempt=attempt,
                    delay=_LOCK_RETRY_DELAY,
                )
                await asyncio.sleep(_LOCK_RETRY_DELAY)

        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_conflict_files(merge_tree_output: str) -> list[str]:
    """Extract conflicting file paths from ``git merge-tree`` output.

    The output contains lines like::

        changed in both
          base   100644 <hash> <path>
          our    100644 <hash> <path>
          their  100644 <hash> <path>

    Or for newer git versions, conflict markers with file paths.
    """
    files: list[str] = []
    lines = merge_tree_output.splitlines()
    in_conflict_block = False

    for line in lines:
        stripped = line.strip()

        # Traditional merge-tree output: "changed in both" section
        if "changed in both" in stripped.lower():
            in_conflict_block = True
            continue

        if in_conflict_block:
            # Blank line or new section ends the block
            if not stripped or (
                not stripped.startswith("base")
                and not stripped.startswith("our")
                and not stripped.startswith("their")
            ):
                in_conflict_block = False
                continue
            # Extract file path (last token on the line)
            parts = stripped.split()
            if len(parts) >= 4:
                filepath = parts[-1]
                if filepath not in files:
                    files.append(filepath)

        # Also catch "CONFLICT (content): Merge conflict in <file>"
        if "CONFLICT" in stripped and "Merge conflict in" in stripped:
            idx = stripped.find("Merge conflict in")
            filepath = stripped[idx + len("Merge conflict in") :].strip()
            if filepath and filepath not in files:
                files.append(filepath)

        # "Auto-merging <file>" followed by conflict is also a signal,
        # but we only flag if there's an actual CONFLICT line
        if stripped.startswith("CONFLICT") and ":" in stripped:
            # Try to extract filename from CONFLICT lines
            after_colon = stripped.split(":", 1)[-1].strip()
            # "Merge conflict in path/to/file"
            if after_colon.startswith("Merge conflict in "):
                filepath = after_colon[len("Merge conflict in ") :]
                if filepath and filepath not in files:
                    files.append(filepath)

    return files


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------


async def _main() -> None:
    """End-to-end smoke test: create 3 worktrees, make non-conflicting
    changes in each, and merge them all back to main.
    """
    import os
    import tempfile

    print("=== SwarmCoordinator smoke test ===\n")

    base = tempfile.mkdtemp(prefix="forge-swarm-test-")
    repo_path = os.path.join(base, "project")
    wt_dir = os.path.join(base, "worktrees")

    wm = WorktreeManager(repo_path, worktrees_dir=wt_dir)

    # Setup repo
    tech_spec = {
        "file_structure": {
            "src/main.py": {"description": "entry point"},
            "src/utils.py": {"description": "helpers"},
            "src/models.py": {"description": "data models"},
        },
    }
    await wm.setup_repo(tech_spec)
    print(f"[1] Repo initialised at {repo_path}")

    # Create 3 worktrees with non-conflicting changes
    ticket_data = [
        {
            "ticket_key": "FORGE-1",
            "branch_name": "forge/FORGE-1",
            "file": "src/auth.py",
            "content": "# Authentication module\ndef login(user, password):\n    return True\n",
        },
        {
            "ticket_key": "FORGE-2",
            "branch_name": "forge/FORGE-2",
            "file": "src/api.py",
            "content": "# API module\ndef get_users():\n    return []\n",
        },
        {
            "ticket_key": "FORGE-3",
            "branch_name": "forge/FORGE-3",
            "file": "src/db.py",
            "content": "# Database module\ndef connect():\n    return None\n",
        },
    ]

    # Simulate coding agent work (create worktrees, write files, commit)
    results: list[CodingTaskResult] = []
    for td in ticket_data:
        ticket_id = td["ticket_key"]
        branch = td["branch_name"]

        print(f"\n[2] Creating worktree for {ticket_id}...")
        wt_path = await wm.create_worktree(ticket_id, branch)

        # Write a file
        filepath = os.path.join(wt_path, td["file"])
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w") as f:
            f.write(td["content"])

        # Commit
        await wm._run_git("-C", wt_path, "add", "-A", cwd=wt_path)
        await wm._run_git(
            "-C",
            wt_path,
            "commit",
            "-m",
            f"Implement {ticket_id}",
            cwd=wt_path,
        )

        status = await wm.get_worktree_status(ticket_id)
        print(f"    Status: {status}")

        results.append(
            CodingTaskResult(
                ticket_id=ticket_id,
                success=True,
                code_artifact={
                    "ticket_key": ticket_id,
                    "git_branch": branch,
                    "files_created": [td["file"]],
                    "files_modified": [],
                },
                cost_usd=0.001,
            )
        )

    # Pre-merge conflict check
    print("\n[3] Running pre-merge conflict check...")
    conflict_reports = []
    for (id_a, branch_a), (id_b, branch_b) in combinations(
        [(r.ticket_id, r.code_artifact["git_branch"]) for r in results],  # type: ignore[index]
        2,
    ):
        try:
            merge_base_out, _ = await wm._run_git(
                "merge-base",
                "main",
                branch_a,
            )
            merge_base = merge_base_out.strip()

            try:
                await wm._run_git("merge-tree", merge_base, branch_a, branch_b)
            except WorktreeError as exc:
                conflict_reports.append(
                    {
                        "ticket_a": id_a,
                        "ticket_b": id_b,
                        "details": str(exc),
                    }
                )
        except WorktreeError:
            pass

    if conflict_reports:
        print(f"    Conflicts found: {conflict_reports}")
    else:
        print("    No conflicts detected!")

    # Merge all
    print("\n[4] Merging branches sequentially...")
    for result in results:
        branch = result.code_artifact["git_branch"]  # type: ignore[index]
        merge_result = await wm.merge_worktree(result.ticket_id, branch)
        status_str = "OK" if merge_result["success"] else "CONFLICT"
        print(f"    {result.ticket_id}: {status_str} — {merge_result}")

    # Verify final state
    print("\n[5] Final repo state:")
    git_log, _ = await wm._run_git("log", "--oneline", "-10")
    for line in git_log.splitlines():
        print(f"    {line}")

    # Show all files on main
    files_out, _ = await wm._run_git("ls-tree", "-r", "--name-only", "HEAD")
    print("\n    Files on main:")
    for f in files_out.splitlines():
        print(f"      {f}")

    # Cleanup
    print("\n[6] Cleaning up...")
    await wm.cleanup_all()
    import shutil

    shutil.rmtree(base)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(_main())
