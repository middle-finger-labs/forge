"""Dependency analyser — validates and optimises ticket execution order.

Runs after the PM stage produces a PRDBoard and before the coding swarm
begins.  Catches file-ownership conflicts, dependency ordering mistakes,
and missed tickets, then attempts to maximise parallelism via topological
sort.

Usage::

    errors = validate_execution_order(prd_board)
    if errors:
        optimised = optimize_execution_order(prd_board)
        prd_board["execution_order"] = optimised
"""

from __future__ import annotations

from collections import defaultdict, deque

import structlog

log = structlog.get_logger().bind(component="dependency_analyzer")


# ---------------------------------------------------------------------------
# 1. validate_execution_order
# ---------------------------------------------------------------------------


def validate_execution_order(prd_board: dict) -> list[str]:
    """Validate the PM's execution_order for correctness.

    Checks:
      - No two tickets in the same parallel group share ``files_owned``
      - All ticket dependencies appear in *earlier* groups
      - Every ticket appears exactly once in the execution order

    Returns a list of human-readable error strings (empty if valid).
    """
    tickets = prd_board.get("tickets", [])
    execution_order: list[list[str]] = prd_board.get("execution_order", [])

    tickets_by_key: dict[str, dict] = {t["ticket_key"]: t for t in tickets}
    all_ticket_keys = set(tickets_by_key)

    errors: list[str] = []

    # Track which tickets we've seen and in which group index
    seen_tickets: dict[str, int] = {}

    for group_idx, group in enumerate(execution_order):
        # -- File overlap within group --
        file_owners: dict[str, list[str]] = defaultdict(list)
        for ticket_key in group:
            ticket = tickets_by_key.get(ticket_key)
            if ticket is None:
                errors.append(f"Group {group_idx}: ticket '{ticket_key}' not found in tickets list")
                continue

            for fp in ticket.get("files_owned", []):
                file_owners[fp].append(ticket_key)

        for fp, owners in file_owners.items():
            if len(owners) > 1:
                errors.append(
                    f"Group {group_idx}: file '{fp}' is owned by multiple "
                    f"tickets in the same group: {owners}"
                )

        # -- Dependency ordering --
        # Only deps in *earlier* groups (already in seen_tickets) are
        # satisfied.  Same-group deps are invalid because the group
        # runs in parallel.
        current_group_set = set(group)
        for ticket_key in group:
            ticket = tickets_by_key.get(ticket_key)
            if ticket is None:
                continue

            for dep in ticket.get("dependencies", []):
                if dep not in seen_tickets:
                    # Check if the dep is at least in the prd_board
                    if dep in current_group_set:
                        errors.append(
                            f"Group {group_idx}: ticket '{ticket_key}' "
                            f"depends on '{dep}' which is in the same "
                            f"parallel group (must be in an earlier group)"
                        )
                    elif dep in all_ticket_keys:
                        errors.append(
                            f"Group {group_idx}: ticket '{ticket_key}' "
                            f"depends on '{dep}' which has not been "
                            f"scheduled in an earlier group"
                        )
                    else:
                        errors.append(
                            f"Group {group_idx}: ticket '{ticket_key}' "
                            f"depends on unknown ticket '{dep}'"
                        )

            # -- Duplicate check --
            if ticket_key in seen_tickets:
                errors.append(
                    f"Ticket '{ticket_key}' appears in both group "
                    f"{seen_tickets[ticket_key]} and group {group_idx}"
                )

        # Mark all tickets in this group as seen *after* checking the group
        for ticket_key in group:
            seen_tickets[ticket_key] = group_idx

    # -- All tickets accounted for --
    missing = all_ticket_keys - set(seen_tickets)
    if missing:
        errors.append(f"Tickets missing from execution_order: {sorted(missing)}")

    extra = set(seen_tickets) - all_ticket_keys
    if extra:
        errors.append(f"Unknown tickets in execution_order: {sorted(extra)}")

    if errors:
        log.warning(
            "execution order validation failed",
            error_count=len(errors),
        )
    else:
        log.info("execution order validation passed")

    return errors


# ---------------------------------------------------------------------------
# 2. optimize_execution_order
# ---------------------------------------------------------------------------


def optimize_execution_order(prd_board: dict) -> list[list[str]]:
    """Re-compute execution_order for maximum parallelism.

    Builds a dependency graph from:
      - Explicit ``dependencies`` between tickets
      - Implicit file-ownership edges (if ticket A and ticket B both own
        the same file, one must run before the other)

    Uses Kahn's algorithm (topological sort) to assign each ticket to the
    earliest possible group.

    Returns a new ``execution_order`` (list of parallel groups).
    """
    tickets = prd_board.get("tickets", [])
    tickets_by_key: dict[str, dict] = {t["ticket_key"]: t for t in tickets}
    all_keys = list(tickets_by_key)

    if not all_keys:
        return []

    # Build adjacency list and in-degree map
    graph: dict[str, set[str]] = defaultdict(set)  # predecessor → successors
    in_degree: dict[str, int] = {k: 0 for k in all_keys}

    def _add_edge(src: str, dst: str) -> None:
        if dst not in graph[src]:
            graph[src].add(dst)
            in_degree[dst] += 1

    # 1. Explicit dependency edges
    for ticket in tickets:
        tk = ticket["ticket_key"]
        for dep in ticket.get("dependencies", []):
            if dep in tickets_by_key:
                _add_edge(dep, tk)

    # 2. File-ownership conflict edges
    #    For tickets sharing files, preserve the original ordering hint
    #    (whichever appeared in an earlier group gets priority).
    original_order = _ticket_order_map(prd_board)
    file_to_tickets: dict[str, list[str]] = defaultdict(list)

    for ticket in tickets:
        for fp in ticket.get("files_owned", []):
            file_to_tickets[fp].append(ticket["ticket_key"])

    for fp, owners in file_to_tickets.items():
        if len(owners) < 2:
            continue
        # Sort by original order to produce a deterministic chain
        sorted_owners = sorted(owners, key=lambda k: original_order.get(k, 0))
        for i in range(len(sorted_owners) - 1):
            _add_edge(sorted_owners[i], sorted_owners[i + 1])

    # Kahn's algorithm — group by topological level
    queue: deque[str] = deque(k for k in all_keys if in_degree[k] == 0)
    groups: list[list[str]] = []

    scheduled: set[str] = set()

    while queue:
        # All nodes in the current queue have satisfied dependencies
        current_group = sorted(queue)  # sorted for determinism
        groups.append(current_group)
        scheduled.update(current_group)

        next_queue: deque[str] = deque()
        for node in current_group:
            for successor in sorted(graph[node]):
                in_degree[successor] -= 1
                if in_degree[successor] == 0:
                    next_queue.append(successor)
        queue = next_queue

    # Detect cycles (tickets that were never scheduled)
    unscheduled = set(all_keys) - scheduled
    if unscheduled:
        log.error(
            "dependency cycle detected — appending unscheduled tickets",
            tickets=sorted(unscheduled),
        )
        groups.append(sorted(unscheduled))

    log.info(
        "execution order optimised",
        original_groups=len(prd_board.get("execution_order", [])),
        optimised_groups=len(groups),
        total_tickets=len(all_keys),
    )

    return groups


# ---------------------------------------------------------------------------
# 3. detect_file_ownership_conflicts
# ---------------------------------------------------------------------------


def detect_file_ownership_conflicts(tickets: list[dict]) -> list[dict]:
    """Scan all tickets for overlapping file ownership.

    Returns a list of conflict dicts::

        {
            "file_path": str,
            "ticket_ids": [str, ...],
            "conflict_type": "shared_ownership",
        }
    """
    file_to_tickets: dict[str, list[str]] = defaultdict(list)

    for ticket in tickets:
        tk = ticket.get("ticket_key", "")
        for fp in ticket.get("files_owned", []):
            file_to_tickets[fp].append(tk)

    conflicts: list[dict] = []
    for fp, owners in sorted(file_to_tickets.items()):
        if len(owners) > 1:
            conflicts.append(
                {
                    "file_path": fp,
                    "ticket_ids": owners,
                    "conflict_type": "shared_ownership",
                }
            )

    if conflicts:
        log.warning(
            "file ownership conflicts detected",
            conflict_count=len(conflicts),
        )
    else:
        log.info("no file ownership conflicts")

    return conflicts


# ---------------------------------------------------------------------------
# 4. suggest_file_ownership_fixes
# ---------------------------------------------------------------------------


def suggest_file_ownership_fixes(
    conflicts: list[dict],
    tickets: list[dict],
) -> list[dict]:
    """Suggest ownership fixes for each file conflict.

    Strategy:
      - The ticket with the fewest dependencies should own the file
        (it runs earliest and likely *creates* the file).
      - Other tickets that share the file should depend on the owner
        (they are assumed to *modify* it afterward).

    Returns a list of suggestion dicts::

        {
            "file_path": str,
            "recommended_owner": str,  # ticket_key
            "tickets_to_resequence": [str, ...],  # ticket_keys to add dependency
        }
    """
    tickets_by_key = {t["ticket_key"]: t for t in tickets}

    suggestions: list[dict] = []

    for conflict in conflicts:
        fp = conflict["file_path"]
        owner_ids = conflict["ticket_ids"]

        if not owner_ids:
            continue

        # Pick the ticket with fewest dependencies as the owner
        # (proxy for "this ticket creates the file")
        def _dep_count(tk: str) -> int:
            return len(tickets_by_key.get(tk, {}).get("dependencies", []))

        sorted_owners = sorted(
            owner_ids,
            key=lambda tk: (_dep_count(tk), tk),
        )
        recommended = sorted_owners[0]
        others = sorted_owners[1:]

        suggestions.append(
            {
                "file_path": fp,
                "recommended_owner": recommended,
                "tickets_to_resequence": others,
            }
        )

        log.info(
            "suggested file ownership fix",
            file=fp,
            owner=recommended,
            resequence=others,
        )

    return suggestions


# ---------------------------------------------------------------------------
# 5. apply_ownership_fixes — auto-repair helper
# ---------------------------------------------------------------------------


def apply_ownership_fixes(
    prd_board: dict,
    suggestions: list[dict],
) -> dict:
    """Apply ownership fix suggestions to the PRD board in-place.

    For each suggestion:
      - Removes the file from ``files_owned`` of non-owner tickets
      - Adds a dependency edge from each non-owner to the owner
      - Re-optimises the execution order

    Returns the mutated *prd_board*.
    """
    tickets_by_key: dict[str, dict] = {t["ticket_key"]: t for t in prd_board.get("tickets", [])}

    for suggestion in suggestions:
        owner = suggestion["recommended_owner"]
        for other_tk in suggestion["tickets_to_resequence"]:
            other = tickets_by_key.get(other_tk)
            if other is None:
                continue

            # Remove file from non-owner's files_owned
            fp = suggestion["file_path"]
            owned = other.get("files_owned", [])
            if fp in owned:
                owned.remove(fp)

            # Add dependency on the owner
            deps = other.get("dependencies", [])
            if owner not in deps:
                deps.append(owner)
                other["dependencies"] = deps

    # Re-optimise after fixing dependencies
    prd_board["execution_order"] = optimize_execution_order(prd_board)

    log.info(
        "ownership fixes applied",
        fix_count=len(suggestions),
    )

    return prd_board


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ticket_order_map(prd_board: dict) -> dict[str, int]:
    """Map ticket_key → original position (group_idx * 1000 + position)."""
    order: dict[str, int] = {}
    for group_idx, group in enumerate(prd_board.get("execution_order", [])):
        for pos, tk in enumerate(group):
            order[tk] = group_idx * 1000 + pos
    return order


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import json

    print("=== Dependency Analyser smoke test ===\n")

    # Build a sample PRD board with intentional issues
    sample_board: dict = {
        "board_id": "TEST-001",
        "tickets": [
            {
                "ticket_key": "FORGE-1",
                "title": "Setup database models",
                "dependencies": [],
                "files_owned": ["src/models.py", "src/db.py"],
            },
            {
                "ticket_key": "FORGE-2",
                "title": "Build API endpoints",
                "dependencies": ["FORGE-1"],
                "files_owned": ["src/api.py", "src/models.py"],  # conflict!
            },
            {
                "ticket_key": "FORGE-3",
                "title": "Create auth module",
                "dependencies": [],
                "files_owned": ["src/auth.py"],
            },
            {
                "ticket_key": "FORGE-4",
                "title": "Add tests",
                "dependencies": ["FORGE-2", "FORGE-3"],
                "files_owned": ["tests/test_api.py", "tests/test_auth.py"],
            },
        ],
        "execution_order": [
            ["FORGE-1", "FORGE-2"],  # BAD: FORGE-2 depends on FORGE-1
            ["FORGE-3", "FORGE-4"],  # BAD: FORGE-4 depends on FORGE-2
        ],
    }

    # 1. Validate
    print("[1] Validating execution order...")
    errors = validate_execution_order(sample_board)
    for err in errors:
        print(f"    ERROR: {err}")
    print(f"    Total errors: {len(errors)}")

    # 2. Detect file conflicts
    print("\n[2] Detecting file ownership conflicts...")
    conflicts = detect_file_ownership_conflicts(sample_board["tickets"])
    for c in conflicts:
        print(f"    CONFLICT: {c['file_path']} — {c['ticket_ids']}")

    # 3. Suggest fixes
    print("\n[3] Suggesting fixes...")
    suggestions = suggest_file_ownership_fixes(conflicts, sample_board["tickets"])
    for s in suggestions:
        print(
            f"    FIX: {s['file_path']} → owner={s['recommended_owner']}, "
            f"resequence={s['tickets_to_resequence']}"
        )

    # 4. Apply fixes
    print("\n[4] Applying fixes and re-optimising...")
    apply_ownership_fixes(sample_board, suggestions)
    print(f"    New execution_order: {json.dumps(sample_board['execution_order'])}")

    # 5. Re-validate
    print("\n[5] Re-validating...")
    errors = validate_execution_order(sample_board)
    if errors:
        for err in errors:
            print(f"    ERROR: {err}")
    else:
        print("    All clear!")

    # 6. Optimise the original (unfixed) board
    print("\n[6] Optimising the original board (ignoring file conflicts)...")
    original_board = {
        "board_id": "TEST-002",
        "tickets": [
            {"ticket_key": "A", "dependencies": [], "files_owned": ["a.py"]},
            {"ticket_key": "B", "dependencies": [], "files_owned": ["b.py"]},
            {"ticket_key": "C", "dependencies": ["A"], "files_owned": ["c.py"]},
            {"ticket_key": "D", "dependencies": ["A", "B"], "files_owned": ["d.py"]},
            {"ticket_key": "E", "dependencies": ["C", "D"], "files_owned": ["e.py"]},
        ],
        "execution_order": [["A"], ["B"], ["C"], ["D"], ["E"]],
    }
    optimised = optimize_execution_order(original_board)
    print(f"    Original: {json.dumps(original_board['execution_order'])}")
    print(f"    Optimised: {json.dumps(optimised)}")
    # Expected: [["A", "B"], ["C", "D"], ["E"]]

    print("\nDone.")
