"""Single background consumer: pinned Git source → preparation → inbox."""
import fcntl
import logging
from pathlib import Path
import threading

import prepare

LOG = logging.getLogger('uvicorn.error')
REPOSITORY = 'https://github.com/morey-tech/rr-scraper'
GPU_REVISION = 'cdbee75f17c01a7cc42f958dc650907174af0554'


class RotatingTokenModel(prepare.Model):
    def __init__(self, base_url, name, token_path):
        self.token_path = Path(token_path)
        super().__init__(base_url, name, self.token_path.read_text())

    def post(self, url, data):
        # Projected service-account tokens rotate while long episodes are prepared.
        self.token = self.token_path.read_text().strip()
        return super().post(url, data)


def fetch_source(cache, episode):
    """Incremental bare Git fetch. No checkout, hooks, shell, or GitHub credentials."""
    from dulwich.client import HttpGitClient
    from dulwich.config import ConfigDict
    from dulwich.objects import Blob, Commit, Tree
    from dulwich.repo import Repo

    cache = Path(cache)
    cache.parent.mkdir(parents=True, exist_ok=True)
    repo = Repo(str(cache)) if cache.exists() else Repo.init_bare(str(cache), mkdir=True, shared_repository='group')
    try:
        client = HttpGitClient('https://github.com', config=ConfigDict(), timeout=60, include_tags=False)
        result = client.fetch('/morey-tech/rr-scraper.git', repo, depth=1,
                              determine_wants=lambda refs, depth=None: [refs[b'HEAD']])
        commit_id = result.refs[b'HEAD']
        repo.refs[b'refs/heads/source'] = commit_id
        commit = repo[commit_id]
        if not isinstance(commit, Commit):
            raise prepare.PreparationError('Repository HEAD is not a commit')
        node = repo[commit.tree]
        for component in ('transcripts', 'individual', f'episode_{episode}.md'):
            if not isinstance(node, Tree):
                raise KeyError(component)
            mode, object_id = node[component.encode()]
            node = repo[object_id]
        if not isinstance(node, Blob) or mode not in (0o100644, 0o100755):
            raise prepare.PreparationError('Episode transcript is not a regular file')
        return prepare.source_from_bytes(node.data, commit_id.decode(), episode)
    except KeyError:
        raise prepare.PreparationError(f'Episode {episode} has no individual transcript in rr-scraper. Check its availability at the source.') from None
    except prepare.PreparationError:
        raise
    except Exception:
        raise prepare.PreparationError('Git fetch failed. Check GitHub connectivity and retry.') from None
    finally:
        repo.close()


def make_intake(report, key):
    items = report['passages']
    by_id = {p['id']: p for p in items}
    questions = []
    skipped = 0
    for entry in report['questions']:
        if entry['status'] == 'duplicate':
            skipped += 1
            continue
        candidate = entry['candidate']
        try:
            cited = prepare.validate_question(candidate, by_id, by_id)
        except prepare.PreparationError:
            skipped += 1
            continue
        evidence = {p for claim in candidate['answer_outline'] for p in claim['passage_ids']}
        context = set(prepare.expand(cited, items))
        review = entry.get('review') if isinstance(entry.get('review'), dict) else {}
        passed = entry['status'] == 'needs_human_review' and not entry.get('error')
        confidence = review.get('confidence')
        if confidence not in ('low', 'medium', 'high'):
            confidence = 'not assessed'
        notes = [str(review[k]) for k in ('reason', 'confidence_reason') if review.get(k)]
        if entry.get('rejection_reason'):
            notes.insert(0, 'Model review rejected: ' + entry['rejection_reason'])
        questions.append({
            'id': key + ':' + entry['id'], 'originalQuestionId': entry['id'],
            'episode': report['source']['episode'], 'section': entry['id'].rsplit('-q', 1)[0],
            'source': report['source'], 'concept': candidate['concept'], 'question': candidate['question'],
            'outline': [p['claim'] for p in candidate['answer_outline']],
            'claims': candidate['answer_outline'], 'qualifications': candidate['qualifications'],
            'prerequisites': candidate['prerequisites'],
            'passages': [{**p, 'isEvidence': p['id'] in evidence} for p in items if p['id'] in context],
            'modelConfidence': confidence + (' (unvalidated)' if entry.get('error') else ''),
            'recommendation': 'keep' if passed and review.get('confidence') == 'high' else 'revise',
            'reviewNotes': notes or ['The model could not complete its review. Check every claim against the source.'],
            'modelStatus': entry['status'], 'suggestion': None,
        })
    return {'id': key, 'episode': report['source']['episode'], 'questions': questions, 'skipped': skipped}



class Pipeline:
    def __init__(self, database, directory, token_path):
        self.db, self.directory, self.token_path = database, Path(directory), token_path

    def run(self, job):
        key = job['id']
        output = self.directory / 'runs' / key
        output.mkdir(parents=True, exist_ok=True)
        (output / 'responses').mkdir(exist_ok=True)
        self.db.job_progress(key, 'Fetching transcript from Git')
        source, text, start = fetch_source(self.directory / 'rr-scraper.git', job['episode'])
        prompts = {stage: (prepare.DIRECTORY / f'{stage}.txt').read_text() for stage in ('extract', 'review')}
        manifest = {
            'pipeline_version': prepare.VERSION,
            'pipeline_sha256': prepare.digest(Path(__file__).read_bytes() + Path(prepare.__file__).read_bytes()),
            'source': source, 'model': {'name': 'local-llm', 'revision': GPU_REVISION},
            'max_passage_chars': prepare.MAX_PASSAGE, 'max_section_chars': prepare.MAX_SECTION,
            'context_limit': prepare.CONTEXT_LIMIT, 'max_output_tokens': prepare.MAX_OUTPUT_TOKENS,
            'temperature': 0,
            'prompt_hashes': {k: prepare.digest(v.encode()) for k, v in prompts.items()},
        }
        intake_id = 'e' + str(job['episode']) + '-' + prepare.digest(prepare.encoded(manifest))[:24]
        self.db.job_progress(key, 'Validating transcript', source_commit=source['commit'])
        if self.db.existing_intake(intake_id):
            self.db.finish_existing(key, intake_id)
            return
        prepare.atomic_write(output / 'source.md', text.encode())
        prepare.atomic_write(output / 'manifest.json', prepare.encoded(manifest))
        items = prepare.passages(source, text, start)
        groups = prepare.sections(items)
        if not groups:
            raise prepare.PreparationError('Transcript contains no passages to prepare')
        report = {'manifest': manifest, 'source': source, 'passages': items, 'sections': groups,
                  'questions': [], 'failures': [], 'status': 'prepared'}
        model = RotatingTokenModel(prepare.DEFAULT_URL, 'local-llm', self.token_path)
        prepare.evaluate(report, model, output, prompts, None,
                         progress=lambda done, total, section: self.db.job_progress(key, f'Preparing {section}', done, total))
        if report['failures']:
            raise prepare.PreparationError(f"{len(report['failures'])} sections failed preparation; no questions imported. " + report['failures'][0]['error'])
        intake = make_intake(report, intake_id)
        if not intake['questions']:
            raise prepare.PreparationError('No structurally valid teaching questions were generated; no questions imported')
        self.db.job_progress(key, 'Importing prepared material')
        self.db.import_intake(key, intake, report)
        LOG.info('Episode %s imported: %s questions, %s malformed/duplicate candidates skipped; source=%s',
                 job['episode'], len(intake['questions']), intake['skipped'], source['commit'])


class Worker:
    def __init__(self, database, pipeline):
        self.db, self.pipeline = database, pipeline
        self.stopping = threading.Event()

    def start(self):
        # Prevent accidental multiple ASGI workers from consuming the singleton queue.
        self.lock = open(self.db.path.parent / 'ingestion.lock', 'a')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.db.recover_jobs()
        self.thread = threading.Thread(target=self.loop, name='episode-ingestion', daemon=True)
        self.thread.start()

    def stop(self):
        self.stopping.set()
        # The process exits after ASGI shutdown; in-flight jobs become retryable on restart.
        self.thread.join(timeout=1)
        if not self.thread.is_alive():
            self.lock.close()

    def loop(self):
        while not self.stopping.is_set():
            try:
                job = self.db.claim_job()
                if not job:
                    self.stopping.wait(2)
                    continue
                LOG.info('Starting ingestion %s for episode %s', job['id'], job['episode'])
                try:
                    self.pipeline.run(job)
                except Exception as exc:
                    message = str(exc) if isinstance(exc, prepare.PreparationError) else 'Internal ingestion error. Check the pod logs and retry.'
                    LOG.exception('Episode %s ingestion failed', job['episode'])
                    self.db.fail_job(job['id'], message)
            except Exception:
                LOG.exception('Ingestion queue unavailable')
                self.stopping.wait(5)
