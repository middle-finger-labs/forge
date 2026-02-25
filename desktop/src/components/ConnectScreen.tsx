import { useState, useCallback, useEffect, useRef } from "react";
import {
  Mail,
  ArrowRight,
  Loader2,
  AlertCircle,
  Wifi,
  CheckCircle,
  ArrowLeft,
  Server,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Lock,
  Search,
  RefreshCw,
} from "lucide-react";
import { useConnectionStore } from "@/stores/connectionStore";

/**
 * Magic link onboarding screen.
 *
 * Modes:
 * 1. No server URL → auto-discover from email domain, or show URL field
 * 2. Server URL known → show email input
 * 3. Awaiting magic link → "check your email" with polling, resend, open mail
 * 4. Password fallback → inline server URL + password fields
 */
export function ConnectScreen() {
  const {
    serverUrl: storedServerUrl,
    connectionStatus,
    connectionError,
    magicLinkEmail,
    cooldownRemaining,
    isDiscovering,
    requestMagicLink,
    setServerUrl,
    connect,
    setConnectionStatus,
    setError,
    serverInfo,
    discoverServer,
    checkMagicLinkStatus,
    verifyMagicLink,
    login,
    setCooldownRemaining,
  } = useConnectionStore();

  const [email, setEmail] = useState("");
  const [url, setUrl] = useState(storedServerUrl || "");
  const [showServerField, setShowServerField] = useState(!storedServerUrl);
  const [showPasswordMode, setShowPasswordMode] = useState(false);
  const [password, setPassword] = useState("");
  const [localCooldown, setLocalCooldown] = useState(0);
  const isLoading = connectionStatus === "connecting";
  const isAwaiting = connectionStatus === "awaiting_magic_link";
  const hasServer = !!storedServerUrl;

  // ─── Resend cooldown timer ────────────────────────
  useEffect(() => {
    if (cooldownRemaining > 0) {
      setLocalCooldown(cooldownRemaining);
    }
  }, [cooldownRemaining]);

  useEffect(() => {
    if (localCooldown <= 0) return;
    const timer = setInterval(() => {
      setLocalCooldown((prev) => Math.max(0, prev - 1));
    }, 1000);
    return () => clearInterval(timer);
  }, [localCooldown > 0]); // Only re-run when transitioning between active/inactive

  // ─── Status polling (3-second interval) ───────────
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!isAwaiting) {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
      return;
    }

    pollingRef.current = setInterval(async () => {
      try {
        const result = await checkMagicLinkStatus();
        if (result.status === "consumed" && result.token) {
          if (pollingRef.current) clearInterval(pollingRef.current);
          pollingRef.current = null;
          try {
            await verifyMagicLink(result.token);
          } catch (err) {
            console.error("[Auth] Magic link verification failed:", err);
          }
        } else if (result.status === "expired" || result.status === "not_found") {
          if (pollingRef.current) clearInterval(pollingRef.current);
          pollingRef.current = null;
        }
      } catch {
        // Non-critical polling failure
      }
    }, 3000);

    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    };
  }, [isAwaiting, checkMagicLinkStatus, verifyMagicLink]);

  // ─── Handlers ─────────────────────────────────────

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!email.trim()) return;

      try {
        if (showPasswordMode) {
          // Password login flow
          const serverTarget = url.trim().replace(/\/+$/, "") || storedServerUrl;
          if (!serverTarget) return;
          if (serverTarget !== storedServerUrl) {
            setServerUrl(serverTarget);
            useConnectionStore.setState({ serverUrl: serverTarget });
            const connected = await connect();
            if (!connected) return;
          }
          await login(email.trim(), password, true);
          return;
        }

        // Magic link flow with auto-discovery
        if (!hasServer && !url.trim()) {
          // No server URL — try auto-discovery
          const discovered = await discoverServer(email.trim());
          if (discovered) {
            const cleaned = discovered.replace(/\/+$/, "");
            setServerUrl(cleaned);
            setUrl(cleaned);
            useConnectionStore.setState({ serverUrl: cleaned });
            const connected = await connect();
            if (!connected) return;
            await requestMagicLink(email.trim());
            setLocalCooldown(60);
          } else {
            // Discovery failed — show server URL field
            setShowServerField(true);
            setError("Could not find a Forge server for this domain. Please enter the server URL.");
          }
          return;
        }

        // Connect if server URL provided but not yet connected
        if (!hasServer && url.trim()) {
          const cleaned = url.trim().replace(/\/+$/, "");
          setServerUrl(cleaned);
          useConnectionStore.setState({ serverUrl: cleaned });
          const connected = await connect();
          if (!connected) return;
        }

        await requestMagicLink(email.trim());
        setLocalCooldown(60);
      } catch {
        // Error is set in the store
      }
    },
    [email, url, password, hasServer, showPasswordMode, storedServerUrl, setServerUrl, connect, requestMagicLink, login, discoverServer, setError]
  );

  const handleTryAgain = useCallback(() => {
    setConnectionStatus("unconfigured");
    setError(null);
    setLocalCooldown(0);
    setCooldownRemaining(0);
  }, [setConnectionStatus, setError, setCooldownRemaining]);

  const handleResend = useCallback(async () => {
    if (localCooldown > 0 || !magicLinkEmail) return;
    try {
      await requestMagicLink(magicLinkEmail);
      setLocalCooldown(60);
    } catch {
      // Error shown in store
    }
  }, [localCooldown, magicLinkEmail, requestMagicLink]);

  const handleOpenMailApp = useCallback(() => {
    try {
      // Use Tauri shell plugin on desktop
      import("@tauri-apps/plugin-shell").then(({ open }) => {
        open("mailto:");
      }).catch(() => {
        // Fallback for web
        window.open("mailto:", "_blank");
      });
    } catch {
      window.open("mailto:", "_blank");
    }
  }, []);

  // ─── "Check your email" waiting screen ─────────────
  if (isAwaiting) {
    return (
      <div className="h-screen flex items-center justify-center" style={{ background: "var(--forge-bg)" }}>
        <div className="w-full max-w-md px-8 text-center">
          <div
            className="inline-flex items-center justify-center w-16 h-16 rounded-2xl mb-6"
            style={{ background: "rgba(99, 102, 241, 0.15)" }}
          >
            <CheckCircle className="w-8 h-8" style={{ color: "var(--forge-accent)" }} />
          </div>
          <h1
            className="text-2xl font-bold mb-2"
            style={{ color: "var(--forge-text)" }}
          >
            Check your email
          </h1>
          <p className="text-sm mb-1" style={{ color: "var(--forge-text-muted)" }}>
            We sent a sign-in link to
          </p>
          <p className="text-sm font-medium mb-6" style={{ color: "var(--forge-text)" }}>
            {magicLinkEmail}
          </p>

          {/* Open Mail App button */}
          <button
            onClick={handleOpenMailApp}
            className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-medium transition-opacity text-white cursor-pointer mb-3"
            style={{ background: "var(--forge-accent)" }}
          >
            <ExternalLink className="w-4 h-4" />
            Open Mail App
          </button>

          <div
            className="text-xs p-4 rounded-lg mb-4"
            style={{
              background: "var(--forge-channel)",
              border: "1px solid var(--forge-border)",
              color: "var(--forge-text-muted)",
            }}
          >
            <p className="mb-2">Click the link in the email to sign in.</p>
            <p>The link expires in 15 minutes.</p>
          </div>

          {/* Resend button with cooldown */}
          <button
            onClick={handleResend}
            disabled={localCooldown > 0}
            className="flex items-center gap-1.5 text-xs mx-auto cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-not-allowed mb-3"
            style={{ color: "var(--forge-text-muted)" }}
            onMouseEnter={(e) => {
              if (localCooldown <= 0) e.currentTarget.style.color = "var(--forge-text)";
            }}
            onMouseLeave={(e) => (e.currentTarget.style.color = "var(--forge-text-muted)")}
          >
            <RefreshCw className="w-3.5 h-3.5" />
            {localCooldown > 0
              ? `Resend in ${localCooldown}s`
              : "Resend email"}
          </button>

          <button
            onClick={handleTryAgain}
            className="flex items-center gap-1 text-xs mx-auto cursor-pointer transition-colors"
            style={{ color: "var(--forge-text-muted)" }}
            onMouseEnter={(e) => (e.currentTarget.style.color = "var(--forge-text)")}
            onMouseLeave={(e) => (e.currentTarget.style.color = "var(--forge-text-muted)")}
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            Use a different email
          </button>
        </div>
      </div>
    );
  }

  // ─── Email input screen ────────────────────────────
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
            {serverInfo?.name ? `Sign in to ${serverInfo.name}` : "Sign in to Forge"}
          </h1>
          <p style={{ color: "var(--forge-text-muted)" }} className="text-sm">
            {showPasswordMode
              ? "Sign in with your email and password"
              : "Enter your email to get a sign-in link"}
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
                disabled={isLoading || isDiscovering}
                autoFocus
                autoComplete="email"
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

          {/* Password field (only in password mode) */}
          {showPasswordMode && (
            <>
              {/* Server URL always shown in password mode */}
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
                    disabled={isLoading}
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
            </>
          )}

          {/* Server URL (magic link mode — shown when no server is configured, or toggled) */}
          {!showPasswordMode && (
            <>
              {hasServer && !showServerField ? (
                <button
                  type="button"
                  onClick={() => setShowServerField(true)}
                  className="flex items-center gap-1 text-xs cursor-pointer transition-colors"
                  style={{ color: "var(--forge-text-muted)" }}
                  onMouseEnter={(e) => (e.currentTarget.style.color = "var(--forge-text)")}
                  onMouseLeave={(e) => (e.currentTarget.style.color = "var(--forge-text-muted)")}
                >
                  <ChevronDown className="w-3 h-3" />
                  Change server ({storedServerUrl})
                </button>
              ) : showServerField ? (
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <label
                      className="block text-xs font-medium"
                      style={{ color: "var(--forge-text-muted)" }}
                    >
                      Server URL
                    </label>
                    {hasServer && (
                      <button
                        type="button"
                        onClick={() => setShowServerField(false)}
                        className="flex items-center gap-0.5 text-xs cursor-pointer"
                        style={{ color: "var(--forge-text-muted)" }}
                      >
                        <ChevronUp className="w-3 h-3" />
                        Hide
                      </button>
                    )}
                  </div>
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
                      disabled={isLoading || isDiscovering}
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
              ) : null}
            </>
          )}

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

          {/* Submit button */}
          <button
            type="submit"
            disabled={
              isLoading ||
              isDiscovering ||
              !email.trim() ||
              (showPasswordMode && !password.trim()) ||
              (showPasswordMode && !url.trim() && !hasServer)
            }
            className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-medium transition-opacity text-white cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            style={{ background: "var(--forge-accent)" }}
          >
            {isDiscovering ? (
              <>
                <Search className="w-4 h-4 animate-pulse" />
                Looking for your server...
              </>
            ) : isLoading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                {showPasswordMode ? "Signing in..." : !hasServer ? "Connecting..." : "Sending link..."}
              </>
            ) : showPasswordMode ? (
              <>
                Sign in
                <ArrowRight className="w-4 h-4" />
              </>
            ) : (
              <>
                Continue with email
                <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>
        </form>

        {/* Toggle between magic link and password mode */}
        <div className="text-center mt-4">
          <button
            type="button"
            onClick={() => {
              setShowPasswordMode(!showPasswordMode);
              setError(null);
              if (!showPasswordMode) {
                // Switching to password mode — show server field
                setShowServerField(true);
              }
            }}
            className="text-xs cursor-pointer transition-colors"
            style={{ color: "var(--forge-text-muted)" }}
            onMouseEnter={(e) => (e.currentTarget.style.color = "var(--forge-accent)")}
            onMouseLeave={(e) => (e.currentTarget.style.color = "var(--forge-text-muted)")}
          >
            {showPasswordMode
              ? "Use magic link instead"
              : "Sign in with password instead"}
          </button>
        </div>

        {/* Help text */}
        <p
          className="text-xs text-center mt-4"
          style={{ color: "var(--forge-text-muted)" }}
        >
          {showPasswordMode
            ? "Enter your server URL, email, and password to sign in."
            : "We'll send you a magic link to sign in. No password needed."}
        </p>
      </div>
    </div>
  );
}
