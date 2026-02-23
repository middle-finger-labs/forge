# Phase 1A: Harden Institutional Holdings Pipeline (13-F Filings)

## Project Context

MarketSavvy is an existing financial research SaaS platform at `git@github.com:Stock-GPT/marketsavvy.git`. This is NOT a greenfield project — all code changes must work within the existing codebase, matching existing patterns and conventions.

### Existing Tech Stack (DO NOT CHANGE)
- **Frontend**: React Router 7 (framework mode), Tailwind CSS 4, TypeScript, pnpm monorepo
- **Backend**: Supabase (PostgreSQL + Auth + RLS), Inngest (event-driven functions)
- **Data Pipeline**: Python 3.12+ (FastAPI, edgartools, httpx), located at `apps/disclosure-pipeline/`
- **Database**: Supabase PostgreSQL with Row Level Security

### Repository Structure
```
apps/
  disclosure-pipeline/     # Python data pipeline (THIS IS WHERE CHANGES GO)
    src/
      sources/
        sec/
          poller.py        # SECForm4Poller, SECForm13FPoller, SECForm13DGPoller
          rss.py           # RSS feed fetcher for SEC EDGAR
        quiver/            # Quiver Quant API client
        usaspending/       # Government contracts
        lda/               # Lobbying data
        company_info/      # Company enrichment
        stock_prices/      # Price fetcher
      db/
        models.py          # Pydantic models (Filing, Form13FHolding, etc.)
        repositories.py    # Database repositories
        client.py          # Supabase client
      events/
        inngest.py         # Inngest event handlers
        contracts.py       # Contract events
      config.py            # Settings
      api.py               # FastAPI app
      main.py              # Entry point
  web/                     # React Router 7 frontend
  e2e/                     # Playwright tests
```

## Problem Statement

The SEC Form 13-F (institutional holdings) pipeline has data integrity issues that result in:
1. **Missing ticker mappings** — `Form13FHolding.ticker` is often `None` because CUSIP-to-ticker resolution is incomplete
2. **Incomplete filings** — Some 13-F filings fail to parse all holdings, resulting in partial data
3. **No retry/error handling** — Individual filing failures silently drop data
4. **Market value accuracy** — Historical issues with 1000x market value corrections suggest ongoing calculation problems
5. **Stale data** — No mechanism to detect when the pipeline hasn't ingested new filings

## Requirements

### 1. CUSIP-to-Ticker Resolution
- The `Form13FHolding` model has a `ticker` field that is often `None`
- Implement a robust CUSIP-to-ticker resolution strategy:
  - Primary: Use SEC EDGAR CUSIP-to-ticker mapping
  - Fallback: Use Financial Modeling Prep (FMP) API for CUSIP lookup
  - Fallback: Use company name fuzzy matching against known tickers
  - Cache resolved mappings in a `cusip_ticker_map` table to avoid repeated lookups
- All institutional holdings should resolve to a tradeable ticker symbol

### 2. Filing Parse Robustness
- In `SECForm13FPoller.parse_item()`, add validation for:
  - Ensure `shares_held > 0` and `market_value > 0` for each holding
  - Validate CUSIP format (9 characters, alphanumeric)
  - Log and skip individual malformed holdings without failing the entire filing
  - Track parse success rate (holdings parsed vs holdings in raw XML)
- Add structured error logging for parse failures with filing accession number context

### 3. Retry Logic and Error Handling
- Wrap individual filing fetch/parse in try/except with exponential backoff
- Add a Dead Letter Queue (DLQ) pattern: failed filings go to a `filing_errors` table with error details
- After all filings are processed, log a summary: total fetched, successfully parsed, failed, skipped
- Implement idempotency: if a filing has already been processed (check by `source_id`), skip it

### 4. Market Value Validation
- Validate that `market_value` for each holding is within reasonable bounds
- Flag holdings where `market_value / shares_held` (implied price) deviates >50% from known stock price
- Log anomalies but still ingest the data (don't drop it)

### 5. Data Freshness Monitoring
- Add a `pipeline_runs` table entry each time the 13-F poller runs
- Record: start_time, end_time, filings_processed, holdings_ingested, errors, status
- This enables the admin dashboard to show when the last successful run occurred

## Constraints
- DO NOT modify the frontend (`apps/web/`) — this is backend pipeline work only
- DO NOT change the database schema directly — use Supabase migrations in `apps/disclosure-pipeline/supabase/`
- Match existing code patterns in `apps/disclosure-pipeline/src/`
- Use `edgartools` library for SEC filing parsing (already a dependency)
- Use `httpx` for HTTP calls (already a dependency)
- Follow existing Pydantic model patterns in `src/db/models.py`
- Follow existing repository patterns in `src/db/repositories.py`
