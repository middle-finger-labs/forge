#!/usr/bin/env bash
set -euo pipefail

# ─── Forge Mobile Build Script ───────────────────────
# Usage:
#   ./scripts/build-mobile.sh ios [dev|release]
#   ./scripts/build-mobile.sh android [dev|release]
#   ./scripts/build-mobile.sh all

PLATFORM="${1:-}"
MODE="${2:-release}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[info]${NC} $*"; }
ok()    { echo -e "${GREEN}[ok]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC} $*"; }
error() { echo -e "${RED}[error]${NC} $*" >&2; }

# ─── Preflight checks ────────────────────────────────

check_deps() {
  command -v pnpm >/dev/null 2>&1 || { error "pnpm not found. Install: npm i -g pnpm"; exit 1; }
  command -v rustc >/dev/null 2>&1 || { error "Rust not found. Install: https://rustup.rs"; exit 1; }

  if [[ "$1" == "ios" ]]; then
    command -v xcodebuild >/dev/null 2>&1 || { error "Xcode not found. Install from App Store."; exit 1; }
    rustup target list --installed | grep -q aarch64-apple-ios || {
      info "Adding iOS Rust target..."
      rustup target add aarch64-apple-ios
    }
  fi

  if [[ "$1" == "android" ]]; then
    [ -n "${ANDROID_HOME:-}" ] || [ -n "${ANDROID_SDK_ROOT:-}" ] || {
      error "ANDROID_HOME or ANDROID_SDK_ROOT not set. Install Android Studio."
      exit 1
    }
    command -v java >/dev/null 2>&1 || { error "Java not found. Install JDK 17."; exit 1; }
    for target in aarch64-linux-android armv7-linux-androideabi x86_64-linux-android; do
      rustup target list --installed | grep -q "$target" || {
        info "Adding Rust target: $target"
        rustup target add "$target"
      }
    done
  fi
}

# ─── Build functions ──────────────────────────────────

build_ios() {
  local mode="$1"
  info "Building iOS ($mode)..."
  check_deps ios

  cd "$(dirname "$0")/.."
  pnpm install --frozen-lockfile 2>/dev/null || pnpm install

  if [[ "$mode" == "dev" ]]; then
    pnpm tauri ios dev
  else
    pnpm tauri ios build
    ok "iOS build complete!"
    info "IPA location: src-tauri/gen/apple/build/"
    echo ""
    info "To upload to TestFlight:"
    echo "  xcrun altool --upload-app --type ios --file <path-to-ipa> --apiKey <key-id> --apiIssuer <issuer-id>"
    echo "  — or —"
    echo "  bundle exec fastlane ios beta"
  fi
}

build_android() {
  local mode="$1"
  info "Building Android ($mode)..."
  check_deps android

  cd "$(dirname "$0")/.."
  pnpm install --frozen-lockfile 2>/dev/null || pnpm install

  if [[ "$mode" == "dev" ]]; then
    pnpm tauri android dev
  else
    pnpm tauri android build
    ok "Android build complete!"
    info "APK/AAB location: src-tauri/gen/android/app/build/outputs/"
    echo ""
    info "To upload to Play Console:"
    echo "  Upload the .aab file at https://play.google.com/console"
    echo "  — or —"
    echo "  bundle exec fastlane android beta"
  fi
}

# ─── Main ─────────────────────────────────────────────

case "$PLATFORM" in
  ios)
    build_ios "$MODE"
    ;;
  android)
    build_android "$MODE"
    ;;
  all)
    build_ios "$MODE"
    build_android "$MODE"
    ;;
  *)
    echo "Forge Mobile Build"
    echo ""
    echo "Usage:"
    echo "  $0 ios [dev|release]      Build iOS app"
    echo "  $0 android [dev|release]  Build Android app"
    echo "  $0 all [dev|release]      Build both platforms"
    echo ""
    echo "Examples:"
    echo "  $0 ios dev        Run on iOS simulator"
    echo "  $0 ios release    Build .ipa for TestFlight"
    echo "  $0 android dev    Run on Android emulator"
    echo "  $0 android        Build .aab for Play Store"
    exit 1
    ;;
esac
