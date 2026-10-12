export const decisions = ['pending', 'approved', 'changes_requested', 'excluded'];

export function newState(bundle) {
  return {schemaVersion: 2, bundleId: bundle.id, reviewer: '', records: {}};
}

export function newReview(question) {
  return {question: question.question, outline: [...question.outline], evidence: '', teaching: '',
    scopeChecked: false, sourceChecked: false, materialChecked: false, notes: '', status: 'pending', updatedAt: null,
    decidedAt: null, reviewedBy: null, approvalScope: 'prototype_review', productionApproved: false};
}

export function approvalProblems(review, reviewer) {
  const problems = [];
  if (!reviewer.trim()) problems.push('Add your reviewer name.');
  if (!review.question.trim() || !review.outline.length || review.outline.some(x => !x.trim())) problems.push('Complete the question and answer outline.');
  if (review.evidence !== 'strong') problems.push('Confirm strong source support.');
  if (review.teaching !== 'clear') problems.push('Confirm a clear teaching point.');
  if (!review.scopeChecked) problems.push('Check scope and qualifications.');
  if (!review.sourceChecked) problems.push('Review the source and context.');
  if (!review.materialChecked) problems.push('Confirm the evidence supports the question and answer outline.');
  return problems;
}

export function editReview(review, edits) {
  if (review.status !== 'pending') throw new Error('Reopen this question before editing.');
  if (!review.sourceChecked) throw new Error('Read and acknowledge the supporting evidence first.');
  return {...review, ...edits, evidence: '', teaching: '', scopeChecked: false, materialChecked: false,
    updatedAt: new Date().toISOString()};
}

export function acknowledgeSource(review, checked) {
  if (review.status !== 'pending') throw new Error('Reopen this question before changing its checks.');
  return {...review, sourceChecked: checked, materialChecked: false, evidence: '', teaching: '',
    scopeChecked: false, updatedAt: new Date().toISOString()};
}

export function decide(review, status, reviewer) {
  if (review.status !== 'pending') throw new Error('Reopen this question before changing the decision.');
  if (!decisions.includes(status) || status === 'pending') throw new Error('Choose a review decision.');
  if (!reviewer.trim()) throw new Error('Add your reviewer name.');
  if (!review.sourceChecked) throw new Error('Read and acknowledge the supporting evidence first.');
  if (status === 'approved' && approvalProblems(review, reviewer).length) throw new Error(approvalProblems(review, reviewer).join(' '));
  if (status !== 'approved' && !review.notes.trim()) throw new Error('Add a note explaining the decision.');
  return {...review, status, reviewedBy: reviewer.trim(), decidedAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(), productionApproved: false};
}

export function reopen(review) {
  return {...review, status: 'pending', reviewedBy: null, decidedAt: null, evidence: '', teaching: '',
    scopeChecked: false, sourceChecked: false, materialChecked: false, updatedAt: new Date().toISOString()};
}

export function validateState(value, bundle) {
  if (!value || ![1, 2].includes(value.schemaVersion) || value.bundleId !== bundle.id || typeof value.reviewer !== 'string'
      || !value.records || typeof value.records !== 'object' || Array.isArray(value.records)) throw new Error('This review file belongs to a different intake or has an invalid format.');
  const legacy = value.schemaVersion === 1;
  const known = new Set(bundle.questions.map(q => q.id));
  for (const [id, review] of Object.entries(value.records)) {
    if (!known.has(id) || !review || !decisions.includes(review.status)
        || typeof review.question !== 'string' || typeof review.notes !== 'string'
        || !Array.isArray(review.outline) || !review.outline.every(x => typeof x === 'string')
        || !['', 'strong', 'partial', 'unsupported'].includes(review.evidence)
        || !['', 'clear', 'needs_work'].includes(review.teaching)
        || typeof review.scopeChecked !== 'boolean' || typeof review.sourceChecked !== 'boolean'
        || (!legacy && (typeof review.materialChecked !== 'boolean' || (review.materialChecked && !review.sourceChecked)))
        || review.productionApproved !== false || review.approvalScope !== 'prototype_review') throw new Error('The review file contains an invalid question or decision.');
    if (review.status !== 'pending') {
      if (typeof review.reviewedBy !== 'string' || !review.reviewedBy.trim() || typeof review.decidedAt !== 'string'
          || !Number.isFinite(Date.parse(review.decidedAt))) throw new Error('A decision is missing its reviewer or timestamp.');
      if (!legacy && !review.sourceChecked) throw new Error('A decision is missing the source-reading acknowledgment.');
      if (review.status === 'approved' && approvalProblems(legacy ? {...review, materialChecked: true} : review, review.reviewedBy).length) throw new Error('An approval is missing its required checks.');
      if (review.status !== 'approved' && !review.notes.trim()) throw new Error('A decision is missing its explanation.');
    }
  }
  if (!legacy) return value;
  // Keep the previous review for reference, but require the new sequence explicitly.
  return {...value, schemaVersion: 2, records: Object.fromEntries(Object.entries(value.records).map(([id, review]) =>
    [id, {...reopen(review), previousReview: review}]))};
}

export function exportReview(state, bundle) {
  state = validateState(state, bundle);
  return {...state, exportedAt: new Date().toISOString(), approvalScope: 'prototype_review',
    productionApproved: false, source: bundle.source,
    records: Object.fromEntries(bundle.questions.map(q => [q.id, {
      ...(state.records[q.id] || newReview(q)),
      sourcePassageIds: q.passages.map(p => p.id), originalQuestionId: q.id,
    }]))};
}
