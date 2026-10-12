#!/usr/bin/env python3
"""Build a small review-UI fixture from immutable episode 428 source passages."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare import digest, encoded, expand, passages, read_source


REVISION = "8b0c3b7570d217d5296ac6dd81f10042d120c5c9"
EXAMPLES = [
    {
        "id": "section-001-q1", "section": "section-001", "concept": "The owners behind the wealth",
        "modelConfidence": "high", "recommendation": "revise", "estimatedMinutes": 3,
        "question": "What is the real source of wealth for most people in America, and how does it differ from common perceptions of rich individuals like tech founders or celebrities?",
        "outline": [
            "The typical wealthy person in America is not like Elon Musk, Jamie Dimon, or Taylor Swift, but rather an ordinary business owner in an unglamorous private sector industry such as auto dealerships, beverage distribution, or contracting.",
            "These 'everywhere millionaires' are often found in mundane, local businesses that serve everyday needs, and their wealth comes from private enterprise rather than celebrity, finance, or real estate."
        ],
        "qualifications": ["The discussion concerns the United States and the wealthy owners described by the guest."],
        "reviewNotes": [
            "The question says “most people in America,” but the evidence describes wealthy Americans. Narrow the population.",
            "Finance and real estate are a minority in the income breakdown, not absent. The second claim currently excludes them.",
            "Keep the distinction between income and wealth, and attribute the characterization to Owen Zidar."
        ],
        "suggestion": {
            "question": "How does Owen Zidar's description of typical wealthy Americans differ from the celebrity-and-tech-founder stereotype?",
            "outline": [
                "Zidar highlights owners of ordinary private businesses, including auto dealers, beverage distributors, and contractors.",
                "He explains that private companies and their owners often receive less public attention than celebrities or public companies.",
                "His later breakdown includes finance and real estate. That statistic concerns income among the top-income private-business owners discussed, not a breakdown of all American wealth."
            ]
        },
        "anchors": ["Owen Zidar: Most people think that the way you get rich", "So I have three young kids", "They're pretty mundane businesses", "Owen Zidar: It's definitely more Main Street."]
    },
    {
        "id": "section-008-q1", "section": "section-008", "concept": "The trade-offs of private equity",
        "modelConfidence": "high", "recommendation": "keep", "estimatedMinutes": 2,
        "question": "How can joining a private equity firm benefit a small business, and what are the potential downsides?",
        "outline": [
            "Private equity firms can provide strategic support to smaller businesses, such as shared billing providers and access to customers, based on their portfolio of similar companies.",
            "However, joining a private equity firm may lead to reduced autonomy, loss of culture, and harder decisions regarding employee retention or business direction."
        ],
        "qualifications": ["These are examples described by Zidar, not a finding that every private equity firm provides the same benefits."],
        "reviewNotes": [
            "The outline pairs operational benefits with culture, staffing, and autonomy trade-offs.",
            "The conditional language fits the examples. No material correction was identified in the assistant's first pass."
        ],
        "suggestion": None,
        "anchors": ["If you have a private equity firm that has a portfolio", "You can also benefit from knowledge", "So you need to be prepared for that.", "Maybe you lose control."]
    },
    {
        "id": "section-007-q3", "section": "section-007", "concept": "Check the topic before the lesson",
        "modelConfidence": "medium", "recommendation": "exclude", "estimatedMinutes": 2,
        "question": "Could a simple, free, and basic business ownership model improve access for small business owners?",
        "outline": [
            "A simple, basic, and free system for business ownership—without high costs, deductibles, or complex institutions—could improve access and affordability.",
            "Small business owners face significant challenges when costs rise, such as a 50% wage increase, especially when they cannot pass those costs on to customers.",
            "Large firms can self-insure and manage costs more effectively, giving them an advantage over small businesses in navigating financial risks."
        ],
        "qualifications": ["The original candidate treats the proposed model as hypothetical."],
        "reviewNotes": [
            "The source is describing healthcare reform, not a business ownership model. The premise is wrong.",
            "The daycare example concerns a 50% health-insurance cost increase. Read the preceding context before interpreting the later wording about wages.",
            "Exclude this candidate. A separate healthcare lesson could be prepared later using the correct context."
        ],
        "suggestion": None,
        "anchors": ["So I'm on the board of a daycare.", "Amy Finkelstein and Liran Einav", "Something that's simple, basic, and free.", "if you're small, you can't compete with a big firm"]
    }
]


def build(repo):
    source, text, start = read_source(repo, REVISION, 428)
    items = passages(source, text, start)
    questions = []
    for example in EXAMPLES:
        evidence = set()
        for anchor in example["anchors"]:
            if text.count(anchor) != 1:
                raise ValueError(f"Expected one source match for {anchor!r}")
            offset = text.index(anchor)
            evidence.update(p["id"] for p in items
                            if p["start_char"] < offset + len(anchor) and p["end_char"] > offset)
        context = set(expand(evidence, items))
        questions.append({k: v for k, v in example.items() if k != "anchors"} | {
            "passages": [p | {"isEvidence": p["id"] in evidence} for p in items if p["id"] in context]
        })
    bundle = {"schemaVersion": 1, "episode": 428, "guest": "Owen Zidar",
              "title": "The businesses behind everyday wealth", "titleType": "editorial_demo_label",
              "source": source, "questions": questions,
              "fixtureNote": "Three curated examples from the episode 428 review conversation, not an import of the full report. Questions and outlines preserve the reviewed examples; context, qualifications, and notes are curated for the demo. Source excerpts come from the pinned transcript.",
              "productionApproved": False}
    bundle["id"] = "episode-428-" + digest(encoded(bundle))[:20]
    return bundle


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    args = parser.parse_args()
    output = Path(__file__).with_name("sample.json")
    output.write_bytes(encoded(build(args.repo)))
    print(output)
