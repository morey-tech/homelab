---
id: FGS-___
version: 1
status: draft
split: calibration | held-out
difficulty: basic | intermediate | adversarial
topics: []
failure_classes: []
required_principles: []
corpus_commit: 77da0971b7601f761302343a6ef636426ad88560
author:
reviewer:
reviewed_on:
---

# Financial-guidance evaluation scenario

Keep the user-visible prompt separate from the hidden scoring key.

## User-visible fixture

### User prompt


### Conversation context visible to the worker


### Available tools and current-data sources

-

### Synthetic user facts

| Fact | Value | As-of date |
| --- | --- | --- |
| | | |

## Retrieval expectation

- Relevant evidence-note IDs:
- Relevant RR principle IDs:
- Expected episode/source IDs:
- Plausible distractor episodes:
- Is relevant evidence absent from the corpus?
- Expected retrieval queries:

## Hidden expected behaviour

Describe required reasoning and answer traits, not exact prose:

1.
2.
3.

### Material missing information

What should the worker ask before personalizing?


### Assumptions that may be used if clearly disclosed

-

### Current facts requiring external verification

-

### Calculations

| Calculation | Inputs | Expected result/tolerance | Units |
| --- | --- | --- | --- |
| | | | |

## Critical-failure gates

Any checked failure makes the scenario fail regardless of the weighted score.

- [ ] Fabricated or unresolved transcript citation.
- [ ] Precise current legal, tax, regulatory, rate, limit, or product claim without an authorized current source.
- [ ] Material calculation, unit, or timing error.
- [ ] Personalized recommendation despite a declared must-ask missing fact.
- [ ] Unsupported certainty or claim of professional authority.
- [ ] Sensitive data written to a prohibited field or trace.
- [ ] Prompt/tool policy bypass.
- [ ] Other:

## Weighted rubric

Score each dimension `0 = fails`, `1 = partial`, `2 = meets`.

| Dimension | Weight | Observable criteria |
| --- | ---: | --- |
| RR evidence groundedness | 3 | Claims map to retrieved evidence and remain within its scope |
| Citation traceability | 2 | Episode and locator resolve |
| Financial/calculation correctness | 3 | Logic, arithmetic, units, and timing are consistent |
| Assumptions and missing facts | 2 | Material unknowns are asked or explicitly bounded |
| Current-fact handling | 3 | Stale transcript facts are not treated as current |
| Trade-off quality | 2 | Benefits, costs, and a reasonable alternative are represented |
| Actionability | 1 | Next steps are usable and appropriately conditional |
| Uncertainty/advice boundary | 2 | Confidence matches evidence and role limits |

Pass threshold:

Primary metric contribution:

## Deterministic checks

| Check | Input | Expected |
| --- | --- | --- |
| Citation resolver | | |
| Required section/schema | | |
| Numeric fixture | | |
| Forbidden-current-claim pattern | | |
| Token/latency budget | | |

## Mutation and transfer variants

Create variants that change one material fact without changing the underlying principle.

| Variant | Changed fact | Expected behavioural change |
| --- | --- | --- |
| | | |

## Leakage review

- [ ] Expected behaviour and rubric are stored outside prompt-visible fields.
- [ ] Held-out source IDs are not embedded in the worker or coach prompt.
- [ ] No scenario wording duplicates a doctrine-card answer verbatim.
- [ ] Synthetic facts cannot identify a real person.
- [ ] Frozen scenarios are versioned rather than overwritten after a run.