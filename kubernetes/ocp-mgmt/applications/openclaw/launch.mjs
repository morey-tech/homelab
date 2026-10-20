// Restart the gateway when Kubernetes projects a replacement MaaS credential.
// No Kubernetes API access is needed by the agent workload.
import { readFileSync, mkdirSync, copyFileSync, realpathSync, constants } from 'node:fs';
import { spawn } from 'node:child_process';
import { pathToFileURL } from 'node:url';

export function isEntrypoint(moduleUrl, entryPath = process.argv[1]) {
  return Boolean(entryPath) && moduleUrl === pathToFileURL(realpathSync(entryPath)).href;
}

export function launch({ keyPath = '/maas/MAAS_API_KEY', command = process.execPath,
  args = ['/app/openclaw.mjs', 'gateway', 'run'], intervalMs = 30000,
  graceMs = 30000 } = {}) {
  const key = readFileSync(keyPath, 'utf8').trim();
  if (!key) throw new Error('Empty MaaS credential');
  const child = spawn(command, args, {
    stdio: 'inherit', env: { ...process.env, MAAS_API_KEY: key },
  });
  let stopping = false;
  let deadline;
  const stop = () => {
    if (stopping) return;
    stopping = true;
    child.kill('SIGTERM');
    deadline = setTimeout(() => child.kill('SIGKILL'), graceMs);
  };
  const poll = setInterval(() => {
    try {
      const current = readFileSync(keyPath, 'utf8').trim();
      if (current && current !== key) {
        console.log('MaaS credential changed; restarting gateway');
        stop();
      }
    } catch {
      // Retain the running process during a transient projection/read failure.
      console.error('Cannot read projected MaaS credential; retaining gateway');
    }
  }, intervalMs);
  process.on('SIGTERM', stop);
  process.on('SIGINT', stop);
  child.on('error', () => {
    console.error('Gateway process could not start');
    process.exit(1);
  });
  child.on('exit', (code) => {
    clearInterval(poll);
    clearTimeout(deadline);
    process.exit(stopping ? 0 : (code ?? 1));
  });
}

if (isEntrypoint(import.meta.url)) {
  mkdirSync('/home/node/.openclaw/workspace', { recursive: true });
  try {
    copyFileSync('/config/AGENTS.md', '/home/node/.openclaw/workspace/AGENTS.md', constants.COPYFILE_EXCL);
  } catch (error) {
    if (error.code !== 'EEXIST') throw error;
  }
  try { launch(); } catch {
    console.error('Cannot start gateway without a readable MaaS credential');
    process.exit(1);
  }
}
