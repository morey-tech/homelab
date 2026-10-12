#!/usr/bin/env python3
"""Materialize draft evaluation inputs from pinned transcripts; no inference calls."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare import PreparationError, digest, encoded, expand, passages, read_source
from retrieve import select_reports


def build(repo, seed_path, reports=()):
    raw = seed_path.read_bytes()
    seed = json.loads(raw)
    sources, texts, passage_sets = {}, {}, {}
    for episode in seed["episodes"]:
        source, text, start = read_source(repo, seed["source_revision"], episode)
        sources[episode], texts[episode] = source, text
        passage_sets[episode] = passages(source, text, start)

    queries, evidence = [], []
    for group in seed["groups"]:
        episode = group["episode"]
        text, items = texts[episode], passage_sets[episode]
        evidence_ids = set()
        for anchor in group["anchors"]:
            if text.count(anchor) != 1:
                raise PreparationError(f"{group['id']}: evidence anchor must match exactly once")
            start = text.index(anchor)
            evidence_ids.update(p["id"] for p in items
                                if p["start_char"] < start + len(anchor) and p["end_char"] > start)
        context_ids = expand(evidence_ids, items)
        evidence.append({"group_id": group["id"], "source": sources[episode],
                         "evidence_ids": sorted(evidence_ids),
                         "must_preserve": group["must_preserve"],
                         "passages": [p for p in items if p["id"] in context_ids]})
        for query in group["queries"]:
            queries.append({**query, "group_id": group["id"], "split": "development",
                            "label_status": "draft_pending_human_review",
                            "expected_behavior": "retrieve_supporting_or_corrective_context",
                            "episode": episode, "source_evidence_ids": sorted(evidence_ids),
                            "record_judgments": None})
    for query in seed["negative_queries"]:
        queries.append({**query, "split": "development",
                        "label_status": "draft_pending_human_review",
                        "expected_behavior": "no_supported_answer",
                        "source_evidence_ids": [], "record_judgments": None})
    if len({q["id"] for q in queries}) != len(queries):
        raise PreparationError("Duplicate query IDs")

    selection = select_reports(reports) if reports else None
    if selection:
        for report in selection["reports"]:
            source = report["source"]
            if source["episode"] not in sources or source != sources[source["episode"]]:
                raise PreparationError("Report source differs from the evaluation snapshot")
    bundle = {"schema_version": 1, "status": "draft_not_scorable",
              "seed_sha256": digest(raw), "sources": list(sources.values()),
              "builder_sha256": digest(Path(__file__).read_bytes()),
              "parser_sha256": digest((Path(__file__).resolve().parents[1] / "prepare.py").read_bytes()),
              "queries": queries, "evidence": evidence,
              "selection_sha256": digest(encoded(selection)) if selection else None,
              "record_count": len(selection["records"]) if selection else 0,
              "remaining_gates": ["Review query intent and source context",
                                  "Freeze eligible teaching-question selection" if selection is None
                                  else "Check corpus coverage for every query",
                                  "Assign and approve record-level relevance judgments",
                                  "Add independent held-out query groups before model selection"]}
    return bundle, texts, selection


def render(bundle):
    lines = ["# Draft embedding evaluation inputs", "", "Development only; not a scored benchmark.", "",
             f"Queries: {len(bundle['queries'])}; eligible corpus records: {bundle['record_count']}.", ""]
    evidence = {e["group_id"]: e for e in bundle["evidence"]}
    for query in bundle["queries"]:
        lines.extend([f"## {query['id']} ({query['kind']})", "", query["text"], "",
                      f"Expected behavior: {query['expected_behavior']}. Labels: pending human review.", ""])
        group = evidence.get(query["group_id"])
        if group:
            lines.extend(["Context requirements:", "", *[f"- {s}" for s in group["must_preserve"]], ""])
            for passage in group["passages"]:
                lines.extend([f"[{passage['id']}]({passage['source_url']})", "",
                              "\n".join("> " + line for line in passage["text"].splitlines()), ""])
        else:
            lines.extend([query["reason"], ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--seed", type=Path, default=Path(__file__).with_name("seed-queries.json"))
    parser.add_argument("--report", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise PreparationError("Use a new output directory; evaluation artifacts are immutable snapshots")
    bundle, texts, selection = build(args.repo, args.seed, args.report)
    args.output.mkdir(parents=True)
    for episode, text in texts.items():
        (args.output / f"episode-{episode}.md").write_bytes(text.encode("utf-8"))
    (args.output / "inputs.json").write_bytes(encoded(bundle))
    (args.output / "review.md").write_text(render(bundle))
    if selection is not None:
        (args.output / "selection.json").write_bytes(encoded(selection))
    print(f"Prepared {len(bundle['queries'])} draft queries and {bundle['record_count']} corpus records in {args.output}")
    print("Not scorable until record-level relevance judgments are reviewed and frozen.")


if __name__ == "__main__":
    try:
        main()
    except (PreparationError, OSError, ValueError, KeyError) as exc:
        print(f"Evaluation input preparation failed: {exc}", file=sys.stderr)
        sys.exit(1)
