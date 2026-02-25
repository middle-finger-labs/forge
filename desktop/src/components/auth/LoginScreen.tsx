import { useState, useCallback } from "react";
import { Mail, Lock, ArrowRight, Loader2, AlertCircle, ArrowLeft } from "lucide-react";
import { useConnectionStore } from "@/stores/connectionStore";

export function LoginScreen() {
  const { login, connectionStatus, connectionError, serverUrl, setConnectionStatus } =
    useConnectionStore();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const isLoading = connectionStatus === "connecting";

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      try {
        await login(email, password, remember);
      } catch {
        // Error is set in the store
      }
    },
    [email, password, remember, login]
  );

  const handleBack = useCallback(() => {
    setConnectionStatus("unconfigured");
  }, [setConnectionStatus]);

  return (
    <div className="h-screen flex items-center justify-center" style={{ background: "var(--forge-bg)" }}>
      <div className="w-full max-w-md px-8">
        {/* Back button */}
        <button
          onClick={handleBack}
          className="flex items-center gap-1 text-xs mb-8 cursor-pointer transition-colors"
          style={{ color: "var(--forge-text-muted)" }}
          onMouseEnter={(e) => (e.currentTarget.style.color = "var(--forge-text)")}
          onMouseLeave={(e) => (e.currentTarget.style.color = "var(--forge-text-muted)")}
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Change server
        </button>

        {/* Header */}
        <div className="text-center mb-8">
          <h1
            className="text-2xl font-bold mb-2"
            style={{ color: "var(--forge-text)" }}
          >
            Sign in to Forge
          </h1>
          <p className="text-sm" style={{ color: "var(--forge-text-muted)" }}>
            {serverUrl}
          </p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Email */}
          <div>
            <label
              className="block text-xs font-medium mb-1.5"
              style={{ color: "var(--forge-text-muted)" }}
            >
              Email
            </label>
            <div className="relative">
              <Mail
                className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4"
                style={{ color: "var(--forge-text-muted)" }}
              />
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
                disabled={isLoading}
                autoFocus
                autoComplete="email"
                className="w-full pl-10 pr-4 py-2.5 rounded-lg text-sm outline-none transition-colors"
                style={{
                  background: "var(--forge-channel)",
                  color: "var(--forge-text)",
                  border: "1px solid var(--forge-border)",
                }}
                onFocus={(e) =>
                  (e.target.style.borderColor = "var(--forge-accent)")
                }
                onBlur={(e) =>
                  (e.target.style.borderColor = "var(--forge-border)")
                }
              />
            </div>
          </div>

          {/* Password */}
          <div>
            <label
              className="block text-xs font-medium mb-1.5"
              style={{ color: "var(--forge-text-muted)" }}
            >
              Password
            </label>
            <div className="relative">
              <Lock
                className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4"
                style={{ color: "var(--forge-text-muted)" }}
              />
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter your password"
                disabled={isLoading}
                autoComplete="current-password"
                className="w-full pl-10 pr-4 py-2.5 rounded-lg text-sm outline-none transition-colors"
                style={{
                  background: "var(--forge-channel)",
                  color: "var(--forge-text)",
                  border: "1px solid var(--forge-border)",
                }}
                onFocus={(e) =>
                  (e.target.style.borderColor = "var(--forge-accent)")
                }
                onBlur={(e) =>
                  (e.target.style.borderColor = "var(--forge-border)")
                }
              />
            </div>
          </div>

          {/* Remember me */}
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
              className="w-4 h-4 rounded accent-[var(--forge-accent)]"
            />
            <span className="text-sm" style={{ color: "var(--forge-text-muted)" }}>
              Remember me
            </span>
          </label>

          {/* Error */}
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

          {/* Submit */}
          <button
            type="submit"
            disabled={isLoading || !email.trim() || !password}
            className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-medium transition-opacity text-white cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            style={{ background: "var(--forge-accent)" }}
          >
            {isLoading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Signing in...
              </>
            ) : (
              <>
                Sign in
                <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>
        </form>
      </div>
    </div>
  );
}
