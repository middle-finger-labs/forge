"""Compact file tree generator for agent context.

Produces a ``tree``-style representation of a repository from the code
index, annotated with language tags and brief descriptions derived from
class/module docstrings.  Designed to fit within ~500-1000 tokens so it
can be prepended to every agent's context window.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import structlog

log = structlog.get_logger().bind(component="file_tree")


@dataclass(slots=True)
class FileInfo:
    """Metadata for a single file in the tree."""

    path: str
    language: str = ""
    chunk_count: int = 0
    description: str = ""  # first docstring or inferred purpose


def build_file_tree(
    chunks: list[dict],
    *,
    max_depth: int = 4,
    max_files: int = 120,
    collapse_threshold: int = 8,
) -> str:
    """Build a compact file tree string from indexed code chunks.

    Args:
        chunks: List of chunk dicts (as returned by CodeChunkStore.search
                or similar).  Each must have at least ``file_path`` and
                ``language``.  Optionally ``docstring`` for descriptions.
        max_depth: Maximum directory depth to show.
        max_files: Maximum number of files to list before summarising.
        collapse_threshold: Collapse directories with more children than
                            this into a summary line.

    Returns:
        A compact string suitable for embedding in an agent prompt.
    """
    # Collect file info from chunks
    file_map: dict[str, FileInfo] = {}
    for c in chunks:
        path = c.get("file_path", "")
        if not path:
            continue
        if path not in file_map:
            file_map[path] = FileInfo(
                path=path,
                language=c.get("language", ""),
            )
        info = file_map[path]
        info.chunk_count += 1
        # Use first class/module docstring as description
        if not info.description and c.get("docstring"):
            doc = c["docstring"]
            # Take first sentence only
            first_line = doc.split("\n")[0].strip()
            if len(first_line) > 60:
                first_line = first_line[:57] + "..."
            info.description = first_line

    if not file_map:
        return "(empty repository)"

    return _render_tree(
        sorted(file_map.values(), key=lambda f: f.path),
        max_depth=max_depth,
        max_files=max_files,
        collapse_threshold=collapse_threshold,
    )


def build_file_tree_from_paths(
    file_paths: list[str],
    *,
    max_depth: int = 4,
    max_files: int = 120,
) -> str:
    """Build a file tree from a plain list of file paths (no chunk data)."""
    infos = [FileInfo(path=p) for p in sorted(set(file_paths))]
    return _render_tree(infos, max_depth=max_depth, max_files=max_files)


# ---------------------------------------------------------------------------
# Tree rendering
# ---------------------------------------------------------------------------


@dataclass
class _TreeNode:
    """Internal node for building the tree structure."""

    name: str
    children: dict[str, _TreeNode] = field(default_factory=dict)
    file_info: FileInfo | None = None
    file_count: int = 0  # total files under this subtree


def _render_tree(
    files: list[FileInfo],
    *,
    max_depth: int = 4,
    max_files: int = 120,
    collapse_threshold: int = 8,
) -> str:
    if len(files) > max_files:
        # Summarise rather than listing everything
        files = files[:max_files]

    # Build tree structure
    root = _TreeNode(name=".")
    for info in files:
        parts = PurePosixPath(info.path).parts
        node = root
        for part in parts[:-1]:
            if part not in node.children:
                node.children[part] = _TreeNode(name=part)
            node = node.children[part]
        leaf_name = parts[-1] if parts else info.path
        leaf = _TreeNode(name=leaf_name, file_info=info)
        node.children[leaf_name] = leaf

    # Count files per subtree
    _count_files(root)

    # Render
    lines: list[str] = []
    _render_node(root, lines, prefix="", depth=0, max_depth=max_depth,
                 collapse_threshold=collapse_threshold)

    # Stats footer
    lang_counts: dict[str, int] = defaultdict(int)
    for info in files:
        if info.language:
            lang_counts[info.language] += 1
    if lang_counts:
        lang_str = ", ".join(
            f"{lang}: {n}" for lang, n in
            sorted(lang_counts.items(), key=lambda x: -x[1])[:6]
        )
        lines.append(f"\n({len(files)} files — {lang_str})")

    return "\n".join(lines)


def _count_files(node: _TreeNode) -> int:
    if node.file_info is not None:
        node.file_count = 1
        return 1
    total = 0
    for child in node.children.values():
        total += _count_files(child)
    node.file_count = total
    return total


def _render_node(
    node: _TreeNode,
    lines: list[str],
    prefix: str,
    depth: int,
    max_depth: int,
    collapse_threshold: int = 8,
    is_last: bool = True,
) -> None:
    children = sorted(
        node.children.values(),
        key=lambda n: (n.file_info is not None, n.name),
    )

    for i, child in enumerate(children):
        last = i == len(children) - 1
        connector = "\u2514\u2500\u2500 " if last else "\u251c\u2500\u2500 "
        extension = "    " if last else "\u2502   "

        if child.file_info is not None:
            # Leaf file
            desc = ""
            if child.file_info.description:
                desc = f"  # {child.file_info.description}"
            lang_tag = ""
            if child.file_info.language:
                lang_tag = f" [{child.file_info.language}]"
            lines.append(f"{prefix}{connector}{child.name}{lang_tag}{desc}")
        else:
            # Directory
            if depth >= max_depth:
                lines.append(f"{prefix}{connector}{child.name}/ ({child.file_count} files)")
            elif child.file_count > collapse_threshold and depth >= 2:
                lines.append(f"{prefix}{connector}{child.name}/ ({child.file_count} files)")
            else:
                lines.append(f"{prefix}{connector}{child.name}/")
                _render_node(
                    child, lines, prefix + extension,
                    depth + 1, max_depth, collapse_threshold,
                    is_last=last,
                )
