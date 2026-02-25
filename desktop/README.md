# Forge Desktop

Native desktop client for [Forge](../README.md) — a conversational interface where AI agents are teammates you chat with. Built with [Tauri v2](https://v2.tauri.app) (Rust) + React 19 + TypeScript.

```
┌─────────────────────────────────────────────────────────────────┐
│  Toolbar                                                        │
├──────────┬──────────────────────────────────┬───────────────────┤
│          │                                  │                   │
│ Sidebar  │         Main Panel               │  Detail Panel     │
│          │                                  │                   │
│ Agents   │  Conversation / Pipeline /       │  DAG Minimap      │
│ Channels │  Activity Feed / Settings        │  Agent Profile    │
│ DMs      │                                  │  Thread View      │
│          │                                  │                   │
├──────────┴──────────────────────────────────┴───────────────────┤
│  Status Bar                                                     │
└─────────────────────────────────────────────────────────────────┘
```

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| **Node.js** | 22+ | Frontend build tooling |
| **pnpm** | 9+ | Package manager (`npm install -g pnpm`) |
| **Rust** | stable | Backend + bundling (`curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh`) |
| **Xcode CLT** | Latest | macOS only (`xcode-select --install`) |
| **Visual C++ Build Tools** | Latest | Windows only |
| **Linux deps** | — | See below |

### Linux system dependencies

```bash
sudo apt-get install -y \
  libwebkit2gtk-4.1-dev \
  libappindicator3-dev \
  librsvg2-dev \
  patchelf \
  libssl-dev \
  libgtk-3-dev \
  libsoup-3.0-dev \
  javascriptcoregtk-4.1-dev
```

## Development

```bash
# Install frontend dependencies
pnpm install

# Start dev server (hot-reload frontend + Rust backend)
pnpm tauri dev
```

This launches Vite on `localhost:1420` and opens the native window. Frontend changes hot-reload instantly; Rust changes trigger a recompile (~5-10s).

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `FORGE_API_URL` | `http://localhost:8000` | Forge API server URL |

## Build

```bash
# Production build
pnpm tauri build
```

Outputs:
- **macOS**: `src-tauri/target/release/bundle/macos/Forge.app` + `.dmg`
- **Windows**: `src-tauri/target/release/bundle/nsis/Forge_x.x.x_x64-setup.exe`
- **Linux**: `.deb` + `.AppImage` in `src-tauri/target/release/bundle/`

### Cross-platform CI builds

Push a `v*` tag to trigger the [build workflow](../.github/workflows/build-desktop.yml), which builds for macOS (aarch64 + x86_64), Ubuntu, and Windows and creates a draft GitHub Release.

```bash
git tag v0.1.0
git push origin v0.1.0
```

## Architecture

### Technology stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Shell | Tauri v2 (Rust) | Native window, system tray, notifications, global shortcuts |
| Frontend | React 19 + TypeScript 5.9 | Component UI |
| Bundler | Vite 7 | Dev server + production build |
| Styling | Tailwind CSS 4 | Utility-first CSS with dynamic themes |
| State | Zustand 5 | Lightweight stores with localStorage persistence |
| Virtualization | TanStack Virtual | Smooth scrolling for 1000+ messages |
| API Client | Fetch + Tauri WebSocket plugin | REST + real-time communication |

### How the React frontend communicates with the Rust backend

Tauri uses an **IPC bridge** between the webview (JavaScript) and the Rust process. The frontend calls Rust functions via `invoke()`:

```typescript
import { invoke } from "@tauri-apps/api/core";

// Call a Rust command
const version = await invoke<string>("get_app_version");
const apiUrl = await invoke<string>("get_forge_api_url");
await invoke("open_in_vscode", { path: "/path/to/project" });
```

Rust commands are defined with the `#[tauri::command]` macro in `src-tauri/src/commands.rs`:

```rust
#[tauri::command]
pub fn get_app_version() -> String {
    env!("CARGO_PKG_VERSION").to_string()
}
```

Available IPC commands:

| Command | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `get_forge_api_url` | — | `String` | Resolve API URL from env or default |
| `get_app_version` | — | `String` | App version from Cargo.toml |
| `open_in_vscode` | `path: String` | — | Launch VS Code with path |
| `open_in_terminal` | `path: String` | — | Open platform terminal at path |
| `get_connection_status` | — | `String` | TCP check to API server |
| `set_close_to_tray` | `enabled: bool` | — | Toggle close-to-tray behavior |
| `update_tray_state` | `active_pipelines`, `has_unread`, `has_pending_approval`, `agents` | — | Update system tray menu from frontend state |

### How the WebSocket connection is managed

The WebSocket layer (`src/services/ws.ts`) handles real-time communication:

```
Frontend (React)                    Forge API Server
     │                                     │
     │  ── ws://server/ws?token=xxx ────> │
     │  <── { type, payload } ──────────  │
     │  ── ping ────────────────────────> │
     │  <── pong ───────────────────────  │
     │                                     │
```

**Connection lifecycle:**

1. `useWebSocket` hook connects when `connectionStatus === "authenticated"`
2. `ForgeWebSocket.connect()` opens a Tauri WebSocket plugin connection
3. Incoming messages are parsed as `{ type, payload }` envelopes
4. Events are dispatched to registered listeners and wired into Zustand stores
5. Heartbeat pings every 30s keep the connection alive

**Reconnection strategy:**

- Exponential backoff: 1s → 2s → 4s → 8s → ... → 30s max
- Message queue: sends queued while disconnected are flushed on reconnect
- Intentional disconnect (logout/close) skips reconnection

**Event types:**

| Event | Store action | Description |
|-------|-------------|-------------|
| `message` | `conversationStore.addMessage()` | New chat message in any conversation |
| `agent_status` | `conversationStore.updateAgentStatus()` | Agent status change (idle/working/error) |
| `pipeline_event` | — | Pipeline step started/completed/failed |
| `presence` | — | User presence updates |
| `typing` | — | Typing indicators |

### How native features are wired up

#### System tray (`src-tauri/src/tray.rs`)

The tray icon shows pipeline status, agent activity, and unread counts. The frontend pushes state updates to Rust via `update_tray_state`, which rebuilds the tray menu.

- **Left-click**: Show/focus the main window
- **Menu → Open Forge**: Show/focus window
- **Menu → Active Pipelines**: Navigate to pipelines view
- **Menu → Agent Status**: Submenu showing each agent's emoji + status
- **Menu → Quit**: Exit the application

#### Notifications (`src/hooks/useNotifications.ts`)

Uses `@tauri-apps/plugin-notification` for native OS notifications:

- Pipeline completed/failed
- Approval requested (high priority)
- Agent DM received
- Budget warnings
- Agent errors

Notifications respect the user's notification level setting (all / approvals only / errors only / none) and include 10-second deduplication.

#### Global shortcuts

| Shortcut | Action |
|----------|--------|
| `Cmd+Shift+F` | Focus Forge window (global, works from any app) |
| `Cmd+K` | Quick Switcher |
| `Cmd+N` | New Pipeline |
| `Cmd+,` | Settings |
| `Cmd+Shift+A` | Activity Feed |
| `Cmd+.` | Toggle detail panel |
| `Cmd+1-7` | Jump to agent DM |
| `Escape` | Close current modal/panel |

#### Window state (`@tauri-apps/plugin-window-state`)

Window position, size, and maximized state persist across restarts automatically via the Tauri window-state plugin.

#### Close to tray

When enabled (default), closing the window hides it to the system tray instead of quitting. The Rust backend intercepts `CloseRequested` events and calls `window.hide()`. Configurable in Settings → General.

#### Auto-start (`@tauri-apps/plugin-autostart`)

Optional launch at login via macOS LaunchAgent / Windows Registry / Linux autostart. Configurable in Settings → General.

## Project structure

```
desktop/
├── src/                              # React frontend
│   ├── components/
│   │   ├── activity/
│   │   │   └── ActivityFeed.tsx      # Unified "All Unreads" view
│   │   ├── agents/
│   │   │   └── AgentProfile.tsx      # Agent detail card
│   │   ├── auth/
│   │   │   └── LoginScreen.tsx       # Email/password login
│   │   ├── conversation/
│   │   │   ├── ConversationView.tsx  # Main chat container
│   │   │   ├── MessageBubble.tsx     # Individual message rendering
│   │   │   ├── MessageInput.tsx      # Chat input with slash commands
│   │   │   ├── MessageList.tsx       # Virtualized message list
│   │   │   └── ThreadView.tsx        # Reply thread panel
│   │   ├── layout/
│   │   │   ├── AppShell.tsx          # CSS Grid shell (toolbar + sidebar + main + detail + status)
│   │   │   ├── DetailPanel.tsx       # Right panel (DAG, profile, thread)
│   │   │   ├── MainPanel.tsx         # Central content router
│   │   │   ├── QuickSwitcher.tsx     # Cmd+K fuzzy search palette
│   │   │   ├── Sidebar.tsx           # Conversation list + agent DMs
│   │   │   ├── StatusBar.tsx         # Connection + pipelines + cost
│   │   │   └── Toolbar.tsx           # Top bar with actions
│   │   ├── pipeline/
│   │   │   ├── ApprovalCard.tsx      # Human-in-the-loop approval UI
│   │   │   ├── CostTracker.tsx       # Pipeline cost breakdown
│   │   │   ├── DAGMinimap.tsx        # Pipeline DAG visualization
│   │   │   ├── NewPipelineModal.tsx  # Create pipeline dialog
│   │   │   └── PipelineChannel.tsx   # Pipeline conversation view
│   │   ├── settings/
│   │   │   ├── SettingsWindow.tsx    # Settings container (5 tabs)
│   │   │   └── tabs/                # General, Notifications, API Keys, Agents, About
│   │   └── ConnectScreen.tsx         # First-launch server configuration
│   ├── hooks/
│   │   ├── useAgentChat.ts           # Agent DM messaging + behaviors
│   │   ├── useAgents.ts              # Agent list with statuses
│   │   ├── useConversation.ts        # Conversation accessor
│   │   ├── useKeyboardShortcuts.ts   # Global keyboard shortcuts
│   │   ├── useNotifications.ts       # Native notification dispatcher
│   │   └── useWebSocket.ts           # WebSocket lifecycle manager
│   ├── services/
│   │   ├── api.ts                    # REST API client (singleton)
│   │   └── ws.ts                     # WebSocket client with reconnect
│   ├── stores/
│   │   ├── connectionStore.ts        # Server URL, auth state, user/org
│   │   ├── conversationStore.ts      # Conversations, messages, agents
│   │   ├── layoutStore.ts            # Panel visibility, modals, navigation
│   │   └── settingsStore.ts          # Theme, notifications, preferences
│   ├── types/
│   │   ├── agent.ts                  # AgentRole, Agent, AGENT_REGISTRY
│   │   ├── conversation.ts           # Conversation, Participant
│   │   ├── message.ts                # Message, MessageContent (union type)
│   │   └── pipeline.ts              # PipelineRun, PipelineStep, PipelineEvent
│   ├── data/
│   │   └── mockData.ts               # Development mock data
│   ├── lib/
│   │   └── utils.ts                  # cn() utility (clsx + tailwind-merge)
│   ├── App.tsx                       # Root router (Connect → Login → AppShell)
│   └── main.tsx                      # React DOM mount
├── src-tauri/                        # Rust backend
│   ├── src/
│   │   ├── main.rs                   # Entry point
│   │   ├── lib.rs                    # Tauri builder, plugins, setup
│   │   ├── commands.rs               # IPC command handlers
│   │   └── tray.rs                   # System tray menu + state
│   ├── Cargo.toml                    # Rust dependencies
│   ├── tauri.conf.json               # Window, bundle, plugin config
│   ├── capabilities/                 # Tauri security capabilities
│   └── icons/                        # App icons (all platforms)
├── package.json                      # Frontend dependencies
├── tsconfig.json                     # TypeScript config (strict)
└── vite.config.ts                    # Vite + Tailwind + path aliases
```

## State management

Four Zustand stores manage all application state:

| Store | Key state | Persistence |
|-------|-----------|-------------|
| `connectionStore` | `serverUrl`, `authToken`, `user`, `org`, `connectionStatus` | localStorage |
| `conversationStore` | `conversations`, `messages`, `agents`, `activeConversationId` | — |
| `layoutStore` | `detailPanelOpen`, `quickSwitcherOpen`, `settingsOpen`, `activityFeedOpen` | — |
| `settingsStore` | `theme`, `notificationLevel`, `closeToTray`, `agentSettings` | localStorage |

## Theming

The app supports dark and light themes via CSS custom properties. Theme selection (dark / light / system) is stored in `settingsStore` and applied by setting CSS variables on `:root`:

```css
--forge-bg         /* Main background */
--forge-sidebar    /* Sidebar background */
--forge-border     /* Border color */
--forge-text       /* Primary text */
--forge-text-muted /* Secondary text */
--forge-accent     /* Brand blue */
--forge-hover      /* Hover state */
--forge-active     /* Active/selected state */
--forge-success    /* Green indicators */
--forge-warning    /* Yellow/orange */
--forge-error      /* Red indicators */
```

## Testing

```bash
# Run unit and integration tests
pnpm test

# Run tests in watch mode
pnpm test:watch

# Type check
npx tsc --noEmit

# Rust check
cd src-tauri && cargo check
```

## License

See [LICENSE](../LICENSE) for details.
