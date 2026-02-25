import { useState, useCallback } from "react";
import { Server, ArrowRight, Loader2, AlertCircle, Wifi } from "lucide-react";
import { useConnectionStore } from "@/stores/connectionStore";

export function ConnectScreen() {
  const { serverUrl, setServerUrl, connect, connectionStatus, connectionError } =
    useConnectionStore();

  const [url, setUrl] = useState(serverUrl || "http://localhost:8000");
  const isConnecting = connectionStatus === "connecting";

  const handleConnect = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      const cleaned = url.replace(/\/+$/, "");
      setServerUrl(cleaned);
      // connect() reads from store, so set first then call
      useConnectionStore.setState({ serverUrl: cleaned });
      await connect();
    },
    [url, setServerUrl, connect]
  );

  return (
    <div className="h-screen flex items-center justify-center" style={{ background: "var(--forge-bg)" }}>
      <div className="w-full max-w-md px-8">
        {/* Logo + header */}
        <div className="text-center mb-10">
          <div
            className="inline-flex items-center justify-center w-16 h-16 rounded-2xl mb-6"
            style={{ background: "var(--forge-accent)", opacity: 0.9 }}
          >
            <Wifi className="w-8 h-8 text-white" />
          </div>
          <h1
            className="text-2xl font-bold mb-2"
            style={{ color: "var(--forge-text)" }}
          >
            Connect to Forge
          </h1>
          <p style={{ color: "var(--forge-text-muted)" }} className="text-sm">
            Enter your Forge server URL to get started
          </p>
        </div>

        {/* Form */}
        <form onSubmit={handleConnect} className="space-y-4">
          <div>
            <label
              className="block text-xs font-medium mb-1.5"
              style={{ color: "var(--forge-text-muted)" }}
            >
              Server URL
            </label>
            <div className="relative">
              <Server
                className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4"
                style={{ color: "var(--forge-text-muted)" }}
              />
              <input
                type="url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://forge.yourcompany.com"
                disabled={isConnecting}
                autoFocus
                className="w-full pl-10 pr-4 py-2.5 rounded-lg text-sm outline-none transition-colors"
                style={{
                  background: "var(--forge-channel)",
                  color: "var(--forge-text)",
                  border: `1px solid ${connectionError ? "var(--forge-error)" : "var(--forge-border)"}`,
                }}
                onFocus={(e) =>
                  (e.target.style.borderColor = "var(--forge-accent)")
                }
                onBlur={(e) =>
                  (e.target.style.borderColor = connectionError
                    ? "var(--forge-error)"
                    : "var(--forge-border)")
                }
              />
            </div>
          </div>

          {/* Error message */}
          {connectionError && (
            <div
              className="flex items-start gap-2 text-xs p-3 rounded-lg"
              style={{
                color: "var(--forge-error)",
                background: "rgba(232, 64, 64, 0.1)",
              }}
            >
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{connectionError}</span>
            </div>
          )}

          {/* Connect button */}
          <button
            type="submit"
            disabled={isConnecting || !url.trim()}
            className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-medium transition-opacity text-white cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            style={{ background: "var(--forge-accent)" }}
          >
            {isConnecting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Connecting...
              </>
            ) : (
              <>
                Connect
                <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>
        </form>

        {/* Help text */}
        <p
          className="text-xs text-center mt-6"
          style={{ color: "var(--forge-text-muted)" }}
        >
          Don't have a server?{" "}
          <span style={{ color: "var(--forge-accent)" }} className="cursor-pointer">
            Set up Forge
          </span>
        </p>
      </div>
    </div>
  );
}
