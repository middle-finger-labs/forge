#!/usr/bin/env python3
"""Swarm stress-test / load simulation.

Simulates a full pipeline with N tickets running through the parallel
execution system — coding, QA, revision cycles, conflict detection, and
merge — without making real LLM calls.

Usage::

    python -m scripts.simulate_swarm                          # 20 tickets, 4 parallel
    python -m scripts.simulate_swarm --tickets 50 --max-parallel 8
    python -m scripts.simulate_swarm --failure-rate 0.3       # 30 % first-pass QA failures
    python -m scripts.simulate_swarm --with-dashboard         # emit events to Redis
    python -m scripts.simulate_swarm --seed 42                # reproducible runs
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import shutil
import string
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

# ---------------------------------------------------------------------------
# Ensure the repo root is on sys.path so relative imports resolve
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from agents.dependency_analyzer import (  # noqa: E402
    detect_file_ownership_conflicts,
    optimize_execution_order,
    validate_execution_order,
)
from agents.worktree_manager import WorktreeManager  # noqa: E402
from config.concurrency import ConcurrencyConfig, ConcurrencyMonitor  # noqa: E402
from workflows.types import CodingTaskResult  # noqa: E402

# ---------------------------------------------------------------------------
# Metrics tracker
# ---------------------------------------------------------------------------


@dataclass
class SimMetrics:
    """Accumulates metrics throughout the simulation."""

    wall_start: float = 0.0
    wall_end: float = 0.0

    tickets_total: int = 0
    tickets_completed: int = 0
    tickets_failed: int = 0

    # Per-ticket timings (ticket_key → seconds)
    coding_durations: dict[str, float] = field(default_factory=dict)
    qa_durations: dict[str, float] = field(default_factory=dict)

    # Agent utilisation: total seconds spent in agent work
    agent_busy_seconds: float = 0.0

    # Revision tracking
    revision_counts: dict[str, int] = field(default_factory=dict)
    total_revisions: int = 0

    # Conflict tracking
    conflicts_detected: int = 0
    conflicts_auto_resolved: int = 0
    conflicts_escalated: int = 0

    # Cost simulation
    total_cost_usd: float = 0.0

    # Group tracking
    groups_total: int = 0
    groups_completed: int = 0

    # Worktree reuse and auto-approve tracking
    worktree_reuses: int = 0
    auto_approves: int = 0

    # Per-group wall times
    group_wall_times: list[float] = field(default_factory=list)

    @property
    def wall_clock_seconds(self) -> float:
        return self.wall_end - self.wall_start

    @property
    def sequential_estimate_seconds(self) -> float:
        return sum(self.coding_durations.values()) + sum(self.qa_durations.values())

    @property
    def speedup(self) -> float:
        seq = self.sequential_estimate_seconds
        if seq == 0:
            return 1.0
        return seq / max(self.wall_clock_seconds, 0.001)

    @property
    def utilisation_pct(self) -> float:
        wall = self.wall_clock_seconds
        if wall == 0:
            return 0.0
        return min(100.0, (self.agent_busy_seconds / wall) * 100.0)


# ---------------------------------------------------------------------------
# DAG generator
# ---------------------------------------------------------------------------

_FILE_POOL = [
    "src/auth.ts",
    "src/api.ts",
    "src/db.ts",
    "src/models.ts",
    "src/utils.ts",
    "src/config.ts",
    "src/logger.ts",
    "src/middleware.ts",
    "src/router.ts",
    "src/handlers.ts",
    "src/validators.ts",
    "src/cache.ts",
    "src/events.ts",
    "src/queue.ts",
    "src/storage.ts",
    "src/crypto.ts",
    "src/email.ts",
    "src/webhooks.ts",
    "src/search.ts",
    "src/analytics.ts",
    "tests/test_auth.ts",
    "tests/test_api.ts",
    "tests/test_db.ts",
    "tests/test_models.ts",
    "tests/test_utils.ts",
    "tests/test_integration.ts",
]


def generate_tickets(n: int, rng: random.Random) -> list[dict]:
    """Generate N mock tickets with a realistic dependency DAG.

    Strategy:
      - First ~20 % have no dependencies (foundational)
      - Middle ~60 % depend on 1-2 earlier tickets
      - Last ~20 % depend on 2-3 earlier tickets (integration)
      - Files are assigned from a pool; some intentional overlap
    """
    tickets: list[dict] = []
    available_files = list(_FILE_POOL)
    rng.shuffle(available_files)

    for i in range(n):
        ticket_key = f"SIM-{i + 1:03d}"
        position_pct = i / max(n - 1, 1)

        # Dependencies
        deps: list[str] = []
        if i > 0:
            if position_pct < 0.2:
                # Foundational: 0-1 deps
                if rng.random() < 0.3 and tickets:
                    deps = [rng.choice(tickets)["ticket_key"]]
            elif position_pct < 0.8:
                # Middle: 1-2 deps
                pool = [t["ticket_key"] for t in tickets]
                dep_count = rng.randint(1, min(2, len(pool)))
                deps = rng.sample(pool, dep_count)
            else:
                # Integration: 2-3 deps
                pool = [t["ticket_key"] for t in tickets]
                dep_count = rng.randint(2, min(3, len(pool)))
                deps = rng.sample(pool, dep_count)

        # File ownership (1-2 files, occasionally sharing)
        n_files = rng.choice([1, 1, 1, 2])
        if i < len(available_files):
            owned = [available_files[i % len(available_files)]]
        else:
            owned = [rng.choice(available_files)]

        if n_files > 1:
            extra = rng.choice(available_files)
            if extra not in owned:
                owned.append(extra)

        # Occasional intentional file overlap (10 % chance)
        if rng.random() < 0.1 and tickets:
            donor = rng.choice(tickets)
            donor_files = donor.get("files_owned", [])
            if donor_files:
                shared = rng.choice(donor_files)
                if shared not in owned:
                    owned.append(shared)

        tickets.append(
            {
                "ticket_key": ticket_key,
                "title": f"Implement {ticket_key}",
                "description": f"Auto-generated ticket {ticket_key}",
                "dependencies": deps,
                "files_owned": owned,
                "acceptance_criteria": [f"{ticket_key} passes unit tests"],
                "priority": rng.choice(["critical", "high", "medium"]),
                "story_points": rng.choice([1, 2, 3, 5, 8]),
            }
        )

    return tickets


def build_prd_board(tickets: list[dict]) -> dict:
    """Build a PRD board and optimise the execution order."""
    board = {
        "board_id": "SIM-BOARD",
        "tickets": tickets,
        "execution_order": [[t["ticket_key"]] for t in tickets],
    }
    board["execution_order"] = optimize_execution_order(board)
    return board


# ---------------------------------------------------------------------------
# Mock agents
# ---------------------------------------------------------------------------


async def mock_coding_agent(
    *,
    ticket: dict,
    worktree_path: str,
    branch_name: str,
    wm: WorktreeManager,
    rng: random.Random,
    metrics: SimMetrics,
    monitor: ConcurrencyMonitor,
) -> tuple[dict, float]:
    """Simulate a coding agent: create a file, sleep, commit."""
    tk = ticket["ticket_key"]
    await monitor.register_engineer(tk)

    t0 = time.monotonic()
    work_time = rng.uniform(1.0, 5.0)
    await asyncio.sleep(work_time)

    # Create files in the worktree
    for fp in ticket.get("files_owned", []):
        full = os.path.join(worktree_path, fp)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        rand_body = "".join(rng.choices(string.ascii_lowercase, k=60))
        with open(full, "w") as f:
            f.write(
                f"// {tk} — auto-generated\n"
                f"export function {tk.replace('-', '_').lower()}() {{\n"
                f"  return '{rand_body}'\n"
                f"}}\n"
            )

    await wm._run_git("-C", worktree_path, "add", "-A", cwd=worktree_path)
    await wm._run_git(
        "-C",
        worktree_path,
        "commit",
        "-m",
        f"Implement {tk}",
        cwd=worktree_path,
    )

    duration = time.monotonic() - t0
    metrics.coding_durations[tk] = duration
    metrics.agent_busy_seconds += duration

    cost = rng.uniform(0.02, 0.15)
    metrics.total_cost_usd += cost

    await monitor.unregister_engineer(tk, duration_seconds=duration)

    return (
        {
            "ticket_key": tk,
            "git_branch": branch_name,
            "files_created": ticket.get("files_owned", []),
            "files_modified": [],
        },
        cost,
    )


async def mock_qa_agent(
    *,
    ticket: dict,
    code_artifact: dict,
    attempt: int,
    failure_rate: float,
    rng: random.Random,
    metrics: SimMetrics,
    monitor: ConcurrencyMonitor,
) -> dict:
    """Simulate a QA review: sleep, then approve or request revision."""
    tk = ticket["ticket_key"]
    await monitor.register_qa(tk)

    t0 = time.monotonic()
    review_time = rng.uniform(0.5, 2.0)
    await asyncio.sleep(review_time)

    duration = time.monotonic() - t0
    metrics.qa_durations[tk] = metrics.qa_durations.get(tk, 0) + duration
    metrics.agent_busy_seconds += duration

    cost = rng.uniform(0.01, 0.05)
    metrics.total_cost_usd += cost

    await monitor.unregister_qa(tk)

    # First attempt: fail at the configured rate
    # Subsequent attempts: lower failure rate (agents learn)
    effective_rate = failure_rate / (attempt**1.5)
    if rng.random() < effective_rate:
        metrics.revision_counts[tk] = metrics.revision_counts.get(tk, 0) + 1
        metrics.total_revisions += 1
        # Decide if the issues are minor-only or include serious problems
        has_serious = rng.random() < 0.5
        severity = rng.choice(["error", "critical"]) if has_serious else "warning"
        return {
            "ticket_key": tk,
            "verdict": "needs_revision",
            "code_quality_score": rng.randint(3, 6),
            "revision_instructions": [f"Fix issue #{rng.randint(1, 99)} in {tk}"],
            "comments": [
                {
                    "comment": f"Issue in {tk}",
                    "severity": severity,
                    "file": rng.choice(ticket.get("files_owned", ["unknown"])),
                },
            ],
        }

    return {
        "ticket_key": tk,
        "verdict": "approved",
        "code_quality_score": rng.randint(7, 10),
        "revision_instructions": [],
        "comments": [],
    }


# ---------------------------------------------------------------------------
# Dashboard event emitter (optional Redis pub/sub)
# ---------------------------------------------------------------------------


class EventEmitter:
    """Emit pipeline events to Redis for live dashboard visualisation."""

    def __init__(self, pipeline_id: str, redis_url: str | None = None) -> None:
        self.pipeline_id = pipeline_id
        self._wm = None
        self._redis_url = redis_url

    async def connect(self) -> None:
        if self._redis_url:
            from memory.working_memory import WorkingMemory

            self._wm = WorkingMemory(self._redis_url)

    async def emit(self, event_type: str, **payload) -> None:
        if self._wm is None:
            return
        event = {
            "pipeline_id": self.pipeline_id,
            "event_type": event_type,
            "timestamp": datetime.now(UTC).isoformat(),
            "payload": payload,
        }
        try:
            await self._wm.publish_event(self.pipeline_id, event)
        except Exception:
            pass  # don't let event failures block simulation

    async def close(self) -> None:
        if self._wm is not None:
            await self._wm.close()


# ---------------------------------------------------------------------------
# Core simulation loop
# ---------------------------------------------------------------------------


async def run_simulation(args: argparse.Namespace) -> SimMetrics:
    """Run the full swarm simulation."""
    rng = random.Random(args.seed)
    metrics = SimMetrics()
    pipeline_id = f"sim-{int(time.time())}"

    # Dashboard events
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    emitter = EventEmitter(
        pipeline_id,
        redis_url=redis_url if args.with_dashboard else None,
    )
    await emitter.connect()

    # Concurrency monitor
    monitor = ConcurrencyMonitor(
        pipeline_id,
        config=ConcurrencyConfig(
            max_concurrent_engineers=args.max_parallel,
            max_concurrent_qa=max(2, args.max_parallel // 2),
            max_retries_per_ticket=3,
        ),
    )

    # Generate tickets and build execution order
    print(f"\n{'=' * 70}")
    print("  FORGE SWARM SIMULATION")
    print(
        f"  Tickets: {args.tickets}  |  Max parallel: {args.max_parallel}"
        f"  |  Failure rate: {args.failure_rate:.0%}"
    )
    if args.seed is not None:
        print(f"  Seed: {args.seed}")
    print(f"{'=' * 70}\n")

    print("[1/6] Generating ticket DAG...")
    tickets = generate_tickets(args.tickets, rng)
    prd_board = build_prd_board(tickets)
    execution_order = prd_board["execution_order"]
    metrics.tickets_total = len(tickets)
    metrics.groups_total = len(execution_order)

    print(f"      {len(tickets)} tickets in {len(execution_order)} groups")
    for i, group in enumerate(execution_order):
        print(f"      Group {i}: {group}")

    # Validate
    print("\n[2/6] Validating execution order...")
    errors = validate_execution_order(prd_board)
    if errors:
        print(f"      {len(errors)} validation errors (auto-fixed)")
        for e in errors[:5]:
            print(f"        - {e}")
    else:
        print("      Validation passed")

    # Detect file ownership conflicts
    conflicts = detect_file_ownership_conflicts(tickets)
    if conflicts:
        print(f"      {len(conflicts)} file ownership conflict(s) detected")
        for c in conflicts[:5]:
            print(f"        - {c['file_path']}: {c['ticket_ids']}")

    # Setup temp git repo
    print("\n[3/6] Setting up git repository...")
    base_dir = tempfile.mkdtemp(prefix="forge-sim-")
    repo_path = os.path.join(base_dir, "project")
    wt_dir = os.path.join(base_dir, "worktrees")
    wm = WorktreeManager(repo_path, worktrees_dir=wt_dir)

    file_structure = {}
    for t in tickets:
        for fp in t.get("files_owned", []):
            file_structure[fp] = {"description": f"Owned by {t['ticket_key']}"}
    await wm.setup_repo({"file_structure": file_structure})
    await wm._run_git("config", "user.email", "sim@forge.dev")
    await wm._run_git("config", "user.name", "Forge Simulator")
    print(f"      Repo at {repo_path}")

    await emitter.emit("pipeline_started", tickets=len(tickets), groups=len(execution_order))

    # Execute groups
    print(f"\n[4/6] Executing {len(execution_order)} groups...\n")
    metrics.wall_start = time.monotonic()
    tickets_by_key = {t["ticket_key"]: t for t in tickets}

    for group_idx, group in enumerate(execution_order):
        group_start = time.monotonic()
        group_tickets = [tickets_by_key[tk] for tk in group]
        n = len(group_tickets)

        await monitor.register_group(group_idx, len(execution_order), n)
        await emitter.emit("group_started", group_index=group_idx, tickets=group)

        print(f"  --- Group {group_idx} ({n} ticket{'s' if n != 1 else ''}) ---")

        # Phase 1: Parallel coding
        coding_results: dict[str, CodingTaskResult] = {}
        semaphore = asyncio.Semaphore(args.max_parallel)

        async def code_ticket(ticket: dict) -> CodingTaskResult:
            tk = ticket["ticket_key"]
            branch = f"forge/{tk}"
            async with semaphore:
                # Backpressure check
                while not await monitor.should_spawn_agent("engineer"):
                    await asyncio.sleep(0.5)

                try:
                    wt_path = await wm.create_worktree(tk, branch)
                except Exception as exc:
                    return CodingTaskResult(
                        ticket_id=tk,
                        success=False,
                        error=str(exc),
                    )

                try:
                    artifact, cost = await mock_coding_agent(
                        ticket=ticket,
                        worktree_path=wt_path,
                        branch_name=branch,
                        wm=wm,
                        rng=rng,
                        metrics=metrics,
                        monitor=monitor,
                    )
                    await emitter.emit(
                        "ticket_status_changed",
                        ticket_key=tk,
                        status="coded",
                    )
                    return CodingTaskResult(
                        ticket_id=tk,
                        success=True,
                        code_artifact=artifact,
                        cost_usd=cost,
                    )
                except Exception as exc:
                    return CodingTaskResult(
                        ticket_id=tk,
                        success=False,
                        error=str(exc),
                    )

        tasks = [asyncio.create_task(code_ticket(t)) for t in group_tickets]
        results = await asyncio.gather(*tasks)

        for r in results:
            coding_results[r.ticket_id] = r
            print(
                f"    {r.ticket_id}: coding {'OK' if r.success else 'FAIL'}"
                f"  ({metrics.coding_durations.get(r.ticket_id, 0):.1f}s)"
            )

        # Phase 2: QA review with revision loop
        max_revisions = 3
        for r in results:
            if not r.success:
                metrics.tickets_failed += 1
                continue

            tk = r.ticket_id
            ticket = tickets_by_key[tk]
            attempt = 1
            approved = False

            while attempt <= max_revisions + 1:
                qa_result = await mock_qa_agent(
                    ticket=ticket,
                    code_artifact=r.code_artifact or {},
                    attempt=attempt,
                    failure_rate=args.failure_rate,
                    rng=rng,
                    metrics=metrics,
                    monitor=monitor,
                )

                verdict = qa_result["verdict"]
                score = qa_result["code_quality_score"]
                await emitter.emit(
                    "qa_verdict",
                    ticket_key=tk,
                    verdict=verdict,
                    score=score,
                    attempt=attempt,
                )

                if verdict == "approved":
                    approved = True
                    print(f"    {tk}: QA approved (score={score}, attempt={attempt})")
                    break

                # Auto-approve if all comments are minor (no error/critical)
                comments = qa_result.get("comments", [])
                has_serious = any(
                    c.get("severity") in ("error", "critical")
                    for c in comments
                    if isinstance(c, dict)
                )
                if not has_serious and comments:
                    approved = True
                    metrics.auto_approves += 1
                    print(f"    {tk}: QA auto-approved (minor only, attempt={attempt})")
                    break

                print(f"    {tk}: QA revision requested (score={score}, attempt={attempt})")
                attempt += 1

                # Simulate revision coding with worktree reuse
                if attempt <= max_revisions + 1:
                    rev_branch = f"forge/{tk}/rev-{attempt}"
                    try:
                        await wm.reset_worktree(tk, rev_branch)
                        metrics.worktree_reuses += 1
                    except Exception:
                        pass  # fall through — coding still simulated
                    rev_time = rng.uniform(0.5, 2.0)
                    await asyncio.sleep(rev_time)
                    metrics.agent_busy_seconds += rev_time
                    metrics.total_cost_usd += rng.uniform(0.01, 0.05)

            if approved:
                metrics.tickets_completed += 1
            else:
                metrics.tickets_failed += 1
                print(f"    {tk}: FAILED after {max_revisions} revision attempts")

        # Phase 3: Merge
        successful = [r for r in results if r.success and r.code_artifact]

        merged_count = 0
        conflict_in_group = 0

        for r in successful:
            branch = r.code_artifact.get("git_branch", "")  # type: ignore[union-attr]
            if not branch:
                continue

            merge_result = await wm.merge_worktree(r.ticket_id, branch)
            if merge_result["success"]:
                merged_count += 1
                await emitter.emit(
                    "ticket_status_changed",
                    ticket_key=r.ticket_id,
                    status="merged",
                )
            else:
                conflict_in_group += 1
                metrics.conflicts_detected += 1

                # Attempt auto-resolve for trivial conflicts
                if rng.random() < 0.6:
                    metrics.conflicts_auto_resolved += 1
                    print(f"    {r.ticket_id}: merge conflict → auto-resolved")
                    await emitter.emit(
                        "ticket_status_changed",
                        ticket_key=r.ticket_id,
                        status="conflict_resolved",
                    )
                else:
                    metrics.conflicts_escalated += 1
                    metrics.tickets_failed += 1
                    metrics.tickets_completed = max(0, metrics.tickets_completed - 1)
                    print(f"    {r.ticket_id}: merge conflict → escalated")
                    await emitter.emit(
                        "ticket_status_changed",
                        ticket_key=r.ticket_id,
                        status="conflict_escalated",
                    )

        group_elapsed = time.monotonic() - group_start
        metrics.group_wall_times.append(group_elapsed)
        metrics.groups_completed += 1

        await monitor.unregister_group(group_idx)
        await emitter.emit(
            "group_completed",
            group_index=group_idx,
            merged=merged_count,
            conflicts=conflict_in_group,
            elapsed=round(group_elapsed, 2),
        )

        print(
            f"    Group {group_idx} done: "
            f"{merged_count} merged, {conflict_in_group} conflicts "
            f"({group_elapsed:.1f}s)\n"
        )

    metrics.wall_end = time.monotonic()

    await emitter.emit(
        "pipeline_completed",
        wall_clock=round(metrics.wall_clock_seconds, 2),
        tickets_completed=metrics.tickets_completed,
    )

    # Cleanup
    print("[5/6] Cleaning up...")
    await wm.cleanup_all()
    shutil.rmtree(base_dir, ignore_errors=True)
    await emitter.close()

    # Report
    print("\n[6/6] Simulation complete.\n")
    print_report(metrics, args)

    return metrics


# ---------------------------------------------------------------------------
# Report printer
# ---------------------------------------------------------------------------


def print_report(m: SimMetrics, args: argparse.Namespace) -> None:
    """Print the final summary report."""
    w = 70
    print(f"{'=' * w}")
    print("  SIMULATION REPORT")
    print(f"{'=' * w}")

    # Timing
    print("\n  Timing")
    print(f"  {'─' * (w - 4)}")
    print(f"  Wall clock time:        {m.wall_clock_seconds:>8.1f}s")
    print(f"  Sequential estimate:    {m.sequential_estimate_seconds:>8.1f}s")
    print(f"  Parallelism speedup:    {m.speedup:>8.2f}x")

    # Utilisation
    print("\n  Agent Utilisation")
    print(f"  {'─' * (w - 4)}")
    print(f"  Max parallel slots:     {args.max_parallel:>8d}")
    print(f"  Total agent-seconds:    {m.agent_busy_seconds:>8.1f}s")
    print(f"  Utilisation:            {m.utilisation_pct:>7.1f}%")

    # Tickets
    print("\n  Tickets")
    print(f"  {'─' * (w - 4)}")
    print(f"  Total:                  {m.tickets_total:>8d}")
    print(f"  Completed:              {m.tickets_completed:>8d}")
    print(f"  Failed:                 {m.tickets_failed:>8d}")
    skipped = m.tickets_total - m.tickets_completed - m.tickets_failed
    if skipped > 0:
        print(f"  Skipped:                {skipped:>8d}")

    # Merge conflicts
    print("\n  Merge Conflicts")
    print(f"  {'─' * (w - 4)}")
    print(f"  Detected:               {m.conflicts_detected:>8d}")
    print(f"  Auto-resolved:          {m.conflicts_auto_resolved:>8d}")
    print(f"  Escalated:              {m.conflicts_escalated:>8d}")

    # Performance optimisations
    print("\n  Performance")
    print(f"  {'─' * (w - 4)}")
    print(f"  Worktree reuses:        {m.worktree_reuses:>8d}")
    print(f"  QA auto-approves:       {m.auto_approves:>8d}")

    # Revisions
    print("\n  QA Revision Cycles")
    print(f"  {'─' * (w - 4)}")
    print(f"  Total revisions:        {m.total_revisions:>8d}")
    if m.revision_counts:
        max_rev_tk = max(m.revision_counts, key=m.revision_counts.get)  # type: ignore[arg-type]
        print(f"  Max revisions (ticket): {m.revision_counts[max_rev_tk]:>8d}  ({max_rev_tk})")
        tickets_with_rev = sum(1 for v in m.revision_counts.values() if v > 0)
        print(
            f"  Tickets needing revision: {tickets_with_rev:>6d}"
            f"  ({tickets_with_rev / max(m.tickets_total, 1):.0%})"
        )

    # Groups
    print("\n  Execution Groups")
    print(f"  {'─' * (w - 4)}")
    print(f"  Total groups:           {m.groups_total:>8d}")
    print(f"  Completed:              {m.groups_completed:>8d}")
    if m.group_wall_times:
        avg_group = sum(m.group_wall_times) / len(m.group_wall_times)
        print(f"  Avg group time:         {avg_group:>8.1f}s")
        print(f"  Longest group:          {max(m.group_wall_times):>8.1f}s")
        print(f"  Shortest group:         {min(m.group_wall_times):>8.1f}s")

    # Cost
    print("\n  Simulated Cost")
    print(f"  {'─' * (w - 4)}")
    print(f"  Total:                  ${m.total_cost_usd:>7.4f}")
    if m.tickets_completed > 0:
        per_ticket = m.total_cost_usd / m.tickets_completed
        print(f"  Per ticket (completed): ${per_ticket:>7.4f}")

    print(f"\n{'=' * w}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the swarm simulation."""
    parser = argparse.ArgumentParser(
        description="Forge swarm stress-test / load simulation",
    )
    parser.add_argument(
        "--tickets",
        "-n",
        type=int,
        default=20,
        help="Number of tickets to simulate (default: 20)",
    )
    parser.add_argument(
        "--max-parallel",
        "-p",
        type=int,
        default=4,
        help="Maximum concurrent coding agents (default: 4)",
    )
    parser.add_argument(
        "--failure-rate",
        "-f",
        type=float,
        default=0.1,
        help="QA first-pass failure rate 0.0-1.0 (default: 0.1)",
    )
    parser.add_argument(
        "--seed",
        "-s",
        type=int,
        default=None,
        help="Random seed for reproducible runs",
    )
    parser.add_argument(
        "--with-dashboard",
        action="store_true",
        help="Emit events to Redis for live dashboard visualisation",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point for the swarm simulation script."""
    args = parse_args()
    try:
        asyncio.run(run_simulation(args))
    except KeyboardInterrupt:
        print("\n\nSimulation interrupted.")
        sys.exit(1)


if __name__ == "__main__":
    main()
