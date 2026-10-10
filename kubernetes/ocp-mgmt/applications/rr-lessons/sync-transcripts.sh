#!/bin/sh
# The CronJob's Forbid policy and init-container ordering serialize cache updates.
set -eu

cache_dir=${TRANSCRIPT_CACHE_DIR:-/transcripts}
source_url=${TRANSCRIPT_REPO_URL:-https://github.com/morey-tech/rr-scraper.git}
repo_dir="$cache_dir/repository.git"
export GIT_TERMINAL_PROMPT=0
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1

mkdir -p "$cache_dir"
git_cache() {
    git -c safe.directory="$repo_dir" --git-dir="$repo_dir" "$@"
}

if [ ! -f "$repo_dir/HEAD" ]; then
    git init --bare --initial-branch=master "$repo_dir"
fi
git_cache config remote.origin.url "$source_url"
git_cache config gc.autoDetach false
git_cache config pack.threads 1
git_cache config pack.windowMemory 32m
git_cache fetch --depth=1 --no-tags origin +refs/heads/master:refs/heads/master
revision=$(git_cache rev-parse refs/heads/master)

if [ -s "$cache_dir/all.md" ] && [ -s "$cache_dir/episode-headings.txt" ] && [ -f "$cache_dir/revision" ] &&
    [ "$(cat "$cache_dir/revision")" = "$revision" ]; then
    echo "Transcript cache unchanged at $revision"
    exit 0
fi

# Publish the revision last. A failed init never starts the lesson container.
git_cache show "$revision:transcripts/all.md" > "$cache_dir/all.md.tmp"
test -s "$cache_dir/all.md.tmp"
# Locate actual headings: missing episode numbers make group boundaries irregular.
# Line links in plain view also work when GitHub suppresses Markdown rendering.
git_cache grep -n -E '^## Episode [0-9]+[[:space:]]*$' "$revision" -- transcripts/groups_of_20 > "$cache_dir/episode-headings.txt.tmp"
test -s "$cache_dir/episode-headings.txt.tmp"
mv "$cache_dir/all.md.tmp" "$cache_dir/all.md"
mv "$cache_dir/episode-headings.txt.tmp" "$cache_dir/episode-headings.txt"
printf '%s\n' "$revision" > "$cache_dir/revision.tmp"
mv "$cache_dir/revision.tmp" "$cache_dir/revision"
# Retain a short recovery window without accumulating every old large snapshot.
git_cache gc --prune=7.days.ago
echo "Transcript cache updated to $revision"
