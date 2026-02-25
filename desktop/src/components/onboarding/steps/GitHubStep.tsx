import { useState, useCallback, useEffect } from "react";
import { Eye, EyeOff, Loader2, Search, AlertCircle, Check, GitBranch, Star, Lock as LockIcon } from "lucide-react";
import { invoke } from "@tauri-apps/api/core";
import { useConnectionStore } from "@/stores/connectionStore";
import { useOnboardingStore, type GitHubRepo } from "@/stores/onboardingStore";

interface ProxyResponse {
  status: number;
  body: string;
  headers: Record<string, string>;
}

export function GitHubStep() {
  const { serverUrl, authToken } = useConnectionStore();
  const { completeStep, githubUser, githubRepos, selectedRepo, setGitHubUser, setGitHubRepos, setSelectedRepo } = useOnboardingStore();

  const [token, setToken] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loadingRepos, setLoadingRepos] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [repoFilter, setRepoFilter] = useState("");

  const isConnected = !!githubUser;

  // Fetch repos after connecting
  const fetchRepos = useCallback(async () => {
    if (!serverUrl || !authToken) return;
    setLoadingRepos(true);
    try {
      const res = await invoke<ProxyResponse>("proxy_fetch", {
        url: `${serverUrl}/api/onboarding/github-repos`,
        method: "GET",
        body: null,
        authToken,
      });
      if (res.status >= 200 && res.status < 300) {
        const repos = JSON.parse(res.body) as GitHubRepo[];
        setGitHubRepos(repos);
      }
    } catch {
      // Non-critical
    } finally {
      setLoadingRepos(false);
    }
  }, [serverUrl, authToken, setGitHubRepos]);

  // If already connected, load repos
  useEffect(() => {
    if (isConnected && githubRepos.length === 0) {
      fetchRepos();
    }
  }, [isConnected, githubRepos.length, fetchRepos]);

  const handleSaveToken = useCallback(async () => {
    if (!token.trim() || !serverUrl || !authToken) return;
    setSaving(true);
    setError(null);

    try {
      const res = await invoke<ProxyResponse>("proxy_fetch", {
        url: `${serverUrl}/api/onboarding/validate-github-token`,
        method: "POST",
        body: JSON.stringify({ token: token.trim() }),
        authToken,
      });

      if (res.status < 200 || res.status >= 300) {
        const body = JSON.parse(res.body);
        throw new Error(body.detail || `Validation failed (${res.status})`);
      }

      const data = JSON.parse(res.body) as { github_user: string; github_name: string };
      setGitHubUser(data.github_user);

      // Fetch repos after connecting
      await fetchRepos();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to validate token");
    } finally {
      setSaving(false);
    }
  }, [token, serverUrl, authToken, setGitHubUser, fetchRepos]);

  const handleSelectRepo = useCallback(async (repo: GitHubRepo) => {
    setSelectedRepo(repo);
    if (serverUrl && authToken) {
      await completeStep(serverUrl, authToken, "github");
    }
  }, [serverUrl, authToken, completeStep, setSelectedRepo]);

  const filteredRepos = githubRepos.filter(
    (r) =>
      r.full_name.toLowerCase().includes(repoFilter.toLowerCase()) ||
      (r.description || "").toLowerCase().includes(repoFilter.toLowerCase())
  );

  // ─── Not connected yet ─────────────────────────────
  if (!isConnected) {
    return (
      <div className="space-y-4">
        <p className="text-sm" style={{ color: "var(--forge-text-muted)" }}>
          Connect a GitHub account so your agents can create branches, push code, and open pull requests.
        </p>

        {/* PAT input */}
        <div>
          <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--forge-text-muted)" }}>
            Personal access token
          </label>
          <div className="relative">
            <input
              type={showToken ? "text" : "password"}
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="ghp_..."
              disabled={saving}
              className="w-full pl-3 pr-10 py-2.5 rounded-lg text-sm outline-none transition-colors font-mono"
              style={{
                background: "var(--forge-channel)",
                color: "var(--forge-text)",
                border: `1px solid ${error ? "var(--forge-error)" : "var(--forge-border)"}`,
              }}
              onFocus={(e) => (e.target.style.borderColor = "var(--forge-accent)")}
              onBlur={(e) => (e.target.style.borderColor = error ? "var(--forge-error)" : "var(--forge-border)")}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSaveToken();
              }}
            />
            <button
              type="button"
              onClick={() => setShowToken(!showToken)}
              className="absolute right-3 top-1/2 -translate-y-1/2 cursor-pointer"
              style={{ color: "var(--forge-text-muted)" }}
            >
              {showToken ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>
          <p className="text-xs mt-1.5" style={{ color: "var(--forge-text-muted)" }}>
            Token needs: <code className="text-xs" style={{ color: "var(--forge-text)" }}>repo</code>, <code className="text-xs" style={{ color: "var(--forge-text)" }}>workflow</code> scopes
          </p>
        </div>

        {/* Error */}
        {error && (
          <div
            className="flex items-start gap-2 text-xs p-3 rounded-lg"
            style={{ color: "var(--forge-error)", background: "rgba(232, 64, 64, 0.1)" }}
          >
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        {/* Save button */}
        <button
          onClick={handleSaveToken}
          disabled={saving || !token.trim()}
          className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-white transition-opacity cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          style={{ background: "var(--forge-accent)" }}
        >
          {saving ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Validating...
            </>
          ) : (
            "Save token"
          )}
        </button>
      </div>
    );
  }

  // ─── Connected — show repo picker ──────────────────
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 text-sm" style={{ color: "var(--forge-text)" }}>
        <Check className="w-4 h-4" style={{ color: "var(--forge-accent)" }} />
        Connected as <span className="font-medium">{githubUser}</span>
      </div>

      <p className="text-sm" style={{ color: "var(--forge-text-muted)" }}>
        Pick a repo for your first project:
      </p>

      {/* Search repos */}
      <div className="relative">
        <Search
          className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4"
          style={{ color: "var(--forge-text-muted)" }}
        />
        <input
          type="text"
          value={repoFilter}
          onChange={(e) => setRepoFilter(e.target.value)}
          placeholder="Search your repos..."
          className="w-full pl-10 pr-4 py-2 rounded-lg text-sm outline-none transition-colors"
          style={{
            background: "var(--forge-channel)",
            color: "var(--forge-text)",
            border: "1px solid var(--forge-border)",
          }}
          onFocus={(e) => (e.target.style.borderColor = "var(--forge-accent)")}
          onBlur={(e) => (e.target.style.borderColor = "var(--forge-border)")}
        />
      </div>

      {/* Repo list */}
      <div
        className="max-h-48 overflow-y-auto rounded-lg"
        style={{ border: "1px solid var(--forge-border)" }}
      >
        {loadingRepos ? (
          <div className="flex items-center justify-center py-6">
            <Loader2 className="w-4 h-4 animate-spin" style={{ color: "var(--forge-text-muted)" }} />
          </div>
        ) : filteredRepos.length === 0 ? (
          <div className="text-xs text-center py-6" style={{ color: "var(--forge-text-muted)" }}>
            No repos found
          </div>
        ) : (
          filteredRepos.map((repo) => {
            const isSelected = selectedRepo?.full_name === repo.full_name;
            return (
              <button
                key={repo.full_name}
                onClick={() => handleSelectRepo(repo)}
                className="w-full flex items-center justify-between px-3 py-2.5 text-left transition-colors cursor-pointer"
                style={{
                  background: isSelected ? "rgba(99, 102, 241, 0.1)" : "transparent",
                  borderBottom: "1px solid var(--forge-border)",
                }}
                onMouseEnter={(e) => {
                  if (!isSelected) e.currentTarget.style.background = "var(--forge-hover)";
                }}
                onMouseLeave={(e) => {
                  if (!isSelected) e.currentTarget.style.background = "transparent";
                }}
              >
                <div>
                  <div className="text-sm flex items-center gap-1.5" style={{ color: "var(--forge-text)" }}>
                    {repo.private && <LockIcon className="w-3 h-3" style={{ color: "var(--forge-text-muted)" }} />}
                    {repo.full_name}
                  </div>
                  {repo.description && (
                    <div className="text-xs mt-0.5 truncate max-w-sm" style={{ color: "var(--forge-text-muted)" }}>
                      {repo.description}
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-3 text-xs shrink-0" style={{ color: "var(--forge-text-muted)" }}>
                  <span className="flex items-center gap-0.5">
                    <Star className="w-3 h-3" /> {repo.stars}
                  </span>
                  <span className="flex items-center gap-0.5">
                    <GitBranch className="w-3 h-3" /> {repo.default_branch}
                  </span>
                  {isSelected && <Check className="w-4 h-4" style={{ color: "var(--forge-accent)" }} />}
                </div>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
