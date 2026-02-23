# Contributing to Forge

## Development Environment Setup

### Prerequisites

- Python 3.12+
- Node.js 22+ (for the dashboard)
- Docker & Docker Compose
- An Anthropic API key (for integration/E2E tests)

### 1. Clone and install

```bash
git clone <repo-url>
cd forge

# Create virtualenv and install with dev dependencies
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Start infrastructure

```bash
docker compose up -d
```

This starts PostgreSQL, Redis, Temporal, and the Temporal UI.

### 3. Dashboard dependencies

```bash
cd dashboard
npm install
cd ..
```

### 4. Environment

```bash
cp .env.example .env   # or create manually
# At minimum, set:
echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env
```

---

## Running Tests

### Unit tests (no infrastructure needed)

```bash
pytest
```

Runs all tests in `tests/`. Infrastructure-dependent tests are automatically skipped if PostgreSQL/Redis are not available.

### Integration tests (requires Docker services)

```bash
docker compose up -d
pytest -m integration
```

These test PostgreSQL state store, Redis working memory, and Temporal workflow execution.

### End-to-end tests (full production stack)

```bash
# Option 1: Use the orchestration script
scripts/run_e2e.sh

# Option 2: Manual
docker compose up -d
python -m worker &
python -m api.run &
FORGE_E2E=1 pytest tests/test_e2e_production.py -v
```

E2E tests require a running worker, API server, and `ANTHROPIC_API_KEY`.

### Dashboard build

```bash
cd dashboard
npm run build      # production build
npx tsc --noEmit   # type check only
```

---

## Code Style

### Python

We use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```bash
# Check for lint issues
ruff check .

# Auto-fix what's possible
ruff check --fix .

# Format code
ruff format .

# Check formatting without modifying
ruff format --check .
```

Configuration (from `pyproject.toml`):

```toml
[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP"]
```

Key rules:
- **E**: pycodestyle errors (line length, whitespace, etc.)
- **F**: pyflakes (unused imports, undefined names)
- **I**: isort-compatible import sorting
- **N**: PEP 8 naming conventions
- **W**: pycodestyle warnings
- **UP**: pyupgrade (modern Python syntax)

### TypeScript / React

The dashboard uses TypeScript strict mode. Check types with:

```bash
cd dashboard && npx tsc --noEmit
```

### Commit Messages

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `refactor`: Code change that neither fixes a bug nor adds a feature
- `docs`: Documentation only
- `test`: Adding or updating tests
- `chore`: Build process, tooling, dependencies

Examples:
```
feat(agents): add CTO conflict resolution agent
fix(workflow): catch ActivityError instead of ApplicationError
refactor(config): extract typed error hierarchy into config/errors.py
docs: rewrite README with architecture walkthrough
test(e2e): add full-stack production test suite
chore(ci): add GitHub Actions workflow
```

---

## PR Process

1. **Create a branch** from `main`:
   ```bash
   git checkout -b feat/my-feature
   ```

2. **Make your changes**, following the code style above.

3. **Run the checks locally**:
   ```bash
   ruff check .
   ruff format --check .
   pytest
   cd dashboard && npm run build && npx tsc --noEmit
   ```

4. **Commit** with a conventional commit message.

5. **Push and open a PR** against `main`:
   ```bash
   git push -u origin feat/my-feature
   gh pr create --title "feat(scope): description" --body "..."
   ```

6. **CI must pass** — the GitHub Actions workflow runs lint, tests, and dashboard build.

7. **Review** — at least one approval required before merge.

### PR Checklist

- [ ] Code follows the project's style (ruff clean, types pass)
- [ ] Tests added/updated for new functionality
- [ ] Docstrings added for new public functions and classes
- [ ] No secrets or credentials in the diff
- [ ] Commit messages follow conventional commits
- [ ] README updated if adding user-facing features or config options

---

## Project Layout

See the [README](README.md) for the full project structure and architecture walkthrough.
