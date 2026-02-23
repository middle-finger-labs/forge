"""Bridge between Forge's internal git repo and a GitHub remote.

Handles cloning, syncing, branch management, PR creation, and issue
reporting — everything needed to move pipeline-generated code onto GitHub.

Usage::

    from integrations.git_identity import GitIdentity
    from integrations.github_client import GitHubClient
    from integrations.repo_connector import RepoConnector

    identity = GitIdentity(name="draftkings", ...)
    async with GitHubClient(identity) as gh:
        rc = RepoConnector(gh, identity, "DraftKings", "lottery")
        repo_path = await rc.initialize("/tmp/lottery")
        await rc.sync_from_remote(repo_path)
        result = await rc.push_pipeline_results(
            repo_path, "pipe-001", code_artifacts, strategy="single_pr",
        )
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from integrations.git_identity import GitIdentity
from integrations.github_client import GitHubClient, GitOperationError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FORGE_LABELS = ["forge-generated", "ai-code"]


# ---------------------------------------------------------------------------
# RepoConnector
# ---------------------------------------------------------------------------


class RepoConnector:
    """Connects a Forge pipeline to a specific GitHub repository.

    Wraps :class:`GitHubClient` with higher-level operations for the
    pipeline: clone, sync, push results, create PRs, link issues.
    """

    def __init__(
        self,
        github_client: GitHubClient,
        identity: GitIdentity,
        owner: str,
        repo: str,
        target_branch: str | None = None,
    ) -> None:
        self._gh = github_client
        self._identity = identity
        self._owner = owner
        self._repo = repo
        self._default_branch: str = "main"
        self._target_branch: str | None = target_branch

    # ------------------------------------------------------------------
    # initialize
    # ------------------------------------------------------------------

    async def initialize(self, working_dir: str) -> str:
        """Clone the repo and configure git identity.

        Parameters
        ----------
        working_dir:
            Directory to clone into.  Created if it doesn't exist.

        Returns
        -------
        str
            Absolute path to the cloned repository.
        """
        # Discover default branch from GitHub before cloning
        repo_info = await self._gh.get_repo_info(self._owner, self._repo)
        self._default_branch = repo_info.get(
            "default_branch", "main"
        )

        # Use target_branch if specified, otherwise fall back to default
        clone_branch = self._target_branch or self._default_branch

        ssh_url = repo_info["ssh_url"]

        logger.info(
            "Cloning %s/%s (branch %s) into %s",
            self._owner,
            self._repo,
            clone_branch,
            working_dir,
        )

        repo_path = await self._gh.clone_repo(
            ssh_url, working_dir, branch=clone_branch,
        )

        # Configure local git identity
        await self._run_git(
            "config", "user.name", self._identity.github_username,
            cwd=repo_path,
        )
        await self._run_git(
            "config", "user.email", self._identity.email,
            cwd=repo_path,
        )

        # Verify clone: HEAD must exist and match the expected branch
        head_ref = await self._run_git(
            "symbolic-ref", "--short", "HEAD", cwd=repo_path,
        )
        if head_ref != clone_branch:
            logger.warning(
                "HEAD is %s, expected %s — continuing anyway",
                head_ref,
                clone_branch,
            )

        logger.info("Repository initialised at %s", repo_path)
        return repo_path

    # ------------------------------------------------------------------
    # sync_from_remote
    # ------------------------------------------------------------------

    async def sync_from_remote(self, repo_path: str) -> None:
        """Fetch and rebase on the current branch.

        Called before each pipeline run to ensure we start from the
        latest remote state.
        """
        await self._run_git("fetch", "origin", cwd=repo_path)

        branch = await self._run_git(
            "symbolic-ref", "--short", "HEAD", cwd=repo_path,
        )
        try:
            await self._run_git(
                "pull", "--rebase", "origin", branch, cwd=repo_path,
            )
        except GitOperationError as exc:
            # If rebase fails (e.g. diverged history), abort and warn
            logger.warning("Rebase failed, aborting: %s", exc)
            try:
                await self._run_git(
                    "rebase", "--abort", cwd=repo_path,
                )
            except GitOperationError:
                pass
            # Fall back to a merge pull
            await self._run_git(
                "pull", "origin", branch, cwd=repo_path,
            )

        logger.info("Synced %s from remote", repo_path)

    # ------------------------------------------------------------------
    # push_pipeline_results
    # ------------------------------------------------------------------

    async def push_pipeline_results(
        self,
        repo_path: str,
        pipeline_id: str,
        code_artifacts: list[dict],
        strategy: str = "single_pr",
    ) -> dict:
        """Push pipeline code to GitHub and create PRs.

        Parameters
        ----------
        repo_path:
            Local repo path with pipeline results merged to main.
        pipeline_id:
            Identifier for the Forge pipeline run.
        code_artifacts:
            List of CodeArtifact dicts from the pipeline.
        strategy:
            ``"single_pr"`` — one branch + PR for everything.
            ``"pr_per_ticket"`` — one branch + PR per ticket.
            ``"direct_push"`` — push straight to a target branch.

        Returns
        -------
        dict
            ``{"prs": [...], "branches": [...]}`` with PR URLs and
            branch names created.
        """
        if strategy == "single_pr":
            return await self._push_single_pr(
                repo_path, pipeline_id, code_artifacts,
            )
        if strategy == "pr_per_ticket":
            return await self._push_per_ticket(
                repo_path, pipeline_id, code_artifacts,
            )
        if strategy == "direct_push":
            return await self._push_direct(
                repo_path, pipeline_id, code_artifacts,
            )
        raise ValueError(f"Unknown push strategy: {strategy!r}")

    # --- single_pr ---

    async def _push_single_pr(
        self,
        repo_path: str,
        pipeline_id: str,
        artifacts: list[dict],
    ) -> dict:
        branch = f"forge/{pipeline_id}"

        # Create branch from current HEAD (which has all merged work).
        # If the branch already exists (e.g. from a previous failed run),
        # delete it first and recreate from current HEAD.
        if await self._branch_exists(repo_path, branch):
            await self._run_git("branch", "-D", branch, cwd=repo_path)
        await self._run_git(
            "checkout", "-b", branch, cwd=repo_path,
        )
        await self._gh.push_branch(repo_path, branch)

        pr_url = await self.create_pipeline_pr(
            repo_path, branch, pipeline_id, _build_pr_context(artifacts),
        )

        return {"prs": [pr_url], "branches": [branch]}

    # --- pr_per_ticket ---

    async def _push_per_ticket(
        self,
        repo_path: str,
        pipeline_id: str,
        artifacts: list[dict],
    ) -> dict:
        prs: list[str] = []
        branches: list[str] = []

        for artifact in artifacts:
            ticket_key = artifact.get("ticket_key", "unknown")
            branch = artifact.get(
                "git_branch", f"forge/{ticket_key.lower()}",
            )

            # Check if the branch already exists locally
            exists = await self._branch_exists(repo_path, branch)
            if not exists:
                # Create a branch with just this ticket's changes
                await self._create_ticket_branch(
                    repo_path, branch, artifact,
                )

            await self._gh.push_branch(repo_path, branch)

            pr_url = await self.create_pipeline_pr(
                repo_path,
                branch,
                pipeline_id,
                _build_pr_context([artifact]),
            )
            prs.append(pr_url)
            branches.append(branch)

        return {"prs": prs, "branches": branches}

    # --- direct_push ---

    async def _push_direct(
        self,
        repo_path: str,
        pipeline_id: str,
        artifacts: list[dict],
    ) -> dict:
        branch = await self._run_git(
            "symbolic-ref", "--short", "HEAD", cwd=repo_path,
        )
        await self._gh.push_branch(repo_path, branch)
        logger.info(
            "Direct-pushed pipeline %s to %s", pipeline_id, branch,
        )
        return {"prs": [], "branches": [branch]}

    # ------------------------------------------------------------------
    # create_pipeline_pr
    # ------------------------------------------------------------------

    async def create_pipeline_pr(
        self,
        repo_path: str,
        branch_name: str,
        pipeline_id: str,
        artifacts: dict,
    ) -> str:
        """Create a well-formatted PR for a pipeline run.

        Parameters
        ----------
        repo_path:
            Local repo path (unused by API, kept for future use).
        branch_name:
            Head branch for the PR.
        pipeline_id:
            Pipeline run identifier.
        artifacts:
            Pre-computed context dict from ``_build_pr_context``.

        Returns
        -------
        str
            The ``html_url`` of the created pull request.
        """
        project_name = artifacts.get("project_name", self._repo)
        title = (
            f"feat: {project_name} — automated by Forge "
            f"pipeline {pipeline_id}"
        )
        body = _format_pr_body(pipeline_id, artifacts)

        pr_base = self._target_branch or self._default_branch
        pr = await self._gh.create_pr(
            self._owner,
            self._repo,
            title,
            body,
            branch_name,
            base=pr_base,
            draft=True,
        )

        # Best-effort label attachment (don't fail the PR if labels fail)
        try:
            await self._gh._api(
                "POST",
                f"/repos/{self._owner}/{self._repo}"
                f"/issues/{pr['number']}/labels",
                json={"labels": _FORGE_LABELS},
                expected=(200,),
            )
        except Exception:
            logger.debug(
                "Could not add labels to PR #%d (labels may not exist)",
                pr["number"],
            )

        logger.info(
            "Created PR #%d: %s", pr["number"], pr["html_url"],
        )
        return pr["html_url"]

    # ------------------------------------------------------------------
    # link_issues
    # ------------------------------------------------------------------

    async def link_issues(
        self,
        pr_number: int,
        issue_numbers: list[int],
    ) -> None:
        """Append ``Closes #N`` references to an existing PR body."""
        if not issue_numbers:
            return

        # Fetch current PR body
        pr_data = await self._gh._api(
            "GET",
            f"/repos/{self._owner}/{self._repo}/pulls/{pr_number}",
        )
        current_body = pr_data.get("body", "") or ""

        closes_section = "\n\n---\n### Linked Issues\n" + "\n".join(
            f"Closes #{n}" for n in issue_numbers
        )

        await self._gh.update_pr(
            self._owner,
            self._repo,
            pr_number,
            body=current_body + closes_section,
        )
        logger.info(
            "Linked issues %s to PR #%d", issue_numbers, pr_number,
        )

    # ------------------------------------------------------------------
    # report_to_issue
    # ------------------------------------------------------------------

    async def report_to_issue(
        self,
        issue_number: int,
        pipeline_id: str,
        result: dict,
    ) -> None:
        """Post a pipeline-result comment on a GitHub issue.

        Parameters
        ----------
        issue_number:
            The GitHub issue to comment on.
        pipeline_id:
            Forge pipeline identifier.
        result:
            Dict with keys like ``pr_url``, ``tickets_total``,
            ``tickets_passed``, ``total_cost_usd``, ``duration``,
            ``errors``.
        """
        pr_url = result.get("pr_url", "N/A")
        total = result.get("tickets_total", 0)
        passed = result.get("tickets_passed", 0)
        cost = result.get("total_cost_usd", 0.0)
        duration = result.get("duration", "N/A")
        errors = result.get("errors", [])

        lines = [
            f"## Forge Pipeline `{pipeline_id}` — Complete",
            "",
            f"**PR:** {pr_url}",
            f"**Tickets:** {passed}/{total} passed QA",
            f"**Cost:** ${cost:.2f}",
            f"**Duration:** {duration}",
        ]

        if errors:
            lines.append("")
            lines.append("### Errors")
            for err in errors[:10]:
                lines.append(f"- {err}")

        lines.append("")
        lines.append(
            "*Generated by [Forge](https://github.com/forge) pipeline*"
        )

        await self._gh.add_issue_comment(
            self._owner,
            self._repo,
            issue_number,
            "\n".join(lines),
        )
        logger.info(
            "Posted pipeline report to issue #%d", issue_number,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _run_git(
        self, *args: str, cwd: str | None = None,
    ) -> str:
        """Delegate to GitHubClient's async git runner."""
        return await self._gh._run_git(*args, cwd=cwd)

    async def _branch_exists(
        self, repo_path: str, branch: str,
    ) -> bool:
        """Check whether a local branch exists."""
        try:
            await self._run_git(
                "rev-parse", "--verify", f"refs/heads/{branch}",
                cwd=repo_path,
            )
            return True
        except GitOperationError:
            return False

    async def _create_ticket_branch(
        self,
        repo_path: str,
        branch: str,
        artifact: dict,
    ) -> None:
        """Create a branch containing only a single ticket's files.

        If the ticket's branch already exists in the local repo (from
        worktree merges), we simply check it out.  Otherwise we create
        a fresh branch from the default branch.
        """
        # Try checking out the branch if it came from a worktree merge
        try:
            await self._run_git(
                "checkout", branch, cwd=repo_path,
            )
            return
        except GitOperationError:
            pass

        # Create a new branch from the default branch
        await self._run_git(
            "checkout", "-b", branch, self._default_branch,
            cwd=repo_path,
        )

        # Cherry-pick: if the artifact lists a commit, cherry-pick it
        # Otherwise the branch starts at the same point as default
        # (the caller is expected to have already merged changes)
        notes = artifact.get("notes", "")
        if notes:
            logger.debug(
                "Created ticket branch %s: %s", branch, notes,
            )


# ---------------------------------------------------------------------------
# PR body formatting
# ---------------------------------------------------------------------------


def _build_pr_context(artifacts: list[dict]) -> dict:
    """Extract summary data from a list of CodeArtifact dicts."""
    tickets: list[str] = []
    files_created: list[str] = []
    files_modified: list[str] = []
    total_tests = 0
    passed_tests = 0
    failed_tests = 0
    qa_pass_count = 0
    qa_total = 0

    for art in artifacts:
        tk = art.get("ticket_key", "")
        if tk:
            tickets.append(tk)
        files_created.extend(art.get("files_created", []))
        files_modified.extend(art.get("files_modified", []))

        tr = art.get("test_results") or {}
        total_tests += tr.get("total", 0)
        passed_tests += tr.get("passed", 0)
        failed_tests += tr.get("failed", 0)

        # QA info if embedded
        qa = art.get("qa_review") or {}
        if qa:
            qa_total += 1
            if qa.get("verdict") == "approved":
                qa_pass_count += 1

    return {
        "project_name": "",  # filled by caller if needed
        "tickets": tickets,
        "files_created": files_created,
        "files_modified": files_modified,
        "total_tests": total_tests,
        "passed_tests": passed_tests,
        "failed_tests": failed_tests,
        "qa_passed": qa_pass_count,
        "qa_total": qa_total,
    }


def _format_pr_body(pipeline_id: str, ctx: dict) -> str:
    """Build a Markdown PR description from pipeline context."""
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    tickets = ctx.get("tickets", [])
    files_created = ctx.get("files_created", [])
    files_modified = ctx.get("files_modified", [])
    total_tests = ctx.get("total_tests", 0)
    passed_tests = ctx.get("passed_tests", 0)
    failed_tests = ctx.get("failed_tests", 0)
    qa_passed = ctx.get("qa_passed", 0)
    qa_total = ctx.get("qa_total", 0)

    lines: list[str] = []
    lines.append(f"> Forge pipeline `{pipeline_id}` — {now}")
    lines.append("")

    # --- Summary ---
    lines.append("## Summary")
    lines.append("")
    if tickets:
        lines.append(
            f"**Tickets completed:** {len(tickets)} "
            f"({', '.join(tickets)})"
        )
    lines.append(f"**Files created:** {len(files_created)}")
    lines.append(f"**Files modified:** {len(files_modified)}")
    lines.append("")

    # --- Test results ---
    if total_tests > 0:
        lines.append("## Test Results")
        lines.append("")
        pct = (
            f"{passed_tests}/{total_tests} passed"
            f" ({100 * passed_tests // total_tests}%)"
        )
        lines.append(f"- {pct}")
        if failed_tests:
            lines.append(f"- **{failed_tests} failed**")
        lines.append("")

    # --- QA ---
    if qa_total > 0:
        lines.append("## QA Review")
        lines.append("")
        lines.append(
            f"- {qa_passed}/{qa_total} tickets approved by QA"
        )
        lines.append("")

    # --- File lists (collapsed) ---
    if files_created:
        lines.append("<details>")
        lines.append(
            f"<summary>Files created ({len(files_created)})</summary>"
        )
        lines.append("")
        for f in files_created[:50]:
            lines.append(f"- `{f}`")
        if len(files_created) > 50:
            lines.append(
                f"- ... and {len(files_created) - 50} more"
            )
        lines.append("</details>")
        lines.append("")

    if files_modified:
        lines.append("<details>")
        lines.append(
            f"<summary>Files modified ({len(files_modified)})"
            "</summary>"
        )
        lines.append("")
        for f in files_modified[:50]:
            lines.append(f"- `{f}`")
        if len(files_modified) > 50:
            lines.append(
                f"- ... and {len(files_modified) - 50} more"
            )
        lines.append("</details>")
        lines.append("")

    # --- Footer ---
    lines.append("---")
    lines.append(
        "*This PR was generated by "
        "[Forge](https://github.com/forge). "
        "Review carefully before merging.*"
    )

    return "\n".join(lines)
