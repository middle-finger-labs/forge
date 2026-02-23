"""Project scaffolding — generates a realistic initial codebase from a TechSpec.

Runs once before the coding swarm starts.  The scaffold commit lives on
``main`` so every worktree branches from a consistent base that includes
config files, directory structure, shared utilities, and placeholder modules.

Usage::

    from agents.project_scaffold import scaffold_project

    await scaffold_project("/tmp/forge/project", tech_spec_dict)
"""

from __future__ import annotations

import asyncio
import json
import os

import structlog

log = structlog.get_logger().bind(component="project_scaffold")


# ---------------------------------------------------------------------------
# Tech-stack detection
# ---------------------------------------------------------------------------


def _detect_stack(tech_stack: dict[str, str]) -> str:
    """Return ``"node"`` or ``"python"`` based on the tech_stack dict."""
    values = " ".join(v.lower() for v in tech_stack.values())
    keys = " ".join(k.lower() for k in tech_stack)

    if any(kw in values for kw in ("node", "typescript", "javascript", "express", "next")):
        return "node"
    if any(kw in keys for kw in ("runtime",)) and "node" in values:
        return "node"
    # Default to python (the pipeline itself is python-based)
    return "python"


# ---------------------------------------------------------------------------
# File generators — Node / TypeScript
# ---------------------------------------------------------------------------


def _node_package_json(tech_spec: dict) -> str:
    """Generate a package.json with deps inferred from the tech spec."""
    tech_stack = tech_spec.get("tech_stack", {})
    services = tech_spec.get("services", [])

    # Base dependencies
    deps: dict[str, str] = {}
    dev_deps: dict[str, str] = {
        "typescript": "^5.7.0",
        "@types/node": "^22.0.0",
    }

    # Infer from tech_stack values
    stack_text = " ".join(v.lower() for v in tech_stack.values())

    if "express" in stack_text:
        deps["express"] = "^4.21.0"
        dev_deps["@types/express"] = "^5.0.0"
    if "fastify" in stack_text:
        deps["fastify"] = "^5.2.0"
    if "drizzle" in stack_text:
        deps["drizzle-orm"] = "^0.38.0"
        dev_deps["drizzle-kit"] = "^0.30.0"
    if "prisma" in stack_text:
        deps["@prisma/client"] = "^6.2.0"
        dev_deps["prisma"] = "^6.2.0"
    if "postgres" in stack_text or "pg" in stack_text:
        deps["pg"] = "^8.13.0"
        dev_deps["@types/pg"] = "^8.11.0"
    if "redis" in stack_text:
        deps["ioredis"] = "^5.4.0"
    if "zod" in stack_text:
        deps["zod"] = "^3.24.0"

    # Testing
    if "vitest" in stack_text:
        dev_deps["vitest"] = "^3.0.0"
    elif "jest" in stack_text:
        dev_deps["jest"] = "^29.7.0"
        dev_deps["@types/jest"] = "^29.5.0"
        dev_deps["ts-jest"] = "^29.2.0"
    else:
        dev_deps["vitest"] = "^3.0.0"

    # Linting
    dev_deps["eslint"] = "^9.18.0"
    dev_deps["prettier"] = "^3.4.0"

    # Ensure at least one framework if endpoints exist
    if services and not deps:
        deps["express"] = "^4.21.0"
        dev_deps["@types/express"] = "^5.0.0"

    # dotenv for env handling
    deps["dotenv"] = "^16.4.0"

    pkg = {
        "name": "forge-project",
        "version": "0.1.0",
        "private": True,
        "type": "module",
        "scripts": {
            "build": "tsc",
            "dev": "tsx watch src/index.ts",
            "start": "node dist/index.js",
            "test": "vitest run",
            "lint": "eslint src/",
            "format": "prettier --write 'src/**/*.ts'",
        },
        "dependencies": dict(sorted(deps.items())),
        "devDependencies": dict(sorted(dev_deps.items())),
    }
    return json.dumps(pkg, indent=2) + "\n"


def _node_tsconfig() -> str:
    return (
        json.dumps(
            {
                "compilerOptions": {
                    "target": "ES2022",
                    "module": "NodeNext",
                    "moduleResolution": "NodeNext",
                    "outDir": "dist",
                    "rootDir": "src",
                    "strict": True,
                    "esModuleInterop": True,
                    "skipLibCheck": True,
                    "forceConsistentCasingInFileNames": True,
                    "resolveJsonModule": True,
                    "declaration": True,
                    "declarationMap": True,
                    "sourceMap": True,
                },
                "include": ["src"],
                "exclude": ["node_modules", "dist"],
            },
            indent=2,
        )
        + "\n"
    )


def _node_eslint() -> str:
    return (
        json.dumps(
            {
                "root": True,
                "parser": "@typescript-eslint/parser",
                "plugins": ["@typescript-eslint"],
                "extends": [
                    "eslint:recommended",
                    "plugin:@typescript-eslint/recommended",
                ],
                "rules": {
                    "no-console": "warn",
                    "@typescript-eslint/no-unused-vars": [
                        "error",
                        {"argsIgnorePattern": "^_"},
                    ],
                    "@typescript-eslint/explicit-function-return-type": "error",
                },
            },
            indent=2,
        )
        + "\n"
    )


def _node_prettierrc() -> str:
    return (
        json.dumps(
            {
                "semi": True,
                "singleQuote": True,
                "trailingComma": "all",
                "printWidth": 100,
                "tabWidth": 2,
            },
            indent=2,
        )
        + "\n"
    )


def _node_gitignore() -> str:
    return "node_modules/\ndist/\n.env\n.env.local\n*.log\ncoverage/\n.DS_Store\n"


def _node_app_error() -> str:
    return (
        "/**\n"
        " * Base error class for application-level errors.\n"
        " * Extend this for feature-specific error types.\n"
        " */\n"
        "export class AppError extends Error {\n"
        "  public readonly statusCode: number;\n"
        "  public readonly code: string;\n"
        "\n"
        "  constructor(message: string, statusCode = 500, code = 'INTERNAL_ERROR') {\n"
        "    super(message);\n"
        "    this.name = 'AppError';\n"
        "    this.statusCode = statusCode;\n"
        "    this.code = code;\n"
        "  }\n"
        "}\n"
        "\n"
        "export class NotFoundError extends AppError {\n"
        "  constructor(resource: string, id?: string) {\n"
        "    const detail = id ? `${resource} '${id}' not found` : `${resource} not found`;\n"
        "    super(detail, 404, 'NOT_FOUND');\n"
        "    this.name = 'NotFoundError';\n"
        "  }\n"
        "}\n"
        "\n"
        "export class ValidationError extends AppError {\n"
        "  constructor(message: string) {\n"
        "    super(message, 400, 'VALIDATION_ERROR');\n"
        "    this.name = 'ValidationError';\n"
        "  }\n"
        "}\n"
    )


def _node_logger() -> str:
    return (
        "/**\n"
        " * Structured logger for the application.\n"
        " */\n"
        "export interface LogContext {\n"
        "  [key: string]: unknown;\n"
        "}\n"
        "\n"
        "function formatMessage(level: string, msg: string, ctx: LogContext): string {\n"
        "  const ts = new Date().toISOString();\n"
        "  const extra = Object.keys(ctx).length\n"
        "    ? ' ' + JSON.stringify(ctx)\n"
        "    : '';\n"
        "  return `${ts} [${level.toUpperCase()}] ${msg}${extra}`;\n"
        "}\n"
        "\n"
        "export const logger = {\n"
        "  info: (msg: string, ctx: LogContext = {}): void =>\n"
        "    console.info(formatMessage('info', msg, ctx)),\n"
        "  warn: (msg: string, ctx: LogContext = {}): void =>\n"
        "    console.warn(formatMessage('warn', msg, ctx)),\n"
        "  error: (msg: string, ctx: LogContext = {}): void =>\n"
        "    console.error(formatMessage('error', msg, ctx)),\n"
        "  debug: (msg: string, ctx: LogContext = {}): void =>\n"
        "    console.debug(formatMessage('debug', msg, ctx)),\n"
        "};\n"
    )


def _node_types(tech_spec: dict) -> str:
    """Generate shared TypeScript types from API endpoints."""
    lines = [
        "/**",
        " * Shared types and interfaces.",
        " *",
        " * Auto-generated from the TechSpec — extend as needed.",
        " */",
        "",
    ]

    # Generate request/response types from endpoints
    seen: set[str] = set()
    for svc in tech_spec.get("services", []):
        for ep in svc.get("endpoints", []):
            for field in ("request_body", "response_model"):
                name = ep.get(field)
                if name and name not in seen:
                    seen.add(name)
                    lines.append(f"export interface {name} {{")
                    lines.append("  // TODO: Define fields")
                    lines.append("}")
                    lines.append("")

    # Types from database models
    for model in tech_spec.get("database_models", []):
        name = model.get("name", "")
        if name and name not in seen:
            seen.add(name)
            lines.append(f"export interface {name} {{")
            for col, col_type in model.get("columns", {}).items():
                ts_type = _sql_to_ts_type(col_type)
                lines.append(f"  {col}: {ts_type};")
            lines.append("}")
            lines.append("")

    return "\n".join(lines)


def _sql_to_ts_type(sql_type: str) -> str:
    """Best-effort mapping from SQL type strings to TypeScript types."""
    upper = sql_type.upper()
    if "UUID" in upper or "TEXT" in upper or "VARCHAR" in upper or "CHAR" in upper:
        return "string"
    if "INT" in upper or "SERIAL" in upper:
        return "number"
    if "BOOL" in upper:
        return "boolean"
    if "TIMESTAMP" in upper or "DATE" in upper:
        return "Date"
    if "JSON" in upper:
        return "Record<string, unknown>"
    return "unknown"


def _node_barrel(dirname: str) -> str:
    """Generate a barrel index.ts for a directory."""
    return f"// Barrel export for {dirname}\n"


# ---------------------------------------------------------------------------
# File generators — Python
# ---------------------------------------------------------------------------


def _python_pyproject(tech_spec: dict) -> str:
    """Generate pyproject.toml from tech spec."""
    tech_stack = tech_spec.get("tech_stack", {})
    stack_text = " ".join(v.lower() for v in tech_stack.values())

    deps = ['"structlog>=24.4.0"']
    if "fastapi" in stack_text:
        deps.append('"fastapi>=0.115.0"')
        deps.append('"uvicorn[standard]>=0.34.0"')
    if "django" in stack_text:
        deps.append('"django>=5.1.0"')
    if "flask" in stack_text:
        deps.append('"flask>=3.1.0"')
    if "sqlalchemy" in stack_text:
        deps.append('"sqlalchemy>=2.0.0"')
    if "postgres" in stack_text or "asyncpg" in stack_text:
        deps.append('"asyncpg>=0.30.0"')
    if "redis" in stack_text:
        deps.append('"redis[hiredis]>=5.2.0"')
    if "pydantic" in stack_text:
        deps.append('"pydantic>=2.10.0"')
    if "httpx" in stack_text:
        deps.append('"httpx>=0.28.0"')

    deps_str = ",\n    ".join(sorted(deps))

    return (
        "[build-system]\n"
        'requires = ["setuptools>=75.0"]\n'
        'build-backend = "setuptools.build_meta"\n'
        "\n"
        "[project]\n"
        'name = "forge-project"\n'
        'version = "0.1.0"\n'
        'requires-python = ">=3.12"\n'
        f"dependencies = [\n    {deps_str},\n]\n"
        "\n"
        "[project.optional-dependencies]\n"
        "dev = [\n"
        '    "pytest>=8.3.0",\n'
        '    "pytest-asyncio>=0.25.0",\n'
        '    "ruff>=0.8.0",\n'
        "]\n"
        "\n"
        "[tool.ruff]\n"
        'target-version = "py312"\n'
        "line-length = 100\n"
        "\n"
        "[tool.ruff.lint]\n"
        'select = ["E", "F", "I", "N", "W", "UP"]\n'
        "\n"
        "[tool.pytest.ini_options]\n"
        'asyncio_mode = "auto"\n'
        'testpaths = ["tests"]\n'
    )


def _python_gitignore() -> str:
    return (
        "__pycache__/\n"
        "*.pyc\n"
        ".venv/\n"
        "venv/\n"
        ".env\n"
        "*.egg-info/\n"
        "dist/\n"
        "build/\n"
        ".pytest_cache/\n"
        ".ruff_cache/\n"
        ".mypy_cache/\n"
        ".DS_Store\n"
        "*.log\n"
    )


def _python_app_error() -> str:
    return (
        '"""Application error hierarchy.\n'
        "\n"
        "Extend AppError for feature-specific errors.  All errors carry a\n"
        "machine-readable ``code`` and an HTTP-friendly ``status_code``.\n"
        '"""\n'
        "\n"
        "from __future__ import annotations\n"
        "\n"
        "\n"
        "class AppError(Exception):\n"
        '    """Base class for all application errors."""\n'
        "\n"
        "    def __init__(\n"
        "        self,\n"
        "        message: str,\n"
        "        *,\n"
        "        status_code: int = 500,\n"
        '        code: str = "INTERNAL_ERROR",\n'
        "    ) -> None:\n"
        "        super().__init__(message)\n"
        "        self.status_code = status_code\n"
        "        self.code = code\n"
        "\n"
        "\n"
        "class NotFoundError(AppError):\n"
        "    def __init__(self, resource: str, id: str | None = None) -> None:\n"
        '        detail = f"{resource} \'{id}\' not found" if id else f"{resource} not found"\n'
        '        super().__init__(detail, status_code=404, code="NOT_FOUND")\n'
        "\n"
        "\n"
        "class ValidationError(AppError):\n"
        "    def __init__(self, message: str) -> None:\n"
        '        super().__init__(message, status_code=400, code="VALIDATION_ERROR")\n'
    )


def _python_logger() -> str:
    return (
        '"""Structured logging setup.\n'
        "\n"
        "Import ``log`` from this module for consistent structured logging\n"
        "across the application.\n"
        '"""\n'
        "\n"
        "from __future__ import annotations\n"
        "\n"
        "import structlog\n"
        "\n"
        "structlog.configure(\n"
        "    processors=[\n"
        "        structlog.contextvars.merge_contextvars,\n"
        "        structlog.processors.add_log_level,\n"
        '        structlog.processors.TimeStamper(fmt="iso"),\n'
        "        structlog.dev.ConsoleRenderer(colors=True),\n"
        "    ],\n"
        "    wrapper_class=structlog.make_filtering_bound_logger(0),\n"
        "    context_class=dict,\n"
        "    logger_factory=structlog.PrintLoggerFactory(),\n"
        "    cache_logger_on_first_use=True,\n"
        ")\n"
        "\n"
        "log = structlog.get_logger()\n"
    )


def _python_types(tech_spec: dict) -> str:
    """Generate shared Pydantic models from the tech spec."""
    lines = [
        '"""Shared types and data models.',
        "",
        "Auto-generated from the TechSpec — extend as needed.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from pydantic import BaseModel",
        "",
    ]

    seen: set[str] = set()
    for svc in tech_spec.get("services", []):
        for ep in svc.get("endpoints", []):
            for field in ("request_body", "response_model"):
                name = ep.get(field)
                if name and name not in seen:
                    seen.add(name)
                    lines.append(f"class {name}(BaseModel):")
                    lines.append("    # TODO: Define fields")
                    lines.append("    pass")
                    lines.append("")
                    lines.append("")

    for model in tech_spec.get("database_models", []):
        name = model.get("name", "")
        if name and name not in seen:
            seen.add(name)
            lines.append(f"class {name}(BaseModel):")
            for col, col_type in model.get("columns", {}).items():
                py_type = _sql_to_py_type(col_type)
                lines.append(f"    {col}: {py_type}")
            lines.append("")
            lines.append("")

    return "\n".join(lines)


def _sql_to_py_type(sql_type: str) -> str:
    """Best-effort mapping from SQL type strings to Python types."""
    upper = sql_type.upper()
    if "UUID" in upper:
        return "str"
    if "TEXT" in upper or "VARCHAR" in upper or "CHAR" in upper:
        return "str"
    if "INT" in upper or "SERIAL" in upper:
        return "int"
    if "BOOL" in upper:
        return "bool"
    if "FLOAT" in upper or "DOUBLE" in upper or "DECIMAL" in upper or "NUMERIC" in upper:
        return "float"
    if "TIMESTAMP" in upper or "DATE" in upper:
        return "str"
    if "JSON" in upper:
        return "dict"
    return "str"


def _python_init(dirname: str) -> str:
    """Generate __init__.py for a package directory."""
    return f'"""{dirname} package."""\n'


# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------


def _docker_compose(tech_spec: dict) -> str:
    """Generate a docker-compose.yml from the tech spec."""
    tech_stack = tech_spec.get("tech_stack", {})
    stack_text = " ".join(v.lower() for v in tech_stack.values())

    services_yaml: list[str] = []

    if "postgres" in stack_text:
        services_yaml.append(
            "  postgres:\n"
            "    image: postgres:16-alpine\n"
            "    environment:\n"
            "      POSTGRES_USER: forge\n"
            "      POSTGRES_PASSWORD: forge\n"
            "      POSTGRES_DB: forge_dev\n"
            "    ports:\n"
            '      - "5432:5432"\n'
            "    volumes:\n"
            "      - pgdata:/var/lib/postgresql/data\n"
        )

    if "redis" in stack_text:
        services_yaml.append(
            '  redis:\n    image: redis:7-alpine\n    ports:\n      - "6379:6379"\n'
        )

    if not services_yaml:
        return ""

    volumes = ""
    if "postgres" in stack_text:
        volumes = "\nvolumes:\n  pgdata:\n"

    return "version: '3.8'\n\nservices:\n" + "\n".join(services_yaml) + volumes


# ---------------------------------------------------------------------------
# Main scaffolding logic
# ---------------------------------------------------------------------------


async def _run_git(
    *args: str,
    cwd: str,
) -> tuple[str, str]:
    """Run a git command, return (stdout, stderr). Raise on failure."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(err.decode().strip() or out.decode().strip())
    return out.decode().strip(), err.decode().strip()


def _write(path: str, content: str) -> None:
    """Write a file, creating parent dirs as needed."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


async def scaffold_project(repo_path: str, tech_spec: dict) -> None:
    """Generate a realistic initial project structure from a TechSpec.

    Creates config files, directory tree, shared utilities, and commits
    everything as ``chore: initial project scaffold`` on ``main``.
    """
    tech_stack: dict[str, str] = tech_spec.get("tech_stack", {})
    file_structure: dict[str, str] = tech_spec.get("file_structure", {})
    stack = _detect_stack(tech_stack)

    scaffold_log = log.bind(stack=stack, repo=repo_path)
    scaffold_log.info("scaffolding project")

    os.makedirs(repo_path, exist_ok=True)

    # ------------------------------------------------------------------
    # 1. Config files
    # ------------------------------------------------------------------
    if stack == "node":
        _write(os.path.join(repo_path, "package.json"), _node_package_json(tech_spec))
        _write(os.path.join(repo_path, "tsconfig.json"), _node_tsconfig())
        _write(os.path.join(repo_path, ".eslintrc.json"), _node_eslint())
        _write(os.path.join(repo_path, ".prettierrc"), _node_prettierrc())
        _write(os.path.join(repo_path, ".gitignore"), _node_gitignore())
    else:
        _write(os.path.join(repo_path, "pyproject.toml"), _python_pyproject(tech_spec))
        _write(os.path.join(repo_path, ".gitignore"), _python_gitignore())

    # ------------------------------------------------------------------
    # 2. Directory structure from file_structure
    # ------------------------------------------------------------------
    created_dirs: set[str] = set()
    for rel_path in file_structure:
        full = os.path.join(repo_path, rel_path)
        if rel_path.endswith("/"):
            os.makedirs(full, exist_ok=True)
            created_dirs.add(rel_path.rstrip("/"))
        else:
            parent = os.path.dirname(full)
            if parent and parent != repo_path:
                os.makedirs(parent, exist_ok=True)
                rel_parent = os.path.relpath(parent, repo_path)
                created_dirs.add(rel_parent)
            # Create empty placeholder file
            if not os.path.exists(full):
                _write(full, "")

    # ------------------------------------------------------------------
    # 3. Barrel / __init__ files in feature directories
    # ------------------------------------------------------------------
    for d in sorted(created_dirs):
        full_dir = os.path.join(repo_path, d)
        if not os.path.isdir(full_dir):
            continue
        if stack == "node":
            idx = os.path.join(full_dir, "index.ts")
            if not os.path.exists(idx):
                _write(idx, _node_barrel(d))
        else:
            init = os.path.join(full_dir, "__init__.py")
            if not os.path.exists(init):
                _write(init, _python_init(d))

    # ------------------------------------------------------------------
    # 4. Shared utility stubs
    # ------------------------------------------------------------------
    if stack == "node":
        shared = os.path.join(repo_path, "src", "shared")
        os.makedirs(shared, exist_ok=True)
        _write(os.path.join(shared, "errors.ts"), _node_app_error())
        _write(os.path.join(shared, "logger.ts"), _node_logger())
        _write(os.path.join(shared, "types.ts"), _node_types(tech_spec))
        idx = os.path.join(shared, "index.ts")
        if not os.path.exists(idx):
            _write(
                idx,
                (
                    "export { AppError, NotFoundError, ValidationError } from './errors.js';\n"
                    "export { logger } from './logger.js';\n"
                    "export type * from './types.js';\n"
                ),
            )
    else:
        shared = os.path.join(repo_path, "src", "shared")
        os.makedirs(shared, exist_ok=True)
        _write(os.path.join(shared, "__init__.py"), _python_init("shared"))
        _write(os.path.join(shared, "errors.py"), _python_app_error())
        _write(os.path.join(shared, "logger.py"), _python_logger())
        _write(os.path.join(shared, "types.py"), _python_types(tech_spec))

    # ------------------------------------------------------------------
    # 5. Docker compose (if applicable)
    # ------------------------------------------------------------------
    stack_text = " ".join(v.lower() for v in tech_stack.values())
    docker_content = _docker_compose(tech_spec)
    if docker_content or "docker" in stack_text:
        if not docker_content:
            docker_content = "version: '3.8'\n\nservices: {}\n"
        _write(os.path.join(repo_path, "docker-compose.yml"), docker_content)

    # ------------------------------------------------------------------
    # 6. Git init + commit (if not already a repo)
    # ------------------------------------------------------------------
    git_dir = os.path.join(repo_path, ".git")
    if not os.path.isdir(git_dir):
        await _run_git("init", cwd=repo_path)
        await _run_git("checkout", "-b", "main", cwd=repo_path)

    await _run_git("add", "-A", cwd=repo_path)

    # Only commit if there are staged changes
    proc = await asyncio.create_subprocess_exec(
        "git",
        "diff",
        "--cached",
        "--quiet",
        cwd=repo_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    if proc.returncode != 0:
        await _run_git("commit", "-m", "chore: initial project scaffold", cwd=repo_path)

    file_count = sum(
        len(files) for root, _dirs, files in os.walk(repo_path) if ".git" not in root.split(os.sep)
    )
    scaffold_log.info("scaffold complete", dirs=len(created_dirs), files=file_count)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------


async def _main() -> None:
    """Scaffold a project from a sample TechSpec and print the result."""
    import shutil
    import tempfile

    sample_tech_spec = {
        "spec_id": "TECH-001",
        "services": [
            {
                "name": "api-gateway",
                "responsibility": "HTTP API for pipeline management",
                "endpoints": [
                    {
                        "method": "POST",
                        "path": "/api/v1/pipelines",
                        "description": "Start a new pipeline run",
                        "request_body": "CreatePipelineRequest",
                        "response_model": "PipelineResponse",
                        "auth_required": True,
                    },
                    {
                        "method": "GET",
                        "path": "/api/v1/pipelines/:id",
                        "description": "Get pipeline status",
                        "response_model": "PipelineResponse",
                        "auth_required": True,
                    },
                ],
                "dependencies": [],
            },
        ],
        "database_models": [
            {
                "name": "PipelineRun",
                "table_name": "pipeline_runs",
                "columns": {
                    "id": "UUID PRIMARY KEY DEFAULT gen_random_uuid()",
                    "status": "TEXT NOT NULL DEFAULT 'pending'",
                    "created_at": "TIMESTAMP NOT NULL DEFAULT now()",
                    "cost_usd": "NUMERIC(10,4) DEFAULT 0",
                },
                "indexes": ["idx_pipeline_runs_status ON pipeline_runs (status)"],
                "relationships": [],
            },
            {
                "name": "AgentEvent",
                "table_name": "agent_events",
                "columns": {
                    "id": "UUID PRIMARY KEY DEFAULT gen_random_uuid()",
                    "pipeline_id": "UUID NOT NULL REFERENCES pipeline_runs(id)",
                    "event_type": "TEXT NOT NULL",
                    "payload": "JSONB DEFAULT '{}'",
                    "created_at": "TIMESTAMP NOT NULL DEFAULT now()",
                },
                "indexes": [],
                "relationships": ["pipeline_runs"],
            },
        ],
        "api_endpoints": [
            {
                "method": "GET",
                "path": "/api/v1/health",
                "description": "Health check",
                "auth_required": False,
            },
        ],
        "tech_stack": {
            "language": "TypeScript 5.7",
            "runtime": "Node.js 22 LTS",
            "framework": "Express 4.x",
            "database": "PostgreSQL 16",
            "cache": "Redis 7",
            "orm": "Drizzle ORM",
            "testing": "Vitest",
            "validation": "Zod",
        },
        "coding_standards": [
            "Use strict TypeScript — no `any`, no implicit returns",
            "All functions must have explicit return types",
            "Use branded types for entity IDs",
            "Prefer `const` over `let`",
            "Error handling with AppError subclasses",
        ],
        "file_structure": {
            "src/index.ts": "Application entry point",
            "src/routes/": "Express route handlers",
            "src/routes/pipelines.ts": "Pipeline CRUD routes",
            "src/routes/health.ts": "Health check endpoint",
            "src/db/": "Database layer",
            "src/db/schema.ts": "Drizzle ORM schema definitions",
            "src/db/connection.ts": "Database connection pool",
            "src/middleware/": "Express middleware",
            "src/middleware/auth.ts": "Authentication middleware",
            "src/middleware/errorHandler.ts": "Global error handler",
            "tests/": "Test files",
        },
        "user_story_mapping": {
            "US-001": ["api-gateway"],
        },
    }

    base = tempfile.mkdtemp(prefix="forge-scaffold-test-")
    repo_path = os.path.join(base, "project")

    try:
        await scaffold_project(repo_path, sample_tech_spec)

        # Print the tree
        print("=== Scaffolded project tree ===")
        for root, dirs, files in sorted(os.walk(repo_path)):
            dirs[:] = sorted(d for d in dirs if d != ".git")
            level = root.replace(repo_path, "").count(os.sep)
            indent = "  " * level
            dirname = os.path.basename(root) or "."
            print(f"{indent}{dirname}/")
            for f in sorted(files):
                print(f"{indent}  {f}")

        # Show git log
        print("\n=== Git log ===")
        out, _ = await _run_git("log", "--oneline", cwd=repo_path)
        print(out)

        # Show a sample file
        print("\n=== src/shared/types.ts ===")
        with open(os.path.join(repo_path, "src", "shared", "types.ts")) as f:
            print(f.read())

        print("\n=== package.json ===")
        with open(os.path.join(repo_path, "package.json")) as f:
            print(f.read())

    finally:
        shutil.rmtree(base)
        print("\nCleaned up temp dir.")


if __name__ == "__main__":
    asyncio.run(_main())
