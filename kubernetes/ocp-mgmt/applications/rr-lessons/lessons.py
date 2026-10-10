#!/usr/bin/env python3
"""Generate one grounded lesson and deliver it once per local calendar day."""

import argparse
from contextlib import redirect_stdout
from collections import Counter
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import re
import sys
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from uuid import uuid4
from zoneinfo import ZoneInfo


REPO = "morey-tech/rr-scraper"
TOKEN_PATH = "/var/run/secrets/inference/token"
MAX_EXCERPT = 12000
PROMPT = Path(__file__).with_name("prompt.txt").read_text()


class LessonError(Exception):
    pass


def log(message, *, stream=None):
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"{timestamp} {message}", file=stream or sys.stdout, flush=True)


def print_lesson(entry, day):
    log(f"Lesson for {day}, episode {entry['episode']} (status={entry['status']})")
    for embed in entry["payload"]["embeds"]:
        print(f"\n{embed['title']}\n\n{embed['description']}", flush=True)
        for field in embed.get("fields", []):
            print(f"\n{field['name']}: {field['value']}", flush=True)
    log("End of lesson")


def request(url, *, payload=None, token=None, limit=2 * 1024 * 1024, service="HTTP"):
    headers = {"User-Agent": "homelab-rr-lessons", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = Request(url, data=None if payload is None else json.dumps(payload).encode(),
                  headers=headers)
    started = monotonic()
    log(f"{service} request started")
    try:
        with urlopen(req, timeout=300 if token else 60) as response:
            data = response.read(limit + 1)
    except HTTPError as exc:
        # URLs and response bodies may contain the webhook credential. Never log them.
        raise LessonError(f"{service} request failed (status {exc.code}, after {monotonic() - started:.1f}s)") from None
    except (URLError, TimeoutError, OSError):
        raise LessonError(f"{service} request failed (connection or timeout, after {monotonic() - started:.1f}s)") from None
    if len(data) > limit:
        raise LessonError(f"{service} response exceeded size limit")
    log(f"{service} request completed in {monotonic() - started:.1f}s ({len(data)} response bytes)")
    return data.decode("utf-8")


def read_transcripts():
    """Read the snapshot published by the Git init container on the cache PVC."""
    cache = Path(os.environ.get("TRANSCRIPT_CACHE_DIR", "/transcripts"))
    commit = (cache / "revision").read_text().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise LessonError("Invalid repository commit")
    with (cache / "all.md").open("rb") as handle:
        data = handle.read(64 * 1024 * 1024 + 1)
    if not data or len(data) > 64 * 1024 * 1024:
        raise LessonError("Cached transcript is empty or exceeds size limit")
    log(f"Loaded {len(data)} transcript bytes from cache at commit {commit}")
    return data.decode("utf-8"), commit


def excerpts(text):
    """Split canonical episode headings into bounded, source-linked passages."""
    lines = text.splitlines()
    headings = [(i, int(m[1])) for i, line in enumerate(lines)
                if (m := re.fullmatch(r"## Episode (\d+)\s*", line))]
    result = []
    for position, (start, episode) in enumerate(headings):
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        buffer, first, last = [], start + 2, start + 2

        def append_chunk():
            body = "\n".join(buffer).strip()
            if len(body) >= 300:
                result.append({"episode": episode, "text": body, "start": first,
                               "end": last, "key": f"{episode}:" +
                               hashlib.sha256(body.encode()).hexdigest()[:20]})

        for index in range(start + 1, end):
            # A malformed/very long paragraph must not overflow the model context.
            parts = [lines[index][i:i + MAX_EXCERPT]
                     for i in range(0, len(lines[index]), MAX_EXCERPT)] or [""]
            for part in parts:
                if buffer and sum(len(s) + 1 for s in buffer) + len(part) > MAX_EXCERPT:
                    append_chunk()
                    buffer = []
                if not buffer:
                    first = index + 1
                buffer.append(part)
                last = index + 1
        append_chunk()
    if not result:
        raise LessonError("No substantive transcript excerpts found")
    return result


def choose(candidates, history, day):
    # Attempted deliveries also count: a lost Discord response may still have posted.
    used = [entry for entry in history.values() if entry["status"] in ("sending", "sent")]
    episode_counts = Counter(entry["episode"] for entry in used)
    chunk_counts = Counter(entry["key"] for entry in used)
    rank = lambda item: (episode_counts[item["episode"]], chunk_counts[item["key"]])
    best = min(map(rank, candidates))
    return random.Random(day).choice([item for item in candidates if rank(item) == best])


def generate(excerpt, history):
    recent = [history[day]["title"] for day in sorted(history)[-14:]]
    user = json.dumps({"episode": excerpt["episode"], "recent_titles": recent,
                       "transcript_excerpt": excerpt["text"]}, ensure_ascii=False)
    token = Path(os.environ.get("LLM_TOKEN_FILE", TOKEN_PATH)).read_text().strip()
    log(f"Generating lesson with {len(recent)} recent titles for context")
    response = json.loads(request(os.environ["LLM_BASE_URL"].rstrip("/") + "/chat/completions",
                                  token=token, service="Inference", payload={
        "model": os.environ.get("LLM_MODEL", "local-llm"),
        "messages": [{"role": "system", "content": PROMPT}, {"role": "user", "content": user}],
        "temperature": 0.5, "max_tokens": 1000,
        "response_format": {"type": "json_object"},
    }))
    choice = response["choices"][0]
    usage = response.get("usage") or {}
    counts = ", ".join(f"{key}={usage[key]}" for key in ("prompt_tokens", "completion_tokens")
                       if isinstance(usage.get(key), int))
    if counts:
        log(f"Inference token usage: {counts}")
    if choice.get("finish_reason") != "stop":
        raise LessonError("Model response did not finish normally")
    lesson = json.loads(choice["message"]["content"])
    if lesson.get("skip") is True:
        return None
    for field, maximum in (("title", 100), ("explanation", 2300), ("takeaway", 650),
                           ("reflection", 350), ("evidence", 350)):
        if not isinstance(lesson.get(field), str) or not 1 <= len(lesson[field].strip()) <= maximum:
            raise LessonError(f"Invalid lesson field: {field}")
        lesson[field] = lesson[field].strip()
    quote = " ".join(lesson["evidence"].split())
    if not 5 <= len(quote.split()) <= 25 or quote not in " ".join(excerpt["text"].split()):
        raise LessonError("Lesson evidence is not a short verbatim source passage")
    if any(re.search(r"https?://", value) for value in lesson.values() if isinstance(value, str)):
        raise LessonError("Model supplied an unexpected link")
    log("Lesson fields and source quotation validated")
    return lesson


def transcript_url(episode, commit):
    cache = Path(os.environ.get("TRANSCRIPT_CACHE_DIR", "/transcripts"))
    matches = []
    for entry in (cache / "episode-headings.txt").read_text().splitlines():
        match = re.fullmatch(
            r"([0-9a-f]{40}):(transcripts/groups_of_20/episodes_\d+_to_\d+\.md):([1-9]\d*):## Episode (\d+)\s*",
            entry)
        if match and int(match[4]) == episode and (commit == "master" or match[1] == commit):
            matches.append((match[2], match[3]))
    if len(matches) != 1:
        raise LessonError(f"Expected one grouped transcript for episode {episode}")
    path, line = matches[0]
    return f"https://github.com/{REPO}/blob/{commit}/{path}?plain=1#L{line}"


def make_payload(lesson, excerpt, commit, day):
    source = transcript_url(excerpt["episode"], commit)
    description = (f"{lesson['explanation']}\n\n**Takeaway**\n{lesson['takeaway']}"
                   f"\n\n**Reflect**\n{lesson['reflection']}"
                   f"\n\n**From the transcript**\n> {lesson['evidence']}")
    if len(description.encode("utf-16-le")) // 2 > 4096:
        raise LessonError("Lesson exceeds Discord embed limit")
    return {"username": "Rational Reminder Lessons", "allowed_mentions": {"parse": []},
            "embeds": [{"title": lesson["title"], "description": description,
                        "url": source, "color": 3447003,
                        "fields": [{"name": "Source", "value":
                                    f"[Episode {excerpt['episode']}](https://rationalreminder.ca/podcast/{excerpt['episode']})"
                                    f" · [Episode transcript]({source})"}],
                        "footer": {"text": f"{day} · Rational Reminder · Generated by local-llm"}}]}


def webhook_url(value):
    parts = urlsplit(value)
    if (parts.scheme != "https" or parts.netloc != "discord.com"
            or not re.fullmatch(r"/api(?:/v\d+)?/webhooks/\d+/[A-Za-z0-9._-]+", parts.path)):
        raise LessonError("Expected a Discord HTTPS webhook URL")
    query = dict(parse_qsl(parts.query))
    query["wait"] = "true"
    return urlunsplit(parts._replace(query=urlencode(query), fragment=""))


def save(path, history):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as handle:
        json.dump(history, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def prepare(history, day, transcript_file=None):
    if transcript_file:
        text, commit = Path(transcript_file).read_text(), "master"
        log(f"Loaded local transcript fixture ({len(text)} characters)")
    else:
        text, commit = read_transcripts()
    candidates = excerpts(text)
    log(f"Indexed {len(candidates)} passages across {len({item['episode'] for item in candidates})} episodes")
    # Try another passage if the model recognizes an intro or housekeeping segment.
    for attempt in range(3):
        excerpt = choose(candidates, history, f"{day}:{attempt}")
        log(f"Generation attempt {attempt + 1}/3: episode {excerpt['episode']}, "
            f"all.md lines {excerpt['start']}-{excerpt['end']}, {len(excerpt['text'])} characters")
        lesson = generate(excerpt, history)
        if lesson:
            return {"status": "prepared", "episode": excerpt["episode"], "key": excerpt["key"],
                    "title": lesson["title"], "commit": commit,
                    "payload": make_payload(lesson, excerpt, commit, day)}
        log("Model skipped this passage; selecting another")
        candidates.remove(excerpt)
        if not candidates:
            break
    raise LessonError("No teachable passage found in three attempts")


def deliver(history, day, path, url, *, entry_key=None):
    entry = history[entry_key or day]
    # Persist intent BEFORE posting. An interrupted/ambiguous delivery is never retried.
    entry["status"] = "sending"
    save(path, history)
    log("Saved delivery intent; posting lesson to Discord")
    response = json.loads(request(url, payload=entry["payload"], service="Discord"))
    if not isinstance(response.get("id"), str) or not response["id"]:
        raise LessonError("Discord did not confirm a message ID")
    entry.update(status="sent", message_id=response["id"])
    save(path, history)
    log(f"Delivered lesson for {day}, episode {entry['episode']}; "
        f"Discord message ID {response['id']}; history saved")


def run(preview=False, transcript_file=None, allow_duplicate=False):
    day = datetime.now(ZoneInfo(os.environ.get("LESSON_TIMEZONE", "America/Toronto"))).date().isoformat()
    directory = Path(os.environ.get("STATE_DIR", "/data"))
    path = directory / "history.json"
    if preview:
        history = json.loads(path.read_text()) if path.exists() else {}
        # Keep preview stdout as a single JSON payload for command-line consumers.
        with redirect_stdout(sys.stderr):
            log(f"Previewing lesson for {day}; loaded {len(history)} history entries")
            entry = (None if allow_duplicate else history.get(day)) or prepare(history, day, transcript_file)
        print(json.dumps(entry["payload"], ensure_ascii=False, indent=2))
        return
    log(f"Starting daily lesson for {day} ({os.environ.get('LESSON_TIMEZONE', 'America/Toronto')})")
    entry_key = day
    if allow_duplicate:
        # A Job's retries share an ID; separate test Jobs can each send a lesson.
        run_id = os.environ.get("LESSON_RUN_ID") or uuid4().hex
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", run_id):
            raise LessonError("Invalid LESSON_RUN_ID")
        entry_key = f"{day}/test-{run_id}"
        log(f"Duplicate testing enabled; history entry {entry_key}")
    url = webhook_url(os.environ["DISCORD_WEBHOOK_URL"].strip())
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "history.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        history = json.loads(path.read_text()) if path.exists() else {}
        log(f"Acquired history lock; loaded {len(history)} history entries")
        if entry_key in history and history[entry_key]["status"] == "sent":
            print_lesson(history[entry_key], day)
            log(f"Lesson for {entry_key} already delivered; skipping")
            return
        if entry_key in history and history[entry_key]["status"] == "sending":
            print_lesson(history[entry_key], day)
            raise LessonError("Delivery unconfirmed; inspect Discord and history before any manual retry")
        if entry_key not in history:
            history[entry_key] = prepare(history, day)
            if allow_duplicate:
                history[entry_key]["test_run"] = True
            save(path, history)
            log("Saved prepared lesson to history")
        else:
            log("Reusing prepared lesson from history")
        print_lesson(history[entry_key], day)
        deliver(history, day, path, url, entry_key=entry_key)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true", help="Generate without posting or changing history")
    parser.add_argument("--transcript-file", help="Local transcript fixture (preview only)")
    parser.add_argument("--allow-duplicate", action="store_true",
                        default=os.environ.get("ALLOW_DUPLICATE_LESSONS", "false").lower() == "true",
                        help="Generate an additional test lesson (or set ALLOW_DUPLICATE_LESSONS=true)")
    args = parser.parse_args()
    if args.transcript_file and not args.preview:
        parser.error("--transcript-file requires --preview")
    try:
        run(args.preview, args.transcript_file, args.allow_duplicate)
    except LessonError as exc:
        log(f"Lesson job failed: {exc}", stream=sys.stderr)
        return 1
    except Exception as exc:
        # Avoid dumping tokens, webhook URLs, model responses, or request bodies.
        log(f"Lesson job failed ({type(exc).__name__}); check configuration and service health", stream=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
