"""Coding agent — executes a single PRD ticket in a git worktree.

Two execution modes, chosen automatically at import time:

1. **Claude Code mode** — if the ``claude`` CLI is on PATH, we run it
   headless via ``claude -p`` with scoped tool permissions.
2. **Anthropic API fallback** — otherwise we call the API directly,
   ask the LLM for a JSON file-map, and write files ourselves.

Both modes commit the result into the worktree branch and return a
``CodeArtifact``-shaped dict (or *None* on failure) plus a USD cost.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
import traceback

import structlog

from agents.stage_5_engineer import SYSTEM_PROMPT as ENGINEER_SYSTEM_PROMPT
from config.agent_config import _PRICING, SONNET_4_5, get_anthropic_client

log = structlog.get_logger().bind(component="coding_agent")

# Default timeout for a single ticket (seconds).
DEFAULT_TIMEOUT_SECONDS = 600

# ---------------------------------------------------------------------------
# Claude CLI detection (one-time, at import)
# ---------------------------------------------------------------------------

_CLAUDE_CLI_PATH: str | None = shutil.which("claude")


def claude_cli_available() -> bool:
    """Return *True* if the ``claude`` CLI is on PATH."""
    return _CLAUDE_CLI_PATH is not None


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _run_cmd(
    *args: str,
    cwd: str | None = None,
    timeout: float | None = None,
) -> tuple[str, str, int]:
    """Run a command, return *(stdout, stderr, returncode)*."""
    # Build a clean env — strip CLAUDECODE so Claude Code CLI doesn't
    # refuse to start when the worker itself runs inside a CC session.
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)

    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    return (
        stdout_bytes.decode().strip(),
        stderr_bytes.decode().strip(),
        proc.returncode or 0,
    )


def _join_standards(standards: list | str) -> str:
    """Join coding standards into a newline-separated string."""
    return "\n".join(standards) if isinstance(standards, list) else str(standards)


def _build_prompt(ticket: dict, tech_spec_context: dict) -> str:
    """Assemble the human prompt from ticket + tech spec context."""
    file_structure = tech_spec_context.get("file_structure", {})
    coding_standards = tech_spec_context.get("coding_standards", [])
    related_endpoints = tech_spec_context.get("related_endpoints", [])
    related_models = tech_spec_context.get("related_models", [])
    existing_contents = tech_spec_context.get("existing_file_contents", {})

    return (
        "Implement the following ticket. Study all provided context "
        "before writing any code.\n\n"
        f"--- TICKET ---\n{json.dumps(ticket, indent=2)}\n--- END TICKET ---\n\n"
        f"--- FILE STRUCTURE ---\n{json.dumps(file_structure, indent=2)}\n"
        "--- END FILE STRUCTURE ---\n\n"
        f"--- CODING STANDARDS ---\n"
        f"{_join_standards(coding_standards)}\n"
        "--- END CODING STANDARDS ---\n\n"
        f"--- RELATED ENDPOINTS ---\n{json.dumps(related_endpoints, indent=2)}\n"
        "--- END RELATED ENDPOINTS ---\n\n"
        f"--- RELATED DATABASE MODELS ---\n{json.dumps(related_models, indent=2)}\n"
        "--- END RELATED MODELS ---\n\n"
        f"--- EXISTING FILE CONTENTS ---\n{json.dumps(existing_contents, indent=2)}\n"
        "--- END EXISTING FILE CONTENTS ---\n\n"
        "Implement the ticket completely, run tests and lint, then return "
        "the CodeArtifact JSON."
    )


def _build_claude_md(tech_spec_context: dict) -> str:
    """Generate a CLAUDE.md for the worktree root."""
    coding_standards = tech_spec_context.get("coding_standards", [])
    file_structure = tech_spec_context.get("file_structure", {})

    standards_text = (
        "\n".join(f"- {s}" for s in coding_standards)
        if isinstance(coding_standards, list)
        else str(coding_standards)
    )
    structure_text = "\n".join(f"- {p}" for p in file_structure)

    return (
        "# Project Context (automated pipeline)\n\n"
        "This workspace is managed by an automated coding pipeline. "
        "Do NOT ask interactive questions — complete the task fully.\n\n"
        "## Coding Standards\n\n"
        f"{standards_text}\n\n"
        "## File Structure\n\n"
        f"{structure_text}\n"
    )


async def _git_add_commit(
    worktree_path: str,
    ticket: dict,
    branch_name: str,
) -> None:
    """Stage everything and commit in the worktree."""
    await _run_cmd("git", "add", "-A", cwd=worktree_path)
    ticket_key = ticket.get("ticket_key", "unknown")
    description = ticket.get("title", ticket.get("description", "implement ticket"))
    # Truncate description for commit message
    short = description[:60] + ("..." if len(description) > 60 else "")
    msg = f"feat({ticket_key}): {short}"
    # Only commit if there are staged changes
    stdout, _, rc = await _run_cmd("git", "diff", "--cached", "--quiet", cwd=worktree_path)
    if rc != 0:
        await _run_cmd("git", "commit", "-m", msg, cwd=worktree_path)


def _detect_changed_files(worktree_path: str, before_files: dict[str, float]) -> tuple[list, list]:
    """Compare filesystem state to detect created/modified files."""
    created: list[str] = []
    modified: list[str] = []

    for root, _dirs, files in os.walk(worktree_path):
        for fname in files:
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, worktree_path)
            if rel.startswith(".git"):
                continue
            if rel == "CLAUDE.md":
                continue
            mtime = os.path.getmtime(full)
            if rel not in before_files:
                created.append(rel)
            elif mtime != before_files[rel]:
                modified.append(rel)

    return created, modified


def _snapshot_files(worktree_path: str) -> dict[str, float]:
    """Snapshot {relative_path: mtime} for every non-.git file."""
    snap: dict[str, float] = {}
    for root, _dirs, files in os.walk(worktree_path):
        for fname in files:
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, worktree_path)
            if rel.startswith(".git"):
                continue
            snap[rel] = os.path.getmtime(full)
    return snap


# ---------------------------------------------------------------------------
# Mode 1: Claude Code CLI
# ---------------------------------------------------------------------------


async def _run_claude_code(
    ticket: dict,
    tech_spec_context: dict,
    worktree_path: str,
    branch_name: str,
    timeout: float,
) -> tuple[dict | None, float]:
    """Execute the ticket using ``claude -p`` in headless mode."""
    agent_log = log.bind(
        mode="claude_code",
        ticket_key=ticket.get("ticket_key", "?"),
        worktree=worktree_path,
    )
    agent_log.info("starting claude code execution")
    start = time.monotonic()

    # Write CLAUDE.md into worktree root
    claude_md_path = os.path.join(worktree_path, "CLAUDE.md")
    with open(claude_md_path, "w") as f:
        f.write(_build_claude_md(tech_spec_context))

    # Snapshot files before execution
    before = _snapshot_files(worktree_path)

    # Retrieve memory context and prepend to prompt
    memory_ctx = await _get_coding_memory_context(ticket)
    prompt = _build_prompt(ticket, tech_spec_context)
    if memory_ctx:
        prompt = (
            f"<context_from_previous_runs>\n{memory_ctx}\n</context_from_previous_runs>\n\n{prompt}"
        )

    cmd = [
        _CLAUDE_CLI_PATH or "claude",
        "-p",
        prompt,
        "--allowedTools",
        "Bash(git:*,npm:*,npx:*,node:*,python:*,pytest:*,pip:*,ruff:*),Read,Write,Edit,Glob,Grep",
        "--output-format",
        "json",
        "--max-turns",
        "30",
    ]

    try:
        stdout, stderr, rc = await _run_cmd(*cmd, cwd=worktree_path, timeout=timeout)
    except TimeoutError:
        agent_log.error("claude code timed out", timeout=timeout)
        return None, 0.0

    elapsed = round(time.monotonic() - start, 2)

    if rc != 0:
        agent_log.error(
            "claude code exited non-zero",
            returncode=rc,
            stderr=stderr[:500],
            duration=elapsed,
        )
        return None, 0.0

    # Parse the JSON output from claude
    result_text: str = ""
    cost_usd = 0.0
    try:
        parsed = json.loads(stdout)
        result_text = parsed.get("result", "") if isinstance(parsed, dict) else ""
        cost_usd = float(parsed.get("cost_usd", 0.0)) if isinstance(parsed, dict) else 0.0
    except (json.JSONDecodeError, ValueError):
        result_text = stdout

    # Detect files changed on disk
    created, modified = _detect_changed_files(worktree_path, before)

    # Commit changes
    await _git_add_commit(worktree_path, ticket, branch_name)

    artifact = {
        "ticket_key": ticket.get("ticket_key", "unknown"),
        "git_branch": branch_name,
        "files_created": created,
        "files_modified": modified,
        "test_results": None,
        "lint_passed": False,
        "notes": result_text[:2000] if result_text else "",
    }

    agent_log.info(
        "claude code complete",
        files_created=len(created),
        files_modified=len(modified),
        duration=elapsed,
        cost_usd=cost_usd,
    )
    return artifact, cost_usd


# ---------------------------------------------------------------------------
# Mode 2: Anthropic API fallback
# ---------------------------------------------------------------------------


async def _run_api_fallback(
    ticket: dict,
    tech_spec_context: dict,
    worktree_path: str,
    branch_name: str,
    timeout: float,
) -> tuple[dict | None, float]:
    """Execute the ticket using the Anthropic Python SDK directly."""
    import importlib.util

    if importlib.util.find_spec("anthropic") is None:
        log.error("anthropic package not installed, cannot use API fallback")
        return None, 0.0

    agent_log = log.bind(
        mode="api_fallback",
        ticket_key=ticket.get("ticket_key", "?"),
        worktree=worktree_path,
    )
    agent_log.info("starting API fallback execution")
    start = time.monotonic()

    human_prompt = _build_prompt(ticket, tech_spec_context)

    # Retrieve memory context and prepend to system prompt
    memory_ctx = await _get_coding_memory_context(ticket)
    memory_prefix = ""
    if memory_ctx:
        memory_prefix = (
            f"<context_from_previous_runs>\n{memory_ctx}\n</context_from_previous_runs>\n\n"
        )

    # Wrap the system prompt to request a JSON file-map output
    system = (
        f"{memory_prefix}{ENGINEER_SYSTEM_PROMPT}\n\n"
        "IMPORTANT: Since you cannot directly access the filesystem, return "
        "your implementation as a JSON object with this structure:\n"
        "```\n"
        "{\n"
        '  "files": {\n'
        '    "path/to/file.py": "file contents ...",\n'
        '    "path/to/other.py": "file contents ..."\n'
        "  },\n"
        '  "commit_message": "feat(FORGE-N): short description",\n'
        '  "test_commands": ["pytest tests/", "npm test"],\n'
        '  "notes": "any implementation notes"\n'
        "}\n"
        "```\n"
        "Return ONLY valid JSON. No markdown fences, no commentary."
    )

    try:
        client = get_anthropic_client()
        response = await asyncio.wait_for(
            client.messages.create(
                model=SONNET_4_5,
                max_tokens=16384,
                system=system,
                messages=[{"role": "user", "content": human_prompt}],
            ),
            timeout=timeout,
        )
    except TimeoutError:
        agent_log.error("API call timed out", timeout=timeout)
        return None, 0.0
    except Exception as exc:
        agent_log.error("API call failed", error=str(exc), traceback=traceback.format_exc())
        return None, 0.0

    elapsed = round(time.monotonic() - start, 2)

    # Estimate cost from token usage
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    input_rate, output_rate = _PRICING.get(SONNET_4_5, (3.0, 15.0))
    cost_usd = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000

    # Extract the text content
    raw_text = ""
    for block in response.content:
        if block.type == "text":
            raw_text += block.text

    # Strip markdown fences if the LLM wrapped them anyway
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.index("\n")
        cleaned = cleaned[first_newline + 1 :]
    if cleaned.endswith("```"):
        cleaned = cleaned[: -len("```")]
    cleaned = cleaned.strip()

    # Parse the file map
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        agent_log.error("LLM returned invalid JSON", raw_length=len(raw_text))
        return None, cost_usd

    files_map: dict[str, str] = payload.get("files", {})
    notes = payload.get("notes", "")
    test_commands: list[str] = payload.get("test_commands", [])

    # Write files to the worktree
    created: list[str] = []
    modified: list[str] = []
    for rel_path, content in files_map.items():
        full_path = os.path.join(worktree_path, rel_path)
        existed = os.path.exists(full_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as f:
            f.write(content)
        if existed:
            modified.append(rel_path)
        else:
            created.append(rel_path)

    agent_log.info(
        "files written",
        created=len(created),
        modified=len(modified),
    )

    # Attempt to run test commands
    test_results = None
    for cmd_str in test_commands:
        try:
            stdout, stderr, rc = await _run_cmd(
                "sh",
                "-c",
                cmd_str,
                cwd=worktree_path,
                timeout=120,
            )
            test_results = {
                "total": 1,
                "passed": 1 if rc == 0 else 0,
                "failed": 0 if rc == 0 else 1,
                "skipped": 0,
                "duration_seconds": 0.0,
                "details": [f"{cmd_str} — {'passed' if rc == 0 else 'failed'}"],
            }
            if rc != 0:
                agent_log.warning("test command failed", cmd=cmd_str, stderr=stderr[:300])
                break
        except (TimeoutError, OSError):
            agent_log.warning("test command timed out or errored", cmd=cmd_str)

    # Commit
    await _git_add_commit(worktree_path, ticket, branch_name)

    artifact = {
        "ticket_key": ticket.get("ticket_key", "unknown"),
        "git_branch": branch_name,
        "files_created": created,
        "files_modified": modified,
        "test_results": test_results,
        "lint_passed": False,
        "notes": notes[:2000],
    }

    agent_log.info(
        "API fallback complete",
        files_created=len(created),
        files_modified=len(modified),
        duration=elapsed,
        cost_usd=round(cost_usd, 4),
    )
    return artifact, cost_usd


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def _get_coding_memory_context(ticket: dict) -> str:
    """Retrieve relevant memories for the coding agent."""
    try:
        from memory.semantic_memory import get_relevant_context

        return await get_relevant_context(
            "developer",
            f"Implement ticket {ticket.get('ticket_key', '')}: {ticket.get('title', '')}",
        )
    except Exception as exc:
        log.debug("memory recall skipped", error=str(exc))
        return ""


async def run_coding_agent_task(
    ticket: dict,
    tech_spec_context: dict,
    worktree_path: str,
    branch_name: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[dict | None, float]:
    """Execute a single PRD ticket in a git worktree.

    Returns *(CodeArtifact dict or None, cost_usd)*.

    Automatically selects Claude Code CLI if available, otherwise falls
    back to the Anthropic API.
    """
    agent_log = log.bind(
        ticket_key=ticket.get("ticket_key", "?"),
        branch=branch_name,
        worktree=worktree_path,
    )

    if not os.path.isdir(worktree_path):
        agent_log.error("worktree path does not exist")
        return None, 0.0

    try:
        if claude_cli_available():
            return await _run_claude_code(
                ticket, tech_spec_context, worktree_path, branch_name, timeout
            )
        else:
            return await _run_api_fallback(
                ticket, tech_spec_context, worktree_path, branch_name, timeout
            )
    except Exception as exc:
        agent_log.error(
            "coding agent failed",
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        return None, 0.0


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------


async def _main() -> None:
    """Smoke test: create a temp repo + worktree, run a simple ticket."""
    import tempfile

    from agents.worktree_manager import WorktreeManager

    print(f"Claude CLI available: {claude_cli_available()}")
    if _CLAUDE_CLI_PATH:
        print(f"  path: {_CLAUDE_CLI_PATH}")

    base = tempfile.mkdtemp(prefix="forge-coding-test-")
    repo_path = os.path.join(base, "project")
    wt_dir = os.path.join(base, "worktrees")

    mgr = WorktreeManager(repo_path, worktrees_dir=wt_dir)

    # Setup a basic repo
    tech_spec = {
        "file_structure": {
            "src/index.js": {"description": "Express app entry point"},
            "src/routes/": {"description": "Route handlers"},
            "package.json": {"description": "Node project config"},
            "tests/": {"description": "Test directory"},
        },
        "coding_standards": [
            "Use ES module syntax (import/export)",
            "Use const for variables that are not reassigned",
            "Add JSDoc comments to exported functions",
        ],
    }
    await mgr.setup_repo(tech_spec)

    # Create a worktree
    wt_path = await mgr.create_worktree("FORGE-1", "forge/FORGE-1")

    # Define a simple ticket
    ticket = {
        "ticket_key": "FORGE-1",
        "title": "Hello World Express route",
        "description": (
            "Create a minimal Express.js app with a GET /hello route "
            "that returns { message: 'Hello, World!' } as JSON."
        ),
        "acceptance_criteria": [
            "GET /hello returns 200 with JSON body { message: 'Hello, World!' }",
            "Server listens on PORT env var or 3000",
        ],
        "files_owned": ["src/index.js", "src/routes/hello.js", "package.json"],
        "technical_guidance": "Use express 4.x. Keep it minimal.",
    }

    print("\n--- running coding agent ---")
    result, cost = await run_coding_agent_task(
        ticket=ticket,
        tech_spec_context=tech_spec,
        worktree_path=wt_path,
        branch_name="forge/FORGE-1",
        timeout=300,
    )

    print("\n--- result ---")
    if result:
        print(json.dumps(result, indent=2))
    else:
        print("  (None — agent failed)")
    print(f"  cost: ${cost:.4f}")

    # Status
    status = await mgr.get_worktree_status("FORGE-1")
    print(f"\n--- worktree status ---\n  {status}")

    # Cleanup
    print("\n--- cleanup ---")
    await mgr.cleanup_all()
    shutil.rmtree(base)
    print("done.")


if __name__ == "__main__":
    asyncio.run(_main())
