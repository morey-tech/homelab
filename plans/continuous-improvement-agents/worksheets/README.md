# Phase 0 authoring worksheets

These worksheets keep source evidence, domain doctrine, improvement doctrine, and evaluation fixtures separate. That separation prevents the model's generic financial or management priors from being mistaken for Rational Reminder or Spear/Kim doctrine.

## Authoring flow

| Order | Worksheet | Output |
| --- | --- | --- |
| 1 | [`transcript-evidence-note.md`](transcript-evidence-note.md) | Reviewed evidence from one RR episode/passage |
| 2 | [`rr-domain-principle-card.md`](rr-domain-principle-card.md) | A financial-planning principle supported by evidence notes |
| 3 | [`coach-doctrine-card.md`](coach-doctrine-card.md) | An operational coaching principle from the two books |
| 4 | [`financial-guidance-scenario.md`](financial-guidance-scenario.md) | A calibration or held-out RR worker evaluation |
| 5 | [`coaching-scenario.md`](coaching-scenario.md) | A coach evaluation plus an uncoached transfer task |

Copy a worksheet for every item. Suggested destination layout for the implementation:

```text
evals/
  corpus-manifest.jsonl
  evidence/RRE-###.md
  principles/RRP-###.md
  doctrine/CIC-###.md
  scenarios/domain/FGS-###.yaml
  scenarios/coaching/CIS-###.yaml
  results/
```

## ID conventions

| Prefix | Meaning |
| --- | --- |
| `RRE` | Rational Reminder evidence note |
| `RRP` | Rational Reminder domain principle |
| `CIC` | Continuous-improvement coach doctrine card |
| `FGS` | Financial-guidance scenario |
| `CIS` | Coaching/improvement scenario |
| `FC` | Failure class |

IDs are permanent. Do not recycle an ID when an item is retired.

## Human-source rule

Use two distinct passes:

1. **Source pass:** a human reads the source and completes evidence, scope, contradiction, and citation fields.
2. **Evaluation pass:** after a delay or by a second reviewer, verify that the card says no more than its evidence supports.

The model may reformat text, detect blank fields, or suggest search terms. It may not originate a doctrine claim and then search for a passage that appears to justify it.

## Freeze rules

- Pin every transcript item to a full `rr-scraper` commit SHA.
- A held-out scenario's expected behaviour, scoring key, and related transfer task are unavailable to the worker and coach.
- Do not edit a frozen scenario after seeing a run. Create a new version and preserve the original result.
- Record model, prompts, cards, retrieval configuration, corpus manifest, and evaluator versions with every run.
- Any scenario containing personal information uses synthetic or irreversibly anonymized data.

## Phase 0 target inventory

- 20 or more evidence notes.
- 10 RR domain-principle cards.
- 10 coach doctrine cards.
- 20 financial-guidance scenarios: 10 calibration and 10 held-out.
- 10 coaching scenarios with 10 related transfer tasks.
- Coverage across retrieval misses, unsupported synthesis, citations, current-fact verification, missing inputs, trade-offs, calculations, advice boundaries, coach takeover, non-transfer, context budget, and redaction.

## Definition of ready

An item is ready only when:

- all required fields are complete;
- sources resolve against the pinned corpus or licensed book notes;
- scope, exceptions, and non-goals are explicit;
- at least one foreseeable misapplication is documented;
- deterministic checks and critical-failure gates are identified where applicable;
- the item has a reviewer and review date; and
- no expected answer has leaked into a prompt-visible field.