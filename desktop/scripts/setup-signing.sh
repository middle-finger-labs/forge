#!/usr/bin/env bash
set -euo pipefail

# ─── Forge Mobile Signing Setup ──────────────────────
# Generates signing keys and prints GitHub Actions secrets to configure.
# Run once per project, then store secrets securely.

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[info]${NC} $*"; }
ok()    { echo -e "${GREEN}[ok]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC} $*"; }

PLATFORM="${1:-}"

# ─── Android Signing Key ─────────────────────────────

setup_android() {
  local keystore="forge-release.keystore"

  if [ -f "$keystore" ]; then
    warn "Keystore '$keystore' already exists. Delete it first to regenerate."
    return
  fi

  info "Generating Android signing keystore..."
  echo ""

  keytool -genkey -v \
    -keystore "$keystore" \
    -alias forge \
    -keyalg RSA \
    -keysize 2048 \
    -validity 10000 \
    -storepass "$(read -rsp 'Keystore password: ' pw && echo "$pw")" \
    -dname "CN=Forge, O=Middle Finger Labs, L=Unknown, ST=Unknown, C=US"

  echo ""
  ok "Keystore generated: $keystore"
  echo ""
  info "Add these GitHub Actions secrets:"
  echo ""
  echo "  ANDROID_KEYSTORE_BASE64:"
  echo "    base64 -i $keystore | pbcopy  (macOS — copied to clipboard)"
  echo "    base64 $keystore              (Linux — copy the output)"
  echo ""
  echo "  ANDROID_KEYSTORE_PASSWORD: <the password you just entered>"
  echo "  ANDROID_KEY_ALIAS: forge"
  echo "  ANDROID_KEY_PASSWORD: <same password>"
  echo ""
  warn "Store '$keystore' securely. NEVER commit it to git."
  warn "If you lose this key, you cannot update the app on Play Store."
}

# ─── iOS Signing Info ─────────────────────────────────

setup_ios() {
  info "iOS signing requires an Apple Developer account (\$99/year)"
  echo ""
  echo "Steps:"
  echo "  1. Create an App ID at https://developer.apple.com/account/resources/identifiers"
  echo "     Bundle ID: com.middlefingerlabs.forge"
  echo ""
  echo "  2. Create a Distribution Certificate"
  echo "     Keychain Access → Certificate Assistant → Request from CA"
  echo "     Upload CSR at https://developer.apple.com/account/resources/certificates"
  echo ""
  echo "  3. Create a Provisioning Profile"
  echo "     Type: App Store Distribution (for TestFlight/App Store)"
  echo "     or: Ad Hoc (for direct device installs)"
  echo ""
  echo "  4. Export the certificate as .p12:"
  echo "     Keychain Access → My Certificates → Export"
  echo ""
  echo "  5. Add these GitHub Actions secrets:"
  echo ""
  echo "     IOS_BUILD_CERTIFICATE_BASE64:"
  echo "       base64 -i Certificates.p12 | pbcopy"
  echo ""
  echo "     IOS_P12_PASSWORD: <certificate export password>"
  echo ""
  echo "     IOS_PROVISION_PROFILE_BASE64:"
  echo "       base64 -i profile.mobileprovision | pbcopy"
  echo ""
  echo "     IOS_KEYCHAIN_PASSWORD: <any random string>"
  echo ""
  echo "     APPLE_DEVELOPMENT_TEAM: <your 10-char Team ID>"
  echo "       Find at: https://developer.apple.com/account → Membership"
  echo ""
  echo "  6. For TestFlight upload, also add:"
  echo "     APP_STORE_CONNECT_API_KEY_ID"
  echo "     APP_STORE_CONNECT_ISSUER_ID"
  echo "     APP_STORE_CONNECT_API_KEY (base64 of .p8 file)"
  echo "       Create at: https://appstoreconnect.apple.com/access/integrations/api"
  echo ""
  info "Update DEVELOPMENT_TEAM in:"
  echo "  - desktop/src-tauri/tauri.conf.json (bundle.iOS.developmentTeam)"
  echo "  - desktop/src-tauri/gen/apple/project.yml (DEVELOPMENT_TEAM)"
}

# ─── Main ─────────────────────────────────────────────

case "$PLATFORM" in
  android)
    setup_android
    ;;
  ios)
    setup_ios
    ;;
  *)
    echo "Forge Signing Setup"
    echo ""
    echo "Usage:"
    echo "  $0 ios       Show iOS signing setup instructions"
    echo "  $0 android   Generate Android signing keystore"
    echo ""
    exit 1
    ;;
esac
