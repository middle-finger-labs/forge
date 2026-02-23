#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Forge GitHub Identity Setup Wizard
# ---------------------------------------------------------------------------
#
# Interactive script that configures SSH identities for Forge's multi-account
# GitHub support.
#
# What it does:
#   1. Asks which GitHub accounts you want to configure
#   2. For each: collects username, email, SSH key path
#   3. Tests each SSH connection
#   4. Writes ~/.forge/identities.yaml
#   5. Optionally sets up ~/.ssh/config blocks
#   6. Prints a summary
#
# Usage:
#   bash scripts/setup_github.sh
#
# Prerequisites:
#   - SSH keys already generated (ed25519 recommended)
#   - GitHub accounts have the SSH public keys added
#
# ---------------------------------------------------------------------------

set -euo pipefail

# Colors (only if terminal supports them)
if [[ -t 1 ]]; then
    BOLD='\033[1m'
    GREEN='\033[0;32m'
    YELLOW='\033[0;33m'
    RED='\033[0;31m'
    CYAN='\033[0;36m'
    RESET='\033[0m'
else
    BOLD='' GREEN='' YELLOW='' RED='' CYAN='' RESET=''
fi

CONFIG_DIR="$HOME/.forge"
CONFIG_FILE="$CONFIG_DIR/identities.yaml"
SSH_CONFIG="$HOME/.ssh/config"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

info()    { echo -e "${GREEN}[+]${RESET} $*"; }
warn()    { echo -e "${YELLOW}[!]${RESET} $*"; }
err()     { echo -e "${RED}[x]${RESET} $*" >&2; }
header()  { echo -e "\n${BOLD}${CYAN}$*${RESET}"; }
divider() { echo "────────────────────────────────────────"; }

prompt() {
    local var_name="$1" prompt_text="$2" default="${3:-}"
    if [[ -n "$default" ]]; then
        echo -en "  ${prompt_text} [${default}]: "
    else
        echo -en "  ${prompt_text}: "
    fi
    read -r value
    value="${value:-$default}"
    eval "$var_name=\"\$value\""
}

confirm() {
    local prompt_text="${1:-Continue?}"
    echo -en "  ${prompt_text} [y/N]: "
    read -r answer
    [[ "${answer,,}" == "y" ]]
}

test_ssh_connection() {
    local key_path="$1"
    local expanded
    expanded="${key_path/#\~/$HOME}"

    if [[ ! -f "$expanded" ]]; then
        echo "key_not_found"
        return
    fi

    local output
    output=$(ssh -T git@github.com \
        -i "$expanded" \
        -o IdentitiesOnly=yes \
        -o StrictHostKeyChecking=accept-new \
        -o ConnectTimeout=10 \
        2>&1) || true

    if echo "$output" | grep -qi "successfully authenticated"; then
        # Extract username
        local user
        user=$(echo "$output" | grep -oP 'Hi \K[^!]+' 2>/dev/null || echo "")
        if [[ -n "$user" ]]; then
            echo "ok:$user"
        else
            echo "ok:unknown"
        fi
    else
        echo "failed:${output:0:100}"
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

header "Forge GitHub Identity Setup Wizard"
echo
echo "This wizard helps you configure SSH identities for Forge."
echo "You'll need SSH keys already generated and added to your GitHub accounts."
echo
echo "Tip: Generate a new key with:"
echo "  ssh-keygen -t ed25519 -C 'your@email.com' -f ~/.ssh/id_ed25519_myname"
echo

# Check for existing config
if [[ -f "$CONFIG_FILE" ]]; then
    warn "Existing config found at $CONFIG_FILE"
    if ! confirm "Overwrite existing configuration?"; then
        info "Keeping existing config. Use 'python run_pipeline.py identities add' to add more."
        exit 0
    fi
    echo
fi

# ---------------------------------------------------------------------------
# Collect identities
# ---------------------------------------------------------------------------

declare -a NAMES USERNAMES EMAILS KEYS ALIASES ORGS
IDENTITY_COUNT=0
FIRST_IDENTITY=true

while true; do
    if $FIRST_IDENTITY; then
        header "Identity #$((IDENTITY_COUNT + 1))"
    else
        echo
        if ! confirm "Add another identity?"; then
            break
        fi
        header "Identity #$((IDENTITY_COUNT + 1))"
    fi
    FIRST_IDENTITY=false
    divider

    prompt name "Short name (e.g. 'personal', 'work')" ""
    if [[ -z "$name" ]]; then
        warn "Name is required — skipping this identity"
        continue
    fi

    prompt username "GitHub username" ""
    if [[ -z "$username" ]]; then
        warn "Username is required — skipping this identity"
        continue
    fi

    local_default_email="${username}@users.noreply.github.com"
    prompt email "Commit email" "$local_default_email"

    default_key="~/.ssh/id_ed25519_${name}"
    prompt ssh_key "SSH private key path" "$default_key"

    default_alias="github-${name}"
    prompt ssh_alias "SSH host alias" "$default_alias"

    prompt org "GitHub org (blank for personal repos)" ""

    # Test the connection
    echo
    info "Testing SSH connection with $ssh_key..."
    result=$(test_ssh_connection "$ssh_key")

    case "$result" in
        ok:*)
            gh_user="${result#ok:}"
            info "Connected as: ${BOLD}$gh_user${RESET}"
            ;;
        key_not_found)
            warn "SSH key not found at ${ssh_key/#\~/$HOME}"
            if ! confirm "Save this identity anyway?"; then
                continue
            fi
            ;;
        failed:*)
            reason="${result#failed:}"
            warn "Connection failed: $reason"
            if ! confirm "Save this identity anyway?"; then
                continue
            fi
            ;;
    esac

    NAMES+=("$name")
    USERNAMES+=("$username")
    EMAILS+=("$email")
    KEYS+=("$ssh_key")
    ALIASES+=("$ssh_alias")
    ORGS+=("${org:-}")
    IDENTITY_COUNT=$((IDENTITY_COUNT + 1))
done

if [[ $IDENTITY_COUNT -eq 0 ]]; then
    err "No identities configured. Exiting."
    exit 1
fi

# ---------------------------------------------------------------------------
# Choose default identity
# ---------------------------------------------------------------------------

echo
if [[ $IDENTITY_COUNT -eq 1 ]]; then
    DEFAULT_IDX=0
    info "Setting '${NAMES[0]}' as the default identity (only one configured)."
else
    header "Choose default identity"
    for i in $(seq 0 $((IDENTITY_COUNT - 1))); do
        echo "  $((i + 1)). ${NAMES[$i]} (${USERNAMES[$i]})"
    done
    prompt default_choice "Default identity [1-$IDENTITY_COUNT]" "1"
    DEFAULT_IDX=$((default_choice - 1))
    if [[ $DEFAULT_IDX -lt 0 || $DEFAULT_IDX -ge $IDENTITY_COUNT ]]; then
        DEFAULT_IDX=0
    fi
fi

# ---------------------------------------------------------------------------
# Write identities.yaml
# ---------------------------------------------------------------------------

header "Writing configuration"
mkdir -p "$CONFIG_DIR"

cat > "$CONFIG_FILE" << 'YAML_HEADER'
# Forge GitHub identities — managed by scripts/setup_github.sh
# Edit manually or use: python run_pipeline.py identities add
identities:
YAML_HEADER

for i in $(seq 0 $((IDENTITY_COUNT - 1))); do
    is_default="false"
    [[ $i -eq $DEFAULT_IDX ]] && is_default="true"

    cat >> "$CONFIG_FILE" << YAML_ENTRY
  - name: "${NAMES[$i]}"
    github_username: "${USERNAMES[$i]}"
    email: "${EMAILS[$i]}"
    ssh_key_path: "${KEYS[$i]}"
    ssh_host_alias: "${ALIASES[$i]}"
    default: $is_default
YAML_ENTRY

    if [[ -n "${ORGS[$i]}" ]]; then
        echo "    github_org: \"${ORGS[$i]}\"" >> "$CONFIG_FILE"
    fi
done

info "Saved to $CONFIG_FILE"

# ---------------------------------------------------------------------------
# SSH config setup
# ---------------------------------------------------------------------------

echo
header "SSH Config Setup"
echo
echo "Forge uses SSH host aliases to route git commands through the correct key."
echo "The following blocks should be in your ~/.ssh/config:"
echo

for i in $(seq 0 $((IDENTITY_COUNT - 1))); do
    expanded_key="${KEYS[$i]/#\~/$HOME}"
    cat << SSH_BLOCK
Host ${ALIASES[$i]}
    HostName github.com
    User git
    IdentityFile $expanded_key
    IdentitiesOnly yes

SSH_BLOCK
done

if confirm "Append these blocks to $SSH_CONFIG?"; then
    # Ensure the file exists
    touch "$SSH_CONFIG"
    chmod 600 "$SSH_CONFIG"

    for i in $(seq 0 $((IDENTITY_COUNT - 1))); do
        expanded_key="${KEYS[$i]/#\~/$HOME}"
        alias="${ALIASES[$i]}"

        # Skip if already present
        if grep -q "^Host $alias\$" "$SSH_CONFIG" 2>/dev/null; then
            warn "Host '$alias' already in $SSH_CONFIG — skipping"
            continue
        fi

        cat >> "$SSH_CONFIG" << SSH_BLOCK

Host $alias
    HostName github.com
    User git
    IdentityFile $expanded_key
    IdentitiesOnly yes
SSH_BLOCK
        info "Added Host $alias"
    done
else
    info "Skipped — add the blocks manually if needed."
fi

# ---------------------------------------------------------------------------
# GitHub token setup
# ---------------------------------------------------------------------------

echo
header "GitHub Token (Optional)"
echo
echo "Forge uses a GitHub PAT for API calls (creating PRs, commenting on issues)."
echo "You can set this now or later via environment variables."
echo

for i in $(seq 0 $((IDENTITY_COUNT - 1))); do
    name_upper=$(echo "${NAMES[$i]}" | tr '[:lower:]' '[:upper:]' | tr '-' '_')
    echo "  For '${NAMES[$i]}': export GITHUB_TOKEN_${name_upper}=ghp_..."
done
echo "  Fallback:       export GITHUB_TOKEN=ghp_..."
echo

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

header "Setup Complete"
divider
echo
echo "Configured ${IDENTITY_COUNT} identit$([ $IDENTITY_COUNT -eq 1 ] && echo 'y' || echo 'ies'):"
echo
printf "  %-15s %-20s %-15s %s\n" "NAME" "USERNAME" "ORG" "DEFAULT"
printf "  %-15s %-20s %-15s %s\n" "----" "--------" "---" "-------"
for i in $(seq 0 $((IDENTITY_COUNT - 1))); do
    def=""
    [[ $i -eq $DEFAULT_IDX ]] && def="*"
    org_display="${ORGS[$i]:-—}"
    printf "  %-15s %-20s %-15s %s\n" "${NAMES[$i]}" "${USERNAMES[$i]}" "$org_display" "$def"
done

echo
echo "Quick start:"
echo "  python run_pipeline.py identities list"
echo "  python run_pipeline.py identities test ${NAMES[0]}"
echo "  python run_pipeline.py repos test git@github.com:${USERNAMES[0]}/some-repo.git"
echo "  python run_pipeline.py start --repo git@github.com:owner/repo.git --spec 'Add feature X'"
echo
