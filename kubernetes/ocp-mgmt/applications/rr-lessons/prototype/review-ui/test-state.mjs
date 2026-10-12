import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {newState, newReview, approvalProblems, editReview, acknowledgeSource, decide, reopen, validateState, exportReview} from './state.mjs';

const bundle = JSON.parse(readFileSync(new URL('./sample.json', import.meta.url)));
const q = bundle.questions[0];
const ready = () => ({...newReview(q), evidence: 'strong', teaching: 'clear', scopeChecked: true, sourceChecked: true, materialChecked: true});

test('approval requires an actual reviewer, every check, and complete wording', () => {
  const review = ready();
  assert.equal(approvalProblems(review, 'Reviewer').length, 0);
  for (const change of [{evidence: 'partial'}, {teaching: 'needs_work'}, {scopeChecked: false}, {sourceChecked: false}, {materialChecked: false}, {question: ' '}, {outline: ['']}]) {
    assert.throws(() => decide({...review, ...change}, 'approved', 'Reviewer'));
  }
  assert.throws(() => decide(review, 'approved', ' '));
  const decided = decide(review, 'approved', 'Reviewer');
  assert.equal(decided.reviewedBy, 'Reviewer');
  assert.equal(decided.productionApproved, false);
});

test('corrections clear judgments, and final decisions require reopening', () => {
  const edited = editReview(ready(), {question: 'A narrower question?'});
  assert.equal(edited.evidence, '');
  assert.equal(edited.sourceChecked, true);
  assert.equal(edited.materialChecked, false);
  assert.equal(edited.scopeChecked, false);
  const approved = decide(ready(), 'approved', 'Reviewer');
  assert.throws(() => editReview(approved, {question: 'Changed'}));
  assert.throws(() => decide(approved, 'excluded', 'Reviewer'));
  assert.equal(reopen(approved).status, 'pending');
  assert.equal(reopen(approved).reviewedBy, null);
  assert.equal(reopen(approved).evidence, '');
});

test('changes and exclusion need an explanation, not a positive grade', () => {
  for (const status of ['excluded', 'changes_requested']) {
    assert.throws(() => decide(newReview(q), status, 'Reviewer'));
    assert.equal(decide({...newReview(q), sourceChecked: true, notes: 'Wrong population.'}, status, 'Reviewer').status, status);
  }
});

test('reading the evidence is required before editing or deciding; revoking it clears comparison checks', () => {
  assert.throws(() => editReview(newReview(q), {question: 'Premature judgment?'}));
  for (const status of ['approved', 'changes_requested', 'excluded']) {
    assert.throws(() => decide({...ready(), sourceChecked: false, notes: 'A note'}, status, 'Reviewer'));
  }
  const read = acknowledgeSource(newReview(q), true);
  assert.equal(read.sourceChecked, true);
  assert.equal(read.materialChecked, false);
  const revoked = acknowledgeSource(ready(), false);
  assert.equal(revoked.sourceChecked, false);
  assert.equal(revoked.materialChecked, false);
  assert.equal(revoked.evidence, '');
  assert.equal(reopen(ready()).sourceChecked, false);
  const state = newState(bundle);
  state.records[q.id] = {...newReview(q), materialChecked: true};
  assert.throws(() => validateState(state, bundle));
});

test('legacy progress preserves drafts and the old review but requires the evidence-first sequence', () => {
  const legacyReview = decide({...ready(), question: 'A previously edited question?', notes: 'Keep this note.'}, 'approved', 'Reviewer');
  delete legacyReview.materialChecked;
  const legacy = {...newState(bundle), schemaVersion: 1, records: {[q.id]: legacyReview}};
  const upgraded = validateState(legacy, bundle);
  const review = upgraded.records[q.id];
  assert.equal(upgraded.schemaVersion, 2);
  assert.equal(review.status, 'pending');
  assert.equal(review.sourceChecked, false);
  assert.equal(review.materialChecked, false);
  assert.equal(review.question, legacyReview.question);
  assert.equal(review.notes, legacyReview.notes);
  assert.deepEqual(review.previousReview, legacyReview);
  assert.equal(legacy.schemaVersion, 1);
  assert.deepEqual(validateState(upgraded, bundle), upgraded);
  assert.equal(exportReview(upgraded, bundle).records[q.id].previousReview.status, 'approved');
});

test('export roundtrips with provenance and rejects another intake or invalid approval', () => {
  const state = newState(bundle);
  state.reviewer = 'Reviewer';
  state.records[q.id] = decide(ready(), 'approved', state.reviewer);
  const exported = exportReview(state, bundle);
  assert.equal(Object.keys(exported.records).length, 3);
  assert.equal(exported.source.commit, bundle.source.commit);
  assert.ok(exported.records[q.id].sourcePassageIds.length);
  assert.equal(validateState(JSON.parse(JSON.stringify(exported)), bundle).records[q.id].status, 'approved');
  assert.throws(() => validateState({...exported, bundleId: 'another-snapshot'}, bundle));
  const tampered = structuredClone(exported);
  tampered.records[q.id].sourceChecked = false;
  assert.throws(() => validateState(tampered, bundle));
  const unknown = structuredClone(exported);
  unknown.records['unknown-question'] = newReview(q);
  assert.throws(() => validateState(unknown, bundle));
});
