#!/bin/bash
# GitHub CLI Auto-Authentication
# Runs once on first shell initialization to authenticate gh CLI
# Uses git credential helper to extract GitHub token

# Marker file to track authentication completion
GH_AUTH_MARKER="$HOME/.config/gh/.auth-initialized"

# Function to authenticate gh CLI
authenticate_gh() {
    # Check if gh is already authenticated
    if gh auth status >/dev/null 2>&1; then
        touch "$GH_AUTH_MARKER"
        return 0
    fi

    # Extract GitHub token from git credential helper
    GITHUB_TOKEN=$(printf "protocol=https\nhost=github.com\n\n" | git credential fill 2>/dev/null | grep "^password=" | cut -d= -f2)

    if [ -n "$GITHUB_TOKEN" ]; then
        # Authenticate gh CLI
        if echo "$GITHUB_TOKEN" | gh auth login --with-token 2>/dev/null; then
            touch "$GH_AUTH_MARKER"
            unset GITHUB_TOKEN
            return 0
        fi
    fi

    # Clear token from memory
    unset GITHUB_TOKEN
    return 1
}

# Only run if marker doesn't exist and gh is installed
if [ ! -f "$GH_AUTH_MARKER" ] && command -v gh >/dev/null 2>&1; then
    # Run authentication in background to avoid blocking shell startup
    (
        # Wait a moment to ensure git credentials are available
        sleep 1
        authenticate_gh
    ) >/dev/null 2>&1 &

    # Disown the background job so it doesn't interfere with shell
    disown
fi
