import {newState, newReview, approvalProblems, editReview, acknowledgeSource, decide, reopen, validateState, exportReview} from './state.mjs';

const app = document.querySelector('#app');
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const icons = {
  book: '<path d="M12 5c-3-2-6-2-9-1v15c3-1 6-1 9 1m0-15c3-2 6-2 9-1v15c-3-1-6-1-9 1V5Z"/>',
  inbox: '<path d="M4 4h16l2 11v5H2v-5L4 4Z"/><path d="M2 15h6l2 3h4l2-3h6"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  arrow: '<path d="M4 12h16m-6-6 6 6-6 6"/>',
  back: '<path d="M20 12H4m6-6-6 6 6 6"/>',
  export: '<path d="M12 3v12m-4-4 4 4 4-4M4 16v5h16v-5"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  edit: '<path d="m15 4 5 5M4 20l5-1L21 7l-5-5L4 14v6Z"/>',
  link: '<path d="M14 3h7v7m0-7L10 14M10 4H3v17h17v-7"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v1"/>',
};
const icon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.info}</svg>`;
const labels = {pending: 'To review', approved: 'Approved', changes_requested: 'Changes requested', excluded: 'Excluded'};
const recommendations = {revise: ['amber', 'Needs a correction'], keep: ['green', 'Ready for human review'], exclude: ['rose', 'Check the premise']};
let mode = 'demo', inboxData = null, inboxError = '', inboxLoading = false;
let publications = {}, publicationError = '';
let jobs = [], jobError = '', revisions = {}, saveChain = Promise.resolve(), writeBlocked = false, saving = 0, submitting = false, deciding = false, jobsInitialized = false, episodeInput = '';
let bundle, state, storageKey, storageWorking = true, storageWarning = '', view = 'inbox', filter = 'pending', activeId, editing = false, showContext = false, toastTimer;

function toast(message) {
  const node = document.querySelector('#toast');
  node.textContent = message;
  node.classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove('visible'), 5000);
}

function save() {
  if (mode === 'server') {
    if (!activeId || !state.records[activeId]) return Promise.resolve();
    const id = activeId, review = structuredClone(state.records[id]);
    saving++;
    const status = document.querySelector('#save-status');
    if (status) status.textContent = 'Saving to the workspace…';
    const operation = saveChain.then(async () => {
      if (writeBlocked) throw new Error('Saving is paused. Reload the inbox to resolve the earlier save error.');
      const result = await api(`./api/reviews/${encodeURIComponent(id)}`, {method: 'PUT', body: {revision: revisions[id] || 0, review}});
      revisions[id] = result.revision;
      if (review.status === 'approved' || publications[id]) void loadPublications();
    });
    saveChain = operation.catch(error => {
      writeBlocked = true; storageWorking = false; storageWarning = error.message;
      const warning = document.querySelector('#storage-warning');
      if (warning) { warning.hidden = false; warning.textContent = storageWarning; }
      toast(`Not saved: ${error.message}`);
    }).finally(() => {
      saving--;
      const status = document.querySelector('#save-status');
      if (status) status.textContent = writeBlocked ? 'Not saved · reload inbox' : saving ? 'Saving to the workspace…' : 'Saved to the workspace';
    });
    return operation;
  }
  try { localStorage.setItem(storageKey, JSON.stringify(state)); storageWorking = true; }
  catch { storageWorking = false; storageWarning = 'Browser storage is unavailable. Export your decisions before closing this page.'; }
  const status = document.querySelector('#save-status');
  if (status) status.textContent = storageWorking ? 'Saved in this browser' : 'Not saved · export to keep';
  const warning = document.querySelector('#storage-warning');
  if (warning) { warning.textContent = storageWarning; warning.hidden = !storageWarning; }
}

function currentQuestion() { return bundle.questions.find(q => q.id === activeId); }
function record(q) { return state.records[q.id] || newReview(q); }
function updateRecord(changes) {
  const q = currentQuestion();
  state.records[q.id] = {...record(q), ...changes, updatedAt: new Date().toISOString()};
  save(); updateApproval();
}

function shell(content) {
  const pending = bundle.questions.filter(q => record(q).status === 'pending').length;
  return `<aside class="sidebar">
    <a href="#inbox" class="brand" data-action="inbox"><span class="brand-mark">${icon('book')}</span><span>Lesson desk<small>RATIONAL REMINDER</small></span></a>
    <div class="workspace-label">YOUR WORKSPACE</div>
    <nav aria-label="Workspace">
      <button class="nav-item ${filter !== 'reviewed' ? 'active' : ''}" data-action="inbox">${icon('inbox')}<span>Review inbox</span><span class="nav-count">${pending}</span></button>
      <button class="nav-item ${filter === 'reviewed' ? 'active' : ''}" data-action="reviewed">${icon('check')}<span>Reviewed</span></button>
    </nav>
    <div class="sidebar-note"><span class="tiny-dot"></span> A thoughtful pause<br><p>Good lessons start with a careful look at the source.</p></div>
    <div class="sidebar-bottom">
      ${mode === 'server' ? `<label class="reviewer-label" for="reviewer-name">Reviewing as</label><input id="reviewer-name" placeholder="Your name" maxlength="100" value="${esc(state.reviewer)}" autocomplete="name"><div id="save-status" class="save-status">${writeBlocked ? 'Not saved · reload inbox' : saving ? 'Saving to the workspace…' : 'Saved to the workspace'}</div>` : `
      <label class="reviewer-label" for="reviewer-name">Reviewing as</label>
      <input id="reviewer-name" placeholder="Your name" maxlength="100" value="${esc(state.reviewer)}" autocomplete="name">
      <button class="nav-item" data-action="export">${icon('export')}<span>Export decisions</span></button>
      <button class="text-button small" data-action="restore">Restore an export</button>
      <button class="text-button small" data-action="guide">How this works</button>
      <div id="save-status" class="save-status">${storageWorking ? 'Saved in this browser' : 'Not saved · export to keep'}</div>`}
    </div>
  </aside>
  <div class="workspace"><header class="topbar"><span>Transcript → teaching question → human review</span><span class="prototype-badge">${mode === 'server' ? 'Review workspace' : 'Workflow prototype'}</span></header>
  ${Object.values(state.records).some(r => r.previousReview && r.status === 'pending') ? '<div class="storage-warning">Earlier review progress has been retained, but the evidence-first workflow requires a fresh review. Your previous decisions are preserved in the export.</div>' : ''}
  <div id="storage-warning" class="storage-warning" role="alert" ${storageWarning ? '' : 'hidden'}>${esc(storageWarning)}</div>
  <main id="main" tabindex="-1">${content}</main></div>
  <dialog id="guide" aria-labelledby="guide-title"><form method="dialog"><button class="dialog-close" aria-label="Close guide">×</button></form>
    <span class="eyebrow">A SMALL, MANUAL INTAKE</span><h2 id="guide-title">From a good question<br>to a trustworthy lesson.</h2>
    <ol class="guide-steps"><li><strong>Read the evidence first.</strong> The draft stays hidden until you confirm you’ve read the source and context.</li><li><strong>Compare the draft.</strong> Read the revealed question, outline, and assistant’s notes. Check each claim against the evidence.</li><li><strong>Make a decision.</strong> Grade support and clarity, confirm whether the evidence matches the material, then approve, request changes, or exclude.</li></ol>
    <p>This demo has three curated questions from episode 428. Approvals are local review decisions. Nothing is published or added to the database.</p><p>Progress stays in this browser on this address. Export decisions to keep a portable copy or move to another browser.</p>
    <button class="button primary" data-action="close-guide">Got it</button>
  </dialog>
  <dialog id="restore-dialog" aria-labelledby="restore-title"><h2 id="restore-title">Restore saved decisions?</h2><p>This replaces the progress for this example intake in this browser. Export your current decisions first if you want to keep them.</p><div class="button-row"><button class="button secondary" data-action="cancel-restore">Cancel</button><button class="button primary" data-action="confirm-restore">Choose review file</button></div></dialog>`;
}

async function loadInbox() {
  inboxLoading = true; inboxError = ''; render();
  try {
    const response = await fetch('./api/inbox', {cache: 'no-store'});
    if (!response.ok) throw new Error('The inbox could not be loaded. Try again shortly.');
    const value = await response.json();
    if (value.apiVersion !== 1 || value.reviewEnabled !== true ||
        !['episodes', 'sections', 'questions', 'reviews'].every(key => Number.isSafeInteger(value.counts?.[key]) && value.counts[key] >= 0)) {
      throw new Error('The inbox response is not supported by this UI.');
    }
    inboxData = value;
    bundle = value.bundle;
    state = {...newState(bundle), reviewer: state.reviewer, records: value.records};
    revisions = value.revisions;
    writeBlocked = false; storageWorking = true; storageWarning = '';
  } catch (error) { inboxError = error.message; inboxData = null; }
  finally { inboxLoading = false; render(); }
}

async function api(url, options = {}) {
  const response = await fetch(url, {cache: 'no-store', ...options,
    headers: options.body ? {'Content-Type': 'application/json'} : {},
    body: options.body ? JSON.stringify(options.body) : undefined});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'The workspace request failed.');
  return result;
}

function publicationCard(q, r) {
  if (mode !== 'server' || !r.sourceChecked) return '';
  const p = publications[q.id];
  if (!p && r.status !== 'approved' && !publicationError) return '';
  const index = p?.action === 'index';
  const label = !p ? 'Not indexed yet' : p.status === 'complete' ? (index ? 'Indexed for retrieval' : 'Removed from retrieval')
    : p.status === 'failed' ? (index ? 'Indexing failed' : 'Index removal failed')
    : p.status === 'processing' ? (index ? 'Indexing approved wording…' : 'Removing from index…')
    : index ? (p.attempts ? 'Waiting to retry indexing' : 'Queued for indexing') : 'Queued for index removal';
  return `<section class="publication-card" aria-live="polite"><strong>${esc(label)}</strong>
    <p>${p && !index ? 'This question is ineligible for retrieval while its approval is withdrawn.' : 'Only the approved question and answer outline are made available for retrieval. No lesson is sent to Discord.'}</p>
    ${publicationError ? `<p class="ingestion-error">${esc(publicationError)}</p>` : ''}
    ${p?.error ? `<p class="ingestion-error">${esc(p.error)}</p>` : ''}
    ${(!p && r.status === 'approved') || p?.status === 'failed' ? `<button class="button secondary" data-publish="${esc(q.id)}">${p ? 'Retry index update' : 'Index approved question'}</button>` : ''}</section>`;
}

async function loadPublications() {
  try {
    const result = await api('./api/publications');
    publications = Object.fromEntries(result.publications.map(p => [p.question_id, p]));
    publicationError = '';
  } catch (error) { publicationError = `Indexing status unavailable: ${error.message}`; }
  document.querySelectorAll('[data-publication-for]').forEach(node => {
    const q = bundle.questions.find(q => q.id === node.dataset.publicationFor);
    if (q) node.innerHTML = publicationCard(q, record(q));
  });
}

function jobList() {
  return `${jobError ? `<p role="alert" class="ingestion-error">${esc(jobError)}</p>` : ''}${jobs.length ? `<h3>Episode preparation</h3><ul class="ingestion-jobs">${jobs.slice(0, 10).map(job => `<li><div><strong>Episode ${job.episode}</strong><span class="pill ${job.status === 'failed' ? 'rose' : job.status === 'complete' ? 'green' : 'neutral'}">${esc(job.status)}</span><p>${esc(job.phase)}${job.total ? ` · ${job.completed}/${job.total}` : ''}</p>${job.error ? `<p class="ingestion-error">${esc(job.error)}</p>` : ''}${job.source_commit ? `<small>Source commit: ${esc(job.source_commit.slice(0, 12))}</small>` : ''}</div>${job.status === 'failed' ? `<button class="button secondary" data-retry="${job.episode}">Retry episode ${job.episode}</button>` : ''}</li>`).join('')}</ul>` : '<p class="muted">No episodes have been queued yet.</p>'}`;
}

async function loadJobs() {
  try {
    const previous = jobs.filter(j => j.status === 'complete').map(j => j.id).join();
    jobs = (await api('./api/ingestions')).jobs; jobError = '';
    if (jobsInitialized && previous !== jobs.filter(j => j.status === 'complete').map(j => j.id).join() && view === 'inbox' && !saving && !submitting && !writeBlocked) await loadInbox();
    jobsInitialized = true;
  } catch (error) { jobError = `Could not check preparation progress: ${error.message}`; }
  const node = document.querySelector('#ingestion-jobs');
  if (node) node.innerHTML = jobList();
  await loadPublications();
}

async function ingest(episode) {
  if (submitting) return;
  submitting = true;
  const button = document.querySelector('#ingest-submit');
  if (button) button.disabled = true;
  try {
    const job = await api('./api/ingestions', {method: 'POST', body: {episode}});
    toast(`Episode ${episode}: ${job.status}. You can leave this page while it prepares.`);
    await loadJobs();
  } catch (error) { jobError = error.message; toast(error.message); }
  finally {
    submitting = false;
    if (button) button.disabled = false;
    const node = document.querySelector('#ingestion-jobs');
    if (node) node.innerHTML = jobList();
  }
}

function serverInbox() {
  const visible = bundle.questions.filter(q => filter === 'all' || (filter === 'reviewed' ? record(q).status !== 'pending' : record(q).status === 'pending'));
  return `<section class="page-heading"><span class="eyebrow">EVIDENCE FIRST. THOUGHTFUL REVIEW.</span><h1>Review inbox<span class="heading-dot">.</span></h1><p>Prepare an episode, then review one question and its evidence at a time.</p></section>
    <section class="paper-card ingestion-card"><h2>Ingest an episode</h2><p>Fetch the transcript and prepare teaching questions with their supporting evidence for your review.</p><form id="ingest-form"><label class="field-label" for="episode-number">Episode number<input id="episode-number" name="episode" type="number" min="1" max="99999" step="1" required placeholder="428" value="${esc(episodeInput)}"></label><button id="ingest-submit" class="button primary" type="submit" ${submitting ? 'disabled' : ''}>Ingest episode ${icon('arrow')}</button></form><p class="small muted">Runs in the background. Questions appear when the entire intake is ready. Nothing is sent to Discord.</p><div id="ingestion-jobs" aria-live="polite">${jobList()}</div></section>
    <div class="section-heading"><h2>Prepared questions</h2><button class="button secondary" data-action="refresh-inbox" ${inboxLoading ? 'disabled' : ''}>Refresh inbox</button></div>
    ${inboxError ? `<p class="ingestion-error" role="alert">${esc(inboxError)}</p>` : ''}
    <div class="list-toolbar"><div class="tabs" role="group" aria-label="Filter questions">${['pending', 'reviewed', 'all'].map(f => `<button class="${filter === f ? 'selected' : ''}" data-filter="${f}">${f === 'pending' ? 'To review' : f === 'all' ? 'All questions' : 'Reviewed'}</button>`).join('')}</div><span class="muted">${inboxData?.counts.episodes ?? '—'} episodes · ${bundle.questions.length} questions</span></div>
    <div class="question-list">${visible.length ? visible.map(q => {
      const r = record(q), revealed = r.sourceChecked;
      return `<button class="question-row" data-open="${esc(q.id)}"><span class="row-icon neutral">${icon('book')}</span><span class="row-copy"><span class="row-section">EPISODE ${q.episode} · ${esc(q.section)}</span><strong>${revealed ? esc(q.concept) : 'Read supporting evidence'}</strong><span class="row-preview">${revealed ? esc(r.question) : 'The question stays hidden until you have read the source.'}</span></span><span class="pill neutral">${esc(labels[r.status])}</span><span class="row-arrow">${icon('arrow')}</span></button>`;
    }).join('') : `<div class="empty-state"><h3>${inboxLoading ? 'Loading questions…' : inboxError ? 'Inbox unavailable' : 'No questions in this view yet'}</h3><p>Completed episode intakes will appear here for review.</p></div>`}</div>`;
}

document.addEventListener('submit', event => {
  if (event.target.id !== 'ingest-form') return;
  event.preventDefault();
  void ingest(Number(document.querySelector('#episode-number').value));
});
document.addEventListener('click', async event => {
  const publication = event.target.closest('[data-publish]');
  if (publication) {
    publication.disabled = true;
    try {
      await saveChain;
      await api(`./api/publications/${encodeURIComponent(publication.dataset.publish)}`, {method: 'POST', body: {}});
      await loadPublications();
      toast('Index update queued.');
    } catch (error) { toast(error.message); publication.disabled = false; }
    return;
  }
  const button = event.target.closest('[data-retry]');
  if (button) void ingest(Number(button.dataset.retry));
});

function inbox() {
  const pending = bundle.questions.filter(q => record(q).status === 'pending');
  const approved = bundle.questions.filter(q => record(q).status === 'approved').length;
  const reviewed = bundle.questions.length - pending.length;
  const visible = bundle.questions.filter(q => filter === 'all' || (filter === 'reviewed' ? record(q).status !== 'pending' : record(q).status === 'pending'));
  return `<section class="page-heading"><span class="eyebrow">A LITTLE REVIEW. A BETTER LESSON.</span><h1>Review inbox<span class="heading-dot">.</span></h1><p>Turn podcast ideas into lessons you can trust.<br>One question, and its evidence, at a time.</p></section>
    <div class="overview"><div><span class="metric">${pending.length}</span><span>questions waiting</span></div><div><span class="metric">${approved}</span><span>approved for this prototype</span></div><div class="progress-metric"><span class="metric">${reviewed}<span class="metric-total"> / ${bundle.questions.length}</span></span><span>review decisions made</span><progress value="${reviewed}" max="${bundle.questions.length}" aria-label="Review progress"></progress></div></div>
    <div class="section-heading"><h2>Your latest intake</h2><span class="muted">Curated sample · 3 questions</span></div>
    <article class="episode-card"><div class="episode-art" aria-hidden="true"><span>RATIONAL<br>REMINDER</span><strong>428</strong><div class="art-lines"></div></div><div class="episode-copy"><span class="eyebrow">EPISODE 428 · OWEN ZIDAR</span><h2>The businesses behind<br>everyday wealth</h2><p>Private businesses, ownership, and the details that change a lesson.</p><div class="episode-meta">${icon('book')}<span>3 source sections</span>${icon('clock')}<span>About 7 minutes to review</span></div></div><button class="button primary" data-action="resume">${pending.length ? (reviewed ? 'Continue reviewing' : 'Start reviewing') : 'View decisions'} ${icon('arrow')}</button></article>
    <div class="list-toolbar"><div class="tabs" role="group" aria-label="Filter questions"><button class="${filter === 'pending' ? 'selected' : ''}" data-filter="pending">To review <span>${pending.length}</span></button><button class="${filter === 'reviewed' ? 'selected' : ''}" data-filter="reviewed">Reviewed <span>${reviewed}</span></button><button class="${filter === 'all' ? 'selected' : ''}" data-filter="all">All questions</button></div><span class="muted small">Evidence first · your judgment</span></div>
    <div class="question-list">${visible.length ? visible.map(q => {
      const r = record(q), [tone, recommendation] = recommendations[q.recommendation], revealed = r.sourceChecked;
      return `<button class="question-row" data-open="${esc(q.id)}"><span class="row-icon ${!revealed ? 'neutral' : r.status === 'pending' ? tone : 'green'}">${icon(r.status === 'pending' ? 'book' : 'check')}</span><span class="row-copy"><span class="row-section">${esc(q.section.replace('section-', 'SECTION '))}</span><strong>${revealed ? esc(q.concept) : `Source review ${bundle.questions.indexOf(q) + 1}`}</strong><span class="row-preview">${revealed ? esc(r.question) : 'Read the supporting evidence before opening the question.'}</span></span><span class="pill ${!revealed ? 'neutral' : r.status === 'pending' ? tone : r.status === 'approved' ? 'green' : 'neutral'}">${!revealed ? 'Read evidence first' : r.status === 'pending' ? recommendation : labels[r.status]}</span><span class="row-arrow">${icon('arrow')}</span></button>`;
    }).join('') : `<div class="empty-state">${icon('check')}<h3>${filter === 'reviewed' ? 'Your decisions will appear here.' : 'You’re through this intake.'}</h3><p>${filter === 'reviewed' ? 'Open a question to begin your first review.' : 'Export your work, or open Reviewed to revisit a decision.'}</p></div>`}</div>
    <p class="page-footnote">This is a three-question preview of the workflow. New episode processing will connect here later.</p>`;
}

function evidenceCard(q, r) {
  const locked = r.status !== 'pending';
  const evidence = q.passages.filter(p => showContext || p.isEvidence);
  return `<aside id="supporting-evidence" tabindex="-1" class="paper-card evidence-card ${r.sourceChecked ? '' : 'evidence-first'}" aria-label="Supporting evidence"><div class="card-heading"><div><span class="eyebrow">STEP 1 · READ THE SOURCE</span><h2>Supporting evidence</h2></div><span class="source-count">${q.passages.filter(p => p.isEvidence).length} excerpts</span></div><p class="evidence-intro">Read the transcript passages and surrounding context before opening the teaching question.</p><button class="context-toggle" data-action="context" aria-expanded="${showContext}">${showContext ? '− Hide neighboring passages' : '+ Show surrounding context'}</button>
      <div class="evidence-scroll">${evidence.map(p => `<article class="passage ${p.isEvidence ? '' : 'neighbor'}"><div class="passage-meta"><span>${esc(p.speaker_hint || 'Transcript')}${p.isEvidence ? '' : ' · context'}</span><a href="${esc(p.source_url)}" target="_blank" rel="noopener noreferrer" aria-label="Open source lines ${p.start_line} to ${p.end_line}">L${p.start_line}–${p.end_line} ${icon('link')}</a></div><blockquote>${esc(p.text)}</blockquote></article>`).join('')}</div>
      <label class="check-row source-check"><input id="source-checked" type="checkbox" ${r.sourceChecked ? 'checked' : ''} ${locked ? 'disabled' : ''}><span>I’ve reviewed the supporting evidence and context.<small>${r.sourceChecked ? 'Reading acknowledged. Revisit these passages as you compare the draft.' : 'Check this to reveal the question and review materials.'}</small></span></label>
    </aside>`;
}

function reviewPage() {
  const q = currentQuestion(), r = record(q), index = bundle.questions.indexOf(q), locked = r.status !== 'pending';
  const [tone, recommendation] = recommendations[q.recommendation];
  const intro = `<div class="review-top"><button class="text-button" data-action="inbox">${icon('back')} Inbox</button><span>EPISODE ${q.episode ?? bundle.episode} <span class="slash">/</span> ${esc(q.section.replace('section-', 'SECTION '))}</span><div class="question-nav"><span>Question ${index + 1} of ${bundle.questions.length}</span><button class="icon-button" data-action="previous" aria-label="Previous question" ${index === 0 ? 'disabled' : ''}>${icon('back')}</button><button class="icon-button" data-action="next" aria-label="Next question" ${index === bundle.questions.length - 1 ? 'disabled' : ''}>${icon('arrow')}</button></div></div>
    <div class="review-title"><div><span class="eyebrow">EVIDENCE FIRST · QUESTION SECOND</span><h1>Read the supporting evidence</h1></div></div>
    ${locked ? `<div class="decision-banner">${icon('check')}<span><strong>${labels[r.status]}</strong> by ${esc(r.reviewedBy)} · ${esc(new Date(r.decidedAt).toLocaleString())}</span><button class="text-button" data-action="reopen">Reopen for review</button></div>` : ''}
    ${evidenceCard(q, r)}`;
  if (!r.sourceChecked) return intro + '<div class="evidence-gate"><strong>Next: review the teaching question</strong><p>Confirm you’ve reviewed the evidence above to reveal the question, answer outline, and assistant’s notes.</p></div>';
  return intro + `<div data-publication-for="${esc(q.id)}">${publicationCard(q, r)}</div><div id="review-material" class="review-material" tabindex="-1"><div class="review-title"><div><span class="eyebrow">STEP 2 · COMPARE THE DRAFT WITH THE EVIDENCE</span><h1>${esc(q.concept)}</h1></div><span class="pill ${locked ? (r.status === 'approved' ? 'green' : 'neutral') : tone}">${locked ? labels[r.status] : recommendation}</span></div>
    <button class="text-button revisit-evidence" data-action="revisit-evidence">${icon('back')} Revisit supporting evidence</button>
    <div class="review-grid">
      <section class="paper-card draft-card"><div class="card-heading"><span class="eyebrow">THE TEACHING QUESTION</span>${!locked ? `<button class="text-button small" data-action="edit">${icon('edit')}${editing ? 'Done editing' : 'Edit draft'}</button>` : ''}</div>
        ${editing && !locked ? `<label class="field-label" for="draft-question">Question</label><textarea id="draft-question" class="question-editor" rows="4" maxlength="1000">${esc(r.question)}</textarea>` : `<h2 class="teaching-question">${esc(r.question)}</h2>`}
        <h3 class="subheading">What the lesson would explain</h3>
        ${editing && !locked ? r.outline.map((claim, i) => `<label class="field-label" for="claim-${i}">Point ${i + 1}</label><textarea id="claim-${i}" data-claim="${i}" rows="3" maxlength="2000">${esc(claim)}</textarea>`).join('') : `<ol class="outline">${r.outline.map(c => `<li>${esc(c)}</li>`).join('')}</ol>`}
        <div class="qualifications"><strong>Keep in mind</strong>${q.qualifications.map(c => `<p>${esc(c)}</p>`).join('')}</div>
        <div class="model-meta"><span class="tiny-dot"></span>Original model confidence: <strong>${esc(q.modelConfidence)}</strong><span>· A suggestion, not a verdict</span></div>
      </section>
      <section class="reviewer-card ${tone}"><div class="card-heading"><span class="eyebrow">ASSISTANT’S FIRST PASS</span>${icon('info')}</div><h3>${mode === 'server' ? 'Model review' : q.recommendation === 'keep' ? 'The explanation holds together.' : q.recommendation === 'exclude' ? 'The source is about something else.' : 'A small wording change matters.'}</h3><ul>${q.reviewNotes.map(n => `<li>${esc(n)}</li>`).join('')}</ul>
      ${q.suggestion ? `<details class="suggestion"><summary>See suggested revision</summary><p><strong>${esc(q.suggestion.question)}</strong></p><ul>${q.suggestion.outline.map(c => `<li>${esc(c)}</li>`).join('')}</ul>${!locked ? '<button class="button secondary" data-action="use-suggestion">Use this draft</button><p class="small muted">You’ll still check the revised text against the evidence.</p>' : ''}</details>` : ''}</section>
    </div>
    <section class="paper-card decision-card"><div class="decision-heading"><span class="step-number">✓</span><div><span class="eyebrow">STEP 3 · CONFIRM YOUR JUDGMENT</span><h2>Is this ready to teach?</h2></div></div><div class="judgment-grid">
      <label class="field-label">Source support<select id="evidence-grade" ${locked ? 'disabled' : ''}><option value="">Choose a grade</option><option value="strong" ${r.evidence === 'strong' ? 'selected' : ''}>Strong — claims are supported</option><option value="partial" ${r.evidence === 'partial' ? 'selected' : ''}>Partial — something needs fixing</option><option value="unsupported" ${r.evidence === 'unsupported' ? 'selected' : ''}>Unsupported — wrong or missing evidence</option></select></label>
      <div class="field-label"><div class="field-heading"><label for="teaching-grade">Teaching value</label><span class="field-help"><button type="button" class="help-button" aria-label="How to judge teaching value" aria-describedby="teaching-value-help">?</button><span id="teaching-value-help" class="help-tooltip" role="tooltip"><strong>What would someone learn?</strong><span>Choose <b>Clear</b> when the question and answer outline teach one focused idea, explain how or why it matters, and offer a useful takeaway.</span><span>Choose <b>Needs work</b> if they are vague, trivial, combine unrelated ideas, or repeat the transcript without explaining it.</span><span>Judge factual accuracy separately under Source support.</span></span></span></div><select id="teaching-grade" ${locked ? 'disabled' : ''}><option value="">Choose a grade</option><option value="clear" ${r.teaching === 'clear' ? 'selected' : ''}>Clear — a useful, focused lesson</option><option value="needs_work" ${r.teaching === 'needs_work' ? 'selected' : ''}>Needs work — unclear or unfocused</option></select></div>
      <label class="check-row scope-check"><input id="scope-checked" type="checkbox" ${r.scopeChecked ? 'checked' : ''} ${locked ? 'disabled' : ''}><span>Scope and qualifications checked.<small>Who, when, and what the source actually claims.</small></span></label>
    </div><label class="check-row material-check"><input id="material-checked" type="checkbox" ${r.materialChecked ? 'checked' : ''} ${locked ? 'disabled' : ''}><span>The supporting evidence matches this question and answer outline.<small>I’ve compared the draft with the source and checked that its claims are supported.</small></span></label><label class="field-label" for="review-notes">Your notes <span class="muted">— what should change, or what made this useful?</span></label><textarea id="review-notes" rows="2" maxlength="5000" placeholder="Leave a clear handoff for the next pass…" ${locked ? 'disabled' : ''}>${esc(r.notes)}</textarea>
    <div class="decision-footer"><div id="approval-hint" class="approval-status" role="status" aria-live="polite" aria-atomic="true"></div>${locked ? '<button class="button primary" data-action="next-pending">Next question to review '+icon('arrow')+'</button>' : `<div class="decision-actions"><button class="text-button exclude-button" data-action="exclude">Exclude</button><button class="button secondary" data-action="request-changes">Request changes</button><button class="button primary" id="approve-button" data-action="approve" aria-describedby="approval-hint">${icon('check')} Approve & continue</button></div>`}</div>
    <p class="small muted decision-note">${mode === 'server' ? 'Approval queues the approved wording for retrieval indexing. ' : ''}Changes or exclusion need a note. Editing clears your grades and comparison checks; your source-reading acknowledgment stays saved.</p></section></div>`;
}

function render() {
  app.innerHTML = shell(view === 'review' ? reviewPage() : mode === 'server' ? serverInbox() : inbox());
  document.title = view === 'review' ? `${record(currentQuestion()).sourceChecked ? currentQuestion().concept : 'Read the supporting evidence'} — Lesson desk` : 'Lesson desk — review inbox';
  updateApproval();
}

function updateApproval() {
  if (view !== 'review') return;
  const r = record(currentQuestion()), button = document.querySelector('#approve-button'), hint = document.querySelector('#approval-hint');
  const problems = approvalProblems(r, state.reviewer);
  if (button) button.disabled = problems.length > 0;
  if (hint) {
    const waiting = r.status === 'pending' && problems.length > 0;
    hint.className = `approval-status ${waiting ? 'requirements-pending' : 'requirements-complete'}`;
    const content = r.status !== 'pending'
      ? (mode === 'server' ? '<strong>Decision saved</strong><p>Indexing follows the current approval. No lesson is sent to Discord.</p>' : '<strong>Decision saved</strong><p>This does not publish or ingest a lesson.</p>')
      : waiting
        ? `<strong>Required before approval · ${problems.length} remaining</strong><p>Complete each item below to enable “Approve & continue”.</p><ul>${problems.map(problem => `<li>${esc(problem)}</li>`).join('')}</ul>`
        : '<strong>Ready to approve</strong><p>All required checks are complete. Choose “Approve & continue” to save your decision.</p>';
    if (hint.innerHTML !== content) hint.innerHTML = content;
  }
}

function openQuestion(id) {
  if (mode === 'server' && inboxLoading) return;
  activeId = id; view = 'review'; editing = false; showContext = true; render(); window.scrollTo(0, 0);
  document.querySelector('#main').focus({preventScroll: true});
}

function goInbox(nextFilter = 'pending') { view = 'inbox'; filter = nextFilter; render(); window.scrollTo(0, 0); if (mode === 'server' && !writeBlocked) void saveChain.then(() => loadInbox()); }

function nextPending() {
  const start = bundle.questions.findIndex(q => q.id === activeId);
  const ordered = [...bundle.questions.slice(start + 1), ...bundle.questions.slice(0, start + 1)];
  const next = ordered.find(q => record(q).status === 'pending');
  if (next) openQuestion(next.id); else goInbox('reviewed');
}

async function commitDecision(status) {
  if (deciding) return;
  deciding = true;
  document.querySelectorAll('#main button, #main input, #main select, #main textarea').forEach(node => { node.disabled = true; });
  const q = currentQuestion(), previous = record(q);
  try {
    if (mode === 'server') await saveChain;
    if (writeBlocked) throw new Error('Reload the inbox to resolve the save error before deciding.');
    state.records[q.id] = decide(record(q), status, state.reviewer);
    await save(); nextPending();
    toast(`${labels[status]}. Your decision is saved ${mode === 'server' ? 'to the workspace' : storageWorking ? 'in this browser' : 'in memory — export to keep it'}.`);
  } catch (error) { state.records[q.id] = previous; render(); toast(error.message); }
  finally { deciding = false; }
}

for (const eventName of ['pointerover', 'focusin']) {
  document.addEventListener(eventName, event => {
    const help = event.target.closest('.field-help');
    if (help && !help.contains(event.relatedTarget)) help.classList.remove('dismissed');
  });
}

document.addEventListener('keydown', event => {
  if (event.key === 'Escape') document.querySelectorAll('.field-help').forEach(help => help.classList.add('dismissed'));
});

document.addEventListener('click', async event => {
  const button = event.target.closest('[data-action], [data-open], [data-filter]');
  if (!button) return;
  event.preventDefault();
  if (deciding) return;
  try {
    if (button.dataset.open) return openQuestion(button.dataset.open);
    if (button.dataset.filter) return goInbox(button.dataset.filter);
    const action = button.dataset.action;
    if (action === 'refresh-inbox' && mode === 'server') { await saveChain; void loadInbox(); return; }
    if (action === 'inbox') goInbox();
    if (action === 'reviewed') goInbox('reviewed');
    if (action === 'resume') {
      const q = bundle.questions.find(q => record(q).status === 'pending');
      if (q) openQuestion(q.id); else goInbox('reviewed');
    }
    if (action === 'previous' || action === 'next') {
      const index = bundle.questions.indexOf(currentQuestion()) + (action === 'next' ? 1 : -1);
      if (bundle.questions[index]) openQuestion(bundle.questions[index].id);
    }
    if (action === 'next-pending') nextPending();
    if (action === 'revisit-evidence') document.querySelector('#supporting-evidence').focus();
    if (action === 'context') { showContext = !showContext; render(); }
    if (action === 'edit') { editing = !editing; render(); if (editing) document.querySelector('#draft-question').focus(); }
    if (action === 'use-suggestion') {
      const q = currentQuestion();
      state.records[q.id] = editReview(record(q), structuredClone(q.suggestion));
      save(); editing = true; render(); toast('Suggested wording added to the draft. Check it against the source.');
    }
    if (action === 'approve') await commitDecision('approved');
    if (action === 'request-changes') await commitDecision('changes_requested');
    if (action === 'exclude') await commitDecision('excluded');
    if (action === 'reopen') { const q = currentQuestion(); state.records[q.id] = reopen(record(q)); save(); openQuestion(q.id); toast('Reopened. Start with the evidence before comparing the draft again.'); }
    if (action === 'guide') document.querySelector('#guide').showModal();
    if (action === 'close-guide') document.querySelector('#guide').close();
    if (action === 'restore') document.querySelector('#restore-dialog').showModal();
    if (action === 'cancel-restore') document.querySelector('#restore-dialog').close();
    if (action === 'confirm-restore') { document.querySelector('#restore-dialog').close(); document.querySelector('#restore-file').click(); }
    if (action === 'export') {
      const url = URL.createObjectURL(new Blob([JSON.stringify(exportReview(state, bundle), null, 2)], {type: 'application/json'}));
      const link = document.createElement('a'); link.href = url; link.download = `episode-428-review-${new Date().toISOString().slice(0, 10)}.json`; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000); toast('Review exported. Keep this file as your portable backup.');
    }
  } catch (error) { toast(error.message); }
});

document.addEventListener('input', event => {
  const target = event.target;
  if (target.id === 'episode-number') { episodeInput = target.value; return; }
  if (target.id === 'reviewer-name') { state.reviewer = target.value; if (mode !== 'server') save(); updateApproval(); return; }
  if (view !== 'review') return;
  if (target.id === 'review-notes') updateRecord({notes: target.value});
  if (target.id === 'draft-question' || target.hasAttribute('data-claim')) {
    const q = currentQuestion(), r = record(q);
    const edits = target.id === 'draft-question' ? {question: target.value} : {outline: r.outline.map((c, i) => i === Number(target.dataset.claim) ? target.value : c)};
    state.records[q.id] = editReview(r, edits); save();
    document.querySelector('#evidence-grade').value = ''; document.querySelector('#teaching-grade').value = '';
    document.querySelector('#scope-checked').checked = false; document.querySelector('#material-checked').checked = false;
    updateApproval();
  }
});

document.addEventListener('change', async event => {
  const target = event.target;
  if (target.id === 'restore-file') {
    try {
      const file = target.files[0]; if (!file) return;
      if (file.size > 1024 * 1024) throw new Error('Choose a review export smaller than 1 MB.');
      const imported = validateState(JSON.parse(await file.text()), bundle);
      state = {schemaVersion: imported.schemaVersion, bundleId: imported.bundleId, reviewer: imported.reviewer, records: imported.records};
      save(); goInbox('all'); toast('Review decisions restored.');
    } catch (error) { toast(`Could not restore: ${error.message}`); }
    target.value = ''; return;
  }
  if (view !== 'review') return;
  if (target.id === 'evidence-grade') updateRecord({evidence: target.value});
  if (target.id === 'teaching-grade') updateRecord({teaching: target.value});
  if (target.id === 'scope-checked') updateRecord({scopeChecked: target.checked});
  if (target.id === 'material-checked') updateRecord({materialChecked: target.checked});
  if (target.id === 'source-checked') {
    const q = currentQuestion(), checked = target.checked;
    state.records[q.id] = acknowledgeSource(record(q), checked);
    save(); render();
    if (checked) document.querySelector('#review-material').focus();
    else document.querySelector('#source-checked').focus({preventScroll: true});
  }
});

try {
  const runtimeResponse = await fetch('./runtime.json', {cache: 'no-store'});
  if (!runtimeResponse.ok) throw new Error('The review workspace configuration could not be loaded.');
  const runtime = await runtimeResponse.json();
  if (!['demo', 'server'].includes(runtime.mode)) throw new Error('Unsupported workspace configuration.');
  mode = runtime.mode;
  if (mode === 'server') {
    bundle = {id: 'server', questions: []}; state = newState(bundle);
    await loadInbox();
    await loadJobs();
    setInterval(() => { if (!document.hidden) void loadJobs(); }, 5000);
  } else {
    const response = await fetch('./sample.json');
    if (!response.ok) throw new Error('The example intake could not be loaded.');
    bundle = await response.json(); storageKey = `rr-lesson-review:${bundle.id}`; state = newState(bundle);
    try {
      const saved = localStorage.getItem(storageKey);
      if (saved) state = validateState(JSON.parse(saved), bundle);
    } catch {
      storageWorking = false; storageWarning = 'Saved progress could not be read. Restore a valid export, or continue with a new review and export your decisions.';
    }
    render();
  }
} catch (error) {
  app.innerHTML = `<main class="loading"><h1>Couldn’t open the inbox.</h1><p>${esc(error.message)}</p><p>Reload this page to try again.</p></main>`;
}
