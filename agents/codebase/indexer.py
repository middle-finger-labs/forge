"""Git repo walker + tree-sitter AST chunker.

Walks a git repository, parses each supported source file with tree-sitter,
and extracts semantically meaningful code chunks (functions, classes, methods,
interfaces, module-level docstrings).

Supports incremental re-indexing: given an old and new commit SHA, only
files that changed between the two are re-parsed.

Supported languages: Python, TypeScript, JavaScript, Rust, Go, Java.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

import structlog

log = structlog.get_logger().bind(component="code_indexer")

# ---------------------------------------------------------------------------
# CodeChunk — the atomic unit of indexed code
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CodeChunk:
    """A semantically meaningful fragment of source code."""

    file_path: str
    language: str
    chunk_type: str  # function, class, method, module, interface, trait, struct, enum
    name: str
    qualified_name: str  # e.g. "MyClass.my_method"
    body: str
    start_line: int
    end_line: int
    signature: str = ""
    docstring: str = ""
    parent_name: str | None = None
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Extension → language mapping
# ---------------------------------------------------------------------------

_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
}

# File patterns to always skip
_SKIP_PATTERNS: set[str] = {
    "node_modules",
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "target",
    "dist",
    "build",
    ".next",
    ".nuxt",
    "vendor",
}

# Maximum file size to parse (512 KB)
_MAX_FILE_SIZE = 512 * 1024


# ---------------------------------------------------------------------------
# Tree-sitter language loading
# ---------------------------------------------------------------------------

_PARSERS: dict[str, object] = {}


def _get_parser(language: str):
    """Return a tree-sitter Parser for the given language, or None."""
    if language in _PARSERS:
        return _PARSERS[language]

    try:
        import tree_sitter

        lang_obj = _load_language(language)
        if lang_obj is None:
            _PARSERS[language] = None
            return None

        parser = tree_sitter.Parser(lang_obj)
        _PARSERS[language] = parser
        log.debug("tree-sitter parser loaded", language=language)
        return parser
    except Exception as exc:
        log.warning("failed to load tree-sitter parser", language=language, error=str(exc))
        _PARSERS[language] = None
        return None


def _load_language(language: str):
    """Load a tree-sitter Language object for the given language name.

    Grammar packages return PyCapsule objects from their ``language()``
    function.  The ``tree_sitter.Language`` wrapper converts these into
    usable Language instances that ``Parser`` accepts.
    """
    import importlib

    import tree_sitter

    # Map our language names to grammar package names
    pkg_map = {
        "python": "tree_sitter_python",
        "typescript": "tree_sitter_typescript",
        "tsx": "tree_sitter_typescript",
        "javascript": "tree_sitter_javascript",
        "rust": "tree_sitter_rust",
        "go": "tree_sitter_go",
        "java": "tree_sitter_java",
    }

    pkg_name = pkg_map.get(language)
    if not pkg_name:
        return None

    try:
        mod = importlib.import_module(pkg_name)
        # Some packages expose language() directly, others have typed sub-languages
        if language == "typescript":
            capsule = mod.language_typescript()
        elif language == "tsx":
            capsule = mod.language_tsx()
        else:
            capsule = mod.language()
        # Wrap PyCapsule in tree_sitter.Language
        return tree_sitter.Language(capsule)
    except (ImportError, AttributeError) as exc:
        log.debug("tree-sitter grammar not available", language=language, error=str(exc))
        return None


# ---------------------------------------------------------------------------
# AST extraction per language
# ---------------------------------------------------------------------------


def _extract_chunks_from_tree(
    tree,
    source_bytes: bytes,
    file_path: str,
    language: str,
) -> list[CodeChunk]:
    """Walk a tree-sitter parse tree and extract code chunks."""
    extractors = {
        "python": _extract_python,
        "typescript": _extract_typescript,
        "tsx": _extract_typescript,
        "javascript": _extract_javascript,
        "rust": _extract_rust,
        "go": _extract_go,
        "java": _extract_java,
    }

    extractor = extractors.get(language)
    if extractor is None:
        return []

    return extractor(tree.root_node, source_bytes, file_path)


def _node_text(node, source_bytes: bytes) -> str:
    """Extract the source text for a tree-sitter node."""
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _find_children(node, *types: str):
    """Yield direct children matching any of the given node types."""
    for child in node.children:
        if child.type in types:
            yield child


def _find_first_child(node, *types: str):
    """Return the first child matching any of the given types, or None."""
    for child in node.children:
        if child.type in types:
            return child
    return None


def _extract_docstring(node, source_bytes: bytes) -> str:
    """Extract a docstring from the first statement in a body block (Python-style)."""
    body = _find_first_child(node, "block", "body")
    if body is None:
        return ""

    for child in body.children:
        if child.type == "expression_statement":
            inner = _find_first_child(child, "string", "concatenated_string")
            if inner:
                text = _node_text(inner, source_bytes)
                # Strip triple-quote delimiters
                for delim in ('"""', "'''", '"""', "'''"):
                    if text.startswith(delim) and text.endswith(delim):
                        return text[len(delim) : -len(delim)].strip()
                return text.strip().strip('"').strip("'")
        break  # Only check the very first statement

    return ""


# ─── Python ──────────────────────────────────────────────────────────────

def _extract_python(root, source_bytes: bytes, file_path: str) -> list[CodeChunk]:
    chunks: list[CodeChunk] = []

    for node in root.children:
        # Decorated definitions wrap the actual function/class
        if node.type == "decorated_definition":
            decorators = [
                _node_text(d, source_bytes) for d in _find_children(node, "decorator")
            ]
            inner = _find_first_child(node, "function_definition", "class_definition")
            if inner and inner.type == "function_definition":
                _extract_python_function(
                    inner, source_bytes, file_path, chunks,
                    extra_decorators=decorators,
                )
            elif inner and inner.type == "class_definition":
                _extract_python_class(inner, source_bytes, file_path, chunks)
        elif node.type == "function_definition":
            _extract_python_function(node, source_bytes, file_path, chunks)
        elif node.type == "class_definition":
            _extract_python_class(node, source_bytes, file_path, chunks)

    return chunks


def _extract_python_function(
    node, source_bytes, file_path, chunks,
    *, parent_name: str | None = None, extra_decorators: list[str] | None = None,
):
    """Extract a single Python function/method into chunks."""
    name_node = _find_first_child(node, "identifier")
    if not name_node:
        return
    name = _node_text(name_node, source_bytes)
    params = _find_first_child(node, "parameters")
    sig = _node_text(params, source_bytes) if params else "()"
    docstring = _extract_docstring(node, source_bytes)
    decorators = extra_decorators or [
        _node_text(d, source_bytes) for d in _find_children(node, "decorator")
    ]

    chunk_type = "method" if parent_name else "function"
    qname = f"{parent_name}.{name}" if parent_name else name

    chunks.append(CodeChunk(
        file_path=file_path,
        language="python",
        chunk_type=chunk_type,
        name=name,
        qualified_name=qname,
        signature=f"def {name}{sig}",
        docstring=docstring,
        body=_node_text(node, source_bytes),
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        parent_name=parent_name,
        metadata={"decorators": decorators} if decorators else {},
    ))


def _extract_python_class(node, source_bytes, file_path, chunks):
    """Extract a Python class and its methods into chunks."""
    cls_name_node = _find_first_child(node, "identifier")
    if not cls_name_node:
        return
    cls_name = _node_text(cls_name_node, source_bytes)
    docstring = _extract_docstring(node, source_bytes)
    bases = _find_first_child(node, "argument_list")
    base_str = _node_text(bases, source_bytes) if bases else ""

    chunks.append(CodeChunk(
        file_path=file_path,
        language="python",
        chunk_type="class",
        name=cls_name,
        qualified_name=cls_name,
        signature=f"class {cls_name}{base_str}",
        docstring=docstring,
        body=_node_text(node, source_bytes),
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
    ))

    # Extract methods from class body
    body = _find_first_child(node, "block", "body")
    if body:
        for child in body.children:
            if child.type == "decorated_definition":
                decos = [
                    _node_text(d, source_bytes)
                    for d in _find_children(child, "decorator")
                ]
                inner = _find_first_child(child, "function_definition")
                if inner:
                    _extract_python_function(
                        inner, source_bytes, file_path, chunks,
                        parent_name=cls_name, extra_decorators=decos,
                    )
            elif child.type == "function_definition":
                _extract_python_function(
                    child, source_bytes, file_path, chunks,
                    parent_name=cls_name,
                )


# ─── TypeScript ──────────────────────────────────────────────────────────

def _extract_typescript(root, source_bytes: bytes, file_path: str) -> list[CodeChunk]:
    chunks: list[CodeChunk] = []
    lang = "tsx" if file_path.endswith(".tsx") else "typescript"

    for node in root.children:
        if node.type == "function_declaration":
            _extract_ts_function(node, source_bytes, file_path, lang, chunks)
        elif node.type == "class_declaration":
            _extract_ts_class(node, source_bytes, file_path, lang, chunks)
        elif node.type in ("interface_declaration", "type_alias_declaration"):
            _extract_ts_interface(node, source_bytes, file_path, lang, chunks)
        elif node.type == "export_statement":
            # Look inside exports
            for child in node.children:
                if child.type == "function_declaration":
                    _extract_ts_function(child, source_bytes, file_path, lang, chunks)
                elif child.type == "class_declaration":
                    _extract_ts_class(child, source_bytes, file_path, lang, chunks)
                elif child.type in ("interface_declaration", "type_alias_declaration"):
                    _extract_ts_interface(child, source_bytes, file_path, lang, chunks)
                elif child.type == "lexical_declaration":
                    _extract_ts_arrow_functions(child, source_bytes, file_path, lang, chunks)
        elif node.type == "lexical_declaration":
            _extract_ts_arrow_functions(node, source_bytes, file_path, lang, chunks)

    return chunks


def _extract_ts_function(node, source_bytes, file_path, lang, chunks):
    name_node = _find_first_child(node, "identifier")
    if not name_node:
        return
    name = _node_text(name_node, source_bytes)
    params = _find_first_child(node, "formal_parameters")
    sig = _node_text(params, source_bytes) if params else "()"

    # JSDoc comment (preceding sibling)
    docstring = _get_jsdoc(node, source_bytes)

    chunks.append(CodeChunk(
        file_path=file_path,
        language=lang,
        chunk_type="function",
        name=name,
        qualified_name=name,
        signature=f"function {name}{sig}",
        docstring=docstring,
        body=_node_text(node, source_bytes),
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
    ))


def _extract_ts_class(node, source_bytes, file_path, lang, chunks):
    name_node = _find_first_child(node, "type_identifier", "identifier")
    if not name_node:
        return
    cls_name = _node_text(name_node, source_bytes)
    docstring = _get_jsdoc(node, source_bytes)

    chunks.append(CodeChunk(
        file_path=file_path,
        language=lang,
        chunk_type="class",
        name=cls_name,
        qualified_name=cls_name,
        signature=f"class {cls_name}",
        docstring=docstring,
        body=_node_text(node, source_bytes),
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
    ))

    # Methods
    body = _find_first_child(node, "class_body")
    if body:
        for child in body.children:
            if child.type in ("method_definition", "public_field_definition"):
                mname_node = _find_first_child(child, "property_identifier", "identifier")
                if not mname_node:
                    continue
                mname = _node_text(mname_node, source_bytes)
                mparams = _find_first_child(child, "formal_parameters")
                msig = _node_text(mparams, source_bytes) if mparams else "()"
                mdoc = _get_jsdoc(child, source_bytes)

                chunks.append(CodeChunk(
                    file_path=file_path,
                    language=lang,
                    chunk_type="method",
                    name=mname,
                    qualified_name=f"{cls_name}.{mname}",
                    signature=f"{mname}{msig}",
                    docstring=mdoc,
                    body=_node_text(child, source_bytes),
                    start_line=child.start_point[0] + 1,
                    end_line=child.end_point[0] + 1,
                    parent_name=cls_name,
                ))


def _extract_ts_interface(node, source_bytes, file_path, lang, chunks):
    name_node = _find_first_child(node, "type_identifier", "identifier")
    if not name_node:
        return
    name = _node_text(name_node, source_bytes)
    docstring = _get_jsdoc(node, source_bytes)
    chunk_type = "interface" if node.type == "interface_declaration" else "type_alias"

    chunks.append(CodeChunk(
        file_path=file_path,
        language=lang,
        chunk_type=chunk_type,
        name=name,
        qualified_name=name,
        signature=f"{'interface' if chunk_type == 'interface' else 'type'} {name}",
        docstring=docstring,
        body=_node_text(node, source_bytes),
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
    ))


def _extract_ts_arrow_functions(node, source_bytes, file_path, lang, chunks):
    """Extract const arrow functions: const foo = (...) => { ... }"""
    for decl in _find_children(node, "variable_declarator"):
        name_node = _find_first_child(decl, "identifier")
        value_node = _find_first_child(decl, "arrow_function")
        if not name_node or not value_node:
            continue
        name = _node_text(name_node, source_bytes)
        params = _find_first_child(value_node, "formal_parameters")
        sig = _node_text(params, source_bytes) if params else "()"
        docstring = _get_jsdoc(node, source_bytes)

        chunks.append(CodeChunk(
            file_path=file_path,
            language=lang,
            chunk_type="function",
            name=name,
            qualified_name=name,
            signature=f"const {name} = {sig} =>",
            docstring=docstring,
            body=_node_text(node, source_bytes),
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        ))


def _get_jsdoc(node, source_bytes: bytes) -> str:
    """Extract JSDoc comment from the node's preceding sibling."""
    if node.prev_named_sibling and node.prev_named_sibling.type == "comment":
        text = _node_text(node.prev_named_sibling, source_bytes)
        if text.startswith("/**"):
            # Strip /** ... */ and leading * on each line
            lines = text.split("\n")
            cleaned = []
            for line in lines:
                line = line.strip()
                line = line.lstrip("/*").rstrip("*/").strip()
                if line:
                    cleaned.append(line)
            return "\n".join(cleaned)
    return ""


# ─── JavaScript ──────────────────────────────────────────────────────────

def _extract_javascript(root, source_bytes: bytes, file_path: str) -> list[CodeChunk]:
    # JS uses the same patterns as TS minus type annotations
    return _extract_typescript(root, source_bytes, file_path)


# ─── Rust ────────────────────────────────────────────────────────────────

def _extract_rust(root, source_bytes: bytes, file_path: str) -> list[CodeChunk]:
    chunks: list[CodeChunk] = []

    for node in root.children:
        if node.type == "function_item":
            name_node = _find_first_child(node, "identifier")
            if not name_node:
                continue
            name = _node_text(name_node, source_bytes)
            params = _find_first_child(node, "parameters")
            sig = _node_text(params, source_bytes) if params else "()"
            docstring = _get_rust_doc(node, source_bytes)
            vis = _find_first_child(node, "visibility_modifier")

            chunks.append(CodeChunk(
                file_path=file_path,
                language="rust",
                chunk_type="function",
                name=name,
                qualified_name=name,
                signature=f"fn {name}{sig}",
                docstring=docstring,
                body=_node_text(node, source_bytes),
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                metadata={"public": vis is not None},
            ))

        elif node.type in ("struct_item", "enum_item"):
            name_node = _find_first_child(node, "type_identifier")
            if not name_node:
                continue
            name = _node_text(name_node, source_bytes)
            docstring = _get_rust_doc(node, source_bytes)
            kind = "struct" if node.type == "struct_item" else "enum"

            chunks.append(CodeChunk(
                file_path=file_path,
                language="rust",
                chunk_type=kind,
                name=name,
                qualified_name=name,
                signature=f"{kind} {name}",
                docstring=docstring,
                body=_node_text(node, source_bytes),
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
            ))

        elif node.type == "trait_item":
            name_node = _find_first_child(node, "type_identifier")
            if not name_node:
                continue
            name = _node_text(name_node, source_bytes)
            docstring = _get_rust_doc(node, source_bytes)

            chunks.append(CodeChunk(
                file_path=file_path,
                language="rust",
                chunk_type="trait",
                name=name,
                qualified_name=name,
                signature=f"trait {name}",
                docstring=docstring,
                body=_node_text(node, source_bytes),
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
            ))

        elif node.type == "impl_item":
            _extract_rust_impl(node, source_bytes, file_path, chunks)

    return chunks


def _extract_rust_impl(node, source_bytes, file_path, chunks):
    """Extract methods from an impl block."""
    type_node = _find_first_child(node, "type_identifier", "generic_type", "scoped_type_identifier")
    if not type_node:
        return
    impl_name = _node_text(type_node, source_bytes)
    body = _find_first_child(node, "declaration_list")
    if not body:
        return

    for child in body.children:
        if child.type == "function_item":
            name_node = _find_first_child(child, "identifier")
            if not name_node:
                continue
            name = _node_text(name_node, source_bytes)
            params = _find_first_child(child, "parameters")
            sig = _node_text(params, source_bytes) if params else "()"
            docstring = _get_rust_doc(child, source_bytes)

            chunks.append(CodeChunk(
                file_path=file_path,
                language="rust",
                chunk_type="method",
                name=name,
                qualified_name=f"{impl_name}::{name}",
                signature=f"fn {name}{sig}",
                docstring=docstring,
                body=_node_text(child, source_bytes),
                start_line=child.start_point[0] + 1,
                end_line=child.end_point[0] + 1,
                parent_name=impl_name,
            ))


def _get_rust_doc(node, source_bytes: bytes) -> str:
    """Extract /// doc comments above a Rust item."""
    lines: list[str] = []
    sibling = node.prev_named_sibling
    # Walk backwards collecting line_comment nodes that start with ///
    while sibling and sibling.type == "line_comment":
        text = _node_text(sibling, source_bytes)
        if text.startswith("///"):
            lines.insert(0, text[3:].strip())
            sibling = sibling.prev_named_sibling
        else:
            break
    return "\n".join(lines)


# ─── Go ──────────────────────────────────────────────────────────────────

def _extract_go(root, source_bytes: bytes, file_path: str) -> list[CodeChunk]:
    chunks: list[CodeChunk] = []

    for node in root.children:
        if node.type == "function_declaration":
            name_node = _find_first_child(node, "identifier")
            if not name_node:
                continue
            name = _node_text(name_node, source_bytes)
            params = _find_first_child(node, "parameter_list")
            sig = _node_text(params, source_bytes) if params else "()"
            docstring = _get_go_doc(node, source_bytes)

            chunks.append(CodeChunk(
                file_path=file_path,
                language="go",
                chunk_type="function",
                name=name,
                qualified_name=name,
                signature=f"func {name}{sig}",
                docstring=docstring,
                body=_node_text(node, source_bytes),
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                metadata={"exported": name[0].isupper()},
            ))

        elif node.type == "method_declaration":
            name_node = _find_first_child(node, "field_identifier")
            receiver = _find_first_child(node, "parameter_list")
            if not name_node:
                continue
            name = _node_text(name_node, source_bytes)
            recv_str = _node_text(receiver, source_bytes) if receiver else ""
            params_list = list(_find_children(node, "parameter_list"))
            sig = _node_text(params_list[1], source_bytes) if len(params_list) > 1 else "()"
            docstring = _get_go_doc(node, source_bytes)

            # Try to extract receiver type name
            parent_name = recv_str.strip("()").split()[-1].strip("*") if recv_str else None

            chunks.append(CodeChunk(
                file_path=file_path,
                language="go",
                chunk_type="method",
                name=name,
                qualified_name=f"{parent_name}.{name}" if parent_name else name,
                signature=f"func {recv_str} {name}{sig}",
                docstring=docstring,
                body=_node_text(node, source_bytes),
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                parent_name=parent_name,
                metadata={"exported": name[0].isupper()},
            ))

        elif node.type == "type_declaration":
            for spec in _find_children(node, "type_spec"):
                type_name_node = _find_first_child(spec, "type_identifier")
                if not type_name_node:
                    continue
                type_name = _node_text(type_name_node, source_bytes)
                docstring = _get_go_doc(node, source_bytes)
                type_body = _find_first_child(spec, "struct_type", "interface_type")
                is_struct = type_body and type_body.type == "struct_type"
                chunk_type = "struct" if is_struct else "interface"

                chunks.append(CodeChunk(
                    file_path=file_path,
                    language="go",
                    chunk_type=chunk_type,
                    name=type_name,
                    qualified_name=type_name,
                    signature=f"type {type_name} {chunk_type}",
                    docstring=docstring,
                    body=_node_text(node, source_bytes),
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                ))

    return chunks


def _get_go_doc(node, source_bytes: bytes) -> str:
    """Extract Go doc comments (// lines above a declaration)."""
    lines: list[str] = []
    sibling = node.prev_named_sibling
    while sibling and sibling.type == "comment":
        text = _node_text(sibling, source_bytes)
        if text.startswith("//"):
            lines.insert(0, text[2:].strip())
            sibling = sibling.prev_named_sibling
        else:
            break
    return "\n".join(lines)


# ─── Java ────────────────────────────────────────────────────────────────

def _extract_java(root, source_bytes: bytes, file_path: str) -> list[CodeChunk]:
    chunks: list[CodeChunk] = []

    # Java wraps everything in a program > ... > class_declaration
    def _walk(node, parent_class: str | None = None):
        for child in node.children:
            if child.type == "class_declaration":
                name_node = _find_first_child(child, "identifier")
                if not name_node:
                    continue
                cls_name = _node_text(name_node, source_bytes)
                docstring = _get_jsdoc(child, source_bytes)

                chunks.append(CodeChunk(
                    file_path=file_path,
                    language="java",
                    chunk_type="class",
                    name=cls_name,
                    qualified_name=f"{parent_class}.{cls_name}" if parent_class else cls_name,
                    signature=f"class {cls_name}",
                    docstring=docstring,
                    body=_node_text(child, source_bytes),
                    start_line=child.start_point[0] + 1,
                    end_line=child.end_point[0] + 1,
                    parent_name=parent_class,
                ))

                # Recurse into class body for methods and inner classes
                body = _find_first_child(child, "class_body")
                if body:
                    _walk(body, cls_name)

            elif child.type == "method_declaration":
                name_node = _find_first_child(child, "identifier")
                if not name_node:
                    continue
                name = _node_text(name_node, source_bytes)
                params = _find_first_child(child, "formal_parameters")
                sig = _node_text(params, source_bytes) if params else "()"
                docstring = _get_jsdoc(child, source_bytes)

                chunks.append(CodeChunk(
                    file_path=file_path,
                    language="java",
                    chunk_type="method",
                    name=name,
                    qualified_name=f"{parent_class}.{name}" if parent_class else name,
                    signature=f"{name}{sig}",
                    docstring=docstring,
                    body=_node_text(child, source_bytes),
                    start_line=child.start_point[0] + 1,
                    end_line=child.end_point[0] + 1,
                    parent_name=parent_class,
                ))

            elif child.type == "interface_declaration":
                name_node = _find_first_child(child, "identifier")
                if not name_node:
                    continue
                iface_name = _node_text(name_node, source_bytes)
                docstring = _get_jsdoc(child, source_bytes)

                chunks.append(CodeChunk(
                    file_path=file_path,
                    language="java",
                    chunk_type="interface",
                    name=iface_name,
                    qualified_name=iface_name,
                    signature=f"interface {iface_name}",
                    docstring=docstring,
                    body=_node_text(child, source_bytes),
                    start_line=child.start_point[0] + 1,
                    end_line=child.end_point[0] + 1,
                ))

    _walk(root)
    return chunks


# ---------------------------------------------------------------------------
# RepoIndexer — orchestrates the full indexing pipeline
# ---------------------------------------------------------------------------


class RepoIndexer:
    """Walks a git repository and extracts code chunks via tree-sitter AST parsing.

    Usage::

        indexer = RepoIndexer("/path/to/repo")
        chunks = await indexer.index()              # full index
        chunks = await indexer.index_incremental(old_sha, new_sha)  # delta only
    """

    def __init__(self, repo_path: str | Path) -> None:
        self.repo_path = Path(repo_path).resolve()

    async def get_head_sha(self) -> str:
        """Return the current HEAD commit SHA."""
        stdout, _, rc = await _run_cmd("git", "rev-parse", "HEAD", cwd=str(self.repo_path))
        if rc != 0:
            raise RuntimeError(f"git rev-parse failed in {self.repo_path}")
        return stdout.strip()

    async def list_files(self) -> list[str]:
        """Return all tracked files in the repository."""
        stdout, _, rc = await _run_cmd("git", "ls-files", cwd=str(self.repo_path))
        if rc != 0:
            raise RuntimeError(f"git ls-files failed in {self.repo_path}")
        return [f for f in stdout.splitlines() if f.strip()]

    async def list_changed_files(self, old_sha: str, new_sha: str) -> list[str]:
        """Return files changed between two commits."""
        stdout, _, rc = await _run_cmd(
            "git", "diff", "--name-only", f"{old_sha}..{new_sha}",
            cwd=str(self.repo_path),
        )
        if rc != 0:
            raise RuntimeError(f"git diff failed: {old_sha}..{new_sha}")
        return [f for f in stdout.splitlines() if f.strip()]

    async def index(self) -> list[CodeChunk]:
        """Full index: parse all supported source files in the repo."""
        files = await self.list_files()
        return await self._parse_files(files)

    async def index_incremental(
        self, old_sha: str, new_sha: str,
    ) -> tuple[list[CodeChunk], list[str]]:
        """Incremental index: parse only changed files.

        Returns (new_chunks, changed_file_paths) so the caller can
        delete old chunks for changed files before inserting new ones.
        """
        changed_files = await self.list_changed_files(old_sha, new_sha)
        log.info(
            "incremental index",
            old_sha=old_sha[:8],
            new_sha=new_sha[:8],
            changed_files=len(changed_files),
        )
        chunks = await self._parse_files(changed_files)
        return chunks, changed_files

    async def _parse_files(self, files: list[str]) -> list[CodeChunk]:
        """Parse a list of files and return all extracted chunks."""
        all_chunks: list[CodeChunk] = []

        for rel_path in files:
            # Skip irrelevant directories
            parts = Path(rel_path).parts
            if any(p in _SKIP_PATTERNS for p in parts):
                continue

            ext = Path(rel_path).suffix
            language = _EXT_TO_LANG.get(ext)
            if language is None:
                continue

            abs_path = self.repo_path / rel_path
            if not abs_path.is_file():
                continue

            # Skip large files
            try:
                size = abs_path.stat().st_size
                if size > _MAX_FILE_SIZE:
                    log.debug("skipping large file", path=rel_path, size=size)
                    continue
            except OSError:
                continue

            try:
                source_bytes = abs_path.read_bytes()
            except OSError:
                continue

            parser = _get_parser(language)
            if parser is None:
                continue

            try:
                tree = parser.parse(source_bytes)
                chunks = _extract_chunks_from_tree(tree, source_bytes, rel_path, language)
                all_chunks.extend(chunks)
                log.debug(
                    "parsed file",
                    path=rel_path,
                    language=language,
                    chunks=len(chunks),
                )
            except Exception as exc:
                log.warning("parse error", path=rel_path, error=str(exc))
                continue

        log.info(
            "indexing complete",
            files_processed=len(files),
            chunks_extracted=len(all_chunks),
        )
        return all_chunks


# ---------------------------------------------------------------------------
# Shell helper (reused from coding_agent pattern)
# ---------------------------------------------------------------------------


async def _run_cmd(
    *args: str,
    cwd: str | None = None,
    timeout: float | None = 30.0,
) -> tuple[str, str, int]:
    """Run a shell command and return (stdout, stderr, returncode)."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    return (
        stdout_bytes.decode().strip(),
        stderr_bytes.decode().strip(),
        proc.returncode or 0,
    )
