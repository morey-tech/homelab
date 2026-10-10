#!/bin/sh
# The CronJob's Forbid policy and init-container ordering serialize cache updates.
set -eu

started_at=$(date +%s)
stage=initialization
log() {
    printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%S+00:00)" "$*"
}
finish() {
    status=$?
    trap - 0
    if [ "$status" -ne 0 ]; then
        log "Transcript sync failed during $stage (exit $status, elapsed $(($(date +%s) - started_at))s)" >&2
    fi
    exit "$status"
}
trap finish 0

cache_dir=${TRANSCRIPT_CACHE_DIR:-/transcripts}
source_url=${TRANSCRIPT_REPO_URL:-https://github.com/morey-tech/rr-scraper.git}
repo_dir="$cache_dir/repository.git"
export GIT_TERMINAL_PROMPT=0
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1

log "Starting transcript sync: $(git --version); cache=$cache_dir"
mkdir -p "$cache_dir"
git_cache() {
    git -c safe.directory="$repo_dir" --git-dir="$repo_dir" "$@"
}

if [ ! -f "$repo_dir/HEAD" ]; then
    log "Initializing bare Git cache"
    git init --quiet --bare --initial-branch=master "$repo_dir"
else
    log "Reusing existing bare Git cache"
fi
git_cache config remote.origin.url "$source_url"
git_cache config gc.autoDetach false
git_cache config pack.threads 1
git_cache config pack.windowMemory 32m
previous_revision=none
if [ -f "$cache_dir/revision" ]; then
    previous_revision=$(cat "$cache_dir/revision")
fi
log "Previously published revision: $previous_revision"
stage=fetch
fetch_started_at=$(date +%s)
log "Fetching origin/master (depth=1, no tags; reusing cached Git objects)"
git_cache fetch --depth=1 --no-tags origin +refs/heads/master:refs/heads/master
revision=$(git_cache rev-parse refs/heads/master)
log "Fetch completed in $(($(date +%s) - fetch_started_at))s; resolved revision: $revision"

stage="cache inspection"
if [ -s "$cache_dir/all.md" ] && [ -s "$cache_dir/episode-headings.txt" ] && [ -f "$cache_dir/revision" ] &&
    [ "$previous_revision" = "$revision" ]; then
    bytes=$(wc -c < "$cache_dir/all.md")
    headings=$(wc -l < "$cache_dir/episode-headings.txt")
    log "Transcript cache unchanged at $revision; reusing $((bytes)) transcript bytes and $((headings)) episode headings"
    log "Transcript sync completed in $(($(date +%s) - started_at))s"
    exit 0
fi
if [ "$previous_revision" = "$revision" ]; then
    log "Rebuilding missing or empty cache artifacts at the existing revision"
else
    log "Building cache artifacts for revision $revision"
fi

# Publish the revision last. A failed init never starts the lesson container.
stage="transcript export"
log "Exporting transcripts/all.md"
git_cache show "$revision:transcripts/all.md" > "$cache_dir/all.md.tmp"
test -s "$cache_dir/all.md.tmp"
bytes=$(wc -c < "$cache_dir/all.md.tmp")
log "Exported $((bytes)) transcript bytes"
# Locate actual headings: missing episode numbers make group boundaries irregular.
# Line links in plain view also work when GitHub suppresses Markdown rendering.
stage="episode heading index"
log "Indexing episode headings from transcripts/groups_of_20"
git_cache grep -n -E '^## Episode [0-9]+[[:space:]]*$' "$revision" -- transcripts/groups_of_20 > "$cache_dir/episode-headings.txt.tmp"
test -s "$cache_dir/episode-headings.txt.tmp"
headings=$(wc -l < "$cache_dir/episode-headings.txt.tmp")
log "Indexed $((headings)) episode headings"
stage="cache publication"
log "Publishing transcript snapshot and heading index, then revision"
mv "$cache_dir/all.md.tmp" "$cache_dir/all.md"
mv "$cache_dir/episode-headings.txt.tmp" "$cache_dir/episode-headings.txt"
printf '%s\n' "$revision" > "$cache_dir/revision.tmp"
mv "$cache_dir/revision.tmp" "$cache_dir/revision"
# Retain a short recovery window without accumulating every old large snapshot.
stage="garbage collection"
gc_started_at=$(date +%s)
log "Running Git garbage collection (prune unreachable objects older than seven days)"
git_cache gc --prune=7.days.ago
log "Git garbage collection completed in $(($(date +%s) - gc_started_at))s"
log "Transcript cache updated to $revision; $((bytes)) transcript bytes and $((headings)) episode headings"
log "Transcript sync completed in $(($(date +%s) - started_at))s"
