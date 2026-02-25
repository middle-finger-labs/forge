import { useState, useCallback } from "react";
import { X, FolderGit2, Globe, HardDrive, Loader2 } from "lucide-react";
import { useLayoutStore } from "@/stores/layoutStore";
import { useRepoStore } from "@/stores/repoStore";
import { cn } from "@/lib/utils";

type SourceType = "git" | "local";

export function IndexRepoModal() {
  const { indexRepoModalOpen, closeIndexRepoModal, openDetailPanel } = useLayoutStore();
  const { addRepo } = useRepoStore();
  const [sourceType, setSourceType] = useState<SourceType>("git");
  const [source, setSource] = useState("");
  const [indexing, setIndexing] = useState(false);
  const [error, setError] = useState("");

  const handleIndex = useCallback(async () => {
    const trimmed = source.trim();
    if (!trimmed) return;

    setError("");
    setIndexing(true);

    try {
      // In production this calls the API; here we simulate
      await new Promise((r) => setTimeout(r, 1000));

      const name = sourceType === "git"
        ? trimmed.split("/").pop()?.replace(".git", "") ?? "repo"
        : trimmed.split("/").pop() ?? "repo";

      const newRepo = {
        id: `repo-${Date.now()}`,
        name,
        source: trimmed,
        sourceType,
        indexingStatus: "indexing" as const,
        indexingProgress: 0,
        chunkCount: 0,
        languages: [],
        fileCount: 0,
        localPath: sourceType === "local" ? trimmed : `/Users/homebase/repos/${name}`,
      };

      addRepo(newRepo);
      closeIndexRepoModal();
      openDetailPanel("codebase");

      // Simulate indexing progress
      setSource("");

      // Simulate the indexing completing after some time
      let progress = 0;
      const interval = setInterval(() => {
        progress += Math.floor(Math.random() * 15) + 5;
        if (progress >= 100) {
          progress = 100;
          clearInterval(interval);
          useRepoStore.getState().updateRepo(newRepo.id, {
            indexingStatus: "ready",
            indexingProgress: 100,
            chunkCount: Math.floor(Math.random() * 500) + 200,
            languages: ["TypeScript", "JavaScript"],
            fileCount: Math.floor(Math.random() * 100) + 30,
            lastIndexedAt: new Date().toISOString(),
          });
        } else {
          useRepoStore.getState().updateRepo(newRepo.id, {
            indexingProgress: progress,
          });
        }
      }, 800);
    } catch (err) {
      setError("Failed to start indexing. Check the URL or path and try again.");
    } finally {
      setIndexing(false);
    }
  }, [source, sourceType, addRepo, closeIndexRepoModal, openDetailPanel]);

  if (!indexRepoModalOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={closeIndexRepoModal}
      />

      {/* Modal */}
      <div className="relative w-full max-w-lg mx-4 rounded-xl border border-[var(--forge-border)] bg-[var(--forge-sidebar)] shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--forge-border)]">
          <div className="flex items-center gap-2.5">
            <FolderGit2 className="w-5 h-5 text-[var(--forge-accent)]" />
            <h2 className="text-base font-semibold text-white">Index Repository</h2>
          </div>
          <button
            onClick={closeIndexRepoModal}
            className="p-1 rounded hover:bg-[var(--forge-hover)] text-[var(--forge-text-muted)] hover:text-white transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content */}
        <div className="px-5 py-4 space-y-4">
          {/* Source type toggle */}
          <div>
            <label className="text-xs font-medium text-[var(--forge-text-muted)] uppercase tracking-wider block mb-2">
              Source Type
            </label>
            <div className="flex gap-2">
              <button
                onClick={() => {
                  setSourceType("git");
                  setSource("");
                  setError("");
                }}
                className={cn(
                  "flex items-center gap-2 px-3 py-2 rounded-lg border text-sm transition-colors flex-1",
                  sourceType === "git"
                    ? "border-[var(--forge-accent)] bg-[var(--forge-accent)]/10 text-white"
                    : "border-[var(--forge-border)] text-[var(--forge-text-muted)] hover:border-[var(--forge-text-muted)]"
                )}
              >
                <Globe className="w-4 h-4" />
                Git URL
              </button>
              <button
                onClick={() => {
                  setSourceType("local");
                  setSource("");
                  setError("");
                }}
                className={cn(
                  "flex items-center gap-2 px-3 py-2 rounded-lg border text-sm transition-colors flex-1",
                  sourceType === "local"
                    ? "border-[var(--forge-accent)] bg-[var(--forge-accent)]/10 text-white"
                    : "border-[var(--forge-border)] text-[var(--forge-text-muted)] hover:border-[var(--forge-text-muted)]"
                )}
              >
                <HardDrive className="w-4 h-4" />
                Local Path
              </button>
            </div>
          </div>

          {/* Source input */}
          <div>
            <label className="text-xs font-medium text-[var(--forge-text-muted)] uppercase tracking-wider block mb-2">
              {sourceType === "git" ? "Repository URL" : "Directory Path"}
            </label>
            <input
              type="text"
              value={source}
              onChange={(e) => {
                setSource(e.target.value);
                setError("");
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && source.trim()) handleIndex();
              }}
              placeholder={
                sourceType === "git"
                  ? "https://github.com/org/repo.git"
                  : "/path/to/your/project"
              }
              className="w-full px-3 py-2.5 rounded-lg border border-[var(--forge-border)] bg-[var(--forge-bg)] text-sm text-[var(--forge-text)] outline-none focus:border-[var(--forge-accent)] transition-colors placeholder:text-[var(--forge-text-muted)]"
              autoFocus
            />
          </div>

          {/* Error */}
          {error && (
            <p className="text-xs text-[var(--forge-error)]">{error}</p>
          )}

          {/* Info */}
          <p className="text-xs text-[var(--forge-text-muted)]">
            {sourceType === "git"
              ? "The repository will be cloned, then files will be chunked and embedded for semantic search."
              : "Files in the directory will be chunked and embedded for semantic search. The directory must exist."}
          </p>
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 px-5 py-3 border-t border-[var(--forge-border)]">
          <button
            onClick={closeIndexRepoModal}
            className="px-4 py-2 rounded-lg text-sm text-[var(--forge-text-muted)] hover:text-white hover:bg-[var(--forge-hover)] transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleIndex}
            disabled={!source.trim() || indexing}
            className={cn(
              "px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2",
              source.trim() && !indexing
                ? "bg-[var(--forge-accent)] text-white hover:bg-[var(--forge-active)]"
                : "bg-[var(--forge-hover)] text-[var(--forge-text-muted)] cursor-not-allowed"
            )}
          >
            {indexing ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                Indexing...
              </>
            ) : (
              "Start Indexing"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
