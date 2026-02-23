#!/usr/bin/env bash
#
# setup_local_models.sh — Check Ollama, GPU, pull models, benchmark, cost estimate
#
# Usage:
#   bash scripts/setup_local_models.sh
#   bash scripts/setup_local_models.sh --model qwen2.5-coder:14b   # smaller model
#
set -euo pipefail

MODEL="${1:-qwen2.5-coder:32b}"
OLLAMA_URL="${OLLAMA_BASE_URL:-http://localhost:11434}"

# Colors (disabled if not a terminal)
if [ -t 1 ]; then
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    RED='\033[0;31m'
    BOLD='\033[1m'
    NC='\033[0m'
else
    GREEN='' YELLOW='' RED='' BOLD='' NC=''
fi

info()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
fail()  { echo -e "${RED}[✗]${NC} $*"; }
header() { echo -e "\n${BOLD}$*${NC}"; }

# -----------------------------------------------------------------------
# 1. Check Ollama installation
# -----------------------------------------------------------------------
header "1. Checking Ollama installation"

if command -v ollama &>/dev/null; then
    OLLAMA_VERSION=$(ollama --version 2>/dev/null || echo "unknown")
    info "Ollama found: $OLLAMA_VERSION"
else
    # Check if running in Docker instead
    if curl -sf "$OLLAMA_URL/api/tags" &>/dev/null; then
        info "Ollama running via Docker at $OLLAMA_URL"
    else
        fail "Ollama not found. Install from https://ollama.com/download"
        echo "  macOS:  brew install ollama"
        echo "  Linux:  curl -fsSL https://ollama.com/install.sh | sh"
        echo "  Docker: docker compose --profile gpu up -d"
        exit 1
    fi
fi

# Check if Ollama server is running
if ! curl -sf "$OLLAMA_URL/api/tags" &>/dev/null; then
    warn "Ollama server not running at $OLLAMA_URL"
    echo "  Start it with: ollama serve"
    echo "  Or via Docker: docker compose --profile gpu up -d"
    exit 1
fi
info "Ollama server reachable at $OLLAMA_URL"

# -----------------------------------------------------------------------
# 2. Check GPU availability
# -----------------------------------------------------------------------
header "2. Checking GPU availability"

GPU_AVAILABLE=false
VRAM_MB=0

if command -v nvidia-smi &>/dev/null; then
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || echo "")
    VRAM_MB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 || echo "0")
    VRAM_FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | head -1 || echo "0")

    if [ -n "$GPU_NAME" ] && [ "$VRAM_MB" -gt 0 ] 2>/dev/null; then
        GPU_AVAILABLE=true
        info "GPU: $GPU_NAME"
        info "VRAM: ${VRAM_MB} MB total, ${VRAM_FREE} MB free"

        if [ "$VRAM_MB" -lt 20000 ] 2>/dev/null; then
            warn "qwen2.5-coder:32b needs ~20 GB VRAM. Consider :14b or :7b instead."
        fi
    fi
elif [ "$(uname)" = "Darwin" ]; then
    # macOS — check for Apple Silicon with unified memory
    CHIP=$(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo "")
    if echo "$CHIP" | grep -qi "apple"; then
        MEM_BYTES=$(sysctl -n hw.memsize 2>/dev/null || echo "0")
        MEM_GB=$((MEM_BYTES / 1073741824))
        GPU_AVAILABLE=true
        info "Apple Silicon detected: $CHIP"
        info "Unified memory: ${MEM_GB} GB"

        if [ "$MEM_GB" -lt 32 ] 2>/dev/null; then
            warn "32 GB+ recommended for qwen2.5-coder:32b. Consider :14b for ${MEM_GB} GB."
        fi
    fi
fi

if [ "$GPU_AVAILABLE" = false ]; then
    warn "No GPU detected. Ollama will use CPU (much slower)."
    echo "  For optimal performance, use a system with an NVIDIA GPU or Apple Silicon."
fi

# -----------------------------------------------------------------------
# 3. Pull model
# -----------------------------------------------------------------------
header "3. Pulling $MODEL"

# Check if already pulled
EXISTING=$(curl -sf "$OLLAMA_URL/api/tags" | python3 -c "
import sys, json
data = json.load(sys.stdin)
names = [m.get('name','') for m in data.get('models',[])]
print('yes' if any('$MODEL'.split(':')[0] in n for n in names) else 'no')
" 2>/dev/null || echo "no")

if [ "$EXISTING" = "yes" ]; then
    info "$MODEL is already pulled"
else
    info "Pulling $MODEL (this may take a while for large models)..."
    if command -v ollama &>/dev/null; then
        ollama pull "$MODEL"
    else
        # Pull via API
        curl -sf "$OLLAMA_URL/api/pull" -d "{\"name\": \"$MODEL\"}" | while read -r line; do
            STATUS=$(echo "$line" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")
            if [ -n "$STATUS" ]; then
                echo "  $STATUS"
            fi
        done
    fi
    info "Pull complete"
fi

# -----------------------------------------------------------------------
# 4. Quick benchmark
# -----------------------------------------------------------------------
header "4. Running benchmark"

BENCH_PROMPT="Write a Python function that checks if a number is prime. Include type hints and a docstring."

info "Sending benchmark prompt..."
BENCH_START=$(python3 -c "import time; print(time.time())")

BENCH_RESULT=$(curl -sf "$OLLAMA_URL/api/generate" -d "{
    \"model\": \"$MODEL\",
    \"prompt\": \"$BENCH_PROMPT\",
    \"stream\": false,
    \"options\": {\"num_predict\": 200}
}" 2>/dev/null || echo "{}")

BENCH_END=$(python3 -c "import time; print(time.time())")

# Parse benchmark results
python3 -c "
import json, sys

result = json.loads('''$BENCH_RESULT''') if '''$BENCH_RESULT''' else {}
elapsed = float('$BENCH_END') - float('$BENCH_START')

eval_count = result.get('eval_count', 0)
eval_duration_ns = result.get('eval_duration', 0)

if eval_count > 0 and eval_duration_ns > 0:
    tokens_per_sec = eval_count / (eval_duration_ns / 1e9)
    print(f'  Tokens generated: {eval_count}')
    print(f'  Generation speed: {tokens_per_sec:.1f} tokens/sec')
    print(f'  Wall time:        {elapsed:.1f}s')
else:
    print(f'  Wall time: {elapsed:.1f}s')
    print(f'  (Could not extract detailed metrics)')
" 2>/dev/null || echo "  Benchmark parsing failed (model may still be loading)"

# -----------------------------------------------------------------------
# 5. Cost savings estimate
# -----------------------------------------------------------------------
header "5. Estimated cost savings"

cat <<'ESTIMATE'

  Assumptions:
    - 20 tickets per pipeline run
    - ~2 LLM calls per ticket (coding + revision)
    - ~4000 input tokens + ~2000 output tokens per call
    - Claude Sonnet 4.5 pricing: $3.00/M input, $15.00/M output

  Per-pipeline coding cost (all cloud):
    Input:  20 × 2 × 4000 × $3.00/1M  = $0.48
    Output: 20 × 2 × 2000 × $15.00/1M = $1.20
    Total:  ~$1.68 per pipeline run

  With local model for coding:
    Coding cost: $0.00 (local inference)
    Savings:     ~$1.68 per pipeline run (100% of coding costs)

  At 10 pipeline runs/day:
    Daily savings:   ~$16.80
    Monthly savings: ~$504.00

  Note: Only coding/engineering calls use local models.
  BA, Research, Architecture, QA, and CTO stages still use cloud APIs.
ESTIMATE

echo ""
info "Setup complete! Local model is ready for inference."
echo "  The Forge worker will automatically route coding tasks to $MODEL."
echo "  Set OLLAMA_BASE_URL=$OLLAMA_URL in your .env if using a non-default address."
