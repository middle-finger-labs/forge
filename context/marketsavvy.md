# MarketSavvy Codebase Context

> This document is injected into every Forge agent's prompt when working on
> the MarketSavvy repository. It describes the existing architecture,
> patterns, and conventions that agents MUST follow.

## Project Overview

MarketSavvy is a financial research SaaS platform providing institutional-grade
data on insider trades, institutional holdings, political trades, lobbying,
government contracts, and PAC donations — all mapped to tradeable tickers.
Comparable to Fintel and QuiverQuant.

**Status:** ~70% complete. UI routes and components exist for all data sections.
The remaining work is data pipeline hardening, entity resolution, and
observability — NOT frontend features.

---

## Monorepo Structure

```
marketsavvy/
├── apps/
│   ├── web/                      # React Router 7 frontend (SSR)
│   │   ├── app/
│   │   │   ├── routes/           # File-based routing (React Router 7)
│   │   │   ├── components/       # Shared UI components
│   │   │   ├── lib/              # Utilities, API clients, hooks
│   │   │   └── styles/           # Tailwind 4 stylesheets
│   │   ├── public/
│   │   └── vite.config.ts
│   │
│   └── disclosure-pipeline/      # Python data pipeline (FastAPI + pollers)
│       ├── pollers/              # SEC, USASpending, FEC, lobby pollers
│       │   ├── sec_poller.py     # SEC EDGAR filings (13-F, Forms 3/4/5)
│       │   ├── usaspending_poller.py  # Government contracts
│       │   ├── fec_poller.py     # FEC campaign finance (Schedule A, committees)
│       │   ├── lobby_poller.py   # Senate lobby disclosures
│       │   └── political_poller.py   # Capitol Trades / political transactions
│       ├── entity_matching.py    # Company/ticker resolution logic
│       ├── pac_matcher.py        # PAC-to-company matching
│       ├── company_enrichment.py # FMP + other enrichment services
│       ├── main.py               # FastAPI app entry point
│       └── requirements.txt
│
├── packages/
│   ├── supabase/                 # Supabase config, migrations, RLS policies
│   │   ├── migrations/           # SQL migration files
│   │   ├── seed.sql
│   │   └── config.toml
│   └── shared/                   # Shared types, constants, utilities
│
├── supabase/                     # Alternative: Supabase project root
│   └── migrations/
│
├── inngest/                      # Inngest function definitions (background jobs)
├── package.json                  # Root pnpm workspace config
├── pnpm-workspace.yaml
├── turbo.json
└── CLAUDE.md                     # Project-level coding conventions
```

---

## Tech Stack

### Frontend (apps/web)

| Layer        | Technology                |
|-------------|--------------------------|
| Framework   | React Router 7 (with SSR) |
| Language    | TypeScript 5.x            |
| Styling     | Tailwind CSS 4             |
| Build       | Vite                       |
| Package Mgr | pnpm                       |
| Monorepo    | Turborepo                  |

### Backend / Data Layer

| Layer        | Technology                 |
|-------------|---------------------------|
| Database    | Supabase (PostgreSQL + RLS) |
| Auth        | Supabase Auth               |
| Background  | Inngest (event-driven jobs) |
| API         | Supabase client + RPC       |

### Python Pipeline (apps/disclosure-pipeline)

| Layer        | Technology                |
|-------------|--------------------------|
| Framework   | FastAPI                    |
| Runtime     | Python 3.11+               |
| Data Sources| SEC EDGAR, USASpending, FEC, Senate Lobby, Capitol Trades |
| Enrichment  | Financial Modeling Prep (FMP) API |
| Scheduling  | Inngest triggers or cron    |

---

## Database Schema Patterns

### Supabase + Row Level Security (RLS)
- All tables live in Supabase PostgreSQL
- RLS policies enforce access control
- Migrations in `supabase/migrations/` or `packages/supabase/migrations/`
- Standard columns: `id` (UUID), `created_at`, `updated_at`

### Key Tables (partial list)
- `companies` — master company records with tickers
- `insider_trades` — SEC Forms 3/4/5 filing data
- `institutional_holdings` — 13-F institutional positions
- `political_trades` — Congressional trading activity
- `lobby_disclosures` — Lobbying activity records
- `government_contracts` — USASpending contract awards
- `pac_donations` / `fec_contributions` — Campaign finance data
- `company_enrichment` — Supplementary company metadata (market cap, sector, etc.)

### Entity Resolution
- `entity_matching.py` is the central module mapping companies to tickers
- Uses CIK numbers, CUSIP, name matching, and GLEIF hierarchy
- Company enrichment provides market cap, shares outstanding, sector, industry
- All data must ultimately resolve to a tradeable ticker symbol

---

## Python Pipeline Architecture

### Pollers
Each poller fetches data from a government API and upserts into Supabase:
- **SEC poller**: EDGAR XBRL/XML feeds for insider trades and 13-F filings
- **USASpending poller**: Federal contract awards via USASpending.gov API
- **FEC poller**: Campaign finance data (Schedule A contributions, committee info)
- **Lobby poller**: Senate lobbying disclosure database
- **Political poller**: Congressional trade data (Capitol Trades or similar)

### Entity Matching Flow
1. Raw filing arrives with company name / CIK / CUSIP
2. `entity_matching.py` attempts resolution: CIK → ticker, CUSIP → ticker, name → ticker
3. Fallback: fuzzy name matching, GLEIF hierarchy lookup, manual mapping table
4. `company_enrichment.py` fills in market cap, sector, industry from FMP API
5. Unresolved entities logged for manual review

### Known Issues (the reason Forge is being used)
- **Institutions pipeline**: 13-F filings have CIK → ticker resolution failures,
  market value calculations may be off by 1000x (recent migration suggests this)
- **Contracts pipeline**: USASpending company names don't match ticker symbols
  (subsidiaries, joint ventures, non-public contractors)
- **Donors/PAC pipeline**: PAC-to-company matching is incomplete,
  amendment reconciliation for corrected filings is unreliable
- **N/A values**: Many data sections show N/A for fields that should be populated
  (missing enrichment, failed entity resolution)

---

## Coding Conventions

### TypeScript (apps/web)
- Use React Router 7 conventions (file-based routes, loaders, actions)
- Tailwind 4 for all styling — no CSS modules or styled-components
- Supabase client for data access (no raw SQL from frontend)
- Type-safe with strict TypeScript
- Components use function declarations, not arrow functions for top-level
- Prefer server-side data loading (loaders) over client-side fetching

### Python (apps/disclosure-pipeline)
- FastAPI for API endpoints
- Type hints on all functions
- Async/await for I/O operations
- Supabase Python client for database operations
- Structured logging
- Pollers are idempotent (safe to re-run)

### Anti-Patterns to Avoid
- Do NOT add new frontend routes or UI components (they already exist)
- Do NOT change the database schema without migration files
- Do NOT introduce new ORMs — use Supabase client directly
- Do NOT hardcode API keys or secrets
- Do NOT modify Supabase RLS policies without explicit instruction
- Do NOT use `any` type in TypeScript
- Do NOT use bare `except` in Python — always catch specific exceptions

---

## Working on This Codebase (for Forge Agents)

### For the Business Analyst
- You are analyzing **change requests** to an existing product, not designing a new one
- The product already has 9+ data sections with UI routes
- Focus on data pipeline and data quality improvements
- Reference existing pipeline code and database tables in your analysis

### For the Architect
- The architecture already EXISTS — you are discovering it, not designing it
- Do NOT propose a new tech stack — the stack is React Router 7 + Supabase + Inngest + Python/FastAPI
- Your job is to identify which existing files need modification and how
- Read the actual codebase before proposing changes

### For the PM
- Tickets should reference specific existing file paths
- Do not create infrastructure tickets (the infra exists)
- Each ticket should modify a small number of specific files
- Use the existing naming conventions for file paths

### For Engineers
- Match the existing code style exactly
- Import from existing modules — do not create parallel implementations
- Test against real data patterns (SEC filing formats, USASpending responses)
- If modifying a Python poller, maintain idempotency

### For QA
- Review against existing conventions, not ideal-world standards
- Do not penalize for pre-existing code patterns or tech debt
- Focus on: correctness of data transformations, entity resolution accuracy,
  error handling in external API calls
- Verify backward compatibility with existing database schema
