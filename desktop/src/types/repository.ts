// ─── Indexing status ─────────────────────────────────────

export type IndexingStatus =
  | "idle"
  | "cloning"
  | "indexing"
  | "ready"
  | "error";

// ─── Repository ─────────────────────────────────────────

export interface Repository {
  id: string;
  name: string;
  /** Git remote URL or local path */
  source: string;
  /** Whether this repo was cloned from a URL or is a local path */
  sourceType: "git" | "local";
  /** Current indexing state */
  indexingStatus: IndexingStatus;
  /** Progress 0-100 when indexing */
  indexingProgress?: number;
  /** ISO timestamp of last successful index */
  lastIndexedAt?: string;
  /** Number of indexed chunks */
  chunkCount: number;
  /** Detected programming languages */
  languages: string[];
  /** Total number of files indexed */
  fileCount: number;
  /** Local path to the cloned/indexed repo */
  localPath: string;
  /** Default branch name */
  defaultBranch?: string;
  /** Error message if indexing failed */
  error?: string;
}

// ─── File tree node ─────────────────────────────────────

export interface FileNode {
  name: string;
  path: string;
  type: "file" | "directory";
  children?: FileNode[];
  /** Language detected for this file */
  language?: string;
  /** Number of chunks this file was split into */
  chunkCount?: number;
  /** File size in bytes */
  size?: number;
}

// ─── Code chunk ─────────────────────────────────────────

export interface RepoChunk {
  id: string;
  repoId: string;
  filePath: string;
  startLine: number;
  endLine: number;
  content: string;
  language: string;
  /** Semantic summary of the chunk */
  summary?: string;
  /** Symbols defined in this chunk (functions, classes, etc.) */
  symbols?: string[];
}

// ─── Search result ──────────────────────────────────────

export interface RepoSearchResult {
  chunk: RepoChunk;
  score: number;
  highlights?: Array<{ start: number; end: number }>;
}

// ─── Dependency edge ────────────────────────────────────

export interface DependencyEdge {
  from: string; // file path
  to: string; // file path
  type: "import" | "require" | "include";
}

// ─── Codebase context (attached to messages) ────────────

export interface CodebaseContext {
  repoId: string;
  repoName: string;
  /** Relevant chunks assembled by RAG */
  chunks: RepoChunk[];
  /** Total token count of assembled context */
  tokenCount: number;
}

// ─── Code reference (in agent responses) ────────────────

export interface CodeReference {
  filePath: string;
  startLine: number;
  endLine?: number;
  repoId: string;
  snippet?: string;
}
