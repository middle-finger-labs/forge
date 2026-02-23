#!/usr/bin/env python3
"""Automated smoke test validating the full Forge stack.

Checks infrastructure (PostgreSQL, Redis, Temporal), the Temporal worker
imports, the FastAPI server, all agent modules, model routing, and the
React dashboard build.

Usage::

    python -m scripts.smoke_test          # from repo root
    python scripts/smoke_test.py          # direct invocation

Exit code 0 if all checks pass, 1 if any fail.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import os
import signal
import subprocess
import sys

# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

_results: list[tuple[str, str, bool, str]] = []
"""(section, check_name, passed, detail)"""


def _record(section: str, name: str, passed: bool, detail: str = "") -> None:
    _results.append((section, name, passed, detail))


# ---------------------------------------------------------------------------
# 1. Infrastructure checks
# ---------------------------------------------------------------------------


async def check_postgresql() -> None:
    section = "Infrastructure"
    try:
        import asyncpg

        dsn = os.environ.get(
            "DATABASE_URL",
            "postgresql://forge:forge_dev_password@localhost:5432/forge_app",
        )
        conn = await asyncio.wait_for(asyncpg.connect(dsn), timeout=5)
        try:
            await conn.fetchval("SELECT 1")
            _record(section, "PostgreSQL reachable", True)

            # Check tables
            expected_tables = {
                "pipeline_runs",
                "ticket_executions",
                "agent_events",
                "cto_interventions",
                "memory_store",
            }
            rows = await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            actual_tables = {r["tablename"] for r in rows}
            missing = expected_tables - actual_tables
            if missing:
                _record(
                    section,
                    "PostgreSQL tables",
                    False,
                    f"Missing tables: {', '.join(sorted(missing))}",
                )
            else:
                count = len(expected_tables)
                _record(section, "PostgreSQL tables", True, f"{count} tables present")
        finally:
            await conn.close()
    except Exception as exc:
        _record(section, "PostgreSQL reachable", False, str(exc))


async def check_redis() -> None:
    section = "Infrastructure"
    try:
        import redis.asyncio as aioredis

        url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        r = aioredis.from_url(url, decode_responses=True)
        try:
            pong = await asyncio.wait_for(r.ping(), timeout=5)
            _record(section, "Redis reachable", bool(pong))
        finally:
            await r.aclose()
    except Exception as exc:
        _record(section, "Redis reachable", False, str(exc))


async def check_temporal() -> None:
    section = "Infrastructure"
    try:
        from temporalio.client import Client

        addr = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
        client = await asyncio.wait_for(
            Client.connect(addr, namespace="default"),
            timeout=5,
        )
        # If connect succeeds, the namespace exists and is reachable
        await client.service_client.check_health()
        _record(section, "Temporal reachable (default namespace)", True)
    except Exception as exc:
        _record(section, "Temporal reachable (default namespace)", False, str(exc))


# ---------------------------------------------------------------------------
# 2. Worker checks
# ---------------------------------------------------------------------------


def check_worker_imports() -> None:
    section = "Worker"

    # Import workflows
    try:
        from workflows.pipeline import ForgePipeline  # noqa: F401

        _record(section, "Import ForgePipeline workflow", True)
    except Exception as exc:
        _record(section, "Import ForgePipeline workflow", False, str(exc))

    # Import all activities
    try:
        from activities.pipeline_activities import ALL_ACTIVITIES

        _record(
            section,
            "Import ALL_ACTIVITIES",
            True,
            f"{len(ALL_ACTIVITIES)} activities",
        )
    except Exception as exc:
        _record(section, "Import ALL_ACTIVITIES", False, str(exc))
        return

    # Verify each activity has the @activity.defn decorator
    for act_fn in ALL_ACTIVITIES:
        name = getattr(act_fn, "__name__", str(act_fn))
        has_defn = getattr(act_fn, "__temporal_activity_definition", None) is not None
        _record(
            section,
            f"@activity.defn on {name}",
            has_defn,
            "" if has_defn else "missing @activity.defn decorator",
        )


# ---------------------------------------------------------------------------
# 3. API server checks
# ---------------------------------------------------------------------------


async def check_api_server() -> None:
    section = "API Server"
    import urllib.error
    import urllib.request

    port = int(os.environ.get("FORGE_API_PORT", "8765"))
    base = f"http://127.0.0.1:{port}"

    # Start the API server as a subprocess on a test port
    env = {**os.environ, "FORGE_API_PORT": str(port)}
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "api.server:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        # Start in a new process group so we can kill the tree
        preexec_fn=os.setsid,
    )

    try:
        # Wait for the server to be ready (up to 10 s)
        ready = False
        for _ in range(40):
            await asyncio.sleep(0.25)
            try:
                req = urllib.request.Request(f"{base}/api/health", method="GET")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    if resp.status == 200:
                        ready = True
                        break
            except (urllib.error.URLError, OSError):
                continue

        if not ready:
            _record(section, "Server started", False, "Timed out waiting for /api/health")
            return

        _record(section, "Server started", True, f"port {port}")

        # GET /api/health
        import json

        try:
            req = urllib.request.Request(f"{base}/api/health", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read())
                healthy = body.get("healthy", False)
                services = body.get("services", {})
                detail = ", ".join(f"{k}={v}" for k, v in services.items())
                _record(section, "GET /api/health", healthy, detail)
        except Exception as exc:
            _record(section, "GET /api/health", False, str(exc))

        # GET /api/pipelines
        try:
            req = urllib.request.Request(f"{base}/api/pipelines", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read())
                is_list = isinstance(body, list)
                if is_list:
                    detail = f"{len(body)} pipelines"
                else:
                    detail = f"Expected list, got {type(body).__name__}"
                _record(section, "GET /api/pipelines", is_list, detail)
        except Exception as exc:
            _record(section, "GET /api/pipelines", False, str(exc))

    finally:
        # Kill the process group
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=3)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 4. Agent checks
# ---------------------------------------------------------------------------

# (agent_module, run_function_name, stage_module)
_AGENTS = [
    ("agents.ba_agent", "run_ba_agent", "agents.stage_1_business_analyst"),
    ("agents.researcher_agent", "run_researcher_agent", "agents.stage_2_researcher"),
    ("agents.architect_agent", "run_architect_agent", "agents.stage_3_architect"),
    ("agents.pm_agent", "run_pm_agent", "agents.stage_4_pm"),
    ("agents.coding_agent", "run_coding_agent_task", "agents.stage_5_engineer"),
    ("agents.qa_agent", "run_qa_agent", "agents.stage_6_qa"),
    ("agents.cto_agent", "run_cto_agent", "agents.stage_7_cto"),
]


def check_agents() -> None:
    section = "Agents"

    for agent_mod, func_name, stage_mod in _AGENTS:
        short = agent_mod.split(".")[-1]

        # Import agent module + run function
        try:
            mod = importlib.import_module(agent_mod)
            fn = getattr(mod, func_name, None)
            if fn is None:
                _record(section, f"{short}: {func_name} exists", False, "function not found")
                continue
            if not inspect.iscoroutinefunction(fn):
                _record(
                    section,
                    f"{short}: {func_name} is async",
                    False,
                    "not a coroutine function",
                )
                continue
            _record(section, f"{short}: {func_name} exists (async)", True)
        except Exception as exc:
            _record(section, f"{short}: import", False, str(exc))
            continue

        # Import stage module and check prompt constants
        try:
            stage = importlib.import_module(stage_mod)
            has_sys = hasattr(stage, "SYSTEM_PROMPT")
            has_human = hasattr(stage, "HUMAN_PROMPT_TEMPLATE")
            if has_sys and has_human:
                _record(section, f"{short}: SYSTEM_PROMPT + HUMAN_PROMPT_TEMPLATE", True)
            else:
                missing = []
                if not has_sys:
                    missing.append("SYSTEM_PROMPT")
                if not has_human:
                    missing.append("HUMAN_PROMPT_TEMPLATE")
                _record(
                    section,
                    f"{short}: prompt constants",
                    False,
                    f"Missing: {', '.join(missing)}",
                )
        except Exception as exc:
            _record(section, f"{short}: stage module import", False, str(exc))


# ---------------------------------------------------------------------------
# 5. Model routing checks
# ---------------------------------------------------------------------------


async def check_model_routing() -> None:
    section = "Model Routing"

    try:
        from config.model_router import ModelRouter, get_model_router  # noqa: F401

        _record(section, "Import ModelRouter", True)
    except Exception as exc:
        _record(section, "Import ModelRouter", False, str(exc))
        return

    try:
        router = get_model_router()
        _record(section, "get_model_router() singleton", True)
    except Exception as exc:
        _record(section, "get_model_router() singleton", False, str(exc))
        return

    # Route for each agent role
    roles = [
        "architect",
        "qa",
        "cto",
        "business_analyst",
        "researcher",
        "pm",
        "developer",
        "engineer",
    ]
    for role in roles:
        try:
            model = await router.route_request(role)
            _record(section, f"route_request({role!r})", True, f"-> {model}")
        except Exception as exc:
            _record(section, f"route_request({role!r})", False, str(exc))

    # Tiny API call if ANTHROPIC_API_KEY is set
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key)
            client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
            _record(section, "Anthropic API key works", True)
        except Exception as exc:
            _record(section, "Anthropic API key works", False, str(exc))
    else:
        _record(
            section,
            "Anthropic API key works",
            True,
            "SKIPPED — ANTHROPIC_API_KEY not set",
        )


# ---------------------------------------------------------------------------
# 6. Dashboard build check
# ---------------------------------------------------------------------------


def check_dashboard() -> None:
    section = "Dashboard"
    dashboard_dir = os.path.join(os.path.dirname(__file__), "..", "dashboard")
    dashboard_dir = os.path.normpath(dashboard_dir)

    if not os.path.isdir(dashboard_dir):
        _record(section, "dashboard/ directory exists", False, f"Not found: {dashboard_dir}")
        return
    _record(section, "dashboard/ directory exists", True)

    node_modules = os.path.join(dashboard_dir, "node_modules")
    if not os.path.isdir(node_modules):
        _record(section, "npm run build", True, "SKIPPED — node_modules not installed")
        return

    try:
        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=dashboard_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            _record(section, "npm run build", True)
        else:
            # Grab last few lines of stderr for context
            stderr_tail = "\n".join(result.stderr.strip().splitlines()[-5:])
            _record(section, "npm run build", False, stderr_tail or result.stdout[-300:])
    except subprocess.TimeoutExpired:
        _record(section, "npm run build", False, "Timed out after 120s")
    except FileNotFoundError:
        _record(section, "npm run build", False, "npm not found on PATH")
    except Exception as exc:
        _record(section, "npm run build", False, str(exc))


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def print_report() -> None:
    current_section = ""
    passed = 0
    failed = 0

    for section, name, ok, detail in _results:
        if section != current_section:
            current_section = section
            print(f"\n{'─' * 60}")
            print(f"  {section}")
            print(f"{'─' * 60}")

        icon = "✅" if ok else "❌"
        line = f"  {icon} {name}"
        if detail:
            line += f"  ({detail})"
        print(line)

        if ok:
            passed += 1
        else:
            failed += 1

    total = passed + failed
    print(f"\n{'═' * 60}")
    print(f"  Results: {passed}/{total} passed", end="")
    if failed:
        print(f", {failed} FAILED")
    else:
        print(" — all clear")
    print(f"{'═' * 60}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> int:
    # Suppress structlog noise during checks
    try:
        import structlog

        structlog.configure(
            wrapper_class=structlog.make_filtering_bound_logger(50),  # CRITICAL only
        )
    except Exception:
        pass

    print("Forge Smoke Test")
    print(f"Working directory: {os.getcwd()}")
    print(f"Python: {sys.executable}")

    # 1. Infrastructure
    await check_postgresql()
    await check_redis()
    await check_temporal()

    # 2. Worker imports (sync)
    check_worker_imports()

    # 3. API server
    await check_api_server()

    # 4. Agents (sync)
    check_agents()

    # 5. Model routing
    await check_model_routing()

    # 6. Dashboard (sync)
    check_dashboard()

    # Report
    print_report()

    any_failed = any(not ok for _, _, ok, _ in _results)
    return 1 if any_failed else 0


if __name__ == "__main__":
    # Ensure we're running from the repo root so relative imports work
    repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    os.chdir(repo_root)

    exit_code = asyncio.run(main())
    sys.exit(exit_code)
