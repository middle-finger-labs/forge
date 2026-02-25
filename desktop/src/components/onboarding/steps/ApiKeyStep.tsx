import { useState, useCallback } from "react";
import { Eye, EyeOff, Loader2, Lock, ExternalLink, AlertCircle } from "lucide-react";
import { invoke } from "@tauri-apps/api/core";
import { useConnectionStore } from "@/stores/connectionStore";
import { useOnboardingStore } from "@/stores/onboardingStore";

interface ProxyResponse {
  status: number;
  body: string;
  headers: Record<string, string>;
}

export function ApiKeyStep() {
  const { serverUrl, authToken } = useConnectionStore();
  const { completeStep } = useOnboardingStore();
  const [key, setKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = useCallback(async () => {
    if (!key.trim() || !serverUrl || !authToken) return;
    setSaving(true);
    setError(null);

    try {
      const res = await invoke<ProxyResponse>("proxy_fetch", {
        url: `${serverUrl}/api/onboarding/validate-api-key`,
        method: "POST",
        body: JSON.stringify({ key: key.trim() }),
        authToken,
      });

      if (res.status < 200 || res.status >= 300) {
        const body = JSON.parse(res.body);
        throw new Error(body.detail || `Validation failed (${res.status})`);
      }

      // Mark step complete
      await completeStep(serverUrl, authToken, "api_key");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to validate key");
    } finally {
      setSaving(false);
    }
  }, [key, serverUrl, authToken, completeStep]);

  const handleOpenConsole = useCallback(() => {
    import("@tauri-apps/plugin-shell").then(({ open }) => {
      open("https://console.anthropic.com/settings/keys");
    }).catch(() => {
      window.open("https://console.anthropic.com/settings/keys", "_blank");
    });
  }, []);

  return (
    <div className="space-y-4">
      <p className="text-sm" style={{ color: "var(--forge-text-muted)" }}>
        Your agents need an Anthropic API key to think.
        Get one at console.anthropic.com if you don't have one.
      </p>

      {/* API key input */}
      <div className="relative">
        <input
          type={showKey ? "text" : "password"}
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder="sk-ant-api03-..."
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
            if (e.key === "Enter") handleSave();
          }}
        />
        <button
          type="button"
          onClick={() => setShowKey(!showKey)}
          className="absolute right-3 top-1/2 -translate-y-1/2 cursor-pointer"
          style={{ color: "var(--forge-text-muted)" }}
        >
          {showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
        </button>
      </div>

      {/* Security note */}
      <div className="flex items-center gap-1.5 text-xs" style={{ color: "var(--forge-text-muted)" }}>
        <Lock className="w-3 h-3" />
        Stored encrypted. Only used for your org's agents.
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

      {/* Actions */}
      <div className="flex items-center justify-between">
        <button
          onClick={handleSave}
          disabled={saving || !key.trim()}
          className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-white transition-opacity cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          style={{ background: "var(--forge-accent)" }}
        >
          {saving ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Validating...
            </>
          ) : (
            "Save key"
          )}
        </button>

        <button
          onClick={handleOpenConsole}
          className="flex items-center gap-1 text-xs cursor-pointer transition-colors"
          style={{ color: "var(--forge-text-muted)" }}
          onMouseEnter={(e) => (e.currentTarget.style.color = "var(--forge-accent)")}
          onMouseLeave={(e) => (e.currentTarget.style.color = "var(--forge-text-muted)")}
        >
          Don't have a key?
          <ExternalLink className="w-3 h-3" />
        </button>
      </div>
    </div>
  );
}
