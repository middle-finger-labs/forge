# Forge — App Store Release Checklist

## Prerequisites

### Apple Developer Account
- [ ] Enroll in Apple Developer Program ($99/year) — https://developer.apple.com/programs/enroll/
- [ ] Create App ID: `com.middlefingerlabs.forge`
- [ ] Create Distribution Certificate
- [ ] Create App Store Provisioning Profile
- [ ] Create App Store Connect API Key (for CI uploads)
- [ ] Update `DEVELOPMENT_TEAM` in `tauri.conf.json` and `project.yml`

### Google Play Console
- [ ] Create Google Play Developer account ($25 one-time)
- [ ] Create app listing for `com.middlefingerlabs.forge`
- [ ] Generate signing keystore: `./scripts/setup-signing.sh android`
- [ ] Create Play Console service account for CI uploads

### GitHub Actions Secrets
Configure at: `Settings → Secrets and variables → Actions`

**iOS secrets:**
- [ ] `IOS_BUILD_CERTIFICATE_BASE64` — Distribution certificate .p12 (base64)
- [ ] `IOS_P12_PASSWORD` — Certificate export password
- [ ] `IOS_PROVISION_PROFILE_BASE64` — Provisioning profile (base64)
- [ ] `IOS_KEYCHAIN_PASSWORD` — Random string for CI keychain
- [ ] `APPLE_DEVELOPMENT_TEAM` — 10-char Team ID
- [ ] `APP_STORE_CONNECT_API_KEY_ID` — API key ID
- [ ] `APP_STORE_CONNECT_ISSUER_ID` — Issuer ID
- [ ] `APP_STORE_CONNECT_API_KEY` — .p8 key content (base64)

**Android secrets:**
- [ ] `ANDROID_KEYSTORE_BASE64` — Keystore file (base64)
- [ ] `ANDROID_KEYSTORE_PASSWORD` — Keystore password
- [ ] `ANDROID_KEY_ALIAS` — Key alias (default: `forge`)
- [ ] `ANDROID_KEY_PASSWORD` — Key password

---

## TestFlight Distribution (Start Here)

### First Upload
1. [ ] Run `./scripts/build-mobile.sh ios release`
2. [ ] Upload to TestFlight via Xcode Organizer or `xcrun altool`
3. [ ] Or push a version tag: `git tag v0.1.0 && git push --tags`
4. [ ] Wait for App Store Connect processing (~15 min)
5. [ ] Add yourself as internal tester

### Testing Checklist
- [ ] App launches and shows login/biometric screen
- [ ] Push notifications arrive (not testable on simulator)
- [ ] Biometric auth works (Face ID / Touch ID)
- [ ] Conversations load and messages display correctly
- [ ] Pipeline list shows with correct status badges
- [ ] Approval swipe-to-approve gesture works
- [ ] Offline mode: disconnect WiFi, queue message, reconnect
- [ ] Deep links open correct conversation (`forge://conversation/xxx`)
- [ ] Tab bar haptic feedback fires on tap
- [ ] Pull-to-refresh works on all lists
- [ ] Large title collapses on scroll (iOS)
- [ ] Android back button navigates correctly
- [ ] App suspends/resumes without losing state

---

## App Store Submission Prep

### App Icon
- [ ] Create 1024x1024 source icon (no transparency, no rounded corners)
- [ ] Run `pnpm mobile:icons` to generate all sizes
- [ ] Verify icons in Xcode asset catalog

### Screenshots (required sizes)
- [ ] iPhone 6.7" (iPhone 15 Pro Max) — 1290×2796 or 1284×2778
- [ ] iPhone 6.1" (iPhone 15 Pro) — 1179×2556
- [ ] iPad 12.9" (iPad Pro) — 2048×2732
- Minimum 3 screenshots per device size
- Suggested screens: Messages list, Conversation view, Pipeline list, Approval queue, Settings

### Metadata
- [ ] Review `fastlane/metadata/en-US/description.txt`
- [ ] Review `fastlane/metadata/en-US/keywords.txt` (100 char max)
- [ ] Review `fastlane/metadata/en-US/release_notes.txt`
- [ ] Set app category: Developer Tools
- [ ] Set age rating: 4+ (no objectionable content)
- [ ] Set pricing: Free

### Legal
- [ ] Privacy policy hosted at public URL
- [ ] Terms of service (optional but recommended)
- [ ] EULA (optional — Apple provides a default)

### App Review Notes
Provide a demo account or explain:
> "Forge connects to a self-hosted server. For review purposes, the app includes
> demo data that displays without a server connection. All pipeline, agent, and
> conversation data shown is simulated."

---

## Build Commands Reference

```bash
# Local development
pnpm ios:dev              # iOS simulator
pnpm android:dev          # Android emulator

# Release builds
pnpm ios:build            # Build .ipa
pnpm android:build        # Build .aab

# Helper scripts
./scripts/build-mobile.sh ios release
./scripts/build-mobile.sh android release
./scripts/setup-signing.sh ios       # Show signing instructions
./scripts/setup-signing.sh android   # Generate keystore

# Fastlane (after `bundle install`)
bundle exec fastlane ios beta        # Build + TestFlight
bundle exec fastlane android beta    # Build + Play Console
```

## Version Bumping

Update version in **all three** locations:
1. `desktop/package.json` → `version`
2. `desktop/src-tauri/tauri.conf.json` → `version`
3. `desktop/src-tauri/Cargo.toml` → `version`

Then tag and push:
```bash
git tag v0.2.0
git push --tags
```
This triggers the `build-mobile.yml` workflow automatically.
