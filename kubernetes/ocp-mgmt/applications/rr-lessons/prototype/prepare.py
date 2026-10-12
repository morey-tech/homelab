#!/usr/bin/env python3
"""Prepare one committed podcast episode for human review; never publish it."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


VERSION = "1"
DIRECTORY = Path(__file__).parent
DEFAULT_URL = "https://local-llm-inference-server.apps.ocp-mgmt.rh-lab.morey.tech/v1"
MAX_PASSAGE = 1800
MAX_SECTION = 6000
MAX_OUTPUT_TOKENS = 2400
CONTEXT_LIMIT = 32768


class PreparationError(Exception):
    pass


def log(message):
    print(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {message}",
          file=sys.stderr, flush=True)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode()


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def git(repo, *args):
    try:
        return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.PIPE)
    except subprocess.CalledProcessError:
        raise PreparationError("Cannot read requested transcript revision from the local Git repository") from None


def read_source(repo, revision, episode):
    # Resolve refs once, then read only immutable objects (never a dirty checkout).
    if episode < 1 or revision.startswith("-"):
        raise PreparationError("Invalid episode or revision")
    commit = git(repo, "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}").decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise PreparationError("Expected a full Git commit hash")
    path = f"transcripts/individual/episode_{episode}.md"
    size = int(git(repo, "cat-file", "-s", f"{commit}:{path}"))
    if not 0 < size <= 2 * 1024 * 1024:
        raise PreparationError("Episode is empty or exceeds the 2 MiB prototype limit")
    raw = git(repo, "show", f"{commit}:{path}")
    return source_from_bytes(raw, commit, episode)


def source_from_bytes(raw, commit, episode):
    """Validate the same immutable source for CLI and background ingestion."""
    if type(episode) is not int or episode < 1 or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise PreparationError("Invalid episode or Git commit")
    if not 0 < len(raw) <= 2 * 1024 * 1024:
        raise PreparationError("Episode is empty or exceeds the 2 MiB prototype limit")
    path = f"transcripts/individual/episode_{episode}.md"
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        raise PreparationError("Episode transcript must be UTF-8") from None
    headings = list(re.finditer(r"^## Episode ([0-9]+)[ \t]*$", text, re.MULTILINE))
    if len(headings) != 1 or int(headings[0][1]) != episode or text[:headings[0].start()].strip():
        raise PreparationError("Individual transcript must contain exactly its own episode heading")
    source = {"repository": "https://github.com/morey-tech/rr-scraper", "commit": commit,
              "path": path, "episode": episode, "sha256": digest(raw), "bytes": len(raw),
              "episode_url": f"https://rationalreminder.ca/podcast/{episode}",
              "transcript_url": f"https://github.com/morey-tech/rr-scraper/blob/{commit}/{path}",
              "title": None, "publication_date": None}
    return source, text, headings[0].end()


def passages(source, text, body_start):
    result = []
    speaker = None
    # Work in source character offsets. Only inter-paragraph whitespace is excluded.
    for match in re.finditer(r"\S.*?(?=\s*\n[^\S\n]*\n|\s*\Z)", text[body_start:], re.DOTALL):
        start, end = body_start + match.start(), body_start + match.end()
        label = re.match(r"([A-Z][\w .’'\-]{0,70}):[ \t]", text[start:end])
        if label:
            speaker = label[1]
        first = True
        while start < end:
            stop = min(start + MAX_PASSAGE, end)
            if stop < end:
                boundary = text.rfind(" ", start + MAX_PASSAGE // 2, stop)
                if boundary != -1:
                    stop = boundary
            body = text[start:stop]
            key = f"e{source['episode']}-" + digest(f"{start}:{body}".encode())[:16]
            result.append({"id": key, "text": body, "start_char": start, "end_char": stop,
                           "start_line": text.count("\n", 0, start) + 1,
                           "end_line": text.count("\n", 0, stop - 1) + 1,
                           "speaker_hint": speaker, "speaker_label_in_passage": bool(label and first)})
            start = stop
            while start < end and text[start].isspace():
                start += 1
            first = False
    if not result:
        raise PreparationError("Episode has no transcript body")
    for i, item in enumerate(result):
        item["previous_id"] = result[i - 1]["id"] if i else None
        item["next_id"] = result[i + 1]["id"] if i + 1 < len(result) else None
        item["source_url"] = source["transcript_url"] + f"?plain=1#L{item['start_line']}-L{item['end_line']}"
    return result


def sections(items):
    groups, current, size = [], [], 0
    for item in items:
        if current and size + len(item["text"]) > MAX_SECTION:
            groups.append(current)
            current, size = [], 0
        current.append(item["id"])
        size += len(item["text"])
    if current:
        groups.append(current)
    return [{"id": f"section-{i + 1:03d}", "focus_ids": ids,
             "passage_ids": expand(ids, items)} for i, ids in enumerate(groups)]


def expand(ids, items):
    wanted = set(ids)
    for i, item in enumerate(items):
        if item["id"] in ids:
            if i:
                wanted.add(items[i - 1]["id"])
            if i + 1 < len(items):
                wanted.add(items[i + 1]["id"])
    return [p["id"] for p in items if p["id"] in wanted]


def string(value, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise PreparationError(f"Expected a nonempty string of at most {limit} characters")
    return value


def strings(value, maximum, limit, minimum=0):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise PreparationError(f"Expected an array of {minimum}–{maximum} strings")
    return [string(v, limit) for v in value]


def validate_question(question, available, focus):
    fields = {"concept", "question", "answer_outline", "context_ids", "qualifications", "prerequisites"}
    if not isinstance(question, dict) or set(question) != fields:
        raise PreparationError("Question fields do not match the required schema")
    string(question["concept"], 160)
    string(question["question"], 300)
    strings(question["qualifications"], 4, 300)
    strings(question["prerequisites"], 4, 160)
    context = strings(question["context_ids"], 4, 80)
    outline = question["answer_outline"]
    if not isinstance(outline, list) or not 1 <= len(outline) <= 4:
        raise PreparationError("Expected one to four answer-outline claims")
    evidence = set()
    for point in outline:
        if not isinstance(point, dict) or set(point) != {"claim", "passage_ids"}:
            raise PreparationError("Each claim needs text and supporting passage IDs")
        string(point["claim"], 500)
        evidence.update(strings(point["passage_ids"], 3, 80, minimum=1))
    if not (evidence | set(context)) <= set(available):
        raise PreparationError("Question cites a passage not supplied to the model")
    if not evidence & set(focus):
        raise PreparationError("Question has no supporting evidence in the focus section")
    return evidence | set(context)


def failed_review_checks(review):
    return [label for key, label in (
        ("supported", "source support"), ("context_sufficient", "sufficient context"),
        ("teachable", "teachability")) if review.get(key) is False]


def review_status_label(entry):
    if entry["status"] == "needs_human_review":
        review = entry.get("review")
        review = review if isinstance(review, dict) else {}
        if (not entry.get("error") and review.get("confidence") == "high"
                and all(review.get(key) is True for key in ("supported", "context_sufficient", "teachable"))):
            return "Ready for human review"
        return "Needs human review"
    return entry["status"]


def validate_review(review):
    if not isinstance(review, dict) or set(review) != {
            "supported", "context_sufficient", "teachable", "reason", "confidence", "confidence_reason"}:
        raise PreparationError("Review fields do not match the required schema")
    for field in ("supported", "context_sufficient", "teachable"):
        if type(review[field]) is not bool:
            raise PreparationError("Review judgments must be JSON booleans")
    string(review["reason"], 1200)
    if not isinstance(review["confidence"], str) or review["confidence"] not in ("low", "medium", "high"):
        raise PreparationError("Review confidence must be low, medium, or high")
    string(review["confidence_reason"], 500)
    passed = all(review[field] for field in ("supported", "context_sufficient", "teachable"))
    if not passed and review["confidence"] != "low":
        raise PreparationError(
            f"Review checks failed: {', '.join(failed_review_checks(review))}. "
            f"Model reported {review['confidence']} confidence despite those failures. "
            f"Reviewer explanation: {review['reason']}")
    return passed


def response_schema(stage, payload):
    def obj(properties):
        return {"type": "object", "properties": properties,
                "required": list(properties), "additionalProperties": False}

    def text(limit):
        return {"type": "string", "minLength": 1, "maxLength": limit}

    def array(item, maximum, minimum=0):
        return {"type": "array", "items": item, "minItems": minimum, "maxItems": maximum}

    if stage == "review":
        return obj({"supported": {"type": "boolean"}, "context_sufficient": {"type": "boolean"},
                    "teachable": {"type": "boolean"}, "reason": text(1200),
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    "confidence_reason": text(500)})
    passage_id = {"type": "string", "enum": [p["id"] for p in payload["passages"]]}
    question = obj({"concept": text(160), "question": text(300),
                    "answer_outline": array(obj({"claim": text(500),
                                                 "passage_ids": array(passage_id, 3, 1)}), 4, 1),
                    "context_ids": array(passage_id, 4), "qualifications": array(text(300), 4),
                    "prerequisites": array(text(160), 4)})
    return obj({"questions": array(question, 3)})


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_endpoint(base_url):
    parsed = urlsplit(base_url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path != "/v1"):
        raise PreparationError("Model URL must be an HTTPS endpoint ending in /v1 without credentials or query parameters")


class Model:
    def __init__(self, base_url, name, token):
        validate_endpoint(base_url)
        if not token.strip():
            raise PreparationError("Inference token is empty")
        self.base_url, self.name, self.token = base_url, name, token.strip()
        self.opener = build_opener(NoRedirects())

    def post(self, url, data):
        request = Request(url, data=encoded(data), headers={"Content-Type": "application/json",
                          "Authorization": f"Bearer {self.token}", "User-Agent": "rr-episode-prototype"})
        try:
            with self.opener.open(request, timeout=300) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
        except HTTPError as exc:
            status = exc.code
            exc.close()
            raise PreparationError(f"Inference HTTP {status}") from None
        except (URLError, OSError):
            raise PreparationError("Inference connection or timeout failure") from None
        if len(raw) > 2 * 1024 * 1024:
            raise PreparationError("Inference response exceeds size limit")
        try:
            return json.loads(raw)
        except (ValueError, UnicodeError):
            raise PreparationError("Inference returned invalid JSON") from None

    def complete(self, messages, schema):
        count = self.post(self.base_url[:-3] + "/tokenize", {
            "model": self.name, "messages": messages, "add_generation_prompt": True}).get("count")
        if type(count) is not int or count < 0 or count + MAX_OUTPUT_TOKENS + 256 > CONTEXT_LIMIT:
            raise PreparationError("Request exceeds context budget or tokenizer returned an invalid count")
        started = time.monotonic()
        result = self.post(self.base_url + "/chat/completions", {
            "model": self.name, "messages": messages, "temperature": 0,
            "max_tokens": MAX_OUTPUT_TOKENS, "response_format": {
                "type": "json_schema", "json_schema": {"name": "episode_preparation", "schema": schema}}})
        log(f"Inference completed: {count} input tokens, {time.monotonic() - started:.1f}s")
        return result


def completion(cache, stage, prompt, payload, model):
    messages = [{"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
    schema = response_schema(stage, payload)
    key = digest(encoded({"messages": messages, "schema": schema}))
    path = cache / f"{stage}-{key}.json"
    if path.exists():
        log(f"Reusing {stage} checkpoint")
        record = json.loads(path.read_text())
    else:
        record = model.complete(messages, schema)
        # Store raw model output even if it is malformed or truncated.
        atomic_write(path, encoded(record))
    try:
        choice = record["choices"][0]
        if choice["finish_reason"] != "stop":
            raise PreparationError(f"Model completion stopped with {choice['finish_reason']!r}")
        content = json.loads(choice["message"]["content"])
    except (KeyError, IndexError, TypeError, ValueError):
        raise PreparationError("Model completion is not a valid JSON object") from None
    if not isinstance(content, dict):
        raise PreparationError("Model completion is not a JSON object")
    return content


def evaluate(report, model, output, prompts, section_limit, progress=None):
    items = report["passages"]
    by_id = {p["id"]: p for p in items}
    chosen = report["sections"][:section_limit] if section_limit else report["sections"]
    seen = set()
    report.update(status="running", questions=[], failures=[], completed_sections=0)
    save_report(output, report)
    for section in chosen:
        if progress:
            progress(report["completed_sections"], len(chosen), section["id"])
        log(f"Preparing {section['id']} ({len(section['focus_ids'])} focus passages)")
        try:
            result = completion(output / "responses", "extract", prompts["extract"], {
                "episode": report["source"]["episode"], "focus_ids": section["focus_ids"],
                "passages": [by_id[key] for key in section["passage_ids"]]}, model)
            questions = result.get("questions")
            if set(result) != {"questions"} or not isinstance(questions, list) or len(questions) > 3:
                raise PreparationError("Extraction must return a questions array with at most three candidates")
        except PreparationError as exc:
            report["failures"].append({"section": section["id"], "error": str(exc)})
            log(f"{section['id']} failed: {exc}")
            save_report(output, report)
            continue
        for number, question in enumerate(questions, 1):
            entry = {"id": f"{section['id']}-q{number}", "candidate": question,
                     "status": "rejected", "human_review": "pending"}
            report["questions"].append(entry)
            try:
                evidence = validate_question(question, section["passage_ids"], section["focus_ids"])
                normalized = re.sub(r"\W+", " ", question["question"].casefold()).strip()
                if normalized in seen:
                    entry.update(status="duplicate", error="Same question text already proposed")
                    continue
                seen.add(normalized)
                context = expand(evidence, items)
                entry["review_passage_ids"] = context
                review = completion(output / "responses", "review", prompts["review"], {
                    "candidate": question, "passages": [by_id[key] for key in context]}, model)
                # Preserve the explanation even when the review itself is invalid.
                entry["review"] = review
                passed = validate_review(review)
                entry["status"] = "needs_human_review" if passed else "rejected"
                if not passed:
                    entry["rejection_reason"] = review["reason"]
                    log(f"{entry['id']} rejected (model confidence: {review['confidence']}): "
                        f"Review checks failed: {', '.join(failed_review_checks(review))}. "
                        f"Reviewer explanation: {review['reason']}")
                else:
                    log(f"{entry['id']}: {review_status_label(entry)} (model confidence: {review['confidence']})")
            except PreparationError as exc:
                entry["error"] = str(exc)
                entry["rejection_reason"] = str(exc)
                log(f"{entry['id']} rejected: {exc}")
        report["completed_sections"] += 1
        save_report(output, report)
    report["status"] = "partial" if len(chosen) < len(report["sections"]) or report["failures"] else "needs_human_review"
    save_report(output, report)


def save_report(output, report):
    report["renderer_sha256"] = digest(Path(__file__).read_bytes())
    atomic_write(output / "report.json", encoded(report))
    source = report["source"]
    status_label = "Preparation complete" if report["status"] == "needs_human_review" else report["status"]
    lines = [f"# Episode {source['episode']} preparation", "", f"Status: **{status_label}**",
             "", f"Source commit: `{source['commit']}`", f"Transcript SHA-256: `{source['sha256']}`",
             "", f"[Original transcript]({source['transcript_url']})", "",
             "High-confidence candidates that pass review are ready for human review. "
             "Medium/low-confidence candidates that pass review need human review. "
             "This report is not an ingestion approval.", ""]
    by_id = {p["id"]: p for p in report["passages"]}
    lines.extend([f"Passages: {len(by_id)}. Sections: {len(report['sections'])}. "
                  f"Completed sections: {report.get('completed_sections', 0)}.", "",
                  "[Local source snapshot](source.md) · [Structured report](report.json)", "",
                  "## Source sections", ""])
    for section in report["sections"]:
        first = by_id[section["focus_ids"][0]]
        last = by_id[section["focus_ids"][-1]]
        lines.append(f"- {section['id']}: lines {first['start_line']}–{last['end_line']}, "
                     f"{len(section['focus_ids'])} focus passages plus neighboring context")
    lines.append("")
    for entry in report.get("questions", []):
        review = entry.get("review")
        review = review if isinstance(review, dict) else {}
        confidence = review.get("confidence")
        confidence_label = (f"{confidence.capitalize()} confidence"
                            if confidence in ("low", "medium", "high") else "Confidence not assessed")
        if entry.get("error") and confidence in ("low", "medium", "high"):
            confidence_label += " (unvalidated)"
        lines.extend([f"## {entry['id']} — {review_status_label(entry)} — {confidence_label}", ""])
        question = entry["candidate"]
        # A bad review should not hide a well-formed question or its evidence.
        try:
            validate_question(question, by_id, by_id)
            valid_question = True
        except PreparationError:
            valid_question = False
        if valid_question:
            lines.extend([question["question"], ""])
        if entry["status"] == "rejected":
            reason = entry.get("rejection_reason") or entry.get("error") or review.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                reason = "No rejection explanation was recorded in this older report."
            lines.extend([f"**Why rejected:** {reason}", ""])
            failed = failed_review_checks(review)
            if failed:
                lines.extend(["**Reviewer checks that failed:** " + ", ".join(failed), ""])
            if entry.get("error") and isinstance(review.get("reason"), str):
                lines.extend(["**Reviewer explanation (review failed validation):** " + review["reason"], ""])
                if isinstance(review.get("confidence"), str):
                    lines.extend([f"Reported confidence: {review['confidence']} (not validated).", ""])
        if entry["status"] == "needs_human_review":
            if "confidence" in review:
                review_note = ("uncalibrated; not production-approved"
                               if review_status_label(entry) == "Ready for human review"
                               else "uncalibrated; human review required")
                lines.extend([f"**Model confidence in source faithfulness: {review['confidence'].capitalize()}** "
                              f"({review_note})", "", review["confidence_reason"], ""])
            else:
                lines.extend(["**Model confidence: Not assessed** — rerun review with the confidence prompt.", ""])
        if not valid_question:
            lines.extend(["Original candidate:", "", "```json", json.dumps(question, ensure_ascii=False, indent=2), "```", ""])
            continue
        lines.extend([f"Concept: {question['concept']}", ""])
        for point in question["answer_outline"]:
            refs = ", ".join(f"[{key}]({by_id[key]['source_url']})" for key in point["passage_ids"])
            lines.append(f"- {point['claim']} ({refs})")
        for field in ("qualifications", "prerequisites"):
            lines.extend(["", f"{field.capitalize()}: " + ("; ".join(question[field]) or "None proposed")])
        if entry["status"] != "rejected" and isinstance(review.get("reason"), str):
            lines.extend(["", "Model review: " + review["reason"]])
        lines.extend(["", "### Source context used for review", ""])
        for key in entry.get("review_passage_ids", []):
            passage = by_id[key]
            lines.extend([f"[{key}]({passage['source_url']})", "",
                          "\n".join("> " + line for line in passage["text"].splitlines()), ""])
    if report.get("failures"):
        lines.extend(["## Failed sections", "", json.dumps(report["failures"], indent=2), ""])
    atomic_write(output / "report.md", "\n".join(lines).encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--episode", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true", help="Parse source without calling inference")
    parser.add_argument("--limit-sections", type=int, default=0, help="Process only the first N sections; report stays partial")
    parser.add_argument("--base-url", default=DEFAULT_URL)
    parser.add_argument("--model", default="local-llm")
    parser.add_argument("--model-revision", default="unspecified", help="Record the deployed weights revision; change it to invalidate checkpoints")
    auth = parser.add_mutually_exclusive_group()
    auth.add_argument("--token-file", type=Path)
    auth.add_argument("--oc-context", help="Read the logged-in oc token into memory; never persist it")
    args = parser.parse_args()
    if args.limit_sections < 0:
        raise PreparationError("Section limit cannot be negative")
    validate_endpoint(args.base_url)
    source, text, body_start = read_source(args.repo, args.revision, args.episode)
    items = passages(source, text, body_start)
    prompts = {name: (DIRECTORY / f"{name}.txt").read_text() for name in ("extract", "review")}
    manifest = {"pipeline_version": VERSION, "pipeline_sha256": digest(Path(__file__).read_bytes()),
                "source": source, "max_passage_chars": MAX_PASSAGE,
                "max_section_chars": MAX_SECTION, "context_limit": CONTEXT_LIMIT,
                "max_output_tokens": MAX_OUTPUT_TOKENS, "temperature": 0,
                "model": args.model, "model_revision": args.model_revision, "base_url": args.base_url,
                "prompt_hashes": {key: digest(value.encode()) for key, value in prompts.items()}}
    manifest_path = args.output / "manifest.json"
    if manifest_path.exists():
        if json.loads(manifest_path.read_text()) != manifest:
            raise PreparationError("Output belongs to a different source, model, or pipeline; choose a new output directory")
    elif args.output.exists() and any(args.output.iterdir()):
        raise PreparationError("Output directory is not empty and has no matching manifest")
    atomic_write(manifest_path, encoded(manifest))
    atomic_write(args.output / "source.md", text.encode())
    report = {"manifest": manifest, "source": source, "status": "prepared", "passages": items,
              "sections": sections(items), "questions": [], "failures": []}
    log(f"Episode {args.episode} at {source['commit']}: {len(items)} passages, {len(report['sections'])} sections")
    if args.prepare_only:
        if not (args.output / "report.json").exists():
            save_report(args.output, report)
    else:
        if args.token_file:
            token = args.token_file.read_text().strip()
        elif args.oc_context:
            try:
                token = subprocess.check_output(["oc", "--context", args.oc_context, "whoami", "-t"],
                                                stderr=subprocess.PIPE, text=True).strip()
            except subprocess.CalledProcessError:
                raise PreparationError("Unable to read logged-in token from the requested oc context") from None
        else:
            raise PreparationError("Use --token-file or --oc-context for model access, or --prepare-only")
        model = Model(args.base_url, args.model, token)
        evaluate(report, model, args.output, prompts, args.limit_sections)
    log(f"Report: {args.output / 'report.md'}")
    return 1 if report["status"] == "partial" else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (PreparationError, OSError, ValueError) as error:
        log(f"Preparation failed: {error}")
        sys.exit(1)
