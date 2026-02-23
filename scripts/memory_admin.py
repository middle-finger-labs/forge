#!/usr/bin/env python3
"""Forge memory admin CLI — inspect, curate, and manage agent memory.

Usage::

    python -m scripts.memory_admin list [--role ROLE] [--type lesson|decision] [--limit N]
    python -m scripts.memory_admin stats
    python -m scripts.memory_admin clear [--role ROLE] [--type lesson|decision] [--confirm]
    python -m scripts.memory_admin export [--output FILE]
    python -m scripts.memory_admin import --input FILE [--confirm]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime

import asyncpg


def _dsn() -> str:
    """Return the PostgreSQL connection string from the environment."""
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://forge:forge_dev_password@localhost:5432/forge_app",
    )


async def _pool() -> asyncpg.Pool:
    """Create a small asyncpg connection pool."""
    return await asyncpg.create_pool(_dsn(), min_size=1, max_size=3)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


async def cmd_list(args: argparse.Namespace) -> None:
    """List memory entries."""
    pool = await _pool()
    try:
        conditions = []
        params: list = []
        idx = 1

        if args.type:
            conditions.append(f"memory_type = ${idx}")
            params.append(args.type)
            idx += 1

        if args.role:
            conditions.append(f"agent_role = ${idx}")
            params.append(args.role)
            idx += 1

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(args.limit)

        rows = await pool.fetch(
            f"""
            SELECT id, agent_role, pipeline_id, content, memory_type, metadata, created_at
            FROM memory_store
            {where}
            ORDER BY created_at DESC
            LIMIT ${idx}
            """,
            *params,
        )

        if not rows:
            print("No memories found.")
            return

        for r in rows:
            meta = r["metadata"]
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except (json.JSONDecodeError, TypeError):
                    meta = {}

            print(f"\n{'=' * 60}")
            print(f"  ID:       {r['id']}")
            print(f"  Type:     {r['memory_type']}")
            print(f"  Role:     {r['agent_role'] or '-'}")
            print(f"  Pipeline: {r['pipeline_id'] or '-'}")
            print(f"  Created:  {r['created_at']}")
            print(f"  Content:  {r['content']}")
            if meta and isinstance(meta, dict) and len(meta) > 0:
                print(f"  Metadata: {json.dumps(meta, default=str, indent=2)}")

        print(f"\n{'=' * 60}")
        print(f"Total: {len(rows)} entries")
    finally:
        await pool.close()


async def cmd_stats(args: argparse.Namespace) -> None:
    """Show memory statistics."""
    pool = await _pool()
    try:
        total = await pool.fetchval("SELECT COUNT(*) FROM memory_store")
        lessons = await pool.fetchval(
            "SELECT COUNT(*) FROM memory_store WHERE memory_type = 'lesson'"
        )
        decisions = await pool.fetchval(
            "SELECT COUNT(*) FROM memory_store WHERE memory_type = 'decision'"
        )

        role_rows = await pool.fetch(
            """
            SELECT agent_role, memory_type, COUNT(*) AS count
            FROM memory_store
            WHERE agent_role IS NOT NULL
            GROUP BY agent_role, memory_type
            ORDER BY count DESC
            """
        )

        pipeline_rows = await pool.fetch(
            """
            SELECT pipeline_id, COUNT(*) AS count
            FROM memory_store
            WHERE pipeline_id IS NOT NULL
            GROUP BY pipeline_id
            ORDER BY count DESC
            LIMIT 10
            """
        )

        print("\nForge Memory Statistics")
        print("=" * 40)
        print(f"  Total entries:    {total}")
        print(f"  Lessons:          {lessons}")
        print(f"  Decisions:        {decisions}")

        if role_rows:
            print("\n  By Role:")
            for r in role_rows:
                print(f"    {r['agent_role']:20s} {r['memory_type']:10s} {r['count']}")

        if pipeline_rows:
            print("\n  Top Pipelines:")
            for r in pipeline_rows:
                print(f"    {r['pipeline_id']:30s} {r['count']} entries")

        print()
    finally:
        await pool.close()


async def cmd_clear(args: argparse.Namespace) -> None:
    """Clear memory entries."""
    pool = await _pool()
    try:
        conditions = []
        params: list = []
        idx = 1

        if args.type:
            conditions.append(f"memory_type = ${idx}")
            params.append(args.type)
            idx += 1

        if args.role:
            conditions.append(f"agent_role = ${idx}")
            params.append(args.role)
            idx += 1

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # Count first
        count = await pool.fetchval(f"SELECT COUNT(*) FROM memory_store {where}", *params)

        if count == 0:
            print("No matching entries to delete.")
            return

        desc = []
        if args.type:
            desc.append(f"type={args.type}")
        if args.role:
            desc.append(f"role={args.role}")
        filter_desc = f" ({', '.join(desc)})" if desc else " (ALL)"

        if not args.confirm:
            print(f"This will delete {count} memory entries{filter_desc}.")
            response = input("Type 'yes' to confirm: ")
            if response.strip().lower() != "yes":
                print("Aborted.")
                return

        result = await pool.execute(f"DELETE FROM memory_store {where}", *params)
        print(f"Deleted {count} entries{filter_desc}. ({result})")
    finally:
        await pool.close()


async def cmd_export(args: argparse.Namespace) -> None:
    """Export memory to a JSON file."""
    pool = await _pool()
    try:
        rows = await pool.fetch(
            """
            SELECT id, agent_role, pipeline_id, content, memory_type, metadata, created_at
            FROM memory_store
            ORDER BY created_at ASC
            """
        )

        entries = []
        for r in rows:
            meta = r["metadata"]
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except (json.JSONDecodeError, TypeError):
                    meta = {}

            entries.append(
                {
                    "id": str(r["id"]),
                    "agent_role": r["agent_role"],
                    "pipeline_id": r["pipeline_id"],
                    "content": r["content"],
                    "memory_type": r["memory_type"],
                    "metadata": meta,
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                }
            )

        ts = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
        output = args.output or f"forge_memory_export_{ts}.json"

        payload = {
            "exported_at": datetime.now(tz=UTC).isoformat(),
            "entries": entries,
        }
        with open(output, "w") as f:
            json.dump(payload, f, indent=2, default=str)

        print(f"Exported {len(entries)} entries to {output}")
    finally:
        await pool.close()


async def cmd_import(args: argparse.Namespace) -> None:
    """Import memory from a JSON file."""
    if not args.input:
        print("Error: --input FILE is required for import", file=sys.stderr)
        sys.exit(1)

    with open(args.input) as f:
        data = json.load(f)

    entries = data.get("entries", [])
    if not entries:
        print("No entries found in import file.")
        return

    if not args.confirm:
        print(f"This will import {len(entries)} memory entries.")
        response = input("Type 'yes' to confirm: ")
        if response.strip().lower() != "yes":
            print("Aborted.")
            return

    pool = await _pool()
    try:
        imported = 0
        for entry in entries:
            meta_json = json.dumps(entry.get("metadata", {}), default=str)
            try:
                await pool.execute(
                    """
                    INSERT INTO memory_store
                        (agent_role, pipeline_id, content, memory_type, metadata)
                    VALUES ($1, $2, $3, $4, $5::jsonb)
                    """,
                    entry.get("agent_role"),
                    entry.get("pipeline_id"),
                    entry["content"],
                    entry.get("memory_type", "lesson"),
                    meta_json,
                )
                imported += 1
            except Exception as exc:
                print(f"  Warning: failed to import entry: {exc}", file=sys.stderr)

        print(f"Imported {imported}/{len(entries)} entries.")
    finally:
        await pool.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point for the memory admin CLI."""
    parser = argparse.ArgumentParser(
        description="Forge memory admin — inspect and curate agent memory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # list
    p_list = sub.add_parser("list", help="List memory entries")
    p_list.add_argument("--role", help="Filter by agent role")
    p_list.add_argument("--type", choices=["lesson", "decision"], help="Filter by memory type")
    p_list.add_argument("--limit", type=int, default=20, help="Max entries (default: 20)")

    # stats
    sub.add_parser("stats", help="Show memory statistics")

    # clear
    p_clear = sub.add_parser("clear", help="Clear memory entries")
    p_clear.add_argument("--role", help="Only clear entries for this role")
    p_clear.add_argument("--type", choices=["lesson", "decision"], help="Only clear this type")
    p_clear.add_argument("--confirm", action="store_true", help="Skip confirmation prompt")

    # export
    p_export = sub.add_parser("export", help="Export memory to JSON")
    p_export.add_argument("--output", "-o", help="Output file path")

    # import
    p_import = sub.add_parser("import", help="Import memory from JSON")
    p_import.add_argument("--input", "-i", required=True, help="Input file path")
    p_import.add_argument("--confirm", action="store_true", help="Skip confirmation prompt")

    args = parser.parse_args()

    commands = {
        "list": cmd_list,
        "stats": cmd_stats,
        "clear": cmd_clear,
        "export": cmd_export,
        "import": cmd_import,
    }

    asyncio.run(commands[args.command](args))


if __name__ == "__main__":
    main()
