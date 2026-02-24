"""CLI for interacting with the Forge pipeline.

Usage — pipeline commands:
    python run_pipeline.py start --spec "Build a todo app" --name TodoApp
    python run_pipeline.py start --spec-file spec.txt
    python run_pipeline.py start --repo git@github.com:owner/repo.git --spec "Add OAuth"
    python run_pipeline.py start --repo git@github.com:owner/repo.git --issue 42
    python run_pipeline.py start --repo git@github.com:owner/repo.git \\
        --spec-file req.md --identity draftkings
    python run_pipeline.py approve <pipeline_id> --stage business_analysis
    python run_pipeline.py reject  <pipeline_id> --stage business_analysis --notes "Missing auth"
    python run_pipeline.py status  <pipeline_id>
    python run_pipeline.py abort   <pipeline_id> --reason "Wrong spec"
    python run_pipeline.py retry   <pipeline_id> --stage coding

Usage — identity management:
    python run_pipeline.py identities list
    python run_pipeline.py identities test <name>
    python run_pipeline.py identities add

Usage — repo testing:
    python run_pipeline.py repos test <repo_url>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import tempfile
from uuid import uuid4

from temporalio.client import Client

from workflows.pipeline import PIPELINE_QUEUE, ForgePipeline
from workflows.types import (
    ApprovalStatus,
    HumanApproval,
    PipelineInput,
    PipelineStage,
    RetryStageRequest,
)

TEMPORAL_ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
TEMPORAL_NAMESPACE = os.environ.get("TEMPORAL_NAMESPACE", "default")

WORKFLOW_ID_PREFIX = "forge-pipeline"


def workflow_id(pipeline_id: str) -> str:
    return f"{WORKFLOW_ID_PREFIX}-{pipeline_id}"


# ---------------------------------------------------------------------------
# Subcommands — pipeline
# ---------------------------------------------------------------------------


async def cmd_start(args: argparse.Namespace) -> None:
    """Start a new pipeline run."""
    from integrations.git_identity import parse_github_url

    # -- Resolve business spec --
    spec_text: str | None = None

    if getattr(args, "issue", None) and getattr(args, "repo", None):
        # Fetch issue body from GitHub as the spec
        spec_text = await _fetch_issue_spec(args.repo, args.issue, args.identity)
    elif args.spec_file:
        with open(args.spec_file) as f:
            spec_text = f.read()
    elif args.spec:
        spec_text = args.spec

    if not spec_text:
        print("error: provide --spec, --spec-file, or --issue (with --repo)", file=sys.stderr)
        sys.exit(1)

    # -- Parse repo info --
    repo_url = getattr(args, "repo", None)
    repo_owner: str | None = None
    repo_name: str | None = None
    if repo_url:
        parsed = parse_github_url(repo_url)
        if parsed:
            repo_owner, repo_name = parsed
        else:
            print(f"warning: could not parse owner/name from repo URL: {repo_url}", file=sys.stderr)

    issue_number = getattr(args, "issue", None)
    identity_name = getattr(args, "identity", None)
    pr_strategy = getattr(args, "pr_strategy", "single_pr")

    pipeline_id = args.id or uuid4().hex[:12]
    project_name = args.name or repo_name or "forge-project"
    wf_id = workflow_id(pipeline_id)

    client = await Client.connect(TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE)

    target_branch = getattr(args, "target_branch", "main")

    pipeline_input = PipelineInput(
        pipeline_id=pipeline_id,
        business_spec=spec_text,
        project_name=project_name,
        repo_url=repo_url,
        repo_owner=repo_owner,
        repo_name=repo_name,
        git_identity_name=identity_name,
        issue_number=issue_number,
        pr_strategy=pr_strategy,
        target_branch=target_branch,
    )

    handle = await client.start_workflow(
        ForgePipeline.run,
        pipeline_input,
        id=wf_id,
        task_queue=PIPELINE_QUEUE,
    )

    print("Pipeline started.")
    print(f"  Pipeline ID:  {pipeline_id}")
    print(f"  Workflow ID:  {wf_id}")
    print(f"  Run ID:       {handle.result_run_id}")
    if repo_url:
        print(f"  Repository:   {repo_owner}/{repo_name}")
        print(f"  PR strategy:  {pr_strategy}")
    if issue_number:
        print(f"  Issue:        #{issue_number}")
    if identity_name:
        print(f"  Identity:     {identity_name}")
    print()
    print("Next steps:")
    print(f"  Check status:  python run_pipeline.py status {pipeline_id}")
    print(
        f"  Approve BA:    python run_pipeline.py approve {pipeline_id} --stage business_analysis"
    )
    print(f"  Approve arch:  python run_pipeline.py approve {pipeline_id} --stage architecture")
    print(f"  Abort:         python run_pipeline.py abort {pipeline_id}")


async def _fetch_issue_spec(repo_url: str, issue_number: int, identity_name: str | None) -> str:
    """Fetch a GitHub issue and format it as a business spec."""
    from integrations.git_identity import GitIdentityManager, parse_github_url
    from integrations.github_client import GitHubClient
    from integrations.issue_tracker import IssueTracker

    parsed = parse_github_url(repo_url)
    if not parsed:
        print(f"error: cannot parse repo URL: {repo_url}", file=sys.stderr)
        sys.exit(1)
    owner, repo = parsed

    mgr = GitIdentityManager()
    if identity_name:
        identity = mgr.get_identity(identity_name)
        if identity is None:
            print(f"error: identity '{identity_name}' not found", file=sys.stderr)
            sys.exit(1)
    else:
        identity = mgr.resolve_identity(repo_url)

    print(f"Fetching issue #{issue_number} from {owner}/{repo}...")
    async with GitHubClient(identity) as gh:
        tracker = IssueTracker(gh, owner, repo)
        spec = await tracker.get_issue_as_spec(issue_number)

    print(f"  Issue fetched ({len(spec)} chars)")
    return spec


async def cmd_approve(args: argparse.Namespace) -> None:
    """Send an approval signal for a pending stage."""

    client = await Client.connect(TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE)
    wf_id = workflow_id(args.pipeline_id)
    handle = client.get_workflow_handle(wf_id)

    approval = HumanApproval(
        stage=PipelineStage(args.stage),
        status=ApprovalStatus.APPROVED,
        notes=args.notes or "",
        approved_by=args.user or "cli-user",
    )

    await handle.signal(ForgePipeline.human_approval, approval)
    print(f"Approved stage '{args.stage}' for pipeline {args.pipeline_id}")


async def cmd_reject(args: argparse.Namespace) -> None:
    """Send a rejection signal for a pending stage."""

    client = await Client.connect(TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE)
    wf_id = workflow_id(args.pipeline_id)
    handle = client.get_workflow_handle(wf_id)

    rejection = HumanApproval(
        stage=PipelineStage(args.stage),
        status=ApprovalStatus.REJECTED,
        notes=args.notes or "",
        approved_by=args.user or "cli-user",
    )

    await handle.signal(ForgePipeline.human_approval, rejection)
    print(f"Rejected stage '{args.stage}' for pipeline {args.pipeline_id}")
    if args.notes:
        print(f"  Notes: {args.notes}")


async def cmd_status(args: argparse.Namespace) -> None:
    """Query pipeline state and cost."""

    client = await Client.connect(TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE)
    wf_id = workflow_id(args.pipeline_id)
    handle = client.get_workflow_handle(wf_id)

    state = await handle.query(ForgePipeline.get_state)
    cost = await handle.query(ForgePipeline.get_cost)

    state["total_cost_usd_queried"] = cost

    print(json.dumps(state, indent=2, default=str))


async def cmd_abort(args: argparse.Namespace) -> None:
    """Abort a running pipeline."""

    client = await Client.connect(TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE)
    wf_id = workflow_id(args.pipeline_id)
    handle = client.get_workflow_handle(wf_id)

    reason = args.reason or "Aborted via CLI"
    await handle.signal(ForgePipeline.abort, reason)
    print(f"Abort signal sent to pipeline {args.pipeline_id}")
    print(f"  Reason: {reason}")


async def cmd_retry(args: argparse.Namespace) -> None:
    """Send a retry signal to resume a failed pipeline from a specific stage."""

    client = await Client.connect(TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE)
    handle = client.get_workflow_handle(workflow_id(args.pipeline_id))

    await handle.signal(
        ForgePipeline.retry_stage,
        RetryStageRequest(stage=PipelineStage(args.stage), requested_by="cli-user"),
    )
    print(f"Retry signal sent for stage '{args.stage}' on pipeline {args.pipeline_id}")


# ---------------------------------------------------------------------------
# Subcommands — identities
# ---------------------------------------------------------------------------


def cmd_identities_list(_args: argparse.Namespace) -> None:
    """List all configured Git identities."""
    from integrations.git_identity import GitIdentityManager

    mgr = GitIdentityManager()
    identities = mgr.list_identities()

    if not identities:
        print("No identities configured.")
        print()
        print("Run 'python run_pipeline.py identities add' to set up an identity,")
        print("or 'bash scripts/setup_github.sh' for the guided setup wizard.")
        return

    print(f"{'Name':<20} {'Username':<20} {'Org':<18} {'Key':<35} {'Default'}")
    print("-" * 100)
    for ident in identities:
        default_marker = "*" if ident.default else ""
        org = ident.github_org or "-"
        print(
            f"{ident.name:<20} {ident.github_username:<20} "
            f"{org:<18} {ident.ssh_key_path:<35} {default_marker}"
        )


def cmd_identities_test(args: argparse.Namespace) -> None:
    """Test SSH connection for a named identity."""
    from integrations.git_identity import GitIdentityManager

    mgr = GitIdentityManager()
    identity = mgr.get_identity(args.identity_name)
    if identity is None:
        print(f"error: identity '{args.identity_name}' not found", file=sys.stderr)
        sys.exit(1)

    print(f"Testing identity '{identity.name}'...")
    print(f"  SSH key:  {identity.ssh_key_path}")
    print(f"  Username: {identity.github_username}")
    print(f"  Email:    {identity.email}")
    print()

    result = mgr.setup_identity(identity)

    if result["key_exists"]:
        print("  SSH key:      found")
    else:
        print("  SSH key:      NOT FOUND")
        print(f"  Error:        {result['error']}")
        return

    if result["connection_ok"]:
        print(f"  Connection:   OK (authenticated as {result['github_user']})")
    else:
        print("  Connection:   FAILED")
        print(f"  Error:        {result['error']}")


def cmd_identities_add(_args: argparse.Namespace) -> None:
    """Interactive setup: add a new Git identity."""
    from integrations.git_identity import GitIdentity, GitIdentityManager

    mgr = GitIdentityManager()
    existing = {ident.name for ident in mgr.list_identities()}

    print("Add a new GitHub identity")
    print("=" * 40)
    print()

    name = input("Short name (e.g. 'personal', 'work'):  ").strip()
    if not name:
        print("error: name is required", file=sys.stderr)
        sys.exit(1)
    if name in existing:
        confirm = input(f"Identity '{name}' already exists. Overwrite? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Cancelled.")
            return

    username = input("GitHub username:  ").strip()
    if not username:
        print("error: username is required", file=sys.stderr)
        sys.exit(1)

    email = input(f"Commit email [{username}@users.noreply.github.com]:  ").strip()
    if not email:
        email = f"{username}@users.noreply.github.com"

    default_key = f"~/.ssh/id_ed25519_{name}"
    ssh_key = input(f"SSH key path [{default_key}]:  ").strip()
    if not ssh_key:
        ssh_key = default_key

    default_alias = f"github-{name}"
    ssh_alias = input(f"SSH host alias [{default_alias}]:  ").strip()
    if not ssh_alias:
        ssh_alias = default_alias

    org = input("GitHub org (leave blank for personal):  ").strip() or None

    is_default = False
    if not any(ident.default for ident in mgr.list_identities()):
        is_default = True
        print("  (Setting as default — first identity)")
    else:
        resp = input("Set as default identity? [y/N]:  ").strip().lower()
        is_default = resp == "y"

    identity = GitIdentity(
        name=name,
        github_username=username,
        email=email,
        ssh_key_path=ssh_key,
        ssh_host_alias=ssh_alias,
        github_org=org,
        default=is_default,
    )

    # Test connection
    print()
    print("Testing SSH connection...")
    result = mgr.setup_identity(identity)

    if not result["key_exists"]:
        print(f"  WARNING: SSH key not found at {ssh_key}")
        proceed = input("  Save anyway? [y/N]: ").strip().lower()
        if proceed != "y":
            print("Cancelled.")
            return
    elif not result["connection_ok"]:
        print(f"  WARNING: SSH connection failed — {result['error']}")
        proceed = input("  Save anyway? [y/N]: ").strip().lower()
        if proceed != "y":
            print("Cancelled.")
            return
    else:
        print(f"  Connected as: {result['github_user']}")

    mgr.add_identity(identity)
    print()
    print(f"Identity '{name}' saved.")

    # Offer SSH config block
    print()
    print("Recommended ~/.ssh/config block:")
    print()
    print(mgr.generate_ssh_config_block(identity))
    print()
    add_config = input("Append to ~/.ssh/config? [y/N]: ").strip().lower()
    if add_config == "y":
        _append_ssh_config(mgr.generate_ssh_config_block(identity))
        print("  Appended to ~/.ssh/config")


def _append_ssh_config(block: str) -> None:
    """Append an SSH config block if it isn't already present."""
    ssh_config = os.path.expanduser("~/.ssh/config")
    existing = ""
    if os.path.isfile(ssh_config):
        with open(ssh_config) as f:
            existing = f.read()

    # Check if the host alias is already configured
    first_line = block.strip().split("\n")[0]
    if first_line in existing:
        print("  (block already present — skipping)")
        return

    with open(ssh_config, "a") as f:
        f.write("\n" + block + "\n")


# ---------------------------------------------------------------------------
# Subcommands — repos
# ---------------------------------------------------------------------------


async def cmd_repos_test(args: argparse.Namespace) -> None:
    """Clone a repo to a temp dir, verify access, show info, and clean up."""
    from integrations.git_identity import GitIdentityManager, parse_github_url
    from integrations.github_client import GitHubClient

    repo_url = args.repo_url

    parsed = parse_github_url(repo_url)
    if not parsed:
        print(f"error: cannot parse repo URL: {repo_url}", file=sys.stderr)
        sys.exit(1)
    owner, repo = parsed

    mgr = GitIdentityManager()
    identity_name = getattr(args, "identity", None)
    if identity_name:
        identity = mgr.get_identity(identity_name)
        if identity is None:
            print(f"error: identity '{identity_name}' not found", file=sys.stderr)
            sys.exit(1)
    else:
        identity = mgr.resolve_identity(repo_url)

    print(f"Testing access to {owner}/{repo}")
    print(f"  Identity:  {identity.name} ({identity.github_username})")
    print(f"  SSH key:   {identity.ssh_key_path}")
    print()

    # API access
    print("1. Checking API access...")
    async with GitHubClient(identity) as gh:
        try:
            info = await gh.get_repo_info(owner, repo)
            print(f"   Repository:       {info['full_name']}")
            print(f"   Default branch:   {info['default_branch']}")
            print(f"   Language:         {info.get('language') or 'N/A'}")
            print(f"   Visibility:       {info.get('visibility', 'unknown')}")
            desc = info.get("description") or "N/A"
            if len(desc) > 60:
                desc = desc[:57] + "..."
            print(f"   Description:      {desc}")
        except Exception as exc:
            print(f"   FAILED: {exc}")
            return

    # Clone access
    print()
    print("2. Testing clone (shallow)...")
    tmp_dir = tempfile.mkdtemp(prefix="forge-test-")
    try:
        async with GitHubClient(identity) as gh:
            dest = os.path.join(tmp_dir, repo)
            await gh.clone_repo(repo_url, dest, branch=info["default_branch"], depth=1)
            print(f"   Cloned to: {dest}")

        # Show recent commits
        import subprocess

        git_env = {**os.environ, **mgr.get_git_env(identity)}
        result = subprocess.run(
            ["git", "log", "--oneline", "-5", "--no-color"],
            capture_output=True,
            text=True,
            cwd=dest,
            env=git_env,
        )
        if result.returncode == 0 and result.stdout.strip():
            print()
            print("3. Recent commits:")
            for line in result.stdout.strip().split("\n"):
                print(f"   {line}")
        print()
        print("All checks passed.")

    except Exception as exc:
        print(f"   Clone FAILED: {exc}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

VALID_APPROVAL_STAGES = ["business_analysis", "architecture"]

PR_STRATEGIES = ["single_pr", "pr_per_ticket", "direct_push"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_pipeline",
        description="Forge pipeline CLI — start, approve, reject, query, and abort pipelines.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # -- start --
    p_start = sub.add_parser("start", help="Start a new pipeline run")
    spec_group = p_start.add_mutually_exclusive_group()
    spec_group.add_argument("--spec", type=str, help="Business spec as inline text")
    spec_group.add_argument("--spec-file", type=str, help="Path to a file containing the spec")
    p_start.add_argument(
        "--repo", type=str, default=None,
        help="GitHub repo URL to clone and work against",
    )
    p_start.add_argument(
        "--issue", type=int, default=None,
        help="GitHub issue number to use as spec (requires --repo)",
    )
    p_start.add_argument(
        "--identity", type=str, default=None,
        help="Git identity name (from identities.yaml)",
    )
    p_start.add_argument(
        "--pr-strategy", type=str, default="single_pr",
        choices=PR_STRATEGIES, help="PR strategy",
    )
    p_start.add_argument(
        "--id",
        type=str,
        default=None,
        help="Pipeline ID (auto-generated if omitted)",
    )
    p_start.add_argument("--name", type=str, default=None, help="Project name")
    p_start.add_argument(
        "--target-branch", type=str, default="main",
        help="Branch to clone and target PRs against (default: main)",
    )

    # -- approve --
    p_approve = sub.add_parser("approve", help="Approve a pending stage")
    p_approve.add_argument("pipeline_id", type=str)
    p_approve.add_argument("--stage", required=True, choices=VALID_APPROVAL_STAGES)
    p_approve.add_argument("--notes", type=str, default="")
    p_approve.add_argument("--user", type=str, default=None, help="Approver identity")

    # -- reject --
    p_reject = sub.add_parser("reject", help="Reject a pending stage")
    p_reject.add_argument("pipeline_id", type=str)
    p_reject.add_argument("--stage", required=True, choices=VALID_APPROVAL_STAGES)
    p_reject.add_argument("--notes", type=str, default="")
    p_reject.add_argument("--user", type=str, default=None, help="Rejector identity")

    # -- status --
    p_status = sub.add_parser("status", help="Query pipeline state and cost")
    p_status.add_argument("pipeline_id", type=str)

    # -- abort --
    p_abort = sub.add_parser("abort", help="Abort a running pipeline")
    p_abort.add_argument("pipeline_id", type=str)
    p_abort.add_argument("--reason", type=str, default=None, help="Abort reason")

    # -- retry --
    p_retry = sub.add_parser("retry", help="Retry a failed pipeline from a specific stage")
    p_retry.add_argument("pipeline_id", type=str)
    p_retry.add_argument(
        "--stage", required=True,
        choices=[s.value for s in PipelineStage
                 if s not in (PipelineStage.INTAKE, PipelineStage.COMPLETE, PipelineStage.FAILED)],
    )

    # -- identities --
    p_ident = sub.add_parser("identities", help="Manage Git identities")
    ident_sub = p_ident.add_subparsers(dest="identities_command", required=True)

    ident_sub.add_parser("list", help="List configured identities")

    p_ident_test = ident_sub.add_parser("test", help="Test SSH connection for an identity")
    p_ident_test.add_argument("identity_name", type=str, help="Identity short name")

    ident_sub.add_parser("add", help="Interactively add a new identity")

    # -- repos --
    p_repos = sub.add_parser("repos", help="Test repository access")
    repos_sub = p_repos.add_subparsers(dest="repos_command", required=True)

    p_repos_test = repos_sub.add_parser("test", help="Clone and verify access to a repo")
    p_repos_test.add_argument("repo_url", type=str, help="GitHub repo URL")
    p_repos_test.add_argument("--identity", type=str, default=None, help="Identity to use")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Sync commands (no Temporal needed)
    if args.command == "identities":
        sync_dispatch = {
            "list": cmd_identities_list,
            "test": cmd_identities_test,
            "add": cmd_identities_add,
        }
        try:
            sync_dispatch[args.identities_command](args)
        except KeyboardInterrupt:
            pass
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(1)
        return

    # Async commands
    async_dispatch = {
        "start": cmd_start,
        "approve": cmd_approve,
        "reject": cmd_reject,
        "status": cmd_status,
        "abort": cmd_abort,
        "retry": cmd_retry,
        "repos": lambda a: cmd_repos_test(a),
    }

    try:
        asyncio.run(async_dispatch[args.command](args))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
