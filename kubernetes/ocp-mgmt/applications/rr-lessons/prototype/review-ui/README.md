# Teaching-question review UI

This directory is the interactive local demo. The [container deployment](../../review/README.md)
reuses its UI assets with an empty SQLite-backed inbox. The cluster does not receive
`sample.json` or this directory's demo `runtime.json`; the HTTP service selects
server mode and hides demo review/export controls. Backend ingestion and deployed
review writes are separate follow-up work.

Serve the MVP from the homelab repository root:

```bash
python3 -m http.server 8765 --bind 127.0.0.1 \
  --directory kubernetes/ocp-mgmt/applications/rr-lessons/prototype/review-ui
```

Open [the review inbox](http://127.0.0.1:8765). In a remote IDE such as DevSpaces,
forward port **8765** and open the forwarded address. Keep using that address:
browser storage is tied to the origin. Stop the server with Ctrl+C when finished.
The UI needs a modern browser; no build, npm install, model endpoint, or database
is required. Opening `index.html` directly does not load the JSON fixture.

## Try one intake

1. Enter your reviewer name and choose **Start reviewing**.
2. Read the exact transcript passages first, with neighboring context shown by
   default. Source links open the immutable episode file at its cited lines.
   The inbox and review page withhold the question, concept title, confidence,
   and assistant recommendation until you check **I've reviewed the supporting
   evidence and context**. This records your acknowledgment; it cannot verify
   that you read or understood the passages.
3. Compare the newly revealed question, answer outline, and assistant's notes
   with the evidence. **Revisit supporting evidence** returns to the source.
   Edit the draft if needed; the first example offers **Use this draft** for a
   suggested correction. Edits clear grades and comparison/scope checks while
   preserving the source-reading acknowledgment.
4. Grade **Source support** and **Teaching value**. Separately confirm **The
   supporting evidence matches this question and answer outline** when supported,
   then choose a decision. The highlighted requirements list updates as you work:

   | Decision | Required | Result |
   |----------|----------|--------|
   | Approve & continue | Reviewer name, complete question and outline, strong source support, clear teaching value, source-reading acknowledgment, evidence-match confirmation, and scope check | Saves an approval and opens the next pending question |
   | Request changes | Source-reading acknowledgment, reviewer name, and explanatory note | Records the requested correction and opens the next pending question |
   | Exclude | Source-reading acknowledgment, reviewer name, and explanatory note | Records why the question should be left out and opens the next pending question |

5. Open **Reviewed** to revisit decisions. **Reopen for review** clears grades and
   checks and returns to the evidence-first step before allowing a new decision.
   Unchecking the source-reading acknowledgment also hides the draft and clears
   comparison checks. Finish with **Export decisions**.

Strong support means every substantive claim is supported by the displayed source
and its necessary context. Partial support means the idea may be salvageable but
needs correction. Unsupported means the evidence or premise does not hold. Clear
teaching value means the question has a useful, focused learning point. The model's
confidence and the assistant's recommendation are suggestions; neither checks a
box or approves a question for you.

## Example provenance

`sample.json` contains three curated examples from the episode 428 review
conversation: one to correct, one with no material issue found in the first pass,
and one with a mistaken healthcare premise to exclude. It is a workflow fixture,
**not an import of the complete generated report**. The earlier temporary report
was unavailable when this UI was built.

Questions and outlines preserve those reviewed examples. Qualifications, first-pass
notes, selected source passages, and a suggested correction are curated for this
demo. The episode card uses an editorial label rather than claiming the podcast's
official title. Speaker labels are parser hints and should be checked against the
source. The sample's section/question IDs refer to the original examples; reviewing
one candidate does not approve all other candidates in its section.

Transcript passages are taken programmatically from episode 428 at rr-scraper commit
`8b0c3b7570d217d5296ac6dd81f10042d120c5c9`, using the existing preparation parser.
They retain exact text, character offsets, line numbers, stable passage IDs, source
hash, and immutable source URLs. Rebuild from a clone containing that commit:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  kubernetes/ocp-mgmt/applications/rr-lessons/prototype/review-ui/build_sample.py \
  --repo /projects/rr-scraper
```

The bundle ID includes a digest of the fixture content. Changed questions, source,
or notes therefore receive a separate browser-storage key; saved decisions from a
different intake cannot be restored onto them.

## Saving and the manual backend boundary

Progress saves to `localStorage` after edits and decisions. If storage is blocked,
the UI warns that progress is only in memory; export still works. Clearing browser
data removes the local copy. This is a single-reviewer prototype: use one tab at a
time, and export before switching browsers or changing the preview address.

**Export decisions** downloads JSON containing the fixture ID, source provenance,
question and outline edits, grades, checkboxes, notes, reviewer name, decision time,
and original question/passage IDs. **Restore an export** replaces local progress
after validating the same intake ID and required decision fields. The name is an
attribution field, not an authenticated identity, and exports are editable files.

Review state and exports now use schema version 2, with separate `sourceChecked`
and `materialChecked` confirmations. Version 1 browser progress and exports are
upgraded: drafts and notes remain, previous records are retained as
`previousReview`, and the current decisions return to pending so the new sequence
is completed explicitly. The UI displays a notice when older reviews need this
fresh pass; an earlier approval does not count as the new evidence-match check.

An `approved` status is scoped to this UI experiment. Exports explicitly retain
`approvalScope: prototype_review` and `productionApproved: false`. They are not
accepted as production approvals or ingestion commands by `prepare.py` or
`retrieve.py`. Reopening replaces the current decision; this MVP has no audit log.

In local demo mode, the UI loads the bundled sample and keeps the browser workflow
described above. In [deployed server mode](../../review/README.md), the same assets
provide an episode-number intake button, background preparation, and SQLite-backed
review decisions. Automatic episode discovery, authentication, and publication to
LanceDB remain future work. The daily lessons CronJob is unchanged.

## Local validation

Run the state-transition and export-validation tests with Node.js 22+:

```bash
node kubernetes/ocp-mgmt/applications/rr-lessons/prototype/review-ui/test-state.mjs
node --check kubernetes/ocp-mgmt/applications/rr-lessons/prototype/review-ui/app.js
```

For a browser smoke test, verify that the question and assistant notes are absent
until the source-reading checkbox is checked. Make a decision of each kind, reload
the page, reopen and
edit an approved question, export/restore the decisions, and check the layout at a
phone width. Check that approval is disabled until all required fields are complete,
editing clears comparison checks but preserves reading acknowledgment, and restoring
a file from another intake is rejected.
