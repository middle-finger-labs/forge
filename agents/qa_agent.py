"""QA agent — wires Stage 6 prompts into the LangGraph runner.

Produces a validated QAReview from a ticket and its code artifact.

Usage::

    from agents.qa_agent import run_qa_agent

    review, cost = await run_qa_agent(ticket, code_artifact, coding_standards)
"""

from __future__ import annotations

import json
import os

import structlog

from agents.langgraph_runner import run_agent
from agents.stage_6_qa import HUMAN_PROMPT_TEMPLATE, SYSTEM_PROMPT
from contracts.schemas import QAReview

log = structlog.get_logger().bind(component="qa_agent")

# Maximum total bytes of source content to include in the prompt to avoid
# blowing past context limits.
_MAX_FILE_CONTENT_BYTES = 60_000
_TEST_FILE_PATTERNS = ("test", "spec", "__tests__", ".test.", ".spec.")


def _read_artifact_files(code_artifact: dict) -> tuple[str, str]:
    """Read source and test files from the worktree referenced by the code artifact.

    Returns (code_file_contents, test_file_contents) — each is a formatted
    string ready for the prompt, or a placeholder if files aren't available.
    """
    worktree_path = code_artifact.get("worktree_path", "")
    all_files = code_artifact.get("files_created", []) + code_artifact.get("files_modified", [])

    if not worktree_path or not os.path.isdir(worktree_path) or not all_files:
        return (
            "[No source files available — reviewing from artifact metadata only]",
            "[No test files available — reviewing from artifact metadata only]",
        )

    code_parts: list[str] = []
    test_parts: list[str] = []
    total_bytes = 0

    for filepath in all_files:
        full_path = os.path.join(worktree_path, filepath)
        if not os.path.isfile(full_path):
            continue

        try:
            with open(full_path, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            continue

        # Truncate individual large files
        if len(content) > 15_000:
            content = content[:15_000] + "\n... [truncated]"

        # Stop accumulating if we've already collected enough
        if total_bytes + len(content) > _MAX_FILE_CONTENT_BYTES:
            remaining = all_files[all_files.index(filepath) :]
            note = f"[{len(remaining)} more files omitted for context limits]"
            if any(_is_test_file(fp) for fp in remaining):
                test_parts.append(note)
            else:
                code_parts.append(note)
            break

        total_bytes += len(content)
        entry = f"### {filepath}\n```\n{content}\n```"

        if _is_test_file(filepath):
            test_parts.append(entry)
        else:
            code_parts.append(entry)

    return (
        "\n\n".join(code_parts) if code_parts else "[No source files found on disk]",
        "\n\n".join(test_parts) if test_parts else "[No test files found on disk]",
    )


def _is_test_file(filepath: str) -> bool:
    """Heuristic: is this filepath a test file?"""
    return any(pat in filepath for pat in _TEST_FILE_PATTERNS)


async def run_qa_agent(
    ticket: dict,
    code_artifact: dict,
    coding_standards: list[str],
    *,
    model: str | None = None,
    max_retries: int = 3,
    org_id: str = "",
) -> tuple[dict | None, float]:
    """Run the QA agent to produce a QAReview.

    Parameters
    ----------
    ticket:
        Dictionary representation of a PRDTicket.
    code_artifact:
        Dictionary representation of a CodeArtifact.
    coding_standards:
        List of coding standard rules from the TechSpec.
    model:
        Optional LLM model override.
    max_retries:
        Maximum validation retry attempts.
    org_id:
        Org ID for prompt version resolution.

    Returns
    -------
    tuple[dict | None, float]
        (Validated QAReview dict or None on failure, cost in USD.)
    """

    # Resolve prompt (org-specific override or default)
    system_prompt = SYSTEM_PROMPT
    try:
        from agents.prompts.evaluation import resolve_stage_prompt

        system_prompt, _ = await resolve_stage_prompt(
            org_id=org_id, stage=6, default_prompt=SYSTEM_PROMPT,
        )
    except Exception as exc:
        log.debug("prompt resolution skipped", error=str(exc))

    ticket_key = ticket.get("ticket_key", "unknown")

    memory_context = ""
    try:
        from memory.semantic_memory import SemanticMemory, get_relevant_context

        # General QA context
        memory_context = await get_relevant_context(
            "qa",
            f"Review code for ticket {ticket_key}: {ticket.get('title', '')}",
        )

        # Extra recall for common rejection reasons
        mem = SemanticMemory()
        rejections = await mem.recall(
            "QA rejections common issues",
            agent_role="qa",
            limit=3,
        )
        if rejections:
            lines = [memory_context] if memory_context else []
            lines.append("<common_qa_issues>")
            for r in rejections:
                content = r.get("content", "")
                if content:
                    lines.append(f"- {content}")
            lines.append("</common_qa_issues>")
            memory_context = "\n".join(lines)
    except Exception as exc:
        log.debug("memory recall skipped", error=str(exc))

    code_file_contents, test_file_contents = _read_artifact_files(code_artifact)

    human_prompt = HUMAN_PROMPT_TEMPLATE.format(
        ticket_json=json.dumps(ticket, indent=2),
        code_artifact_json=json.dumps(code_artifact, indent=2),
        code_file_contents=code_file_contents,
        test_file_contents=test_file_contents,
        coding_standards="\n".join(f"- {s}" for s in coding_standards),
    )

    return await run_agent(
        system_prompt=system_prompt,
        human_prompt=human_prompt,
        output_model=QAReview,
        model=model,
        max_retries=max_retries,
        memory_context=memory_context or None,
    )


# ---------------------------------------------------------------------------
# Manual test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio

    TEST_TICKET = {
        "ticket_key": "FORGE-2",
        "title": "Implement user registration endpoint",
        "ticket_type": "feature",
        "priority": "high",
        "story_points": 5,
        "description": (
            "Create POST /api/v1/auth/register endpoint. Accept email and "
            "password, hash password with bcrypt (rounds=12), insert user, "
            "return user object without password field."
        ),
        "acceptance_criteria": [
            "POST /api/v1/auth/register returns 201 with user object",
            "Password is hashed with bcrypt before storage",
            "Duplicate email returns 409 Conflict",
            "Response never includes password or password_hash field",
        ],
        "files_owned": [
            "src/features/auth/router.ts",
            "src/features/auth/service.ts",
            "src/features/auth/__tests__/register.test.ts",
        ],
        "dependencies": ["FORGE-1"],
        "user_story_refs": ["US-001"],
        "status": "in_review",
    }

    TEST_CODE_ARTIFACT = {
        "ticket_key": "FORGE-2",
        "git_branch": "forge/forge-2",
        "files_created": [
            "src/features/auth/router.ts",
            "src/features/auth/service.ts",
            "src/features/auth/__tests__/register.test.ts",
        ],
        "files_modified": [],
        "test_results": {
            "total": 4,
            "passed": 4,
            "failed": 0,
            "skipped": 0,
            "duration_seconds": 0.8,
            "details": [
                "register_success — PASSED",
                "register_duplicate_email — PASSED",
                "register_password_hashed — PASSED",
                "register_no_password_in_response — PASSED",
            ],
        },
        "lint_passed": True,
        "notes": "All acceptance criteria addressed.",
    }

    TEST_CODING_STANDARDS = [
        "All functions must have explicit return types",
        "Use Zod for request validation",
        "No raw SQL — use Drizzle ORM query builder",
        "Passwords must be hashed with bcrypt, minimum 12 rounds",
    ]

    async def main() -> None:
        """Run the QA agent against a sample ticket and code artifact and print results."""
        print("Running QA agent...")
        print("=" * 60)

        result, cost = await run_qa_agent(
            TEST_TICKET,
            TEST_CODE_ARTIFACT,
            TEST_CODING_STANDARDS,
        )

        print("=" * 60)
        print(f"Cost: ${cost:.4f}")
        print()

        if result is None:
            print("FAILED: Agent did not produce valid output.")
        else:
            print("SUCCESS: Valid QAReview produced.")
            print(f"  Ticket:    {result['ticket_key']}")
            print(f"  Verdict:   {result['verdict']}")
            print(f"  Score:     {result['code_quality_score']}/10")
            compliance = result.get("criteria_compliance", {})
            passed = sum(1 for v in compliance.values() if v)
            print(f"  Criteria:  {passed}/{len(compliance)} passed")
            comments = result.get("comments", [])
            print(f"  Comments:  {len(comments)}")
            for c in comments[:5]:
                print(f"    [{c['severity']}] {c['file_path']}: {c['comment'][:60]}")
            security = result.get("security_concerns", [])
            if security:
                print(f"  Security:  {len(security)} concerns")
            revisions = result.get("revision_instructions", [])
            if revisions:
                print(f"  Revisions: {len(revisions)} instructions")

    asyncio.run(main())
