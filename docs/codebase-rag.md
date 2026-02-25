# Codebase RAG (Retrieval-Augmented Generation)

## Overview

Forge indexes codebases using AST-based parsing and dual-embedding vectors to provide agents with relevant code context during pipeline execution. This enables agents to understand existing code patterns, reference specific files, and make contextually-aware decisions.

## Architecture

```
                    ┌─────────────┐
                    │  Git Repo   │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  RepoIndexer │  (tree-sitter AST parsing)
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  CodeChunks  │  (functions, classes, methods, interfaces)
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │ ChunkEmbedder│  (dual embeddings)
                    └──┬───────┬──┘
                       │       │
              ┌────────▼┐  ┌──▼────────┐
              │  Code   │  │Description│
              │Embedding│  │ Embedding │
              └────┬────┘  └─────┬─────┘
                   │             │
              ┌────▼─────────────▼────┐
              │    pgvector Storage    │
              └───────────┬───────────┘
                          │
              ┌───────────▼───────────┐
              │   Context Assembler    │  (semantic search + structural expansion)
              └───────────┬───────────┘
                          │
              ┌───────────▼───────────┐
              │    Agent Prompt        │
              └───────────────────────┘
```

## Indexing Pipeline

### 1. AST Parsing

The `RepoIndexer` walks a git repository and parses each supported source file using tree-sitter:

**Supported Languages:**
- Python (`.py`)
- TypeScript (`.ts`, `.tsx`)
- JavaScript (`.js`, `.jsx`)
- Rust (`.rs`)
- Go (`.go`)
- Java (`.java`)

**Extracted Chunk Types:**
- Functions and methods (with signatures, docstrings, decorators)
- Classes and structs
- Interfaces and traits
- Type aliases and enums

Each chunk captures:
- `file_path`, `language`, `chunk_type`, `name`, `qualified_name`
- `body` (full source text), `signature`, `docstring`
- `start_line`, `end_line` for precise file references
- `parent_name` for methods/nested types
- `metadata` (decorators, visibility, exported status)

### 2. Incremental Indexing

For efficiency, Forge supports incremental re-indexing:

```python
indexer = RepoIndexer("/path/to/repo")

# Full index (initial)
chunks = await indexer.index()

# Incremental (subsequent updates)
new_chunks, changed_paths = await indexer.index_incremental(old_sha, new_sha)
```

Only files changed between two commits are re-parsed. The caller deletes old chunks for changed files and inserts new ones.

### 3. Dual Embeddings

The `ChunkEmbedder` produces two 384-dimensional vectors per chunk using `multi-qa-MiniLM-L6-cos-v1`:

1. **Code embedding** - from the raw source text, capturing syntactic patterns
2. **Description embedding** - from a synthesized natural-language description

This dual approach enables both:
- **Code-to-code search**: "Find functions similar to this one"
- **NL-to-code search**: "Function that validates email addresses"

### 4. Storage

Embedded chunks are stored in PostgreSQL with pgvector:
- `code_chunks` table holds chunk metadata + dual embedding vectors
- Cosine similarity search (`<=>` operator) for retrieval
- Org-scoped and repo-scoped access control

## Context Assembly

The Context Assembler builds agent prompts by:

1. **Semantic search** - Find chunks matching the task description
2. **Structural expansion** - Include parent classes, related types
3. **RRF merging** - Reciprocal Rank Fusion combines code + description results
4. **Token budgeting** - Fit within the agent's context window
5. **Role filtering** - Different agents get different context configs

## Desktop App Integration

The desktop app provides:
- **Repos sidebar section** - Lists indexed repos with status, chunk counts, languages
- **Repo context picker** - Select a repo as context for agent DMs
- **Codebase Explorer** - File tree, search, dependency graph in the detail panel
- **Code references** - Agent responses include file:line references with "Open in VS Code" buttons

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/repos` | GET | List indexed repositories |
| `/api/repos` | POST | Index a new repository |
| `/api/repos/:id/reindex` | POST | Trigger re-indexing |
| `/api/repos/:id` | DELETE | Remove a repository |
| `/api/repos/:id/files` | GET | Get file tree |
| `/api/repos/:id/files/:path/chunks` | GET | Get chunks for a file |
| `/api/repos/:id/search` | POST | Semantic search within repo |
| `/api/repos/:id/dependencies` | GET | Get dependency graph |

## Configuration

Key constants in `agents/codebase/indexer.py`:
- `_MAX_FILE_SIZE`: 512 KB (files larger than this are skipped)
- `_SKIP_PATTERNS`: Directories to ignore (node_modules, .git, etc.)

Key constants in `agents/codebase/embedder.py`:
- `_EMBEDDING_MODEL`: `multi-qa-MiniLM-L6-cos-v1`
- `_EMBEDDING_DIMS`: 384
- `_MAX_CODE_CHARS`: 8,000 (truncation limit for code text)
- `_MAX_DESC_CHARS`: 2,000 (truncation limit for descriptions)
