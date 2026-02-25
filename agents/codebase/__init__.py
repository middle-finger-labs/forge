"""AST-based code indexing pipeline.

Ingests a codebase into searchable, semantically-aware chunks using
tree-sitter for AST parsing, sentence-transformers for dual embeddings
(code + natural-language description), and pgvector for storage & retrieval.

Modules:
    indexer  — git repo walker + tree-sitter AST chunker
    embedder — dual embedding generator (code + NL description)
    store    — pgvector CRUD, hybrid search, incremental re-index
    context_assembler — retrieval + ranking for agent context injection
    file_tree — compact file tree generator for agent prompts
"""

from agents.codebase.context_assembler import (
    AssembledContext,
    ContextAssembler,
    get_agent_context_config,
)
from agents.codebase.embedder import ChunkEmbedder
from agents.codebase.file_tree import build_file_tree, build_file_tree_from_paths
from agents.codebase.indexer import CodeChunk, RepoIndexer
from agents.codebase.store import CodeChunkStore

__all__ = [
    "AssembledContext",
    "ChunkEmbedder",
    "CodeChunk",
    "CodeChunkStore",
    "ContextAssembler",
    "RepoIndexer",
    "build_file_tree",
    "build_file_tree_from_paths",
    "get_agent_context_config",
]
