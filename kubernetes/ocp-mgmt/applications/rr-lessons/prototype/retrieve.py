#!/usr/bin/env python3
"""Local, question-first LanceDB retrieval experiment; no deployment or publication."""

import argparse
from importlib.metadata import version
import json
import math
from pathlib import Path
import shutil
import sys
import tempfile

from prepare import PreparationError, atomic_write, digest, encoded, expand, validate_question, validate_review

MODEL = "BAAI/bge-small-en-v1.5"
REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
POLICY = "prototype_high_confidence_v1"
TABLE = "teaching_questions"


def select_reports(directories):
    """Select an experimental corpus without changing the original review decisions."""
    records, reports, excluded = {}, [], []
    for directory in directories:
        raw = (directory / "report.json").read_bytes()
        report = json.loads(raw)
        source = report["source"]
        snapshot = (directory / "source.md").read_bytes()
        manifest_raw = (directory / "manifest.json").read_bytes()
        generation_manifest = json.loads(manifest_raw)
        if digest(snapshot) != source["sha256"] or generation_manifest["source"] != source:
            raise PreparationError("Source snapshot or generation manifest does not match report")
        text = snapshot.decode("utf-8")
        by_id = {}
        for passage in report["passages"]:
            start, end = passage["start_char"], passage["end_char"]
            body = text[start:end]
            expected_id = f"e{source['episode']}-" + digest(f"{start}:{body}".encode())[:16]
            start_line = text.count("\n", 0, start) + 1
            end_line = text.count("\n", 0, end - 1) + 1
            expected_url = source["transcript_url"] + f"?plain=1#L{start_line}-L{end_line}"
            if (not 0 <= start < end <= len(text) or body != passage["text"]
                    or passage["id"] != expected_id or passage["id"] in by_id
                    or passage["start_line"] != start_line or passage["end_line"] != end_line
                    or passage["source_url"] != expected_url):
                raise PreparationError("Passage text, identity, offsets, or citation differs from source")
            by_id[passage["id"]] = passage
        reports.append({"episode": source["episode"], "report_sha256": digest(raw),
                        "manifest_sha256": digest(manifest_raw), "source": source,
                        "preparation_manifest": generation_manifest,
                        "status": report["status"], "completed_sections": report.get("completed_sections", 0),
                        "total_sections": len(report["sections"])})
        for entry in report["questions"]:
            reason = None
            review = entry.get("review", {})
            if entry["status"] != "needs_human_review" or entry.get("error"):
                reason = "Candidate did not pass preparation/review"
            elif entry.get("human_review") not in ("pending", "approved"):
                reason = "Human review state does not permit prototype selection"
            elif not isinstance(review, dict) or review.get("confidence") != "high":
                reason = "Model confidence is not high"
            else:
                try:
                    if not validate_review(review):
                        reason = "Model review checks did not pass"
                except PreparationError as exc:
                    reason = str(exc)
            if reason:
                excluded.append({"episode": source["episode"], "id": entry["id"], "reason": reason})
                continue
            candidate = entry["candidate"]
            referenced = validate_question(candidate, by_id, by_id)
            context_ids = entry.get("review_passage_ids", [])
            if (len(context_ids) != len(set(context_ids)) or not set(context_ids) <= set(by_id)
                    or not set(expand(referenced, report["passages"])) <= set(context_ids)):
                raise PreparationError("Selected candidate is missing reviewed evidence or neighboring context")
            record_id = f"e{source['episode']}-" + digest(encoded({"source": source, "entry": entry}))[:24]
            record = {"id": record_id, "candidate_id": entry["id"], "source": source,
                      "candidate": candidate, "review": review, "human_review": entry["human_review"],
                      "selection_policy": POLICY, "production_approved": False,
                      "passages": [by_id[key] for key in context_ids]}
            records[record_id] = record
    if not records:
        raise PreparationError("No eligible high-confidence candidates")
    return {"schema_version": 1, "selection_policy": POLICY, "production_approved": False,
            "reports": sorted(reports, key=lambda x: (x["episode"], x["report_sha256"])),
            "records": sorted(records.values(), key=lambda x: x["id"]),
            "excluded": sorted(excluded, key=lambda x: (x["episode"], x["id"]))}


class Embedder:
    def __init__(self):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(MODEL, revision=REVISION, device="cpu",
                                         cache_folder="/tmp/rr-embedding-models", trust_remote_code=False,
                                         model_kwargs={"use_safetensors": True})
        self.spec = {"model": MODEL, "revision": REVISION, "dimensions": 384,
                     "normalize": True, "metric": "cosine", "query_prefix": QUERY_PREFIX,
                     "document_template": "concept + newline + question", "device": "cpu",
                     "sentence_transformers": version("sentence-transformers"),
                     "transformers": version("transformers"), "torch": version("torch")}

    def encode(self, texts, query=False):
        inputs = [QUERY_PREFIX + text if query else text for text in texts]
        for text in inputs:
            tokens = self.model.tokenizer(text, truncation=False)["input_ids"]
            if len(tokens) > self.model.max_seq_length:
                raise PreparationError("Embedding input exceeds model limit; refusing silent truncation")
        return self.model.encode(inputs, normalize_embeddings=True, show_progress_bar=False).tolist()


def ingest(bundle, output, embedder):
    import lancedb
    import pyarrow as pa

    fingerprint = {"schema_version": 1, "selection_sha256": digest(encoded(bundle)),
                   "implementation_sha256": digest(Path(__file__).read_bytes()),
                   "embedding": embedder.spec, "lancedb": version("lancedb")}
    if output.exists():
        if not (output / "manifest.json").is_file():
            raise PreparationError("Output exists without an index manifest; use a new directory")
        existing = json.loads((output / "manifest.json").read_text())
        if existing != fingerprint or (output / "selection.json").read_bytes() != encoded(bundle):
            raise PreparationError("Index inputs or embedding configuration changed; use a new directory")
        table = lancedb.connect(output / "db").open_table(TABLE)
        if table.count_rows() != len(bundle["records"]):
            raise PreparationError("Index row count does not match selection")
        return {"records": table.count_rows(), "reused": True}
    texts = [item["candidate"]["concept"] + "\n" + item["candidate"]["question"]
             for item in bundle["records"]]
    vectors = embedder.encode(texts)
    if len(vectors) != len(texts):
        raise PreparationError("Embedding count does not match selection")
    if any(len(vector) != embedder.spec["dimensions"]
           or not all(math.isfinite(value) for value in vector)
           or not any(vector) for vector in vectors):
        raise PreparationError("Embedding has invalid dimensions, nonfinite values, or zero magnitude")
    rows = [{"id": item["id"], "episode": item["source"]["episode"], "text": text,
             "payload": encoded(item).decode(), "vector": vector}
            for item, text, vector in zip(bundle["records"], texts, vectors)]
    schema = pa.schema([("id", pa.string()), ("episode", pa.int64()), ("text", pa.string()),
                        ("payload", pa.string()), ("vector", pa.list_(pa.float32(), embedder.spec["dimensions"]))])
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        db = lancedb.connect(staging / "db")
        table = db.create_table(TABLE, rows, schema=schema)
        if table.count_rows() != len(rows):
            raise PreparationError("Index write did not persist all selected records")
        atomic_write(staging / "selection.json", encoded(bundle))
        atomic_write(staging / "manifest.json", encoded(fingerprint))
        del table, db
        staging.rename(output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return {"records": len(rows), "reused": False}


def search(output, query, embedder, limit=3):
    import lancedb

    if not query.strip() or not 1 <= limit <= 10:
        raise PreparationError("Provide a nonempty query and limit between 1 and 10")
    manifest = json.loads((output / "manifest.json").read_text())
    if manifest["embedding"] != embedder.spec:
        raise PreparationError("Query embedder differs from indexed embedding configuration")
    table = lancedb.connect(output / "db").open_table(TABLE)
    hits = table.search(embedder.encode([query], query=True)[0]).distance_type("cosine").limit(limit).to_list()
    return {"query": query, "selection_sha256": manifest["selection_sha256"],
            "production_approved": False,
            "note": "Nearest candidates only; distance is not confidence or proof of relevance. No answer was generated.",
            "hits": [{"distance": hit["_distance"], **json.loads(hit["payload"])} for hit in hits]}


def render(result):
    lines = ["# Prototype retrieval", "", result["query"], "", result["note"], ""]
    for hit in result["hits"]:
        candidate = hit["candidate"]
        lines.extend([f"## Episode {hit['source']['episode']} — {hit['candidate_id']}", "",
                      candidate["question"], "",
                      f"Cosine distance: {hit['distance']:.4f}. Model confidence: high (uncalibrated).",
                      "Prototype selection only; not approved for production.", "",
                      f"Source commit: `{hit['source']['commit']}`", "", "### Proposed answer outline", ""])
        by_id = {p["id"]: p for p in hit["passages"]}
        for point in candidate["answer_outline"]:
            refs = ", ".join(f"[{key}]({by_id[key]['source_url']})" for key in point["passage_ids"])
            lines.append(f"- {point['claim']} ({refs})")
        for field in ("qualifications", "prerequisites"):
            lines.extend(["", f"{field.capitalize()}: " + ("; ".join(candidate[field]) or "None proposed")])
        lines.extend(["", "### Original evidence and surrounding context", ""])
        for passage in hit["passages"]:
            lines.extend([f"[{passage['id']}]({passage['source_url']})", "",
                          "\n".join("> " + line for line in passage["text"].splitlines()), ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    index = commands.add_parser("ingest")
    index.add_argument("--report", type=Path, action="append", required=True, help="Preparation output directory; repeatable")
    index.add_argument("--output", type=Path, required=True, help="New local index directory")
    index.add_argument("--allow-prototype-high-confidence", action="store_true", required=True,
                       help="Explicitly permit model-high candidates still awaiting human review")
    query = commands.add_parser("search")
    query.add_argument("--index", type=Path, required=True)
    query.add_argument("--query", required=True)
    query.add_argument("--limit", type=int, default=3)
    query.add_argument("--output", type=Path, required=True, help="Retrieval artifact directory")
    args = parser.parse_args()
    if args.command == "ingest":
        bundle = select_reports(args.report)
        print(json.dumps(ingest(bundle, args.output, Embedder())))
    else:
        result = search(args.index, args.query, Embedder(), args.limit)
        atomic_write(args.output / "retrieval.json", encoded(result))
        atomic_write(args.output / "retrieval.md", render(result).encode())
        print(f"Retrieved {len(result['hits'])} candidates to {args.output}")


if __name__ == "__main__":
    try:
        main()
    except (PreparationError, OSError, ValueError, KeyError) as exc:
        print(f"Retrieval prototype failed: {exc}", file=sys.stderr)
        sys.exit(1)
