"""Conflict resolver — analyses and resolves merge conflicts between coding agents.

When the swarm coordinator detects that two ticket branches modify the same
files, this module classifies the conflict severity and routes it to the
appropriate resolution strategy:

- **trivial** — barrel/index file additions → take the union automatically
- **moderate** — overlapping logic in the same function → LLM-assisted rewrite
- **severe** — fundamental design disagreement → CTO intervention

Usage::

    from agents.conflict_resolver import analyze_conflict, resolve_conflict

    analysis = await analyze_conflict(conflict_report, tech_spec)
    resolution = await resolve_conflict(analysis, conflict_report, ...)
"""

from __future__ import annotations

import asyncio
import json
import os

import structlog

from agents.worktree_manager import WorktreeError, WorktreeManager
from config.agent_config import _PRICING, SONNET_4_5, get_anthropic_client

log = structlog.get_logger().bind(component="conflict_resolver")


def _write_file(path: str, content: str) -> None:
    """Write content to a file (sync helper for asyncio.to_thread)."""
    with open(path, "w") as f:
        f.write(content)


# ---------------------------------------------------------------------------
# Patterns used for severity classification
# ---------------------------------------------------------------------------

# Files that are typically barrel/index files where additions can be unioned
_BARREL_PATTERNS: tuple[str, ...] = (
    "__init__.py",
    "index.ts",
    "index.js",
    "index.tsx",
    "mod.rs",
    "exports.py",
    "__all__",
)

# File path fragments that suggest auto-generated or aggregate content
_AGGREGATE_PATTERNS: tuple[str, ...] = (
    "requirements.txt",
    "package.json",
    "pyproject.toml",
    "Cargo.toml",
    "go.sum",
    ".gitignore",
)


# ---------------------------------------------------------------------------
# analyze_conflict
# ---------------------------------------------------------------------------


async def analyze_conflict(
    conflict_report: dict,
    tech_spec: dict,
) -> dict:
    """Classify a merge conflict and recommend a resolution strategy.

    Parameters
    ----------
    conflict_report:
        From ``SwarmCoordinator.pre_merge_conflict_check``::

            {
                "ticket_a": str,
                "ticket_b": str,
                "conflicting_files": [str, ...],
                "conflict_details": str,
            }

    tech_spec:
        The architecture tech spec for file-ownership context.

    Returns
    -------
    dict
        Analysis with keys: ``severity``, ``strategy``, ``affected_files``,
        ``rationale``, and the original ``conflict_report``.
    """
    files = conflict_report.get("conflicting_files", [])
    details = conflict_report.get("conflict_details", "")
    ticket_a = conflict_report.get("ticket_a", "?")
    ticket_b = conflict_report.get("ticket_b", "?")

    clog = log.bind(ticket_a=ticket_a, ticket_b=ticket_b, files=files)

    if not files:
        clog.info("no conflicting files — treating as trivial")
        return {
            "severity": "trivial",
            "strategy": "auto_resolve",
            "affected_files": [],
            "rationale": "No conflicting files identified in merge-tree output.",
            "conflict_report": conflict_report,
        }

    # Classify each file
    trivial_files: list[str] = []
    non_trivial_files: list[str] = []

    file_structure = tech_spec.get("file_structure", {})

    for f in files:
        basename = os.path.basename(f)

        is_barrel = any(pat in basename for pat in _BARREL_PATTERNS)
        is_aggregate = any(pat in f for pat in _AGGREGATE_PATTERNS)

        if is_barrel or is_aggregate:
            trivial_files.append(f)
        else:
            non_trivial_files.append(f)

    # Determine severity
    if not non_trivial_files:
        severity = "trivial"
        strategy = "auto_resolve"
        rationale = (
            f"All {len(trivial_files)} conflicting file(s) are barrel/index "
            f"or aggregate files — both sets of additions should be kept."
        )

    elif _is_same_function_conflict(details):
        severity = "moderate"
        strategy = "llm_rewrite"
        rationale = (
            f"{len(non_trivial_files)} file(s) have overlapping changes in "
            f"the same functions. An LLM rewrite can merge both intents."
        )

    elif _is_design_conflict(non_trivial_files, file_structure):
        severity = "severe"
        strategy = "cto_escalation"
        rationale = (
            f"{len(non_trivial_files)} file(s) suggest a fundamental design "
            f"conflict — different tickets are reshaping the same core "
            f"abstractions. CTO should arbitrate."
        )

    else:
        # Default: if there are non-trivial conflicts, call it moderate
        severity = "moderate"
        strategy = "llm_rewrite"
        rationale = (
            f"{len(non_trivial_files)} file(s) have overlapping changes. "
            f"LLM rewrite recommended to merge both contributions."
        )

    clog.info(
        "conflict analysed",
        severity=severity,
        strategy=strategy,
        trivial_files=len(trivial_files),
        non_trivial_files=len(non_trivial_files),
    )

    return {
        "severity": severity,
        "strategy": strategy,
        "affected_files": files,
        "trivial_files": trivial_files,
        "non_trivial_files": non_trivial_files,
        "rationale": rationale,
        "conflict_report": conflict_report,
    }


# ---------------------------------------------------------------------------
# auto_resolve_trivial
# ---------------------------------------------------------------------------


async def auto_resolve_trivial(
    worktree_manager: WorktreeManager,
    ticket_a_id: str,
    ticket_b_id: str,
    branch_a: str,
    branch_b: str,
    conflict_files: list[str],
) -> bool:
    """Attempt automatic resolution for trivial conflicts.

    For barrel/index files where both tickets add new exports/imports,
    take the union of both changes.  Performs a real merge in the base
    repo, resolves the listed files by concatenating unique additions,
    then commits the merge.

    Returns True if all files were resolved and the merge committed.
    """
    clog = log.bind(
        ticket_a=ticket_a_id,
        ticket_b=ticket_b_id,
        files=conflict_files,
    )

    wm = worktree_manager

    # Start the merge so we get conflict markers in the working tree
    try:
        await wm._run_git("merge", "--no-ff", branch_b, "-m", f"Merge {branch_b}")
        # If this succeeds, there was no actual conflict at merge time
        clog.info("merge succeeded without conflict — no resolution needed")
        return True
    except WorktreeError:
        # Expected: merge fails due to conflicts
        pass

    all_resolved = True
    for filepath in conflict_files:
        full_path = os.path.join(wm.base_project_path, filepath)

        if not os.path.exists(full_path):
            clog.warning("conflicting file not found in worktree", file=filepath)
            all_resolved = False
            continue

        try:
            resolved_content = await asyncio.to_thread(_resolve_barrel_file, full_path)
            if resolved_content is not None:
                await asyncio.to_thread(_write_file, full_path, resolved_content)
                await wm._run_git("add", filepath)
                clog.info("auto-resolved file", file=filepath)
            else:
                clog.warning("could not auto-resolve file", file=filepath)
                all_resolved = False
        except Exception as exc:
            clog.warning("auto-resolve error", file=filepath, error=str(exc))
            all_resolved = False

    if all_resolved:
        try:
            await wm._run_git(
                "commit",
                "--no-edit",
                "-m",
                f"Auto-resolve trivial conflicts: {', '.join(conflict_files)}",
            )
            clog.info("auto-resolve merge committed")
            return True
        except WorktreeError as exc:
            clog.error("commit after auto-resolve failed", error=str(exc))

    # Abort the failed merge
    try:
        await wm._run_git("merge", "--abort")
    except WorktreeError:
        pass

    return False


# ---------------------------------------------------------------------------
# resolve_via_rewrite
# ---------------------------------------------------------------------------


async def resolve_via_rewrite(
    ticket_a: dict,
    ticket_b: dict,
    conflict_files: list[str],
    tech_spec_context: dict,
    worktree_manager: WorktreeManager,
    branch_a: str,
    branch_b: str,
) -> dict:
    """Use an LLM to rewrite conflicting files to satisfy both tickets.

    Reads both versions of each conflicting file, asks the LLM to produce
    a merged version that satisfies both tickets' acceptance criteria,
    then writes the result to branch_a's worktree and commits.

    Returns::

        {
            "success": bool,
            "resolved_files": [str, ...],
            "failed_files": [str, ...],
            "cost_usd": float,
            "target_branch": str,
        }
    """
    clog = log.bind(
        ticket_a=ticket_a.get("ticket_key", "?"),
        ticket_b=ticket_b.get("ticket_key", "?"),
        files=conflict_files,
    )

    wm = worktree_manager
    ticket_a_id = ticket_a.get("ticket_key", "unknown-a")
    ticket_b_id = ticket_b.get("ticket_key", "unknown-b")

    resolved_files: list[str] = []
    failed_files: list[str] = []
    total_cost = 0.0

    for filepath in conflict_files:
        clog.info("resolving file via LLM rewrite", file=filepath)

        # Read both versions
        version_a = await _read_file_from_branch(wm, branch_a, filepath)
        version_b = await _read_file_from_branch(wm, branch_b, filepath)

        if version_a is None and version_b is None:
            clog.warning("neither branch has the file", file=filepath)
            failed_files.append(filepath)
            continue

        # Ask LLM to merge
        merged_content, cost = await _llm_merge_files(
            filepath=filepath,
            version_a=version_a or "",
            version_b=version_b or "",
            ticket_a=ticket_a,
            ticket_b=ticket_b,
            tech_spec_context=tech_spec_context,
        )
        total_cost += cost

        if merged_content is not None:
            resolved_files.append(filepath)
            clog.info("file resolved via LLM", file=filepath)
        else:
            failed_files.append(filepath)
            clog.warning("LLM merge failed for file", file=filepath)

    # If we resolved all files, apply to branch_a's worktree and commit
    success = len(failed_files) == 0 and len(resolved_files) > 0

    if success:
        wt_path = os.path.join(wm.worktrees_dir, ticket_a_id)
        if os.path.isdir(wt_path):
            for filepath in resolved_files:
                full = os.path.join(wt_path, filepath)
                os.makedirs(os.path.dirname(full), exist_ok=True)
                # Re-run merge to get the merged content
                version_a = await _read_file_from_branch(wm, branch_a, filepath)
                version_b = await _read_file_from_branch(wm, branch_b, filepath)
                merged, _ = await _llm_merge_files(
                    filepath=filepath,
                    version_a=version_a or "",
                    version_b=version_b or "",
                    ticket_a=ticket_a,
                    ticket_b=ticket_b,
                    tech_spec_context=tech_spec_context,
                )
                if merged:
                    await asyncio.to_thread(_write_file, full, merged)

            try:
                await wm._run_git("-C", wt_path, "add", "-A", cwd=wt_path)
                await wm._run_git(
                    "-C",
                    wt_path,
                    "commit",
                    "-m",
                    f"Resolve conflicts with {ticket_b_id}",
                    cwd=wt_path,
                )
                clog.info("rewrite committed to branch", branch=branch_a)
            except WorktreeError as exc:
                clog.error("commit after rewrite failed", error=str(exc))
                success = False

    result = {
        "success": success,
        "resolved_files": resolved_files,
        "failed_files": failed_files,
        "cost_usd": total_cost,
        "target_branch": branch_a,
    }
    clog.info("rewrite resolution complete", **result)
    return result


# ---------------------------------------------------------------------------
# escalate_to_cto
# ---------------------------------------------------------------------------


async def escalate_to_cto(
    conflict_report: dict,
    analysis: dict,
    pipeline_state: dict,
) -> dict:
    """Escalate a severe conflict to the CTO agent for arbitration.

    The CTO decides: reorder tickets (make sequential), modify one
    ticket's approach, or accept one and reject the other.

    Returns::

        {
            "decision": dict | None,
            "cost_usd": float,
            "action": str,  # "reorder" | "modify" | "accept_reject" | "failed"
        }
    """
    clog = log.bind(
        ticket_a=conflict_report.get("ticket_a"),
        ticket_b=conflict_report.get("ticket_b"),
    )
    clog.info("escalating conflict to CTO agent")

    from agents.cto_agent import run_cto_agent

    trigger_description = (
        f"Merge conflict between tickets {conflict_report.get('ticket_a')} "
        f"and {conflict_report.get('ticket_b')}.\n"
        f"Conflicting files: {', '.join(conflict_report.get('conflicting_files', []))}\n"
        f"Severity: {analysis.get('severity', 'unknown')}\n"
        f"Analysis: {analysis.get('rationale', 'N/A')}\n"
        f"Conflict details:\n{conflict_report.get('conflict_details', '')[:500]}"
    )

    context = {
        "conflict_report": conflict_report,
        "analysis": analysis,
        "resolution_options": [
            "reorder: Make the conflicting tickets execute sequentially instead of in parallel",
            "modify: Change one ticket's implementation approach to avoid the conflict",
            "accept_reject: Accept one ticket's changes and reject the other",
        ],
    }

    decision, cost = await run_cto_agent(
        trigger_type="conflict_resolution",
        trigger_description=trigger_description,
        pipeline_state=pipeline_state,
        context=context,
    )

    if decision is None:
        clog.error("CTO agent failed to produce a decision")
        return {"decision": None, "cost_usd": cost, "action": "failed"}

    # Parse the CTO's recommended action
    action = _extract_cto_action(decision)

    clog.info(
        "CTO decision received",
        action=action,
        decision_summary=decision.get("decision", "")[:100],
    )

    return {
        "decision": decision,
        "cost_usd": cost,
        "action": action,
    }


# ---------------------------------------------------------------------------
# Top-level dispatcher
# ---------------------------------------------------------------------------


async def resolve_conflict(
    analysis: dict,
    conflict_report: dict,
    *,
    worktree_manager: WorktreeManager,
    tickets_by_id: dict[str, dict],
    tech_spec_context: dict,
    pipeline_state: dict | None = None,
) -> dict:
    """Route a conflict to the appropriate resolution strategy.

    Parameters
    ----------
    analysis:
        From ``analyze_conflict``.
    conflict_report:
        Original conflict report.
    worktree_manager:
        For git operations.
    tickets_by_id:
        Mapping of ticket_id → ticket dict.
    tech_spec_context:
        Architecture context for LLM calls.
    pipeline_state:
        Current pipeline state (needed for CTO escalation).

    Returns
    -------
    dict
        Resolution result with ``strategy``, ``success``, and
        strategy-specific fields.
    """
    strategy = analysis.get("strategy", "cto_escalation")
    ticket_a_id = conflict_report.get("ticket_a", "")
    ticket_b_id = conflict_report.get("ticket_b", "")

    clog = log.bind(
        strategy=strategy,
        ticket_a=ticket_a_id,
        ticket_b=ticket_b_id,
    )

    if strategy == "auto_resolve":
        clog.info("attempting auto-resolve")

        # Get branch names from tickets
        ticket_a = tickets_by_id.get(ticket_a_id, {})
        ticket_b = tickets_by_id.get(ticket_b_id, {})
        branch_a = ticket_a.get("branch_name", f"forge/{ticket_a_id}")
        branch_b = ticket_b.get("branch_name", f"forge/{ticket_b_id}")

        success = await auto_resolve_trivial(
            worktree_manager=worktree_manager,
            ticket_a_id=ticket_a_id,
            ticket_b_id=ticket_b_id,
            branch_a=branch_a,
            branch_b=branch_b,
            conflict_files=analysis.get("trivial_files", []),
        )

        return {
            "strategy": "auto_resolve",
            "success": success,
            "cost_usd": 0.0,
        }

    if strategy == "llm_rewrite":
        clog.info("attempting LLM rewrite resolution")

        ticket_a = tickets_by_id.get(ticket_a_id, {})
        ticket_b = tickets_by_id.get(ticket_b_id, {})
        branch_a = ticket_a.get("branch_name", f"forge/{ticket_a_id}")
        branch_b = ticket_b.get("branch_name", f"forge/{ticket_b_id}")

        result = await resolve_via_rewrite(
            ticket_a=ticket_a,
            ticket_b=ticket_b,
            conflict_files=analysis.get("non_trivial_files", []),
            tech_spec_context=tech_spec_context,
            worktree_manager=worktree_manager,
            branch_a=branch_a,
            branch_b=branch_b,
        )

        return {
            "strategy": "llm_rewrite",
            **result,
        }

    # Default: CTO escalation
    clog.info("escalating to CTO")
    result = await escalate_to_cto(
        conflict_report=conflict_report,
        analysis=analysis,
        pipeline_state=pipeline_state or {},
    )

    return {
        "strategy": "cto_escalation",
        "success": result.get("action") != "failed",
        **result,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_same_function_conflict(details: str) -> bool:
    """Heuristic: does the merge-tree output suggest overlapping function edits?"""
    # Look for patterns suggesting the same code region was edited
    indicators = [
        "changed in both",
        "content conflict",
        "modify/modify",
    ]
    details_lower = details.lower()
    return any(indicator in details_lower for indicator in indicators)


def _is_design_conflict(
    non_trivial_files: list[str],
    file_structure: dict,
) -> bool:
    """Heuristic: are the conflicting files core architectural components?"""
    core_indicators = (
        "config",
        "schema",
        "model",
        "types",
        "interface",
        "abstract",
        "base",
        "core",
        "main",
        "app",
    )

    core_count = 0
    for f in non_trivial_files:
        basename = os.path.basename(f).lower()
        name_without_ext = os.path.splitext(basename)[0]
        if any(indicator in name_without_ext for indicator in core_indicators):
            core_count += 1

    # If more than half the conflicting files are core files, it's a design conflict
    return core_count > len(non_trivial_files) / 2 and len(non_trivial_files) >= 2


def _resolve_barrel_file(filepath: str) -> str | None:
    """Resolve a barrel/index file by taking the union of both sides.

    Reads the file with conflict markers, extracts both sides, and
    produces a merged version containing all unique lines from both.
    Returns None if the file doesn't contain recognisable conflict markers.
    """
    with open(filepath) as f:
        content = f.read()

    if "<<<<<<<" not in content:
        return None

    # Parse conflict markers
    resolved_lines: list[str] = []
    seen_lines: set[str] = set()
    in_ours = False
    in_theirs = False

    for line in content.splitlines():
        if line.startswith("<<<<<<<"):
            in_ours = True
            continue
        if line.startswith("======="):
            in_ours = False
            in_theirs = True
            continue
        if line.startswith(">>>>>>>"):
            in_theirs = False
            continue

        if in_ours or in_theirs:
            # Keep unique lines from both sides
            stripped = line.rstrip()
            if stripped and stripped not in seen_lines:
                seen_lines.add(stripped)
                resolved_lines.append(line)
        else:
            # Lines outside conflict markers are kept as-is
            resolved_lines.append(line)

    return "\n".join(resolved_lines) + "\n"


async def _read_file_from_branch(
    wm: WorktreeManager,
    branch: str,
    filepath: str,
) -> str | None:
    """Read a file's content from a specific git branch."""
    try:
        content, _ = await wm._run_git("show", f"{branch}:{filepath}")
        return content
    except WorktreeError:
        return None


async def _llm_merge_files(
    filepath: str,
    version_a: str,
    version_b: str,
    ticket_a: dict,
    ticket_b: dict,
    tech_spec_context: dict,
) -> tuple[str | None, float]:
    """Ask the LLM to produce a merged version of a conflicting file.

    Returns (merged_content or None, cost_usd).
    """
    import importlib.util

    if importlib.util.find_spec("anthropic") is None:
        log.error("anthropic package not installed")
        return None, 0.0

    system = (
        "You are a senior software engineer resolving a merge conflict. "
        "Two developers working on different tickets have modified the same file. "
        "Your job is to produce a single merged version that:\n"
        "1. Preserves ALL functionality from both versions\n"
        "2. Satisfies both tickets' acceptance criteria\n"
        "3. Resolves any naming or structural conflicts cleanly\n"
        "4. Maintains consistent code style\n\n"
        "Return ONLY the merged file content. No markdown fences, no commentary."
    )

    ticket_a_summary = (
        f"Ticket {ticket_a.get('ticket_key', '?')}: "
        f"{ticket_a.get('title', 'N/A')}\n"
        f"Acceptance criteria: "
        f"{json.dumps(ticket_a.get('acceptance_criteria', []))}"
    )

    ticket_b_summary = (
        f"Ticket {ticket_b.get('ticket_key', '?')}: "
        f"{ticket_b.get('title', 'N/A')}\n"
        f"Acceptance criteria: "
        f"{json.dumps(ticket_b.get('acceptance_criteria', []))}"
    )

    human = (
        f"File: {filepath}\n\n"
        f"--- VERSION A ({ticket_a.get('ticket_key', 'A')}) ---\n"
        f"{version_a}\n\n"
        f"--- VERSION B ({ticket_b.get('ticket_key', 'B')}) ---\n"
        f"{version_b}\n\n"
        f"--- TICKET A CONTEXT ---\n{ticket_a_summary}\n\n"
        f"--- TICKET B CONTEXT ---\n{ticket_b_summary}\n\n"
        "Produce the merged file content that satisfies both tickets."
    )

    try:
        client = get_anthropic_client()
        response = await asyncio.wait_for(
            client.messages.create(
                model=SONNET_4_5,
                max_tokens=16384,
                system=system,
                messages=[{"role": "user", "content": human}],
            ),
            timeout=120.0,
        )
    except Exception as exc:
        log.error("LLM merge call failed", file=filepath, error=str(exc))
        return None, 0.0

    # Calculate cost
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    input_rate, output_rate = _PRICING.get(SONNET_4_5, (3.0, 15.0))
    cost = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000

    # Extract text
    merged = ""
    for block in response.content:
        if block.type == "text":
            merged += block.text

    # Strip markdown fences if present
    merged = merged.strip()
    if merged.startswith("```"):
        first_nl = merged.find("\n")
        if first_nl > 0:
            merged = merged[first_nl + 1 :]
    if merged.endswith("```"):
        merged = merged[:-3].rstrip()

    return merged + "\n", cost


def _extract_cto_action(decision: dict) -> str:
    """Parse the CTO decision to determine the recommended action."""
    decision_text = (
        decision.get("decision", "")
        + " "
        + decision.get("rationale", "")
        + " "
        + json.dumps(decision.get("action_items", []))
    ).lower()

    if any(w in decision_text for w in ("reorder", "sequential", "serialize")):
        return "reorder"
    if any(w in decision_text for w in ("modify", "rewrite", "change approach", "refactor")):
        return "modify"
    if any(w in decision_text for w in ("accept", "reject", "prefer", "discard", "drop")):
        return "accept_reject"

    # Check pipeline_action field
    action = decision.get("pipeline_action", "")
    if action == "retry_ticket":
        return "modify"

    return "modify"  # safe default


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------


async def _main() -> None:
    """End-to-end smoke test: create conflicting worktrees, analyse, and
    auto-resolve a trivial barrel-file conflict.
    """
    import shutil
    import tempfile

    print("=== ConflictResolver smoke test ===\n")

    base = tempfile.mkdtemp(prefix="forge-conflict-test-")
    repo_path = os.path.join(base, "project")
    wt_dir = os.path.join(base, "worktrees")

    wm = WorktreeManager(repo_path, worktrees_dir=wt_dir)

    # 1. Setup repo with a barrel file
    tech_spec = {
        "file_structure": {
            "src/__init__.py": {"description": "package init"},
            "src/utils.py": {"description": "helpers"},
        },
    }
    await wm.setup_repo(tech_spec)

    # Write initial barrel content
    init_path = os.path.join(repo_path, "src/__init__.py")
    with open(init_path, "w") as f:
        f.write("# src package\nfrom src.utils import helper\n")
    await wm._run_git("add", "-A")
    await wm._run_git("commit", "-m", "Add initial imports")
    print(f"[1] Repo ready at {repo_path}")

    # 2. Create two worktrees that both add to __init__.py
    wt_a = await wm.create_worktree("FORGE-1", "forge/FORGE-1")
    wt_b = await wm.create_worktree("FORGE-2", "forge/FORGE-2")

    # Ticket A adds auth import
    init_a = os.path.join(wt_a, "src/__init__.py")
    with open(init_a, "w") as f:
        f.write("# src package\nfrom src.utils import helper\nfrom src.auth import login\n")

    auth_path = os.path.join(wt_a, "src/auth.py")
    with open(auth_path, "w") as f:
        f.write("def login():\n    return True\n")
    await wm._run_git("-C", wt_a, "add", "-A", cwd=wt_a)
    await wm._run_git("-C", wt_a, "commit", "-m", "Add auth module", cwd=wt_a)

    # Ticket B adds api import
    init_b = os.path.join(wt_b, "src/__init__.py")
    with open(init_b, "w") as f:
        f.write("# src package\nfrom src.utils import helper\nfrom src.api import get_users\n")

    api_path = os.path.join(wt_b, "src/api.py")
    with open(api_path, "w") as f:
        f.write("def get_users():\n    return []\n")
    await wm._run_git("-C", wt_b, "add", "-A", cwd=wt_b)
    await wm._run_git("-C", wt_b, "commit", "-m", "Add api module", cwd=wt_b)

    print("[2] Both worktrees committed conflicting __init__.py changes")

    # 3. Merge A into main first (this will succeed)
    merge_a = await wm.merge_worktree("FORGE-1", "forge/FORGE-1")
    print(f"[3] Merge FORGE-1: {'OK' if merge_a['success'] else 'CONFLICT'}")

    # 4. Analyse the conflict for B vs main
    conflict_report = {
        "ticket_a": "FORGE-1",
        "ticket_b": "FORGE-2",
        "conflicting_files": ["src/__init__.py"],
        "conflict_details": "changed in both: src/__init__.py",
    }

    analysis = await analyze_conflict(conflict_report, tech_spec)
    print(f"[4] Analysis: severity={analysis['severity']}, strategy={analysis['strategy']}")
    print(f"    Rationale: {analysis['rationale']}")

    # 5. Attempt auto-resolve
    assert analysis["severity"] == "trivial", f"Expected trivial, got {analysis['severity']}"

    resolved = await auto_resolve_trivial(
        worktree_manager=wm,
        ticket_a_id="FORGE-1",
        ticket_b_id="FORGE-2",
        branch_a="forge/FORGE-1",
        branch_b="forge/FORGE-2",
        conflict_files=["src/__init__.py"],
    )
    print(f"[5] Auto-resolve: {'SUCCESS' if resolved else 'FAILED'}")

    if resolved:
        # Verify the merged __init__.py has both imports
        result_init = os.path.join(repo_path, "src/__init__.py")
        with open(result_init) as f:
            content = f.read()
        print("[6] Merged __init__.py content:")
        for line in content.splitlines():
            print(f"    {line}")

        has_auth = "from src.auth import login" in content
        has_api = "from src.api import get_users" in content
        print(f"    Has auth import: {has_auth}")
        print(f"    Has api import: {has_api}")

    # Show git log
    git_log, _ = await wm._run_git("log", "--oneline", "-10")
    print("\n[7] Git log:")
    for line in git_log.splitlines():
        print(f"    {line}")

    # Cleanup
    await wm.cleanup_all()
    shutil.rmtree(base)
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(_main())
